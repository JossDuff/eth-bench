"""Run the solver over the seed questions with Inspect's mock model."""

import pytest
from inspect_ai import Task, eval
from inspect_ai.model import ChatMessageSystem, ChatMessageUser

from eth_bench.dataset import load_dataset
from eth_bench.solver import eth_bench_solver, read_template


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    task = Task(dataset=load_dataset(), solver=eth_bench_solver())
    log_dir = str(tmp_path_factory.mktemp("logs"))
    [log] = eval(task, model="mockllm/model", log_dir=log_dir, display="none")
    assert log.status == "success", log.error
    return {sample.id: sample for sample in log.samples}


def _by_type(samples, question_type):
    return [s for s in samples.values() if s.metadata["type"] == question_type]


def test_every_sample_ran(samples):
    assert len(samples) == len(load_dataset())
    assert all(s.output.completion for s in samples.values())


def test_multiple_choice_prompt_lists_lettered_choices_and_asks_for_answer_line(samples):
    for sample in _by_type(samples, "multiple_choice"):
        [user] = [m for m in sample.messages if isinstance(m, ChatMessageUser)]
        assert "ANSWER: $LETTER" in user.text
        for letter, choice in zip("ABCDEFGH", sample.choices, strict=False):
            assert f"{letter}) {choice}" in user.text
        assert not any(isinstance(m, ChatMessageSystem) for m in sample.messages)


def test_free_text_types_share_one_system_message(samples):
    system_text = read_template("system.txt")
    for question_type in ("open", "false_premise"):
        for sample in _by_type(samples, question_type):
            [system] = [m for m in sample.messages if isinstance(m, ChatMessageSystem)]
            assert system.text == system_text
            [user] = [m for m in sample.messages if isinstance(m, ChatMessageUser)]
            assert user.text == sample.input
            assert "ANSWER:" not in user.text


def test_cot_flag_switches_template(tmp_path):
    dataset = load_dataset().filter(lambda s: s.metadata["type"] == "multiple_choice")
    task = Task(dataset=dataset, solver=eth_bench_solver(cot=True))
    [log] = eval(task, model="mockllm/model", log_dir=str(tmp_path), display="none")
    for sample in log.samples:
        [user] = [m for m in sample.messages if isinstance(m, ChatMessageUser)]
        assert "Think step by step" in user.text
        assert "last line of your response" in user.text
