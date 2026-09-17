"""Assist files: parsing, skill documents, the link-reading tool, and MCP tool use.

Everything runs offline. The MCP test starts a tiny stdio server from this file.
"""

import sys
import textwrap

import pytest
from inspect_ai import Task, eval
from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
    get_model,
)

from eth_bench.assist import (
    MAX_TOOL_OUTPUT_BYTES,
    AssistError,
    SkillBase,
    load_assist,
    load_assist_config,
    read_document,
    resolve_assist_path,
)
from eth_bench.dataset import load_dataset
from eth_bench.solver import eth_bench_solver, read_template
from eth_bench.tasks import eth_bench

FAKE_MCP_SERVER = textwrap.dedent(
    """
    import os
    from mcp.server.fastmcp import FastMCP

    if os.environ.get("STARTS_LOG"):
        with open(os.environ["STARTS_LOG"], "a") as f:
            f.write("started\\n")

    server = FastMCP("fake")

    @server.tool()
    def lookup_spec(name: str) -> str:
        \"\"\"Look up a constant.\"\"\"
        return f"{name} = 42"

    server.run()
    """
)


def write(path, text):
    path.write_text(textwrap.dedent(text))
    return path


# --- config -----------------------------------------------------------------------


def test_env_vars_are_expanded_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "s3cret")
    monkeypatch.setenv("DB", "/data/corpus.sqlite")
    config = load_assist_config(
        write(
            tmp_path / "a.yaml",
            """
            name: two-servers
            mcp_servers:
              - name: remote
                transport: http
                url: https://example.org/mcp
                headers: {Authorization: "Bearer ${TOKEN}"}
              - name: local
                transport: stdio
                command: wikipethia
                args: [mcp, --db, "${DB}"]
                tools: [search_posts]
            """,
        )
    )
    remote, local = config.mcp_servers
    assert remote.headers == {"Authorization": "Bearer s3cret"}
    assert local.args == ["mcp", "--db", "/data/corpus.sqlite"]
    assert local.tools == ["search_posts"]


