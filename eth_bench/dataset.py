"""Load YAML question files into an Inspect dataset.

Questions live in `questions/<section>/*.yaml`. Each file holds a list of questions.
The section is the directory name; it is not a field in the file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from inspect_ai.dataset import MemoryDataset, Sample
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

QuestionType = Literal["multiple_choice", "open", "false_premise"]
Difficulty = Literal["recall", "understanding", "reasoning"]

QUESTION_TYPES: tuple[str, ...] = ("multiple_choice", "open", "false_premise")
DIFFICULTIES: tuple[str, ...] = ("recall", "understanding", "reasoning")

MIN_CHOICES = 2
MAX_CHOICES = 8

_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LETTERS = "ABCDEFGH"


_EMPTY = ("", "~", "null", "Null", "NULL")


def _empty_to_none(value: object) -> object:
    """Treat a blank or explicit-null optional field as absent.

    Files are read with YAML's BaseLoader, which keeps every scalar as the text the
    author typed (so `0x60` stays `0x60` and `32` stays `32`) but also means an empty
    or `null` value arrives as a string.
    """
    if isinstance(value, str) and value.strip() in _EMPTY:
        return None
    return value


def questions_dir() -> Path:
    """Locate the questions directory.

    Inside an installed wheel the questions are copied into the package. In a
    development checkout they live at the repository root.
    """
    packaged = Path(__file__).parent / "questions"
    if packaged.is_dir():
        return packaged
    return Path(__file__).parent.parent / "questions"


def sections() -> list[str]:
    """All section names, i.e. the subdirectories of the questions directory."""
    return sorted(p.name for p in questions_dir().iterdir() if p.is_dir())


class Question(BaseModel):
    """One benchmark question as written in YAML."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=_ID_PATTERN.pattern)
    type: QuestionType
    question: str = Field(min_length=1)
    choices: list[str] | None = None
    answer: str = Field(min_length=1)
    difficulty: Difficulty | None = None
    source: str | None = None
    tags: list[str] | None = None
    multiple_correct: bool = False

    @field_validator("choices", "difficulty", "source", "tags", mode="before")
    @classmethod
    def _optional_blank_is_none(cls, value: object) -> object:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def _check_shape(self) -> Question:
        if self.type == "multiple_choice":
            self._check_multiple_choice()
        else:
            if self.choices is not None:
                raise ValueError(f"{self.type} questions must not have choices")
            if self.multiple_correct:
                raise ValueError(f"{self.type} questions cannot set multiple_correct")
        return self

    def _check_multiple_choice(self) -> None:
        if not self.choices:
            raise ValueError("multiple_choice questions need choices")
        if not MIN_CHOICES <= len(self.choices) <= MAX_CHOICES:
            raise ValueError(f"need between {MIN_CHOICES} and {MAX_CHOICES} choices")
        if len({c.strip() for c in self.choices}) != len(self.choices):
            raise ValueError("choices must be distinct")
        valid = _LETTERS[: len(self.choices)]
        letters = self.answer_letters()
        if not self.multiple_correct and len(letters) != 1:
            raise ValueError("answer must be a single letter unless multiple_correct is set")
        if self.multiple_correct and len(letters) < 2:
            raise ValueError("multiple_correct questions need at least two answer letters")
        for letter in letters:
            if letter not in valid:
                raise ValueError(f"answer letter {letter!r} is not one of {valid}")
        if len(set(letters)) != len(letters):
            raise ValueError("answer letters must be distinct")

    def answer_letters(self) -> list[str]:
        """Answer letters for a multiple choice question, e.g. ['B'] or ['A', 'C']."""
        return [part.strip() for part in self.answer.split(",") if part.strip()]

    def to_sample(self, section: str) -> Sample:
        target: str | list[str]
        if self.type == "multiple_choice":
            letters = self.answer_letters()
            target = letters if self.multiple_correct else letters[0]
        else:
            target = self.answer.strip()
        return Sample(
            id=self.id,
            input=self.question.strip(),
            choices=self.choices,
            target=target,
            metadata={
                "section": section,
                "type": self.type,
                "difficulty": self.difficulty,
                "source": self.source,
                "tags": self.tags or [],
                "multiple_correct": self.multiple_correct,
            },
        )


class QuestionFileError(ValueError):
    """A question file failed to parse or validate."""


def question_files(section: str) -> list[Path]:
    """The YAML files in one section, in sorted order."""
    directory = questions_dir() / section
    if not directory.is_dir():
        raise QuestionFileError(f"unknown section {section!r}; expected one of {sections()}")
    return sorted(p for p in directory.iterdir() if p.suffix in (".yaml", ".yml"))


def load_question_file(path: Path) -> list[Question]:
    """Parse and validate one YAML file. Raises QuestionFileError with a clear location."""
    with path.open() as f:
        # BaseLoader: every scalar stays exactly as written. safe_load would turn
        # 0x60 into 96, 010 into 8, yes into True, and 2022-09-15 into a date.
        raw = yaml.load(f, Loader=yaml.BaseLoader)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise QuestionFileError(f"{path}: expected a list of questions at the top level")
    questions: list[Question] = []
    for index, record in enumerate(raw):
        if not isinstance(record, dict):
            raise QuestionFileError(f"{path}: item {index} is not a mapping")
        try:
            questions.append(Question.model_validate(record))
        except ValidationError as e:
            label = record.get("id", f"item {index}")
            raise QuestionFileError(f"{path} ({label}): {e}") from e
    return questions


def load_questions(section: str) -> list[Question]:
    """All questions in one section."""
    result: list[Question] = []
    for path in question_files(section):
        result.extend(load_question_file(path))
    return result


def load_dataset(shuffle_seed: int | None = 42) -> MemoryDataset:
    """Every question in every section as an Inspect dataset.

    Choice order is shuffled per sample with the given seed so results are
    reproducible. Pass None to keep the order from the YAML files.
    """
    samples: list[Sample] = []
    seen: dict[str, str] = {}
    for section in sections():
        for question in load_questions(section):
            if question.id in seen:
                raise QuestionFileError(
                    f"duplicate question id {question.id!r} in sections "
                    f"{seen[question.id]!r} and {section!r}"
                )
            seen[question.id] = section
            samples.append(question.to_sample(section))
    dataset = MemoryDataset(samples, name="eth_bench", location=str(questions_dir()))
    if shuffle_seed is not None:
        dataset.shuffle_choices(seed=shuffle_seed)
    return dataset
