"""Every question file in questions/ must parse and validate.

This is the check contributors run after adding a question.
"""

import pytest

from eth_bench.dataset import load_dataset, load_question_file, question_files, sections

ALL_FILES = [path for section in sections() for path in question_files(section)]


def test_every_section_has_questions():
    for section in sections():
        assert question_files(section), f"section {section!r} has no question files"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_question_file_is_valid(path):
    questions = load_question_file(path)
    assert questions, f"{path} contains no questions"


def test_question_ids_are_globally_unique():
    dataset = load_dataset(shuffle_seed=None)
    ids = [sample.id for sample in dataset]
    assert len(ids) == len(set(ids))