def test_unset_env_var_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    path = write(
        tmp_path / "a.yaml",
        """
        name: x
        mcp_servers: [{name: s, transport: http, url: "${NOPE}"}]
        """,
    )
    with pytest.raises(AssistError, match="NOPE"):
        load_assist_config(path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("name: x\n", "at least one"),
        ("name: x\nmcp_servers: [{name: s, transport: http}]\n", "needs a url"),
        ("name: x\nmcp_servers: [{name: s, transport: stdio}]\n", "needs a command"),
        ("name: x\nskills: [{name: s, source: a.md, follow: true}]\n", "follow"),
        ("name: Bad Name\nskills: [{name: s, source: a.md}]\n", "lowercase"),
        ("- just\n- a list\n", "mapping"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path, body, message):
    with pytest.raises(AssistError, match=message):
        load_assist_config(write(tmp_path / "a.yaml", body))


def test_example_assist_files_parse(monkeypatch):
    monkeypatch.setenv("WIKIPETHIA_DB", "/tmp/corpus.sqlite")
    from pathlib import Path

    for path in sorted(Path("assists").glob("*.yaml")):
        assert load_assist_config(path).name == path.stem


def test_assist_resolves_by_bundled_name_or_path(tmp_path):
    assert resolve_assist_path("ethskills").name == "ethskills.yaml"
    assert resolve_assist_path("assists/ethskills.yaml").name == "ethskills.yaml"
    own = write(tmp_path / "mine.yaml", "name: mine\nskills: [{name: s, source: SKILL.md}]\n")
    assert resolve_assist_path(own) == own
    with pytest.raises(AssistError, match="bundled assists"):
        resolve_assist_path("nope")


# --- skills -----------------------------------------------------------------------


@pytest.fixture
def skill_dir(tmp_path):
    """A skill directory, with a file outside it that the skill must not reach."""
    skill = tmp_path / "skill"
    skill.mkdir()
    write(skill / "SKILL.md", "# My skill\nAlways say {hello}. See topic.md.\n")
    write(skill / "topic.md", "Topic details: the answer is 42.\n")
    write(tmp_path / "secret.md", "not for you\n")
    return skill


def test_skill_document_is_inlined_and_braces_survive(skill_dir):
    assist = load_assist(
        write(
            skill_dir / "assist.yaml",
            """
            name: skill-only
            instructions: Read the skill first.
            skills: [{name: mine, source: SKILL.md}]
            """,
        )
    )
    assert assist.tool_sources == []
    assert assist.system_text.startswith("Read the skill first.")
    assert "# Skill: mine" in assist.system_text
    assert "Always say {hello}." in assist.system_text


@pytest.mark.anyio
async def test_read_document_tool_stays_inside_the_skill_directory(skill_dir):
    assist = load_assist(
        write(
            skill_dir / "assist.yaml",
            """
            name: linked
            skills: [{name: mine, source: SKILL.md, follow_links: true}]
            """,
        )
    )
    [tool] = assist.tool_sources
    assert "read_document" in assist.system_text
    assert "the answer is 42" in await tool(str(skill_dir / "topic.md"))
    assert (await tool(str(skill_dir.parent / "secret.md"))).startswith("Refused")
    assert (await tool("../secret.md")).startswith("Refused")
    assert (await tool("/etc/passwd")).startswith("Refused")
    assert (await tool(str(skill_dir / "missing.md"))).startswith("Could not read")


@pytest.mark.anyio
async def test_read_document_tool_url_scope_is_the_origin():
    tool = read_document([SkillBase("https://ethskills.com/SKILL.md")])
    assert (await tool("https://evil.example/SKILL.md")).startswith("Refused")
    # Malformed locations come back as text, never as an exception that kills the sample.
    for bad in ("https://ethskills.com:abc/x", "http://[ethskills.com/SKILL.md"):
        assert (await tool(bad)).startswith(("Refused", "Could not read"))


def test_relative_links_resolve_against_the_skill(skill_dir):
    url_base = SkillBase("https://ethskills.com/SKILL.md")
    assert url_base.resolve("protocol/SKILL.md") == "https://ethskills.com/protocol/SKILL.md"
    assert url_base.resolve("/crops/SKILL.md") == "https://ethskills.com/crops/SKILL.md"
    assert (
        url_base.resolve("https://ethskills.com/gas/SKILL.md")
        == "https://ethskills.com/gas/SKILL.md"
    )
    assert url_base.resolve("https://evil.example/x") is None
    local = SkillBase(str(skill_dir / "SKILL.md"))
    assert local.resolve("topic.md") == str(skill_dir / "topic.md")
    assert local.resolve("../secret.md") is None


@pytest.mark.anyio
async def test_read_document_follows_relative_links_as_written(skill_dir):
    assist = load_assist(
        write(
            skill_dir / "assist.yaml",
            "name: r\nskills: [{name: mine, source: SKILL.md, follow_links: true}]\n",
        )
    )
    [tool] = assist.tool_sources
    assert "the answer is 42" in await tool("topic.md")


def test_missing_skill_document_is_an_assist_error(tmp_path):
    with pytest.raises(AssistError, match="could not read skill document"):
        load_assist(write(tmp_path / "a.yaml", "name: a\nskills: [{name: s, source: nope.md}]\n"))


# --- solver -----------------------------------------------------------------------


def _one_of_each_type():
    seen: set[str] = set()

    def keep(sample):
        if sample.metadata["type"] in seen:
            return False
        seen.add(sample.metadata["type"])
        return True

    return load_dataset().filter(keep)


def test_assist_text_reaches_every_question_type(skill_dir, tmp_path):
    assist = load_assist(
        write(skill_dir / "assist.yaml", "name: s\nskills: [{name: mine, source: SKILL.md}]\n")
    )
    task = Task(dataset=_one_of_each_type(), solver=eth_bench_solver(assist=assist))
    [log] = eval(task, model="mockllm/model", log_dir=str(tmp_path), display="none")
    assert log.status == "success", log.error
    for sample in log.samples:
        [system] = [m for m in sample.messages if isinstance(m, ChatMessageSystem)]
        assert "# Skill: mine" in system.text
        assert sample.metadata["assist"] == "s"
        if sample.metadata["type"] == "multiple_choice":
            assert system.text.startswith(read_template("assist_multiple_choice.txt"))
            assert "tools" not in system.text.lower()  # skill-only assist offers none
            [user] = [m for m in sample.messages if isinstance(m, ChatMessageUser)]
            assert "ANSWER: $LETTER" in user.text
        else:
            assert system.text.startswith(read_template("system.txt"))


def test_without_an_assist_nothing_changes(tmp_path):
    task = Task(dataset=_one_of_each_type(), solver=eth_bench_solver())
    [log] = eval(task, model="mockllm/model", log_dir=str(tmp_path), display="none")
    for sample in log.samples:
        assert "assist" not in sample.metadata
        assert not any(isinstance(m, ChatMessageTool) for m in sample.messages)
        if sample.metadata["type"] == "multiple_choice":
            assert not any(isinstance(m, ChatMessageSystem) for m in sample.messages)


def _fake_mcp_assist(tmp_path, name="fake-mcp"):
    server_py = write(tmp_path / "server.py", FAKE_MCP_SERVER)
    starts = tmp_path / "starts.log"
    assist = load_assist(
        write(
            tmp_path / "assist.yaml",
            f"""
            name: {name}
            mcp_servers:
              - name: fake
                transport: stdio
                command: "{sys.executable}"
                args: ["{server_py}"]
                env: {{STARTS_LOG: "{starts}"}}
            """,
        )
    )
    return assist, starts


def test_mcp_server_tools_are_offered_and_called(tmp_path):
    assist, starts = _fake_mcp_assist(tmp_path)
    dataset = load_dataset().filter(lambda s: s.id == "consensus-slots-per-epoch")
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "lookup_spec", {"name": "SLOTS_PER_EPOCH"}),
            ModelOutput.from_content("mockllm/model", "ANSWER: B"),
        ],
    )
    task = Task(dataset=dataset, solver=eth_bench_solver(assist=assist))
    [log] = eval(task, model=model, log_dir=str(tmp_path / "logs"), display="none")
    assert log.status == "success", log.error
    [sample] = log.samples
    [tool_result] = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert tool_result.text == "SLOTS_PER_EPOCH = 42"
    assert sample.output.completion == "ANSWER: B"
    model_events = [e for e in sample.events if e.event == "model"]
    assert all("lookup_spec" in [t.name for t in e.tools] for e in model_events)
    [system] = [m for m in sample.messages if isinstance(m, ChatMessageSystem)]
    assert "Call the available tools first" in system.text
    # One server process for the whole sample: listing tools reused the connection.
    assert starts.read_text().count("started") == 1


