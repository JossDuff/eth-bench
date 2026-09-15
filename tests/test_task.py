"""The eth_bench task: section and type filters, and the metrics it reports."""

import subprocess
import sys

import pytest
from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model

from eth_bench.dataset import load_dataset, sections
from eth_bench.tasks import eth_bench


def _sections_in(task):
    return {s.metadata["section"] for s in task.dataset}


def test_default_task_has_every_question():
    assert len(eth_bench().dataset) == len(load_dataset())
    assert _sections_in(eth_bench()) == set(sections())


def test_sections_filter_accepts_string_or_list():
    assert _sections_in(eth_bench(sections="eips")) == {"eips"}
    assert _sections_in(eth_bench(sections="eips, consensus")) == {"eips", "consensus"}
    assert _sections_in(eth_bench(sections=["history", "crops"])) == {"history", "crops"}


def test_types_filter():
    task = eth_bench(types="false_premise")
    assert {s.metadata["type"] for s in task.dataset} == {"false_premise"}


def test_unknown_section_or_type_is_an_error():
    with pytest.raises(ValueError, match="unknown sections"):
        eth_bench(sections="eip")
    with pytest.raises(ValueError, match="unknown types"):
        eth_bench(types="essay")


def test_shuffle_seed_none_keeps_file_order():
    ordered = {s.id: s.choices for s in eth_bench(shuffle_seed=None).dataset if s.choices}
    from_files = {s.id: s.choices for s in load_dataset(shuffle_seed=None) if s.choices}
    assert ordered == from_files


def test_reported_metrics_break_down_by_section_type_and_difficulty(tmp_path):
    grader = get_model(
        "mockllm/model",
        custom_outputs=lambda *_: ModelOutput.from_content("mockllm/model", "GRADE: CORRECT"),
    )
    [log] = eval(
        eth_bench(),
        model="mockllm/model",
        model_roles={"grader": grader},
        log_dir=str(tmp_path),
        display="none",
    )
    assert log.status == "success", log.error
    metrics = {name: m.value for entry in log.results.scores for name, m in entry.metrics.items()}

    for section in sections():
        for suffix in ("", "_stderr", "_correct_given_attempted", "_not_attempted"):
            assert f"{section}{suffix}" in metrics, f"missing {section}{suffix}"
    # Free-text answers were all graded CORRECT; the mock never answers MC with a letter.
    assert metrics["hallucination"] == 1.0
    assert 0.0 < metrics["all"] < 1.0
    assert metrics["all"] == pytest.approx(
        sum(metrics[section] for section in sections()) / len(sections())
    )
    assert metrics["all_stderr"] > 0.0
    assert metrics["all_correct_given_attempted"] == 1.0
    assert metrics["all_not_attempted"] == 0.0
    assert metrics["type_multiple_choice"] == 0.0
    assert metrics["type_open"] == 1.0
    assert metrics["type_false_premise"] == 1.0
    assert "difficulty_recall" in metrics


def test_cli_finds_the_task_through_the_entry_point(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            "eth_bench",
            "-T",
            "sections=history",
            "--model",
            "mockllm/model",
            "--model-role",
            "grader=mockllm/model",
            "--limit",
            "2",
            "--log-dir",
            str(tmp_path),
            "--display",
            "none",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.glob("*.eval"))
