# eth-bench

A benchmark that measures how much a language model knows about Ethereum.

It asks the model a few hundred questions across several sections, such as EIPs,
ERCs, the consensus layer, and the execution layer. You get an overall score and a
score per section. One section tests whether the model pushes back on made-up facts
instead of inventing an answer.

Built on [Inspect AI](https://inspect.aisi.org.uk/), so it works with any model
Inspect can talk to.

## Results

Overall score on the 245-question set as of 16 September 2026. Every run was
graded by `anthropic/claude-fable-5-1`. The score is the mean of the section
scores.

| Model               | Overall |
|---------------------|---------|
| GPT-6 Astra         | 0.961   |
| GPT-5.6 Sol         | 0.951   |
| Claude Opus 5       | 0.930   |
| Claude Fable 5.1    | 0.926   |
| GPT-5.6 Terra       | 0.891   |
| Claude Sonnet 5     | 0.875   |
| Gemma 4 26B-A4B-it  | 0.496   |
| Qwen3.8-27b         | 0.447   |
| Nemotrom            | TODO    |

## Run it

Install [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/JossDuff/eth-bench
cd eth-bench
uv sync
uv run inspect eval eth_bench --model <your-model> --model-role grader=anthropic/claude-fable-5-1
```

The grader is a second model that marks the free-text answers. The run refuses to
start without one, so the model under test can never grade itself. Using Claude as
the grader needs `ANTHROPIC_API_KEY` set in your environment.

`<your-model>` is an Inspect model string. Some common ones:

| Your model is...                     | Use                                                 |
|--------------------------------------|-----------------------------------------------------|
| A hosted API                         | `openai/gpt-...`, `anthropic/claude-...`, `google/gemini-...` |
| Behind an OpenAI-compatible endpoint | `openai-api/myprovider/my-model` with `MYPROVIDER_BASE_URL` and `MYPROVIDER_API_KEY` set |
| A local checkpoint                   | `hf/local -M model_path=./my-model`                 |
| A local checkpoint, served by vLLM   | `vllm/local -M model_path=./my-model`               |
| A LoRA adapter                       | `vllm/<base-model>:./my-adapter`                    |
| Running in Ollama                    | `ollama/<model-name>`                               |

Full list: [Inspect model providers](https://inspect.aisi.org.uk/providers.html).

## Read the results

The terminal prints a table when the run finishes:

| Row                              | Meaning |
|----------------------------------|---------|
| `all`                            | The overall score: the mean of the section scores, weighting every section equally. |
| `eips`, `consensus`, ...         | Accuracy for that section. |
| `all_stderr`, `eips_stderr`, ... | Standard error for the row above. Two models whose scores differ by less than this are not distinguishable. |
| `type_open`, `type_multiple_choice`, `type_false_premise` | Accuracy by question format. |
| `difficulty_recall`, ...         | Accuracy by difficulty tier. |
| `..._correct_given_attempted`    | Of the free-text answers the model committed to, how many were right. High means it guesses well or knows when to stay quiet. |
| `..._not_attempted`              | How often the model declined to answer a free-text question instead of guessing. |

To see every question, the model's answer, and the grader's reasoning:

```sh
uv run inspect view
```

## Run part of it

```sh
# One section, or several
uv run inspect eval eth_bench -T sections=eips --model <your-model> --model-role grader=...
uv run inspect eval eth_bench -T sections=eips,consensus --model <your-model> --model-role grader=...

# Only multiple choice, no grader needed
uv run inspect eval eth_bench -T types=multiple_choice --model <your-model>

# Let the model think before answering multiple choice questions
uv run inspect eval eth_bench -T cot=true --model <your-model> --model-role grader=...

# A quick smoke test on five questions
uv run inspect eval eth_bench --limit 5 --model <your-model> --model-role grader=...
```

Sections: `eips`, `ercs`, `consensus`, `execution`, `history`, `crops`, `misc`,
`hallucination`.

## Add a question

Questions live in `questions/<section>/` as YAML. Add one to any file there, or
make a new file:

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

Then check it:

```sh
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full question format and writing
guidelines.
