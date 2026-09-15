"""Metrics beyond Inspect's built-in accuracy and stderr.

Both are borrowed from SimpleQA and only apply to the free-text question types
(open and false-premise), which are graded three ways. Multiple choice answers are
always CORRECT or INCORRECT, so including them would dilute both numbers with the
share of multiple choice questions in the run.

They are declared with `scores="unreduced"`, the same contract as Inspect's own
`frequency()` metric, so they receive the raw C / I / N letters for every epoch
regardless of which epoch reducer is configured.
"""

from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Metric, SampleScore, metric

FREE_TEXT_TYPES = ("open", "false_premise")


def _free_text(scores: list[SampleScore]) -> list[SampleScore]:
    return [
        s
        for s in scores
        if (s.sample_metadata or {}).get("type") in FREE_TEXT_TYPES
        and s.score.value in (CORRECT, INCORRECT, NOANSWER)
    ]


@metric(scores="unreduced")
def correct_given_attempted() -> Metric:
    """CORRECT / (CORRECT + INCORRECT) over free-text questions.

    Rewards a model that says it does not know instead of guessing wrong.
    """

    def compute(scores: list[SampleScore]) -> float:
        attempted = [s for s in _free_text(scores) if s.score.value in (CORRECT, INCORRECT)]
        if not attempted:
            return 0.0
        correct = sum(1 for s in attempted if s.score.value == CORRECT)
        return correct / len(attempted)

    return compute


@metric(scores="unreduced")
def not_attempted_rate() -> Metric:
    """Fraction of free-text answers graded NOT_ATTEMPTED."""

    def compute(scores: list[SampleScore]) -> float:
        free_text = _free_text(scores)
        if not free_text:
            return 0.0
        return sum(1 for s in free_text if s.score.value == NOANSWER) / len(free_text)

    return compute
