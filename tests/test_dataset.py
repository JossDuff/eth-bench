"""Behaviour of the loader itself, using inline questions rather than the real files."""

import pytest
from pydantic import ValidationError

from eth_bench.dataset import Question, QuestionFileError, load_dataset, load_question_file

MC = {
    "id": "sample-mc",
    "type": "multiple_choice",
    "question": "Pick B.",
    "choices": ["a", "b", "c", "d"],
    "answer": "B",
}
OPEN = {"id": "sample-open", "type": "open", "question": "Why?", "answer": "Because."}


def test_multiple_choice_sample_has_letter_target():
    sample = Question.model_validate(MC).to_sample("demo")
    assert sample.target == "B"
    assert sample.choices == ["a", "b", "c", "d"]
    assert sample.metadata["section"] == "demo"
    assert sample.metadata["type"] == "multiple_choice"


def test_open_sample_has_text_target_and_no_choices():
    sample = Question.model_validate(OPEN).to_sample("demo")
    assert sample.target == "Because."
    assert sample.choices is None


def test_multiple_correct_target_is_a_list():
    q = Question.model_validate({**MC, "answer": "A, C", "multiple_correct": True})
    assert q.to_sample("demo").target == ["A", "C"]


def test_numeric_choices_and_answers_become_strings():
    q = Question.model_validate({**MC, "choices": [16, 32, 64, 128]})
    assert q.choices == ["16", "32", "64", "128"]
    q = Question.model_validate({**OPEN, "answer": 42})
    assert q.answer == "42"


@pytest.mark.parametrize(
    "bad",
    [
        {**MC, "answer": "E"},  # letter out of range
        {**MC, "answer": "A, B"},  # two letters without multiple_correct
        {**MC, "answer": "A", "multiple_correct": True},  # one letter with multiple_correct
        {**MC, "choices": ["a"]},  # too few choices
        {**MC, "choices": ["a", "a", "b"]},  # duplicate choices
        {**MC, "choices": None},  # MC without choices
        {**OPEN, "choices": ["a", "b"]},  # open question with choices
        {**OPEN, "type": "essay"},  # unknown type
        {**OPEN, "difficulty": "hard"},  # unknown difficulty
        {**OPEN, "id": "Has Spaces"},  # bad id
        {**OPEN, "fork": "london"},  # unknown field
        {**MC, "choices": ["yes", True, "b"]},  # unquoted YAML boolean
    ],
    ids=lambda d: str(sorted(d.items()))[:60],
)
def test_invalid_questions_are_rejected(bad):
    with pytest.raises(ValidationError):
        Question.model_validate(bad)


def test_file_errors_name_the_file_and_question(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("- id: broken-one\n  type: open\n  question: q\n  answer: a\n  choices: [x]\n")
    with pytest.raises(QuestionFileError, match=r"broken\.yaml \(broken-one\)"):
        load_question_file(path)


def test_top_level_must_be_a_list(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("id: not-a-list\n")
    with pytest.raises(QuestionFileError, match="expected a list"):
        load_question_file(path)


def test_shuffle_is_deterministic_and_keeps_the_right_answer():
    unshuffled = {s.id: s for s in load_dataset(shuffle_seed=None)}
    first = {s.id: s for s in load_dataset(shuffle_seed=7)}
    second = {s.id: s for s in load_dataset(shuffle_seed=7)}
    for sample_id, original in unshuffled.items():
        if not original.choices:
            continue
        assert first[sample_id].choices == second[sample_id].choices
        assert first[sample_id].target == second[sample_id].target
        original_answer = original.choices["ABCDEFGH".index(original.target)]
        shuffled = first[sample_id]
        assert shuffled.choices["ABCDEFGH".index(shuffled.target)] == original_answer
    assert any(
        first[i].choices != unshuffled[i].choices for i in unshuffled if unshuffled[i].choices
    )
