"""One solver for every question type.

Multiple choice questions go through Inspect's built-in `multiple_choice` solver,
which formats the lettered options and asks for an `ANSWER: X` line. Open and
false-premise questions get one shared system message and a plain generate. The two
free-text types must be presented identically so nothing hints that a premise may
be false.

With an assist (see assist.py) the model also gets tools and extra system text, and
`generate` runs a bounded tool-call loop before the final answer. Without one,
behaviour is unchanged.
"""

from pathlib import Path

from inspect_ai.model import ChatMessageSystem
from inspect_ai.solver import Generate, Solver, TaskState, multiple_choice, solver, use_tools
from inspect_ai.tool import mcp_connection

from eth_bench.assist import Assist

TEMPLATES_DIR = Path(__file__).parent / "templates"

ASSIST_TOOLS_HINT = (
    "Call the available tools first to check the facts, then give your final reply in that format."
)


def read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text().strip()


def _prepend_system(state: TaskState, text: str) -> None:
    # Not `system_message()`: that runs str.format over the text, and skill documents
    # are full of braces.
    state.messages.insert(0, ChatMessageSystem(content=text))


def bounded_tool_use(generate: Generate, max_rounds: int) -> Generate:
    """Wrap `generate` so the model gets at most `max_rounds` rounds of tool calls.

    Each round is one model turn plus the execution of every tool it called. When
    the budget is spent, or the sample is about to hit its message limit, one final
    turn runs with no tools at all, so the model must answer from what it has
    gathered rather than being cut off mid-search. Tools are removed for that turn,
    not just `tool_choice`, because some providers ignore `tool_choice` when the
    model is reasoning.
    """

    def near_message_limit(state: TaskState) -> bool:
        # A round adds one assistant message plus one tool message per call, and the
        # final turn needs one more; stop while there is still room for that turn.
        return state.message_limit is not None and len(state.messages) + 2 >= state.message_limit

    async def bounded(state: TaskState, tool_calls="loop", **kwargs) -> TaskState:
        for _ in range(max_rounds):
            if near_message_limit(state):
                break
            state = await generate(state, tool_calls="single", **kwargs)
            if state.messages[-1].role != "tool":
                return state
        state.tools = []
        state.tool_choice = "none"
        return await generate(state, tool_calls="none", **kwargs)

    return bounded


@solver
def eth_bench_solver(
    cot: bool = False, assist: Assist | None = None, tool_rounds: int = 10
) -> Solver:
    """Dispatch on the question type stored in sample metadata.

    Args:
        cot: Allow chain-of-thought on multiple choice questions. When false the
            model is told the entire response must be the `ANSWER: X` line.
        assist: Tools and documents to give the model under test. None for a bare run.
        tool_rounds: With an assist, how many rounds of tool calls the model may make
            before it is made to answer.
    """
    single = multiple_choice(cot=cot)
    multi = multiple_choice(cot=cot, multiple_correct=True)
    free_text_system = read_template("system.txt")
    mc_system = read_template("assist_multiple_choice.txt")
    if assist and assist.has_tools:
        mc_system = f"{mc_system} {ASSIST_TOOLS_HINT}"

    async def answer(state: TaskState, generate: Generate) -> TaskState:
        question_type = state.metadata.get("type")
        if question_type == "multiple_choice":
            if assist:
                _prepend_system(state, f"{mc_system}\n\n{assist.system_text}")
            chosen = multi if state.metadata.get("multiple_correct") else single
            return await chosen(state, generate)
        if question_type in ("open", "false_premise"):
            text = free_text_system
            if assist:
                text = f"{text}\n\n{assist.system_text}"
            _prepend_system(state, text)
            return await generate(state)
        raise ValueError(f"sample {state.sample_id} has unknown question type {question_type!r}")

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if assist is None:
            return await answer(state, generate)
        state.metadata["assist"] = assist.name
        if not assist.has_tools:
            return await answer(state, generate)
        # One connection to each MCP server for the whole sample. Listing the tools
        # happens inside it too, otherwise that alone opens and closes a connection.
        async with mcp_connection(assist.tool_sources):
            state = await use_tools(*assist.tool_sources)(state, generate)
            return await answer(state, bounded_tool_use(generate, tool_rounds))

    return solve
