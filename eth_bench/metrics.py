"""Metrics beyond Inspect's built-in accuracy and stderr.

Both are borrowed from SimpleQA. They only carry information for questions graded
three ways (open and false-premise); multiple choice answers are always CORRECT or
INCORRECT and so always count as attempted.

These metrics need the C / I / N letters intact. Inspect's default "mean" epoch
reducer converts them to floats first, which makes NOT_ATTEMPTED look like INCORRECT.
The task therefore uses the "mode" reducer (see tasks.py); `--epochs N` on the command
line keeps it, `--epochs-reducer mean` would not.
"""

import logging

from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Metric, SampleScore, metric

logger = logging.getLogger(__name__)

GRADES = (CORRECT, INCORRECT, NOANSWER)


def _grades_intact(scores: list[SampleScore], metric_name: str) -> bool:
    bad = [s.score.value for s in scores if s.score.value not in GRADES]
    if bad:
        logger.warning(
            "%s: %d of %d score values are not C/I/N letters (e.g. %r). The epoch reducer "
            "probably converted them to numbers; use the mode reducer. Reporting NaN.",
            metric_name,
            len(bad),
            len(scores),
            bad[0],
        )
        return False
    return True


@metric
def correct_given_attempted() -> Metric:
    """CORRECT / (CORRECT + INCORRECT).

    Rewards a model that says it does not know instead of guessing wrong.
    """

    def compute(scores: list[SampleScore]) -> float:
        if not _grades_intact(scores, "correct_given_attempted"):
            return float("nan")
        attempted = [s for s in scores if s.score.value in (CORRECT, INCORRECT)]
        if not attempted:
            return 0.0
        correct = sum(1 for s in attempted if s.score.value == CORRECT)
        return correct / len(attempted)

    return compute


@metric
def not_attempted_rate() -> Metric:
    """Fraction of answers graded NOT_ATTEMPTED."""

    def compute(scores: list[SampleScore]) -> float:
        if not _grades_intact(scores, "not_attempted_rate"):
            return float("nan")
        if not scores:
            return 0.0
        return sum(1 for s in scores if s.score.value == NOANSWER) / len(scores)

    return compute
