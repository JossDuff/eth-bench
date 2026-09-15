# Contributing questions

Questions are YAML files in `questions/<section>/`. The section is the directory
name. Put a question in any existing file in that directory, or make a new file.
File names are up to you; grouping by topic (`eip-1559.yaml`, `upgrades.yaml`) works
well.

After editing, run:

```sh
uv run pytest
```

Every file is checked. A failure names the file and the question id.

## The three question types

### Multiple choice

The model sees the lettered options and must reply with a single `ANSWER: X` line.
Graded by exact letter match. Choices are shuffled at run time, so their order in
the file does not matter, and `answer` refers to the order in the file.

```yaml
- id: eip-1559-base-fee-max-change
  type: multiple_choice
  question: |
    Under EIP-1559, by what maximum fraction can the base fee change between
    consecutive blocks?
  choices:
    - 1/4
    - 1/8
    - 1/16
    - 1/32
  answer: B
  difficulty: recall
  source: https://eips.ethereum.org/EIPS/eip-1559
```

### Open

The model answers in free text. A grader model compares the response against
`answer` and returns CORRECT, INCORRECT, or NOT_ATTEMPTED. Write `answer` as
grading guidance: state the facts, then say what a complete answer must include.

```yaml
- id: evm-call-vs-delegatecall
  type: open
  question: |
    What is the difference between CALL and DELEGATECALL?
  answer: |
    CALL runs the target's code in the target's own context. DELEGATECALL runs
    the target's code in the caller's context: the caller's storage is used and
    msg.sender and msg.value are preserved. A complete answer must state that
    DELEGATECALL uses the caller's storage and preserves msg.sender.
  difficulty: understanding
  source: https://eips.ethereum.org/EIPS/eip-7
```

### False premise

Only for the `hallucination` section. The question states something untrue. The
model scores CORRECT for rejecting or questioning the premise, INCORRECT for
answering as if it were true, and NOT_ATTEMPTED for a bare "I don't know" that
never engages with the claim. `answer` explains what is false so the grader can
check.

```yaml
- id: fake-push0-byzantium
  type: false_premise
  question: |
    The Byzantium upgrade introduced the PUSH0 opcode. Which EIP specified it?
  answer: |
    The premise is false. PUSH0 was introduced by EIP-3855 in Shanghai (2023),
    not Byzantium (2017). A correct response points this out.
  difficulty: recall
```

## Fields

| Field              | Required | Notes |
|--------------------|----------|-------|
| `id`               | yes      | Unique across the whole benchmark. Lowercase letters, digits, and hyphens. |
| `type`             | yes      | `multiple_choice`, `open`, or `false_premise`. |
| `question`         | yes      | The prompt. Use `\|` for multiple lines. |
| `choices`          | MC only  | 2 to 8 distinct options. Not allowed on other types. |
| `answer`           | yes      | MC: the correct letter in file order. Others: the answer key for the grader. |
| `difficulty`       | no       | `recall`, `understanding`, or `reasoning`. |
| `source`           | no       | URL of the spec, EIP, or primary source that backs the answer. Strongly encouraged. |
| `tags`             | no       | Free-form list, for future filtering. |
| `multiple_correct` | no       | MC only. Set `true` and give `answer` as `"A, C"` when more than one option is right. |

Anything else is an error, so typos in field names are caught.

## YAML notes

Every value is read as the exact text you typed. `0x60` stays `0x60`, `32` stays
`32`, `yes` stays `yes`, and `2022-09-15` stays a string. You never need to quote a
value to protect it. Leaving an optional field blank (`source:`) is the same as
leaving it out.

## Writing good questions

- **Ground truth comes from primary sources.** The EIP text, consensus-specs,
  execution-specs, the Yellow Paper, or official client documentation. Put the link
  in `source`.
- **Answer as of current mainnet.** If the truth changed at a fork, anchor the
  question in its text: "Before Pectra, ..." or "What did Byzantium introduce?"
  The model only sees the question, so a fact that depends on an era must say so.
- **One fact per question.** If the answer needs two facts, write two questions or
  one `reasoning`-tier open question.
- **Distractors must be tempting.** Wrong choices should be what a model with
  shallow knowledge would pick: a neighbouring number, the previous fork's value, a
  related but different mechanism. Exactly one option must be right.
- **Answer keys are grading guidance, not model answers.** Say what a complete
  answer must include so the grader applies the same bar every time. Do not
  demand detail that a correct, concise answer would leave out.
- **False premises should be tempting and stable.** Prefer real things with a
  wrong attribute (a real opcode in the wrong fork, a real client in the wrong
  language, a real constant with the wrong value) over invented EIP numbers, which
  can become real as numbering advances. Never hint that the premise may be false.
- **Spread difficulty.** Aim for a mix of recall, understanding, and reasoning in
  every section.

## Sections

| Directory        | Covers |
|------------------|--------|
| `eips`           | Contents, motivation, mechanics, and status of specific EIPs. |
| `ercs`           | Application-layer standards: tokens, interfaces, metadata, account abstraction. |
| `consensus`      | Beacon chain: Gasper, slots and epochs, attestations, finality, slashing, validators. |
| `execution`      | EVM, gas, transactions, fee market, state, blocks. |
| `history`        | Network upgrades from Frontier onward, the DAO fork, the Merge. |
| `crops`          | The Ethereum Foundation's mandate: Censorship Resistance, Open source and free, Privacy, Security. |
| `hallucination`  | False-premise questions only. |
| `misc`           | Anything that does not fit a section yet: layer 2, MEV and PBS, roadmap, networking. |

To add a section, create a new directory under `questions/`. Nothing else needs
to change.

## Code changes

```sh
uv sync --all-groups
uv run ruff check .
uv run ruff format .
uv run pytest
```

The tests run the whole benchmark against Inspect's mock model, so no API key is
needed.
