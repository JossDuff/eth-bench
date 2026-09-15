"""One solver for every question type.

Multiple choice questions go through Inspect's built-in `multiple_choice` solver,
which formats the lettered options and asks for an `ANSWER: X` line. Open and
false-premise questions get one shared system message and a plain generate. The two
free-text types must be presented identically so nothing hints that a premise may
be false.
"""

from pathlib import Path

from inspect_ai.solver import Generate, Solver, TaskState, multiple_choice, solver, system_message

TEMPLATES_DIR = Path(__file__).parent / "templates"


def read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text().strip()


@solver
def eth_bench_solver(cot: bool = False) -> Solver:
    """Dispatch on the question type stored in sample metadata.

    Args:
        cot: Allow chain-of-thought on multiple choice questions. When false the
            model is told the entire response must be the `ANSWER: X` line.
    """
    single = multiple_choice(cot=cot)
    multi = multiple_choice(cot=cot, multiple_correct=True)
    free_text_system = system_message(read_template("system.txt"))

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        question_type = state.metadata.get("type")
        if question_type == "multiple_choice":
            chosen = multi if state.metadata.get("multiple_correct") else single
            return await chosen(state, generate)
        if question_type in ("open", "false_premise"):
            state = await free_text_system(state, generate)
            return await generate(state)
        raise ValueError(f"sample {state.sample_id} has unknown question type {question_type!r}")

    return solve
