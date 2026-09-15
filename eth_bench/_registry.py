"""Entry point for Inspect's task registry.

Inspect imports this module (via the `inspect_ai` entry point in pyproject.toml)
so that `inspect eval eth_bench` resolves to the task in tasks.py.
"""

from eth_bench.tasks import eth_bench  # noqa: F401
