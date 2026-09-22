"""Import evals from austintgriffith/ethevals and clawdbotatg/eth-evals.

    git clone https://github.com/austintgriffith/ethevals /tmp/ethevals
    git clone https://github.com/clawdbotatg/eth-evals /tmp/eth-evals
    uv run python scripts/import_ethevals.py /tmp/ethevals --eth-evals /tmp/eth-evals

Writes `questions/<section>/ethevals.yaml` and `questions/<section>/eth-evals.yaml` for
every section that receives questions, replacing any earlier import. Each question
keeps its upstream id and links back to its source file.

From eth-evals (MIT) only closed-book tasks with an objective answer are taken: the
`kind: fact` knowledge tasks and the computed `gen-*` tasks. `kind: recommendation`
tasks grade agreement with ethskills' opinions, which eth-evals itself scores apart
from facts, so they are left out. Tasks that ethevals already ported are skipped.

What is converted and how:

- `kind: goal` evals build files in a workspace and are judged on the files. This
  benchmark grades text, so they are skipped.
- Prompts that list lettered options and are graded on the letter become
  `multiple_choice`: the options are lifted out of the prompt into `choices`.
- Other deterministic graders (exact, bigint, regex, json) become `open` questions
  whose answer key states the expected value and how strictly to match it.
- Judged evals (`expect:` rubric lines) become `open` questions whose answer key is
  the rubric. Mentions of `answer.md` are reworded, since there is no file here.

Two evals duplicate facts this benchmark already tests, and one has two identical
options upstream; those three are skipped by id.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://github.com/austintgriffith/ethevals/blob/main/evals/{pillar}/{id}.yaml"

# Where each eval lives here. Pillars that have no counterpart get their own section.
SECTION_BY_ID = {
    # concepts
    "concepts-01-nothing-is-automatic": "building",
    "concepts-02-walkaway-test": "crops",
    "concepts-03-keeper-bounty-math": "building",
    "concepts-04-hyperstructures": "crops",
    "concepts-05-fee-switch-fork": "crops",
    "concepts-06-sybil-resistance": "crops",
    "concepts-07-crops-pillars": "crops",
    "concepts-08-verified-is-not-open": "crops",
    "concepts-09-eip1559-mechanics": "eips",
    "concepts-10-mev-backrun": "misc",
    "concepts-11-spot-price-oracle": "security",
    "concepts-12-blockhash-current": "solidity",
    "concepts-13-eip712-replay": "ercs",
    "concepts-14-eip7702-delegation": "eips",
    "concepts-15-paymaster-deposit": "ercs",
    "concepts-16-peerdas-eip": "eips",
    "concepts-17-forced-inclusion": "crops",
    "concepts-18-admin-power-mechanisms": "crops",
    "concepts-19-why-slashing": "consensus",
    "concepts-20-honesty-live-data": "misc",
    "concepts-22-7702-no-recursion": "eips",
    "concepts-23-7702-bad-tuple": "eips",
    "concepts-25-1271-replay-safe": "ercs",
    # transactions
    "transactions-01-selector-string": "solidity",
    "transactions-02-abi-encode-static": "solidity",
    "transactions-03-decode-calldata": "solidity",
    "transactions-04-dynamic-types": "solidity",
    "transactions-05-struct-argument": "solidity",
    "transactions-06-token-decimals": "ercs",
    "transactions-07-bounded-approve": "ercs",
    "transactions-08-permit-2612": "ercs",
    "transactions-09-event-signature": "solidity",
    "transactions-10-read-a-receipt": "execution",
    "transactions-11-internal-transactions": "execution",
    "transactions-12-effective-gas-price": "execution",
    "transactions-13-nonce-replacement": "execution",
    "transactions-14-gwei-to-wei": "execution",
    "transactions-15-intrinsic-gas": "execution",
    "transactions-16-create2-truncation": "execution",
    "transactions-17-eip55-checksum": "execution",
    "transactions-18-storage-packing": "solidity",
    "transactions-19-nested-calldata": "solidity",
    "transactions-20-decode-a-revert": "solidity",
    "transactions-21-decode-raw-tx": "execution",
    "transactions-22-legacy-v-chainid": "execution",
    "transactions-23-serialize-zero-tx": "execution",
    "transactions-24-7702-self-nonce": "eips",
    "transactions-25-safe-tx-hash": "security",
}
PILLAR_DEFAULT = {"building": "building", "security": "security"}

SKIP = {
    # Already tested here: eip-7702-chain-id-zero and erc-4337-banned-validation-opcodes.
    "concepts-21-7702-chainid-zero",
    "concepts-24-4337-banned-opcodes",
    # Broken upstream: options B and C are byte-identical, so the question has no
    # single right answer as written.
    "transactions-17-eip55-checksum",
}

OPTION_RE = re.compile(r"^\s*([A-H])\)\s+(.+?)\s*$", re.MULTILINE)
ANSWER_LINE_RE = re.compile(
    r"\n?[^\n]*(End your reply|Answer with only|Reply with|Respond with)[^\n]*"
    r"(Answer:|answer line|last line|<letter>|<integer>)[^\n]*\n?",
    re.IGNORECASE,
)
ANSWER_MD_RE = re.compile(r"\n?[^\n]*Write your answer to answer\.md[^\n]*\n?", re.IGNORECASE)


def section_for(ev: dict) -> str:
    return SECTION_BY_ID.get(ev["id"]) or PILLAR_DEFAULT[ev["pillar"]]


def reword_rubric(text: str) -> str:
    text = re.sub(r"\banswer\.md\b", "the response", text)
    return re.sub(r"^the response ", "The response ", text)


def letter_expected(grader: dict | None) -> str | None:
    if not grader:
        return None
    if grader["type"] == "exact" and re.fullmatch(r"[A-H]", str(grader["expect"])):
        return grader["expect"]
    if grader["type"] == "any_of":
        for option in grader["options"]:
            hit = letter_expected(option)
            if hit:
                return hit
    return None


def describe_grader(grader: dict, reference: str | None) -> str:
    t = grader["type"]
    if t == "any_of":
        parts = [describe_grader(o, None) for o in grader["options"]]
        return "Any of the following counts as correct: " + " OR ".join(parts) + "."
    if t == "exact":
        case = " (case-sensitive)" if grader.get("case_sensitive") else " (case-insensitive)"
        return f"The response's final answer must be exactly `{grader['expect']}`{case}."
    if t == "bigint":
        return (
            f"The response's final answer must be the integer {grader['expect']} "
            f"(decimal or the equivalent hex)."
        )
    if t == "numeric":
        return f"The response's final answer must be the number {grader['expect']}."
    if t == "regex":
        ref = f" The reference answer is: {reference}." if reference else ""
        return (
            f"The response's answer must match the pattern `{grader['pattern']}` "
            f"(that is, it must name the concept the pattern captures).{ref}"
        )
    if t == "regex_all":
        pats = ", ".join(f"`{p}`" for p in grader["patterns"])
        ref = f" The reference answer is: {reference}." if reference else ""
        return f"The response must mention every one of these: {pats}.{ref}"
    if t == "json":
        return (
            f"The response must give a JSON object matching {json.dumps(grader['expect'])} "
            f"(other keys may be present)."
        )
    raise ValueError(f"unknown grader type {t}")


def convert(ev: dict) -> dict | None:
    if ev["kind"] != "quiz" or ev["id"] in SKIP:
        return None
    prompt: str = ev["prompt"]
    grader = ev.get("grader")
    source = SOURCE_URL.format(pillar=ev["pillar"], id=ev["id"])
    base: dict = {"id": ev["id"], "type": None, "question": None}

    letter = letter_expected(grader)
    options = OPTION_RE.findall(prompt)
    if letter and len(options) >= 2:
        question = OPTION_RE.sub("", prompt)
        question = ANSWER_LINE_RE.sub("\n", question)
        base.update(
            type="multiple_choice",
            question=question.strip() + "\n",
            choices=[text for _, text in options],
            answer=letter,
            difficulty="understanding",
        )
    elif grader:
        checks = ev.get("checks") or {}
        must_fail = checks.get("must_fail") or []
        wrong = ""
        if must_fail:
            wrong = " Grade INCORRECT for these tempting wrong answers: " + "; ".join(
                f"`{m}`" for m in must_fail
            )
        answer = describe_grader(grader, ev.get("reference")) + wrong
        base.update(
            type="open",
            question=prompt.strip() + "\n",
            answer=answer + "\n",
            difficulty="reasoning"
            if grader["type"] in ("bigint", "exact", "json", "numeric")
            else "recall",
        )
    else:
        rubric = "\n".join(f"- {reword_rubric(' '.join(line.split()))}" for line in ev["expect"])
        question = ANSWER_MD_RE.sub("\n", prompt)
        base.update(
            type="open",
            question=question.strip() + "\n",
            answer=(
                "Grade CORRECT only if the response satisfies every one of these points; "
                "a response that misses any of them is INCORRECT:\n" + rubric + "\n"
            ),
            difficulty="reasoning",
        )
    base["source"] = source
    base["tags"] = ["ethevals", ev["pillar"]]
    return base


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data or len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_presenter)


ETH_EVALS_URL = "https://github.com/clawdbotatg/eth-evals/blob/main/tasks/{file}"

# eth-evals categories follow ethskills' skill files; map each to a section here.
ETH_EVALS_SECTION = {
    "addresses": "building",
    "concepts": "building",
    "contract-reading": "solidity",
    "crops": "crops",
    "cryptoecon": "crops",
    "cypherpunk": "crops",
    "frontend": "building",
    "fundamentals": "misc",
    "gas": "execution",
    "honesty": "misc",
    "indexing": "building",
    "l2s": "misc",
    "mev": "misc",
    "navigation": "building",
    "protocol": "eips",
    "roadmap": "history",
    "security": "security",
    "standards": "ercs",
    "testing": "building",
    "toolchain": "building",
    "tooling": "building",
    "wallets": "building",
    # computed tasks (no `kind`), by file
    "gen-calldata": "solidity",
    "gen-derivations": "execution",
    "gen-gas": "execution",
    "gen-indexing": "solidity",
    "gen-units": "execution",
}


# eth-evals tasks left out because the benchmark already tests the same fact, or
# because they are extra instances of a computation that is already represented.
ETH_EVALS_SKIP = {
    # same fact as an existing question
    "crops-k-01": "crops-what-is-crops",
    "concepts-k-10": "crops-what-is-crops",
    "crops-k-03": "crops-busl-not-free",
    "crops-k-08": "crops-walkaway-test",
    "cypherpunk-k-08": "crops-credible-neutrality-rules",
    "navigation-k-05": "crops-sourcify-vs-etherscan",
    "protocol-k-02": "history-withdrawals-upgrade",
    "protocol-k-03": "eip-7702-what-it-does / wallets-k-01",
    "standards-k-06": "wallets-k-01",
    "fundamentals-k-05": "wallets-k-01",
    "fundamentals-k-08": "gas-k-07",
    "fundamentals-k-09": "pbs-what-it-is",
    "fundamentals-k-10": "roadmap-verkle-to-binary-pivot",
    "protocol-k-07": "roadmap-verkle-to-binary-pivot",
    "roadmap-k-01": "history-next-upgrade-mid-2026",
    "roadmap-k-02": "bal-block-level-access-lists",
    "roadmap-k-03": "history-current-fork-mid-2026",
    "roadmap-k-07": "eip-7251-why-raise-staking-cap",
    "gas-k-02": "protocol-k-01",
    "standards-k-10": "erc-8004-registries",
    "security-k-05": "erc-4626-inflation-attack",
    "l2s-k-03": "execution-create2-address-inputs",
    # honesty probes: one gas-price (concepts-20) and one ETH-price probe are enough
    "honesty-k-03": "concepts-20-honesty-live-data",
    "honesty-k-04": "concepts-20-honesty-live-data",
    "honesty-k-05": "concepts-20-honesty-live-data",
    # extra seeded instances of one computation
    "gas-intrinsic-03": "gas-intrinsic-02",
    "gas-intrinsic-04": "gas-intrinsic-02",
    "gas-basefee-03": "gas-basefee-01",
    "gas-basefee-04": "gas-basefee-01",
    "units-04": "transactions-14-gwei-to-wei",
    "units-05": "units-02",
    "calldata-encgiven-04": "calldata-encgiven-02",
    "calldata-decgiven-04": "calldata-decgiven-02",
}


def convert_eth_evals(task: dict, file: str) -> dict | None:
    """One eth-evals JSONL task to a question, or None if it is not an objective task."""
    kind = task.get("kind")
    if kind == "recommendation":
        return None
    if kind is None and not file.startswith("gen-"):
        return None
    prompt: str = task["prompt"]
    grader = task["grader"]
    base: dict = {"id": task["id"], "type": None, "question": None}
    quote = " ".join(str(task.get("source_quote", "")).split())
    reference = f' Reference from ethskills: "{quote}"' if quote else ""

    letter = letter_expected(grader)
    options = OPTION_RE.findall(prompt)
    if letter and len(options) >= 2:
        question = ANSWER_LINE_RE.sub("\n", OPTION_RE.sub("", prompt))
        base.update(
            type="multiple_choice",
            question=question.strip() + "\n",
            choices=[text for _, text in options],
            answer=letter,
            difficulty="understanding",
        )
    else:
        must_fail = (task.get("checks") or {}).get("must_fail") or []
        wrong = ""
        if must_fail:
            wrong = " Grade INCORRECT for these tempting wrong answers: " + "; ".join(
                f"`{m}`" for m in must_fail
            )
        computed = grader["type"] in ("bigint", "exact", "json", "numeric")
        base.update(
            type="open",
            question=prompt.strip() + "\n",
            answer=describe_grader(grader, task.get("reference")) + reference + wrong + "\n",
            difficulty="reasoning" if computed and file.startswith("gen-") else "recall",
        )
    base["source"] = ETH_EVALS_URL.format(file=file)
    base["tags"] = ["eth-evals", task["category"]]
    return base


def eth_evals_section(task: dict, file: str) -> str:
    stem = file.removesuffix(".jsonl")
    if stem.startswith("gen-"):
        return ETH_EVALS_SECTION[stem]
    return ETH_EVALS_SECTION[task["category"]]


def write_sections(by_section: dict[str, list[dict]], filename: str, header: str) -> None:
    for old in (ROOT / "questions").glob(f"*/{filename}"):
        old.unlink()
    for section, items in sorted(by_section.items()):
        target = ROOT / "questions" / section / filename
        target.parent.mkdir(exist_ok=True)
        target.write_text(
            header + yaml.dump(items, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=88)
        )


def report(label: str, by_section: dict[str, list[dict]], skipped: list[str]) -> None:
    counts = {s: len(v) for s, v in sorted(by_section.items())}
    types = Counter(q["type"] for v in by_section.values() for q in v)
    print(f"{label}: imported {sum(counts.values())} questions; skipped {len(skipped)}")
    for s in skipped:
        print(f"  - {s}")
    print("  by section:", counts)
    print("  by type:", dict(types))


def main(ethevals: Path, eth_evals: Path | None) -> int:
    by_section: dict[str, list[dict]] = {}
    skipped: list[str] = []
    ported: set[str] = set()
    for path in sorted((ethevals / "evals").glob("*/*.yaml")):
        ev = yaml.safe_load(path.read_text())
        src = ev.get("source") or {}
        if src.get("repo") == "clawdbotatg/eth-evals":
            ported.add(src.get("task"))
        converted = convert(ev)
        if converted is None:
            skipped.append(f"{ev['id']} ({ev['kind']})")
            continue
        by_section.setdefault(section_for(ev), []).append(converted)
    write_sections(
        by_section,
        "ethevals.yaml",
        "# Imported from https://github.com/austintgriffith/ethevals by\n"
        "# scripts/import_ethevals.py. Edit the script, not this file.\n\n",
    )
    report("ethevals", by_section, skipped)

    if eth_evals is None:
        return 0
    by_section = {}
    dropped: Counter[str] = Counter()
    taken = {
        q["id"]
        for path in (ROOT / "questions").glob("*/*.yaml")
        if path.name != "eth-evals.yaml"
        for q in (yaml.safe_load(path.read_text()) or [])
        if isinstance(q, dict)
    }
    for path in sorted((eth_evals / "tasks").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            task = json.loads(line)
            if task["id"] in ported:
                dropped["already ported via ethevals"] += 1
                continue
            if task["id"] in taken:
                dropped["id already present"] += 1
                continue
            if task["id"] in ETH_EVALS_SKIP:
                dropped["duplicates a fact already tested"] += 1
                continue
            converted = convert_eth_evals(task, path.name)
            if converted is None:
                dropped[f"kind {task.get('kind')}"] += 1
                continue
            by_section.setdefault(eth_evals_section(task, path.name), []).append(converted)
    write_sections(
        by_section,
        "eth-evals.yaml",
        "# Imported from https://github.com/clawdbotatg/eth-evals (MIT, Austin Griffith)\n"
        "# by scripts/import_ethevals.py. Edit the script, not this file.\n\n",
    )
    report("eth-evals", by_section, [f"{n} x {r}" for r, n in dropped.items()])
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    other = Path(argv[argv.index("--eth-evals") + 1]) if "--eth-evals" in argv else None
    sys.exit(main(Path(argv[0]), other))
