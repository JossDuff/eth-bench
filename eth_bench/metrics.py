"""Metrics beyond Inspect's built-in accuracy and stderr.

Both are borrowed from SimpleQA and only apply to the free-text question types
(open and false-premise), which are graded three ways. Multiple choice answers are
always CORRECT or INCORRECT, so including them would dilute both numbers with the
share of multiple choice questions in the run.

Each metric reports a value per section plus an "all" value that is the mean over
sections, matching how the overall accuracy is reported.

They are declared with `scores="unreduced"`, the same contract as Inspect's own
`frequency()` metric, so they receive the raw C / I / N letters for every epoch
regardless of which epoch reducer is configured.
"""

from collections import defaultdict
from collections.abc import Callable
from statistics import mean

from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Metric, SampleScore, Value, metric

FREE_TEXT_TYPES = ("open", "false_premise")


def _free_text(scores: list[SampleScore]) -> list[SampleScore]:
    return [
        s
        for s in scores
        if (s.sample_metadata or {}).get("type") in FREE_TEXT_TYPES
        and s.score.value in (CORRECT, INCORRECT, NOANSWER)
    ]


def _by_section(scalar: Callable[[list[SampleScore]], float | None], label: str) -> Metric:
    """Apply a scalar metric to the free-text scores of each section, plus "all".

    Rows are named `<section>_<label>` and the aggregate `all_<label>`, because
    Inspect flattens grouped results into the task's single metrics list. A section
    where the metric is undefined (for example nothing was attempted) gets no row and
    does not drag the "all" mean down.
    """

    def compute(scores: list[SampleScore]) -> Value:
        by_section: dict[str, list[SampleScore]] = defaultdict(list)
        for s in _free_text(scores):
            by_section[str((s.sample_metadata or {}).get("section"))].append(s)
        result: dict[str, float] = {}
        for section in sorted(by_section):
            value = scalar(by_section[section])
            if value is not None:
                result[f"{section}_{label}"] = value
        if result:
            result[f"all_{label}"] = mean(result.values())
        return result

    return compute


def _correct_given_attempted(scores: list[SampleScore]) -> float | None:
    attempted = [s for s in scores if s.score.value in (CORRECT, INCORRECT)]
    if not attempted:
        return None
    return sum(1 for s in attempted if s.score.value == CORRECT) / len(attempted)


def _not_attempted_rate(scores: list[SampleScore]) -> float | None:
    if not scores:
        return None
    return sum(1 for s in scores if s.score.value == NOANSWER) / len(scores)


@metric(scores="unreduced")
def correct_given_attempted() -> Metric:
    """CORRECT / (CORRECT + INCORRECT) over free-text questions, per section.

    Rewards a model that says it does not know instead of guessing wrong.
    """
    return _by_section(_correct_given_attempted, "correct_given_attempted")


@metric(scores="unreduced")
def not_attempted_rate() -> Metric:
    """Fraction of free-text answers graded NOT_ATTEMPTED, per section."""
    return _by_section(_not_attempted_rate, "not_attempted")
