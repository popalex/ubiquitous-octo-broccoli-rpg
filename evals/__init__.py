"""On-demand LLM eval harness (TODO §5a).

Runs the real prompts from ``app/prompts.py`` against a real local model and
scores the output, either with structural assertions (where the signal is
binary) or an LLM judge with a pass/fail verdict (for fuzzy checks).

These tests are marked ``eval`` and excluded from the default/CI run; invoke
them with ``pytest -m eval`` (or ``make eval``) with a model reachable. See
``evals/conftest.py`` for configuration env vars.
"""
