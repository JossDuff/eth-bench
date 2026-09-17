"""Assists: things the model under test gets beyond the bare question.

An assist is a YAML file naming any number of MCP servers and skill documents. The
model is given the servers' tools, the skills' root documents in its system prompt,
and (optionally) a tool to read documents a skill links to. The grader never sees any
of it, so an assisted run is scored exactly like a bare one and the two can be
compared directly.

    inspect eval eth_bench -T assist=wikipethia --model ... --model-role grader=...

Config format:

    name: wikipethia
    instructions: |            # optional, appended to the system prompt
      Use the tools to check facts before answering.
    mcp_servers:
      - name: wikipethia
        transport: http        # or stdio
        url: https://mcp.wikipethia.org/mcp
        headers: {Authorization: "Bearer ${TOKEN}"}
        tools: all             # or a list of tool names
      - name: local
        transport: stdio
        command: wikipethia
        args: [mcp, --db, "${WIKIPETHIA_DB}"]
    skills:
      - name: ethskills
        source: https://ethskills.com/SKILL.md    # URL, or a path relative to this file
        follow_links: true     # give the model a tool to read documents from the same place

`${VAR}` anywhere in a string is replaced from the environment, so secrets stay out of
the file. An unset variable is an error.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import yaml
from inspect_ai.tool import Tool, ToolSource, mcp_server_http, mcp_server_stdio, mcp_tools, tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DOCUMENT_CHARS = 200_000
_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class AssistError(ValueError):
    """An assist file failed to load or validate."""


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    transport: Literal["http", "stdio"]
    tools: Literal["all"] | list[str] = "all"
    # http
    url: str | None = None
    headers: dict[str, str] | None = None
    timeout: float = 30
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None

    @model_validator(mode="after")
    def _check_transport_fields(self) -> MCPServerConfig:
        if self.transport == "http" and not self.url:
            raise ValueError(f"mcp server {self.name!r}: http transport needs a url")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"mcp server {self.name!r}: stdio transport needs a command")
        return self


class SkillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    follow_links: bool = False


class AssistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    instructions: str | None = None
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    skills: list[SkillConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_not_empty(self) -> AssistConfig:
        if not self.mcp_servers and not self.skills:
            raise ValueError("an assist needs at least one mcp server or skill")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", self.name):
            raise ValueError(
                f"assist name {self.name!r} must be lowercase letters, digits, hyphens"
            )
        return self


def expand_env(value: Any) -> Any:
    """Replace `${VAR}` in every string inside a parsed YAML value."""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise AssistError(f"environment variable {name} is not set")
            return os.environ[name]

        return _ENV_VAR.sub(replace, value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def load_assist_config(path: str | Path) -> AssistConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise AssistError(f"{path}: {e}") from e
    if not isinstance(raw, dict):
        raise AssistError(f"{path}: expected a mapping at the top level")
    try:
        return AssistConfig.model_validate(expand_env(raw))
    except ValueError as e:
        raise AssistError(f"{path}: {e}") from e


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def _read_source(source: str) -> str:
    """Read a document from a URL or a local path, truncating very large ones."""
    if _is_url(source):
        response = httpx.get(source, follow_redirects=True, timeout=30)
        response.raise_for_status()
        text = response.text
    else:
        text = Path(source).read_text()
    if len(text) > MAX_DOCUMENT_CHARS:
        text = text[:MAX_DOCUMENT_CHARS] + f"\n\n[truncated at {MAX_DOCUMENT_CHARS} characters]"
    return text


def _skill_scope(source: str) -> str:
    """The prefix a skill's linked documents must share with its root document."""
    if _is_url(source):
        parsed = urlparse(source)
        return f"{parsed.scheme}://{parsed.netloc}/"
    return str(Path(source).resolve().parent) + "/"


@tool
def read_document(scopes: list[str]) -> Tool:
    """Reads a document a skill links to, restricted to the skills' own locations."""

    async def execute(location: str) -> str:
        """Read a document that a skill document links to.

        Args:
            location: The document's URL, or its path for a skill loaded from disk.
                It must be under the same site or directory as the skill it was
                linked from.
        """
        target = location if _is_url(location) else str(Path(location).resolve())
        if not any(target.startswith(scope) for scope in scopes):
            return (
                f"Refused: {location} is outside the documents this assist may read. "
                f"Allowed locations start with: {', '.join(scopes)}"
            )
        try:
            return _read_source(target)
        except (OSError, httpx.HTTPError) as e:
            return f"Could not read {location}: {e}"

    return execute


class Assist:
    """A loaded assist: the tools to offer and the text to put in the system prompt."""

    def __init__(self, config: AssistConfig, base_dir: Path | None = None) -> None:
        self.config = config
        base_dir = base_dir or Path.cwd()
        self.tool_sources: list[Tool | ToolSource] = []
        for server in config.mcp_servers:
            self.tool_sources.append(mcp_tools(_make_server(server, base_dir), tools=server.tools))

        documents: list[str] = []
        scopes: list[str] = []
        for skill in config.skills:
            source = skill.source if _is_url(skill.source) else str(base_dir / skill.source)
            documents.append(f"# Skill: {skill.name}\nSource: {source}\n\n{_read_source(source)}")
            if skill.follow_links:
                scopes.append(_skill_scope(source))
        if scopes:
            self.tool_sources.append(read_document(scopes))

        parts: list[str] = []
        if config.instructions:
            parts.append(config.instructions.strip())
        if self.tool_sources:
            parts.append(
                "You have tools available. Use them to look up anything you are not certain of "
                "before answering."
            )
        if scopes:
            parts.append(
                "The skill documents below link to further documents. Use the read_document "
                "tool to read any of them that are relevant."
            )
        parts.extend(documents)
        self.system_text = "\n\n".join(parts)

    @property
    def name(self) -> str:
        return self.config.name


def _make_server(server: MCPServerConfig, base_dir: Path):
    if server.transport == "http":
        assert server.url is not None
        return mcp_server_http(
            name=server.name, url=server.url, headers=server.headers, timeout=server.timeout
        )
    assert server.command is not None
    cwd = (base_dir / server.cwd) if server.cwd else None
    return mcp_server_stdio(
        name=server.name, command=server.command, args=server.args, env=server.env, cwd=cwd
    )


def assists_dir() -> Path:
    """The bundled assist files: inside the package when installed, else the repo root."""
    packaged = Path(__file__).parent / "assists"
    if packaged.is_dir():
        return packaged
    return Path(__file__).parent.parent / "assists"


def resolve_assist_path(value: str | Path) -> Path:
    """Turn `-T assist=...` into a file.

    Accepts a path, or the bare name of a bundled assist (`wikipethia` for
    `assists/wikipethia.yaml`). Relative paths are tried against the current directory
    and then the repository root, because Inspect changes directory while it builds
    the task.
    """
    given = Path(value)
    candidates = [given, Path(__file__).parent.parent / given]
    if given.suffix == "" and "/" not in str(given):
        candidates.append(assists_dir() / f"{given}.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    bundled = sorted(p.stem for p in assists_dir().glob("*.yaml"))
    raise AssistError(f"no assist file at {value!r}; bundled assists: {bundled}")


def load_assist(path: str | Path) -> Assist:
    """Load an assist by path or bundled name. Skill sources resolve relative to the file."""
    resolved = resolve_assist_path(path)
    return Assist(load_assist_config(resolved), base_dir=resolved.parent)
