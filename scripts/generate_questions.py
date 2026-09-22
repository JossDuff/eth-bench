"""Draft benchmark questions with a model, for human review.

    uv run python scripts/generate_questions.py                 # every section, 10 each
    uv run python scripts/generate_questions.py -s eips -n 5    # one section
    uv run python scripts/generate_questions.py --model gpt-5.6-terra

The model is given CONTRIBUTING.md, the ids and texts of the section's existing
questions (so it does not repeat them), and a few existing questions as format
examples. Its output is parsed with the same loader the benchmark uses, so every
draft that lands in `drafts/<section>.yaml` is structurally valid. Anything that
fails validation, uses the wrong type for its section, or reuses an id goes to
`drafts/<section>.rejected.yaml` with the reason.

Drafts are not questions yet. Every answer key must be checked against a primary
source before it is moved into `questions/`.

Needs OPENAI_API_KEY in the environment or in .env.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from eth_bench.dataset import Question, load_questions, sections

ROOT = Path(__file__).resolve().parent.parent

SYSTEM = """\
You write questions for eth-bench, a benchmark of Ethereum knowledge for language
models. The contributing guide below is the specification: follow its schema, its
three question types, and its writing rules exactly.

{contributing}

Additional requirements for this batch:

- Hard but unambiguous. Prefer exact constants, computed values, mechanisms, and
  behaviour that a model with shallow knowledge gets wrong. Avoid definitions a
  search engine answers in one line.
- Every question must be answerable from a primary source (EIP text, consensus or
  execution specs, Solidity docs, EF blog) and must cite it in `source`.
- If the answer depends on a fork or a compiler version, say so in the question.
- Mix types and difficulties as the guide asks. In the `hallucination` section
  every question is `false_premise`; in every other section none is.
- Do not repeat or lightly reword any existing question, in any section. Ids must
  be new, lowercase, hyphenated, short (at most five words), and start with the
  section's usual prefix.
- Output ONLY a YAML list of questions in the schema. No prose, no code fences.
"""

USER = """\
Section: `{section}`
{scope}

Existing questions across every section, and drafts already written for other
sections. Do not duplicate or lightly reword any of them, whichever section they
are in; a fact already tested anywhere in the benchmark is off limits:
{existing}
{extra_context}

Format examples from other sections:
{examples}

