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
        timeout: 30            # seconds to connect; tool calls themselves are not bounded
        tools: all             # or a list of tool names
      - name: local
        transport: stdio
        command: wikipethia
        args: [mcp, --db, "${WIKIPETHIA_DB}"]
        env: {RUST_LOG: info}  # optional extra environment for the process
        cwd: .                 # optional, relative to this file
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
from urllib.parse import urljoin, urlparse

import anyio
import httpx
import yaml
from inspect_ai.tool import Tool, ToolSource, mcp_server_http, mcp_server_stdio, mcp_tools, tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eth_bench.dataset import package_data_dir

# The most of a document the model is ever shown, in characters, and the matching
# tool-output ceiling the task must set so Inspect does not truncate below it.
MAX_DOCUMENT_CHARS = 100_000
MAX_TOOL_OUTPUT_BYTES = 4 * MAX_DOCUMENT_CHARS

_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_document_cache: dict[str, str] = {}


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


# --- documents --------------------------------------------------------------------


def _is_url(source: str) -> bool:
    try:
        return urlparse(source).scheme in ("http", "https")
    except ValueError:
        return False


def _truncate(text: str) -> str:
    if len(text) > MAX_DOCUMENT_CHARS:
        return text[:MAX_DOCUMENT_CHARS] + f"\n\n[truncated at {MAX_DOCUMENT_CHARS} characters]"
    return text


def read_document_sync(source: str) -> str:
    """Read a skill's root document when the task is built.

    Cached per process, so resolving the task once per model does not refetch it.
    """
    if source not in _document_cache:
        try:
            if _is_url(source):
                response = httpx.get(source, follow_redirects=True, timeout=30)
                response.raise_for_status()
                text = response.text
            else:
                text = Path(source).read_text()
        except (OSError, httpx.HTTPError, httpx.InvalidURL) as e:
            raise AssistError(f"could not read skill document {source}: {e}") from e
        _document_cache[source] = _truncate(text)
    return _document_cache[source]


_http: httpx.AsyncClient | None = None


async def _read_document_async(source: str) -> str:
    """Read a linked document from inside a tool call without blocking the event loop."""
    global _http
    if _is_url(source):
        if _http is None:
            _http = httpx.AsyncClient(follow_redirects=True, timeout=30)
        response = await _http.get(source)
        response.raise_for_status()
        return _truncate(response.text)
    return _truncate(await anyio.Path(source).read_text())


class SkillBase:
    """Where a skill's root document lives, for resolving and bounding its links."""

    def __init__(self, source: str) -> None:
        self.is_url = _is_url(source)
        if self.is_url:
            parsed = urlparse(source)
            self.root = source
            self.scope = f"{parsed.scheme}://{parsed.netloc}/"
        else:
            resolved = Path(source).resolve()
            self.root = str(resolved)
            self.scope = str(resolved.parent) + "/"

    def resolve(self, location: str) -> str | None:
        """The absolute location `location` refers to relative to this skill, or None
        if it falls outside the skill's site or directory."""
        if _is_url(location):
            target = location
        elif self.is_url:
            target = urljoin(self.root, location)
        else:
            target = str((Path(self.scope) / location).resolve())
        return target if target.startswith(self.scope) else None


@tool
def read_document(bases: list[SkillBase]) -> Tool:
    """Reads a document a skill links to, restricted to the skills' own locations."""

    async def execute(location: str) -> str:
        """Read a document that a skill document links to.

        Args:
            location: The document's URL or path, exactly as the skill document
                links to it. Relative links are resolved against the skill. Only
                documents under the same site or directory as a skill can be read.
        """
        try:
            targets = [t for base in bases if (t := base.resolve(location))]
            if not targets:
                return (
                    f"Refused: {location} is outside the documents this assist may read. "
                    f"Allowed locations start with: {', '.join(b.scope for b in bases)}"
                )
            return await _read_document_async(targets[0])
        except Exception as e:  # noqa: BLE001 - anything the model can cause must come back as text
            return f"Could not read {location}: {e}"

    return execute


# --- runtime ----------------------------------------------------------------------


class Assist:
    """A loaded assist: the tools to offer and the text to put in the system prompt."""

    def __init__(self, config: AssistConfig, base_dir: Path | None = None) -> None:
        self.config = config
        base_dir = base_dir or Path.cwd()
        self.tool_sources: list[Tool | ToolSource] = []
        for server in config.mcp_servers:
            self.tool_sources.append(mcp_tools(_make_server(server, base_dir), tools=server.tools))

        documents: list[str] = []
        bases: list[SkillBase] = []
        for skill in config.skills:
            source = skill.source if _is_url(skill.source) else str(base_dir / skill.source)
            documents.append(
                f"# Skill: {skill.name}\nSource: {source}\n\n{read_document_sync(source)}"
            )
            if skill.follow_links:
                bases.append(SkillBase(source))
        if bases:
            self.tool_sources.append(read_document(bases))

        parts: list[str] = []
        if config.instructions:
            parts.append(config.instructions.strip())
        if self.tool_sources:
            parts.append(
                "You have tools available. Use them to look up anything you are not certain of "
                "before answering."
            )
        if bases:
            parts.append(
                "The skill documents below link to further documents. Use the read_document "
                "tool to read any of them that are relevant."
            )
        parts.extend(documents)
        self.system_text = "\n\n".join(parts)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def has_tools(self) -> bool:
        return bool(self.tool_sources)


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
    """The bundled assist files."""
    return package_data_dir("assists")


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
