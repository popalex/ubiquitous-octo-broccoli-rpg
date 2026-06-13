"""Fixtures for the eval suite.

Configuration (all optional — defaults target the project's DEV_MODE setup of
Ollama + ``llama3.2:3b``):

    EVAL_PROVIDER          provider name ("ollama" | "openai"). Default "ollama".
    EVAL_MODEL             model for the prompt under test. Default DEV_MODEL_NAME.
    EVAL_JUDGE_MODEL       model for the LLM judge. Default = EVAL_MODEL.
    EVAL_OLLAMA_BASE_URL   Ollama endpoint. Default "http://localhost:11434"
                           (the host-side address; inside compose it's
                           http://ollama:11434).

When the provider is Ollama and unreachable, the whole eval session skips with a
clear message instead of erroring — so `pytest -m eval` is safe to run anywhere.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest
import pytest_asyncio

from app.config import get_settings
from app.providers.base import build_provider


@pytest.fixture(scope="session")
def eval_config() -> dict:
    base = get_settings()
    model = os.environ.get("EVAL_MODEL", base.dev_model_name)
    return {
        "provider": os.environ.get("EVAL_PROVIDER", "ollama"),
        "model": model,
        "judge_model": os.environ.get("EVAL_JUDGE_MODEL", model),
        "ollama_base_url": os.environ.get("EVAL_OLLAMA_BASE_URL", "http://localhost:11434"),
    }


@pytest.fixture(scope="session")
def eval_settings(eval_config: dict):
    # Point the provider at the host-side Ollama (or whatever the env overrides).
    return get_settings().model_copy(update={"ollama_base_url": eval_config["ollama_base_url"]})


@pytest.fixture(scope="session")
def _reachable(eval_config: dict) -> None:
    """Skip the whole eval session cleanly when the model can't be reached."""
    if eval_config["provider"] != "ollama":
        return  # only Ollama has a cheap probe; trust other providers to error per-call
    url = eval_config["ollama_base_url"].rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 - fixed local scheme
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(
            f"Ollama unreachable at {eval_config['ollama_base_url']} ({exc}). "
            "Start the stack (docker compose up) or set EVAL_OLLAMA_BASE_URL / "
            "EVAL_PROVIDER to run evals."
        )


# Provider fixtures are async + function-scoped on purpose: pytest-asyncio gives
# each test its own event loop, and an httpx.AsyncClient binds to the loop it's
# first used on. A session-scoped client would break ("Event loop is closed")
# once the first test's loop closes. A fresh client per test — built and closed
# inside that test's loop — keeps every request on a live loop. The cost (one
# client per test) is negligible next to the model call itself.
@pytest_asyncio.fixture
async def eval_provider(_reachable, eval_config: dict, eval_settings):
    provider = build_provider(eval_config["provider"], eval_config["model"], eval_settings, slot="eval")
    try:
        yield provider
    finally:
        await provider.aclose()


@pytest_asyncio.fixture
async def judge_provider(_reachable, eval_config: dict, eval_settings):
    provider = build_provider(eval_config["provider"], eval_config["judge_model"], eval_settings, slot="eval-judge")
    try:
        yield provider
    finally:
        await provider.aclose()