Write exactly {n} new questions for the `{section}` section.
"""

SECTION_SCOPE = {
    "eips": "Contents, motivation, mechanics, and status of specific EIPs.",
    "ercs": "Application-layer standards: tokens, interfaces, metadata, account abstraction.",
    "consensus": "Beacon chain: Gasper, slots and epochs, attestations, finality, slashing, validators.",
    "execution": "EVM, gas, transactions, fee market, state, blocks.",
    "history": "Network upgrades from Frontier onward, incidents, the DAO fork, the Merge.",
    "crops": (
        "The Ethereum Foundation's mandate and its CROPS values as they apply to the "
        "protocol and ecosystem: censorship resistance (inclusion lists, PBS and relay "
        "censorship, encrypted mempools, forced inclusion), open source and free "
        "licensing (which licenses count, relicensing, source-available), privacy at the "
        "protocol and wallet layer (stealth addresses, shielded pools, privacy pools, "
        "viewing keys), and protocol security as the mandate frames it (client diversity, "
        "the walkaway test, simplicity, governance minimisation). Questions should test "
        "knowledge of these mechanisms and of the mandate's own arguments. General "
        "smart-contract security (reentrancy, signatures, encoding) belongs in other "
        "sections and must not appear here."
    ),
    "hallucination": "False-premise questions only: real things with a wrong attribute.",
    "misc": "Layer 2, MEV and PBS, roadmap, networking, JSON-RPC and Engine API.",
    "solidity": "The Solidity language and compiler: semantics, ABI, storage layout, security.",
}


def existing_summary(section: str, out: Path) -> str:
    """Every live question in every section, plus drafts already on disk for the other
    sections, so the model cannot repeat a question that lives elsewhere."""
    lines = []
    for other in sections():
        for q in load_questions(other):
            first = q.question.strip().splitlines()[0]
            lines.append(f"- [{other}] {q.id}: {first[:100]}")
    for path in sorted(out.glob("*.yaml")):
        if path.stem == section or path.stem.endswith(".rejected"):
            continue
        for record in yaml.load(path.read_text(), Loader=yaml.BaseLoader) or []:
            first = str(record.get("question", "")).strip().splitlines()[0]
            lines.append(f"- [draft {path.stem}] {record.get('id')}: {first[:100]}")
    return "\n".join(lines) or "(none yet)"


MANDATE_URL = "https://ethereum.foundation/ef-mandate.pdf"


def extra_context(section: str, out: Path) -> str:
    """Section-specific reference text. For crops, the EF Mandate itself."""
    if section != "crops":
        return ""
    cached = out / "ef-mandate.txt"
    if not cached.exists():
        pdf = out / "ef-mandate.pdf"
        if not pdf.exists():
            pdf.write_bytes(httpx.get(MANDATE_URL, follow_redirects=True, timeout=60).content)
        try:
            subprocess.run(["pdftotext", "-layout", str(pdf), str(cached)], check=True)
        except (OSError, subprocess.CalledProcessError):
            print("warning: pdftotext unavailable; crops drafts will lack the mandate text")
            return ""
    text = cached.read_text()
    return (
        f"\nReference text, the EF Mandate (draw the crops questions from it and cite it as "
        f"{MANDATE_URL} in `source`):\n\n{text[:60000]}\n"
    )


def format_examples(section: str) -> str:
    """One existing question of each type, drawn from other sections."""
    wanted = ["multiple_choice", "open", "false_premise"]
    picked: list[str] = []
    for other in sections():
        if other == section:
            continue
        for q in load_questions(other):
            if q.type in wanted:
                wanted.remove(q.type)
                picked.append(dump([q.model_dump(exclude_none=True, exclude_defaults=True)]))
        if not wanted:
            break
    return "\n".join(picked)


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data or len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_presenter)


def dump(items: list[dict]) -> str:
    return yaml.dump(items, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=88)


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text


def generate(client: OpenAI, model: str, section: str, n: int, out: Path) -> str:
    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    messages = [
        {"role": "system", "content": SYSTEM.format(contributing=contributing)},
        {
            "role": "user",
            "content": USER.format(
                section=section,
                scope=SECTION_SCOPE.get(section, ""),
                existing=existing_summary(section, out),
                extra_context=extra_context(section, out),
                examples=format_examples(section),
                n=n,
            ),
        },
    ]
    response = client.chat.completions.create(
        model=model, messages=messages, max_completion_tokens=24000
    )
    return response.choices[0].message.content or ""


def validate(section: str, raw_text: str, taken: set[str]) -> tuple[list[dict], list[dict]]:
    """Split model output into records that pass the benchmark's own checks and rejects."""
    try:
        raw = yaml.load(strip_fences(raw_text), Loader=yaml.BaseLoader)
    except yaml.YAMLError as e:
        return [], [{"error": f"output was not valid YAML: {e}", "raw": raw_text}]
    if not isinstance(raw, list):
        return [], [{"error": "output was not a YAML list", "raw": raw_text}]

    accepted: list[dict] = []
    rejected: list[dict] = []
    for record in raw:
        if not isinstance(record, dict):
            rejected.append({"error": "item is not a mapping", "item": record})
            continue
        try:
            q = Question.model_validate(record)
        except ValidationError as e:
            rejected.append({"error": str(e).splitlines()[0], "item": record})
            continue
        if (section == "hallucination") != (q.type == "false_premise"):
            rejected.append(
                {"error": f"type {q.type} is not allowed in section {section}", "item": record}
            )
            continue
        if q.id in taken:
            rejected.append({"error": f"id {q.id} already exists", "item": record})
            continue
        taken.add(q.id)
        accepted.append(q.model_dump(exclude_none=True, exclude_defaults=True))
    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-s", "--sections", nargs="*", default=None, help="sections to draft (default: all)"
    )
    parser.add_argument("-n", type=int, default=10, help="questions per section")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--out", default="drafts", help="output directory")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI()
    out = ROOT / args.out
    out.mkdir(exist_ok=True)

    taken = {q.id for s in sections() for q in load_questions(s)}
    total_ok = total_bad = 0
    for section in args.sections or sections():
        print(f"{section}: asking {args.model} for {args.n} questions...", flush=True)
        text = generate(client, args.model, section, args.n, out)
        accepted, rejected = validate(section, text, taken)
        (out / f"{section}.yaml").write_text(dump(accepted) if accepted else "[]\n")
        if rejected:
            (out / f"{section}.rejected.yaml").write_text(dump(rejected))
        total_ok += len(accepted)
        total_bad += len(rejected)
        print(f"{section}: {len(accepted)} accepted, {len(rejected)} rejected", flush=True)
    print(
        f"\n{total_ok} drafts in {out}/, {total_bad} rejected. Review every answer key before moving any into questions/."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
