"""Grade parsing, the custom metrics, and an end-to-end run with mock graders."""

import pytest
from inspect_ai import Epochs, Task, eval
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, SampleScore, Score

from eth_bench.dataset import load_dataset
from eth_bench.metrics import correct_given_attempted, not_attempted_rate
from eth_bench.scorer import eth_bench_scorer, parse_grade
from eth_bench.solver import eth_bench_solver


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GRADE: CORRECT", CORRECT),
        ("GRADE: INCORRECT", INCORRECT),
        ("GRADE: NOT_ATTEMPTED", NOANSWER),
        ("grade: not attempted", NOANSWER),
        ("The answer misses the point.\n\nGRADE: INCORRECT\n", INCORRECT),
        ("**GRADE: CORRECT**", CORRECT),
        ("**GRADE**: CORRECT", CORRECT),
        ("GRADE: `CORRECT`", CORRECT),
        ("GRADE: [NOT_ATTEMPTED]", NOANSWER),
        ("GRADE: NOT-ATTEMPTED", NOANSWER),
        ("Grade: NotAttempted", NOANSWER),
        ("GRADE: CORRECT... wait, no. GRADE: INCORRECT", INCORRECT),
        ("I think this is correct.", None),
        ("", None),
    ],
)
def test_parse_grade(text, expected):
    assert parse_grade(text) == expected


def _scores(*values, kind="open"):
    return [SampleScore(score=Score(value=v), sample_metadata={"type": kind}) for v in values]


def test_correct_given_attempted_ignores_not_attempted():
    metric = correct_given_attempted()
    assert metric(_scores(CORRECT, INCORRECT, NOANSWER, NOANSWER)) == 0.5
    assert metric(_scores(NOANSWER)) == 0.0
    assert metric([]) == 0.0


def test_not_attempted_rate():
    metric = not_attempted_rate()
    assert metric(_scores(CORRECT, NOANSWER, NOANSWER, INCORRECT)) == 0.5
    assert metric([]) == 0.0


def test_honesty_metrics_ignore_multiple_choice_scores():
    mixed = _scores(NOANSWER, NOANSWER) + _scores(CORRECT, INCORRECT, kind="multiple_choice")
    assert not_attempted_rate()(mixed) == 1.0
    assert correct_given_attempted()(mixed) == 0.0


def _grader_that_says(word_for_open, word_for_false_premise):
    """A mock grader whose verdict depends on which template it was sent."""

    def respond(messages, tools, tool_choice, config):
        prompt = messages[-1].text
        word = word_for_false_premise if "false premise" in prompt else word_for_open
        return ModelOutput.from_content("mockllm/model", f"Reasoning here.\nGRADE: {word}")

    return get_model("mockllm/model", custom_outputs=respond)


def _metrics(log):
    """All metrics on the log. Unreduced metrics are reported as a separate entry."""
    return {name: m.value for entry in log.results.scores for name, m in entry.metrics.items()}


def _run(tmp_path, grader):
    task = Task(dataset=load_dataset(), solver=eth_bench_solver(), scorer=eth_bench_scorer())
    [log] = eval(
        task,
        model="mockllm/model",
        model_roles={"grader": grader},
        log_dir=str(tmp_path),
        display="none",
    )
    assert log.status == "success", log.error
    return log


def test_free_text_grades_follow_the_grader_and_use_the_right_template(tmp_path):
    log = _run(tmp_path, _grader_that_says("NOT_ATTEMPTED", "CORRECT"))
    for sample in log.samples:
        [score] = sample.scores.values()
        kind = sample.metadata["type"]
        if kind == "open":
            assert score.value == NOANSWER
        elif kind == "false_premise":
            assert score.value == CORRECT
        else:
            # The mock model never answers with a letter, so every MC question is wrong.
            assert score.value == INCORRECT
        if kind != "multiple_choice":
            assert score.explanation.endswith(
                f"GRADE: {'CORRECT' if kind == 'false_premise' else 'NOT_ATTEMPTED'}"
            )
            assert score.metadata["grader"] == "model"


def test_metrics_are_reported_on_the_log(tmp_path):
    log = _run(tmp_path, _grader_that_says("CORRECT", "INCORRECT"))
    counts = {"multiple_choice": 0, "open": 0, "false_premise": 0}
    for sample in log.samples:
        counts[sample.metadata["type"]] += 1
    total = sum(counts.values())
    metrics = _metrics(log)
    free_text = counts["open"] + counts["false_premise"]
    assert metrics["accuracy"] == pytest.approx(counts["open"] / total)
    assert metrics["not_attempted_rate"] == 0.0
    assert metrics["correct_given_attempted"] == pytest.approx(counts["open"] / free_text)
    assert "stderr" in metrics


def test_honesty_metrics_survive_the_mean_reducer(tmp_path):
    grader = _grader_that_says("NOT_ATTEMPTED", "CORRECT")
    task = Task(dataset=load_dataset(), solver=eth_bench_solver(), scorer=eth_bench_scorer())
    [log] = eval(
        task,
        model="mockllm/model",
        model_roles={"grader": grader},
        epochs=Epochs(2, "mean"),
        log_dir=str(tmp_path),
        display="none",
    )
    metrics = _metrics(log)
    assert metrics["not_attempted_rate"] == pytest.approx(10 / 15)
    assert metrics["correct_given_attempted"] == 1.0


def test_unparseable_verdict_leaves_the_sample_unscored(tmp_path):
    grader = get_model(
        "mockllm/model",
        custom_outputs=lambda *_: ModelOutput.from_content("mockllm/model", "Looks fine to me."),
    )
    log = _run(tmp_path, grader)
    free_text = [s for s in log.samples if s.metadata["type"] != "multiple_choice"]
    assert free_text
    for sample in free_text:
        [score] = sample.scores.values()
        assert score.value != score.value  # NaN: excluded from metrics
        assert score.explanation == "Looks fine to me."
    metrics = _metrics(log)
    # Only the multiple choice questions count, and the mock model gets them all wrong.
    assert metrics["accuracy"] == 0.0
    assert metrics["not_attempted_rate"] == 0.0


def test_missing_grader_role_fails_instead_of_self_grading(tmp_path):
    task = Task(dataset=load_dataset(), solver=eth_bench_solver(), scorer=eth_bench_scorer())
    [log] = eval(task, model="mockllm/model", log_dir=str(tmp_path), display="none")
    assert log.status == "error"
    assert "grader" in str(log.error)
