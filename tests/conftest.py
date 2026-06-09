from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from app.config import Settings
from app.db import Base
from app.providers.base import BaseModelProvider, ProviderMessage

PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
EMBEDDING_DIM = 768


def make_test_settings(**overrides) -> Settings:
    defaults: dict = dict(
        database_url="postgresql+psycopg://test:test@localhost/test",
        openai_api_key="test-key",
        dev_mode=False,
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

    def set_text_response(self, text: str) -> None:
        self._text_response = text

    def set_json_response(self, payload: dict) -> None:
        self._json_response = payload

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
        return self._json_response


# ---------------------------------------------------------------------------
# Database fixtures (testcontainers)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(image=PGVECTOR_IMAGE, driver="psycopg") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_engine(pg_container):
    url = pg_container.get_connection_url()
    engine = create_engine(url, pool_pre_ping=True, future=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Generator[Session]:
    """
    Each test gets its own transaction that is rolled back on exit.
    Services that call db.commit() will only release a SAVEPOINT, not the
    outer transaction, so the rollback still cleans up everything.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Factory session wiring (autouse so factories always use the right session)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _wire_factory_session(db_session: Session) -> None:
    """Keep factory-boy in sync with the per-test database session."""
    from tests.factories import (
        CharacterCardFactory,
        EpisodeSummaryFactory,
        MemoryFactFactory,
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
async def async_client(db_session: Session) -> AsyncIterator[AsyncClient]:
    """HTTP client with the real app; only the DB dependency is overridden."""
    from app.db import get_db
    from app.main import app

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def async_client_mocked_orchestrator(
    db_session: Session,
) -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    """
    HTTP client where get_orchestrator() returns a MagicMock so LLM calls
    never touch a real provider.
    """
    from app.db import get_db
    from app.main import app
    from app.services.orchestrator import OrchestratorService, get_orchestrator

    def _override_db():
        yield db_session

    mock_orch = MagicMock(spec=OrchestratorService)
    mock_orch.chat = AsyncMock()
    mock_orch.gm_chat = AsyncMock()
    mock_orch.chat_stream = AsyncMock(return_value=iter([]))
    mock_orch.gm_chat_stream = AsyncMock(return_value=iter([]))

    app.dependency_overrides[get_db] = _override_db
    get_orchestrator.cache_clear()
    with patch("app.main.get_orchestrator", return_value=mock_orch):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, mock_orch
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
