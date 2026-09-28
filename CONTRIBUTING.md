# Contributing questions

Questions are promptfoo test cases in YAML files under `questions/<section>/`. The
section is the directory name. Put a question in any existing file in that directory,
or make a new file. File names are up to you; grouping by topic (`eip-1559.yaml`,
`upgrades.yaml`) works well.

After editing, run:

```sh
npm test
```

Every file is checked. A failure names the file and the question.

## The three question types

Every question has the same shape: a `description` that is its id, `vars` holding
the question and the answer key, `metadata` for filtering, and one assertion that
grades it. Only the `vars.type` and the assertion differ between types.

### Multiple choice

The model sees the lettered options and must reply with a single `ANSWER: X` line.
Graded by a regex that accepts `ANSWER: <the letter>` and rejects any other letter, or a list of letters.

```yaml
- description: eips/eip-1559-base-fee-max-change
  vars:
    type: multiple_choice
    question: |
      Under EIP-1559, by what maximum fraction can the base fee change between
      consecutive blocks?
    choices:
      - 1/32
      - 1/4
      - 1/8
      - 1/16
    answer: C
  metadata:
    section: eips
    type: multiple_choice
    difficulty: recall
    source: https://eips.ethereum.org/EIPS/eip-1559
  assert:
    - type: regex
      value: 'ANSWER:\W*{{answer}}\b(?!\s*,\s*[A-H]\b)'
      metric: eips
```

Nothing reorders the choices at run time, so put the correct choice at a random
position. The tests fail if any one letter is the answer to more than 40% of the
multiple choice questions.

When more than one option is right, set `multiple_correct: true` in `vars`, give
`answer` as `"A, C"`, and write a regex that accepts exactly that set in any order; see
`crops/crops-rollup-stages` for the pattern. There is no partial credit.

### Open

The model answers in free text. A grader model compares the response against
`answer` and returns CORRECT, INCORRECT, or NOT_ATTEMPTED. Only CORRECT passes. Write
`answer` as grading guidance: state the facts, then say what a complete answer must
include.

```yaml
- description: execution/evm-call-vs-delegatecall
  vars:
    type: open
    question: |
      What is the difference between CALL and DELEGATECALL?
    answer: |
      CALL runs the target's code in the target's own context. DELEGATECALL runs
      the target's code in the caller's context: the caller's storage is used and
      msg.sender and msg.value are preserved. A complete answer must state that
      DELEGATECALL uses the caller's storage and preserves msg.sender.
  metadata:
    section: execution
    type: open
    difficulty: understanding
    source: https://eips.ethereum.org/EIPS/eip-7
  assert:
    - type: llm-rubric
      value: '{{answer}}'
      metric: execution
```

### False premise

Only for the `hallucination` section. The question states something untrue. The
model scores CORRECT for rejecting or questioning the premise, INCORRECT for
answering as if it were true, and NOT_ATTEMPTED for a bare "I don't know" that
never engages with the claim. `answer` explains what is false so the grader can
check. The assertion is the same `llm-rubric` as for open questions; the grading
prompt in `src/grading.yaml` switches on `vars.type`.

```yaml
- description: hallucination/fake-push0-byzantium
  vars:
    type: false_premise
    question: |
      The Byzantium upgrade introduced the PUSH0 opcode. Which EIP specified it?
    answer: |
      The premise is false. PUSH0 was introduced by EIP-3855 in Shanghai (2023),
      not Byzantium (2017). A correct response points this out.
  metadata:
    section: hallucination
    type: false_premise
    difficulty: recall
  assert:
    - type: llm-rubric
      value: '{{answer}}'
      metric: hallucination
```

## Fields

| Field                    | Required | Notes |
|--------------------------|----------|-------|
| `description`            | yes      | `<section>/<id>`. The id is unique across the whole benchmark: lowercase letters, digits, and hyphens. |
| `vars.type`              | yes      | `multiple_choice`, `open`, or `false_premise`. |
| `vars.question`          | yes      | The prompt. Use `\|` for multiple lines. |
| `vars.choices`           | MC only  | 2 to 8 distinct options. Not allowed on other types. Quote options that look like numbers (`'32'`, `'0x60'`) so YAML keeps them as text. |
| `vars.answer`            | yes      | MC: the correct letter. Others: the answer key for the grader. |
| `vars.multiple_correct`  | no       | MC only. `true` when more than one option is right. |
| `metadata.section`       | yes      | The directory name. |
| `metadata.type`          | yes      | Same as `vars.type`. |
| `metadata.difficulty`    | no       | `recall`, `understanding`, or `reasoning`. |
| `metadata.source`        | no       | URL of the spec, EIP, or primary source that backs the answer. Strongly encouraged. |
| `metadata.tags`          | no       | Free-form list, for filtering. |
| `assert`                 | yes      | Exactly one assertion: `regex` for MC (see above; copy it as is, it reads the letter from `vars.answer`), `llm-rubric` with `'{{answer}}'` otherwise. `metric` is the section. |

Anything else in `vars` or `metadata` is an error, so typos in field names are caught.

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
| `solidity`       | The Solidity language and compiler: semantics, ABI encoding, storage layout, language-level security. |
| `security`       | Smart contract and wallet security: vulnerabilities, incident post-mortems, oracle and upgrade safety, dangerous signing requests. |
| `building`       | Building dApps: frontend and wallet UX, approvals and decimals, RPC and indexing, chain choice, deployment. |
| `hallucination`  | False-premise questions only. |
| `misc`           | Anything that does not fit a section yet: layer 2, MEV and PBS, roadmap, networking. |

Questions imported from [ethevals](https://github.com/austintgriffith/ethevals) and
[eth-evals](https://github.com/clawdbotatg/eth-evals) live in `ethevals.yaml` and
`eth-evals.yaml` inside their section and keep their upstream ids.

To add a section, create a new directory under `questions/`. Set `metadata.section`
and the assertion `metric` to its name; nothing else needs to change.

## Assists

An assist is a promptfoo config at the repository root, `promptfooconfig.<name>.yaml`,
whose providers carry an `mcp` block (tools) or use the `ethskills` prompt (a document
in the system prompt). To add one, copy an existing file and change the provider
labels and the `mcp` block. Secrets stay in the environment; reference them as
`{{ env.VAR }}`. Check it with `npx promptfoo validate -c promptfooconfig.<name>.yaml`.

## Code changes

```sh
npm install
npm test
npx promptfoo validate
npx promptfoo eval -r echo --filter-metadata type=multiple_choice -n 20 --no-write
```

The last command runs the multiple choice questions against promptfoo's `echo`
provider, which returns the prompt itself, so no API key is needed.
