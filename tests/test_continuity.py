from __future__ import annotations

from unittest.mock import patch

import pytest

from app.providers.base import ProviderError
from app.services.continuity import ContinuityService
from tests.conftest import MockProvider


@pytest.fixture()
def service(mock_provider: MockProvider) -> ContinuityService:
    return ContinuityService(mock_provider)


async def test_no_issues_returns_draft_unchanged(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    mock_provider.set_json_response({"ok": True, "issues": [], "revised_response": ""})
    result = await service.validate(
        hard_rules="No killing.",
        world_canon="Magic exists.",
        recent_transcript="USER: Hi",
        user_message="Hello",
        draft_reply="Hello, traveler.",
    )
    assert result.final_reply == "Hello, traveler."
    assert result.applied is False
    assert result.issues == []


async def test_issues_present_triggers_revision(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    mock_provider.set_json_response(
        {
            "ok": False,
            "issues": ["Character used magic they don't possess"],
            "revised_response": "Revised reply.",
        }
    )
    result = await service.validate(
        hard_rules="No magic.",
        world_canon="",
        recent_transcript="",
        user_message="Cast a spell!",
        draft_reply="*casts fireball*",
    )
    assert result.final_reply == "Revised reply."
    assert result.applied is True
    assert "Character used magic they don't possess" in result.issues


async def test_whitespace_revised_falls_back_to_draft(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    mock_provider.set_json_response(
        {"ok": True, "issues": [], "revised_response": "   "}
    )
    result = await service.validate(
        hard_rules="",
        world_canon="",
        recent_transcript="",
        user_message="Hi",
        draft_reply="Original reply.",
    )
    assert result.final_reply == "Original reply."


async def test_applied_true_when_revised_differs_from_draft(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    mock_provider.set_json_response(
        {"ok": True, "issues": [], "revised_response": "Different reply."}
    )
    result = await service.validate(
        hard_rules="",
        world_canon="",
        recent_transcript="",
        user_message="Hi",
        draft_reply="Original draft.",
    )
    assert result.applied is True
    assert result.final_reply == "Different reply."


async def test_provider_error_propagates(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    with patch.object(
        mock_provider, "generate_json", side_effect=ProviderError("LLM failure")
    ):
        with pytest.raises(ProviderError, match="LLM failure"):
            await service.validate(
                hard_rules="",
                world_canon="",
                recent_transcript="",
                user_message="Hi",
                draft_reply="Draft.",
            )


async def test_empty_issues_list_in_response(
    service: ContinuityService, mock_provider: MockProvider
) -> None:
    mock_provider.set_json_response({"ok": True})
    result = await service.validate(
        hard_rules="",
        world_canon="",
        recent_transcript="",
        user_message="Test",
        draft_reply="My reply.",
    )
    assert result.issues == []
    assert result.final_reply == "My reply."
