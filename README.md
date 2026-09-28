# eth-bench

A benchmark that measures how much a language model knows about Ethereum.

It asks the model a few hundred questions across several sections, such as EIPs,
ERCs, the consensus layer, and the execution layer. You get an overall pass rate and
a score per section. One section tests whether the model pushes back on made-up
facts instead of inventing an answer.

Built on [promptfoo](https://www.promptfoo.dev/), so it works with any model
promptfoo can talk to, and results open in promptfoo's web UI.

## Results

These numbers come from the previous, Inspect-based version of this benchmark on a
245-question set, as of 17 September 2026, graded by Claude Fable 5.1. The overall
score there was the mean of the section scores. They will be replaced by promptfoo
runs over the current 584-question set.

| Model                           | Overall |
|---------------------------------|---------|
| GPT-6 Astra                     | 0.961   |
| GPT-5.6 Sol                     | 0.951   |
| Claude Opus 5                   | 0.930   |
| Claude Fable 5.1                | 0.926   |
| GPT-5.6 Terra                   | 0.891   |
| Claude Sonnet 5                 | 0.875   |
| Qwen3.8-27b + wikipethia        | 0.794   |
| Gemma 4 26B-A4B-it + wikipethia | 0.719   |
| Qwen3.8-27b + eth-mcp           | 0.655   |
| Gemma 4 26B-A4B-it + eth-mcp    | 0.558   |
| Qwen3.8-27b                     | 0.525   |
| Gemma 4 26B-A4B-it              | 0.479   |

## Run it

You need Node.js 22.22 or newer.

```sh
git clone https://github.com/JossDuff/eth-bench
cd eth-bench
npm install
export ANTHROPIC_API_KEY=...            # for the grader
npx promptfoo eval --filter-providers 'Claude Sonnet 5'
npx promptfoo view
```

`promptfooconfig.yaml` lists the models in the results table. `--filter-providers`
picks one or more of them by label (it is a regular expression). To run any other
model, name it on the command line instead:

```sh
npx promptfoo eval -r openai:chat:gpt-6-astra
npx promptfoo eval -r ollama:chat:qwen3.8:27b
npx promptfoo eval -r openrouter:google/gemma-4-26b-it
```

`-r` takes any [promptfoo provider](https://www.promptfoo.dev/docs/providers/). For
an OpenAI-compatible endpoint, such as vLLM, add a provider entry to
`promptfooconfig.yaml` with `apiBaseUrl` and `apiKeyEnvar`; the Qwen and Gemma
entries there are examples. The Qwen entry also shows how to pass extra request
fields, such as turning off thinking.

### The grader

Open and false-premise questions are marked by a second model, the grader. It is
`anthropic:messages:claude-fable-5-1` in `src/grading.yaml`, so runs need
`ANTHROPIC_API_KEY`. Change it with `--grader`:

```sh
npx promptfoo eval -r ollama:chat:qwen3.8:27b --grader openai:chat:gpt-6-astra
```

The grader must be a different model from the one under test, otherwise the model
grades its own answers. Numbers you share should name the grader.

Multiple choice questions are graded by letter match and need no grader:

```sh
npx promptfoo eval -r ollama:chat:qwen3.8:27b --filter-metadata type=multiple_choice
```

## Read the results

The terminal prints a summary when the run finishes. `npx promptfoo view` opens the
web UI with every question, the model's answer, and the grader's reasoning, and it
shows models side by side when you have run more than one.

| Where                         | Meaning |
|-------------------------------|---------|
| Pass rate                     | The share of questions answered correctly. This is the headline score. |
| `eips`, `consensus`, ...      | Per-section scores. Each question tags its section as a named metric, so these appear as columns in the UI and in `namedScores` in JSON output. |
| Grader reason                 | Starts with `CORRECT`, `INCORRECT`, or `NOT_ATTEMPTED`. Only `CORRECT` passes; `NOT_ATTEMPTED` means the model declined or hedged rather than answering wrongly. |
| Metadata filters              | Filter by `section`, `type` (`multiple_choice`, `open`, `false_premise`), or `difficulty` (`recall`, `understanding`, `reasoning`) in the UI or with `--filter-metadata`. |

To keep a record of a run:

```sh
npx promptfoo eval --filter-providers 'Claude Sonnet 5' -o results/claude-sonnet-5.json
```

## Run part of it

```sh
# One section, or several (the pattern matches the question id, which starts with the section)
npx promptfoo eval --filter-pattern '^eips/'
npx promptfoo eval --filter-pattern '^(eips|consensus)/'

# One question type
npx promptfoo eval --filter-metadata type=false_premise

# Let the model think before answering multiple choice questions
npx promptfoo eval --var cot=true

# A quick smoke test on five questions, or a random sample of twenty
npx promptfoo eval -n 5
npx promptfoo eval --filter-sample 20 --filter-sample-seed 1

# Run every question three times, eight at a time
npx promptfoo eval --repeat 3 -j 8
```

Sections: `building`, `consensus`, `crops`, `eips`, `ercs`, `execution`,
`hallucination`, `history`, `misc`, `security`, `solidity`.

promptfoo caches model responses, so rerunning after changing the grader or a
question's answer key only pays for what changed. Add `--no-cache` to force fresh
answers.

## Assisted runs

An assisted run gives the model tools or documents to use while answering. The
grader never sees them, so an assisted run is scored exactly like a bare one and the
two can be compared directly. Each assist is its own config file:

| Config                          | Gives the model |
|---------------------------------|-----------------|
| `promptfooconfig.wikipethia.yaml` | Search and spec-lookup tools over the [wikipethia](https://github.com/JossDuff/wikipethia) corpus, through its MCP server. The hosted server rate-limits parallel requests; the file shows how to point at a local corpus instead. |
| `promptfooconfig.eth-mcp.yaml`    | Search, constant lookup and spec-function tools from [ethereum-mcp](https://github.com/b17z/ethereum-mcp) over a local index of the consensus specs and EIPs (`uv tool install eth-mcp`, then `ethereum-mcp build`). |
| `promptfooconfig.ethskills.yaml`  | The [ethskills](https://ethskills.com) index in the system prompt. No tools, so it works with any model. |

```sh
npx promptfoo eval -c promptfooconfig.wikipethia.yaml --filter-providers 'Claude Sonnet 5'
npx promptfoo eval -c promptfooconfig.ethskills.yaml --filter-providers 'Qwen3.8-27b'
```

For the two MCP assists, promptfoo connects to the server and runs the tool loop, up
to ten tool calls per question. As of promptfoo 0.123 only its Anthropic provider
runs that loop; the OpenAI-compatible provider executes one tool call and returns
the tool's result as the answer. So the MCP configs list Claude models only. To test
another MCP server, copy one of these files and change the `mcp` block. Expect an
assisted run to take several times longer than a bare one.

## Add a question

Questions live in `questions/<section>/` as promptfoo test cases. Add one to any
file there, or make a new file:

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

Then check it:

```sh
npm test
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full question format and writing
guidelines.