def test_tool_rounds_are_bounded_then_the_model_must_answer(tmp_path):
    assist, _ = _fake_mcp_assist(tmp_path, name="chatty")

    def keeps_searching(_input, tools, tool_choice, _config):
        # The final turn must remove the tools, not just set tool_choice: some
        # providers ignore tool_choice while the model is reasoning.
        if not tools:
            assert tool_choice == "none"
            return ModelOutput.from_content("mockllm/model", "ANSWER: B")
        return ModelOutput.for_tool_call("mockllm/model", "lookup_spec", {"name": "X"})

    dataset = load_dataset().filter(lambda s: s.id == "consensus-slots-per-epoch")
    task = Task(dataset=dataset, solver=eth_bench_solver(assist=assist, tool_rounds=3))
    model = get_model("mockllm/model", custom_outputs=keeps_searching)
    [log] = eval(task, model=model, log_dir=str(tmp_path / "logs"), display="none")
    assert log.status == "success", log.error
    [sample] = log.samples
    assert len([m for m in sample.messages if isinstance(m, ChatMessageTool)]) == 3
    assert sample.output.completion == "ANSWER: B"
    assert sample.limit is None


def test_message_limit_leaves_room_for_the_final_answer(tmp_path):
    assist, _ = _fake_mcp_assist(tmp_path, name="capped")

    def keeps_searching(_input, tools, _tool_choice, _config):
        if not tools:
            return ModelOutput.from_content("mockllm/model", "ANSWER: B")
        return ModelOutput.for_tool_call("mockllm/model", "lookup_spec", {"name": "X"})

    dataset = load_dataset().filter(lambda s: s.id == "consensus-slots-per-epoch")
    # system + user = 2 messages; one round adds 2 more; the final answer needs 1.
    task = Task(
        dataset=dataset, solver=eth_bench_solver(assist=assist, tool_rounds=10), message_limit=6
    )
    model = get_model("mockllm/model", custom_outputs=keeps_searching)
    [log] = eval(task, model=model, log_dir=str(tmp_path / "logs"), display="none")
    [sample] = log.samples
    assert sample.limit is None, "the cap pre-empted the forced answer"
    assert len([m for m in sample.messages if isinstance(m, ChatMessageTool)]) == 1
    assert sample.output.completion == "ANSWER: B"


# --- task -------------------------------------------------------------------------


def test_task_records_the_assist(skill_dir):
    path = write(skill_dir / "assist.yaml", "name: mine\nskills: [{name: s, source: SKILL.md}]\n")
    task = eth_bench(assist=str(path), sections="eips")
    assert task.name == "eth_bench_mine"
    assert task.metadata == {"assist": "mine"}
    assert task.message_limit is None
    assert task.config.max_tool_output == MAX_TOOL_OUTPUT_BYTES
    bare = eth_bench(sections="eips")
    assert bare.name == "eth_bench"
    assert bare.message_limit is None
    assert bare.config.max_tool_output is None
