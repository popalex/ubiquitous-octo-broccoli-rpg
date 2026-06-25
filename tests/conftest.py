from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.config import Settings
from app.db import Base
from app.providers.base import BaseModelProvider, ProviderMessage

PGVECTOR_IMAGE = "pgvector/pgvector:pg18"
EMBEDDING_DIM = 768


def make_test_settings(**overrides) -> Settings:
    defaults: dict = dict(
        database_url="postgresql+psycopg://test:test@localhost/test",
        openai_api_key="test-key",
        dev_mode=False,
        # Pin the gameplay feature flags off in the test baseline so the suite is
        # insulated from the product defaults (now on in app.config). Tests opt
        # into exactly the sections they exercise — this also keeps the post-turn
        # judge's single-section bare-payload mapping unambiguous in fixtures.
        gm_enabled=False,
        suggestions_enabled=False,
        world_state_enabled=False,
        quests_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider(BaseModelProvider):
    """Deterministic, configurable provider for unit tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(model_name="mock", settings=settings or make_test_settings())
        self._text_response: str = "Mock reply."
        self._json_response: dict = {
            "ok": True,
            "issues": [],
            "revised_response": "Mock reply.",
        }
        self._json_responses: list[dict] = []

    def set_text_response(self, text: str) -> None:
        self._text_response = text

    def set_json_response(self, payload: dict) -> None:
        self._json_response = payload

    def set_json_responses(self, payloads: list[dict]) -> None:
        """Queue distinct payloads for successive generate_json calls (FIFO);
        falls back to the single set_json_response payload when exhausted."""
        self._json_responses = list(payloads)

    async def generate_text(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        return self._text_response

    async def generate_text_stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        yield self._text_response

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIM for _ in texts]

    async def generate_json(
        self,
        messages: Sequence[ProviderMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        if self._json_responses:
            return self._json_responses.pop(0)
        return self._json_response


# ---------------------------------------------------------------------------
# Database fixtures (testcontainers)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(image=PGVECTOR_IMAGE, driver="psycopg") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(pg_container):
    url = pg_container.get_connection_url()
    engine = create_async_engine(url, pool_pre_ping=True, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """
    Each test gets its own transaction that is rolled back on exit.
    Services that call db.commit() will only release a SAVEPOINT, not the
    outer transaction, so the rollback still cleans up everything.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    yield session
    await session.close()
    await transaction.rollback()
    await connection.close()


# ---------------------------------------------------------------------------
# Factory session wiring (autouse so factories always use the right session)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_factory_session(db_session: AsyncSession) -> None:
    """Keep factory-boy in sync with the per-test database session."""
    from tests.factories import (
        CharacterCardFactory,
        CharacterSheetFactory,
        EpisodeSummaryFactory,
        ItemFactory,
        MemoryFactFactory,
        QuestFactory,
        SessionFactory,
        TurnFactory,
        WorldStateFactory,
    )

    for klass in (
        CharacterCardFactory,
        WorldStateFactory,
        SessionFactory,
        TurnFactory,
        MemoryFactFactory,
        EpisodeSummaryFactory,
        QuestFactory,
        CharacterSheetFactory,
        ItemFactory,
    ):
        klass._meta.sqlalchemy_session = db_session  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Provider fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_provider() -> MockProvider:
    return MockProvider()


# ---------------------------------------------------------------------------
# FastAPI client fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP client with the real app; only the DB dependency is overridden."""
    from app.db import get_db
    from app.main import app

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def async_client_mocked_orchestrator(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    """
    HTTP client where get_orchestrator() returns a MagicMock so LLM calls
    never touch a real provider.
    """
    from app.db import get_db
    from app.main import app
    from app.services.orchestrator import OrchestratorService, get_orchestrator

    async def _override_db():
        yield db_session

    mock_orch = MagicMock(spec=OrchestratorService)
    mock_orch.chat = AsyncMock()
    mock_orch.gm_chat = AsyncMock()
    mock_orch.chat_stream = AsyncMock(return_value=iter([]))
    mock_orch.gm_chat_stream = AsyncMock(return_value=iter([]))

    app.dependency_overrides[get_db] = _override_db
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, mock_orch
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
