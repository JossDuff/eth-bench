"""One scorer for every question type.

Multiple choice answers are graded by Inspect's built-in `choice` scorer. Open and
false-premise answers are graded by a second model, the `grader` role, which reads
the question, the answer key, and the response and returns CORRECT, INCORRECT, or
NOT_ATTEMPTED. Those map onto Inspect's C, I, and N score values.

The grader is chosen with `--model-role grader=<model>` and is required: without it
the model under test would silently grade its own answers.
"""

import re

from inspect_ai.model import get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    Score,
    Scorer,
    Target,
    accuracy,
    choice,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

from eth_bench.metrics import correct_given_attempted, not_attempted_rate
from eth_bench.solver import read_template

GRADER_ROLE = "grader"

GRADE_VALUES = {
    "CORRECT": CORRECT,
    "INCORRECT": INCORRECT,
    "NOT_ATTEMPTED": NOANSWER,
}

# Tolerates markdown around the label and the value: **GRADE**: `CORRECT`, [NOT-ATTEMPTED], etc.
_GRADE_LINE = re.compile(
    r"GRADE\W{0,6}(CORRECT|INCORRECT|NOT[_\s-]?ATTEMPTED)\b",
    re.IGNORECASE,
)


def parse_grade(text: str) -> str | None:
    """Pull the grade out of a grader's response. The last GRADE line wins.

    Returns Inspect's C / I / N value, or None if no grade line was found.
    """
    matches = _GRADE_LINE.findall(text)
    if not matches:
        return None
    word = matches[-1].upper()
    if word.startswith("NOT"):
        word = "NOT_ATTEMPTED"
    return GRADE_VALUES[word]


@scorer(metrics=[accuracy(), stderr(), correct_given_attempted(), not_attempted_rate()])
def eth_bench_scorer() -> Scorer:
    multiple_choice_scorer = choice()

    async def score(state: TaskState, target: Target) -> Score:
        question_type = state.metadata.get("type")
        if question_type == "multiple_choice":
            return await multiple_choice_scorer(state, target)
        if question_type not in ("open", "false_premise"):
            raise ValueError(
                f"sample {state.sample_id} has unknown question type {question_type!r}"
            )

        response = state.output.completion
        prompt = read_template(f"grade_{question_type}.txt").format(
            question=state.input_text,
            answer=target.text,
            response=response,
        )
        grader = get_model(role=GRADER_ROLE, required=True)
        verdict = await grader.generate(prompt)
        grade = parse_grade(verdict.completion)
        metadata = {"grader": grader.name}
        if grade is None:
            # A grader that failed to produce a verdict is not the model under
            # test's fault. Leave the sample unscored so metrics skip it; the raw
            # verdict stays visible in `inspect view`.
            return Score.unscored(
                reason="grader_failed",
                answer=response,
                explanation=verdict.completion,
                metadata=metadata,
            )
        return Score(
            value=grade,
            answer=response,
            explanation=verdict.completion,
            metadata=metadata,
        )

    return score
