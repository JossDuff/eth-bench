# eth-bench

A benchmark that measures how much a language model knows about Ethereum.

It asks the model a few hundred questions across several sections, such as EIPs,
ERCs, the consensus layer, and the execution layer. You get an overall score and a
score per section. One section tests whether the model pushes back on made-up facts
instead of inventing an answer.

Built on [Inspect AI](https://inspect.aisi.org.uk/), so it works with any model
Inspect can talk to.

## Run it

Install [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/ethereum/eth-bench
cd eth-bench
uv sync
uv run inspect eval eth_bench --model <your-model> --model-role grader=anthropic/claude-fable-5-1
```

The grader is a second model that marks the free-text answers. It needs
`ANTHROPIC_API_KEY` set in your environment.

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

The terminal prints the overall score and a score for each section, each with a
standard error. To see every question, the model's answer, and why it was marked
right or wrong:

```sh
uv run inspect view
```

## Run one section

```sh
uv run inspect eval eth_bench -T sections=eips --model <your-model> --model-role grader=...
```

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
