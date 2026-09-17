"""The benchmark task.

One parameterized task covers every section, following the pattern the Inspect Evals
collection uses for MMLU: sections are a task parameter and a dataset filter, and
the per-section breakdown comes from grouped metrics.

    inspect eval eth_bench --model <model> --model-role grader=<grader>
    inspect eval eth_bench -T sections=eips,consensus --model <model> --model-role grader=<grader>
    inspect eval eth_bench -T assist=wikipethia --model <model> --model-role grader=<grader>
"""

from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import accuracy, grouped, stderr

from eth_bench.assist import MAX_TOOL_OUTPUT_BYTES, load_assist
from eth_bench.dataset import QUESTION_TYPES, load_dataset
from eth_bench.dataset import sections as all_sections
from eth_bench.metrics import correct_given_attempted, not_attempted_rate
from eth_bench.scorer import eth_bench_scorer
from eth_bench.solver import eth_bench_solver


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return list(value)


def _check_known(kind: str, wanted: list[str], known: list[str]) -> None:
    unknown = sorted(set(wanted) - set(known))
    if unknown:
        raise ValueError(f"unknown {kind} {unknown}; choose from {sorted(known)}")


@task
def eth_bench(
    sections: str | list[str] | None = None,
    types: str | list[str] | None = None,
    cot: bool = False,
    shuffle_seed: int | None = 42,
    assist: str | None = None,
    tool_rounds: int = 10,
    assist_message_limit: int | None = None,
) -> Task:
    """Ethereum knowledge benchmark.

    Args:
        sections: Section name or comma-separated list. Default: every section.
        types: Question type or comma-separated list (multiple_choice, open,
            false_premise). Default: every type.
        cot: Allow chain-of-thought on multiple choice questions. Default: the
            whole response must be the `ANSWER: X` line.
        shuffle_seed: Seed for shuffling answer choices. Same seed, same order.
        assist: Name of a bundled assist (a file in `assists/`) or path to an assist
            YAML file, giving the model under test MCP tools and/or skill documents
            (see assist.py). Default: a bare run.
        tool_rounds: With an assist, how many rounds of tool calls the model may make
            before it is made to answer with tools disabled.
        assist_message_limit: With an assist, an optional hard cap on the messages a
            sample may reach. Tool rounds already bound the conversation; set this
            only as a backstop. The solver stops calling tools early to leave room
            for the final answer.
    """
    dataset = load_dataset(shuffle_seed)

    wanted_sections = _as_list(sections)
    if wanted_sections:
        _check_known("sections", wanted_sections, all_sections())
        dataset = dataset.filter(
            lambda s: s.metadata["section"] in wanted_sections,
            name=f"eth_bench[{','.join(wanted_sections)}]",
        )

    wanted_types = _as_list(types)
    if wanted_types:
        _check_known("types", wanted_types, list(QUESTION_TYPES))
        dataset = dataset.filter(lambda s: s.metadata["type"] in wanted_types)

    loaded_assist = load_assist(assist) if assist else None
    name = "eth_bench" if loaded_assist is None else f"eth_bench_{loaded_assist.name}"

    return Task(
        dataset=dataset,
        solver=eth_bench_solver(cot=cot, assist=loaded_assist, tool_rounds=tool_rounds),
        scorer=eth_bench_scorer(),
        message_limit=assist_message_limit if loaded_assist else None,
        # Inspect truncates tool output to 16 KiB by default; skill documents are
        # bigger than that and a silently middle-truncated document is worse than none.
        config=GenerateConfig(max_tool_output=MAX_TOOL_OUTPUT_BYTES if loaded_assist else None),
        metadata={"assist": loaded_assist.name} if loaded_assist else None,
        # Inspect flattens each grouped metric into the metrics list, so every group
        # gets an explicit name. "all" is the equal-weighted mean over sections.
        metrics=[
            grouped(accuracy(), "section", all="groups"),
            grouped(
                stderr(),
                "section",
                all="groups",
                name_template="{group_name}_stderr",
                all_label="all_stderr",
            ),
            grouped(accuracy(), "type", all=False, name_template="type_{group_name}"),
            grouped(accuracy(), "difficulty", all=False, name_template="difficulty_{group_name}"),
            correct_given_attempted(),
            not_attempted_rate(),
        ],
        name=name,
    )
