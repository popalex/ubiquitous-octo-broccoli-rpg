from __future__ import annotations

from dataclasses import dataclass

from app.prompts import CONTINUITY_CHECK_PROMPT
from app.providers.base import BaseModelProvider, ProviderMessage


@dataclass(slots=True)
class ContinuityResult:
    final_reply: str
    applied: bool
    issues: list[str]


class ContinuityService:
    def __init__(self, memory_provider: BaseModelProvider) -> None:
        self.memory_provider = memory_provider

    async def validate(
        self,
        *,
        hard_rules: str,
        world_canon: str,
        recent_transcript: str,
        user_message: str,
        draft_reply: str,
    ) -> ContinuityResult:
        payload = await self.memory_provider.generate_json(
            [
                ProviderMessage(role="system", content=CONTINUITY_CHECK_PROMPT),
                ProviderMessage(
                    role="user",
                    content=(
                        f"Hard rules:\n{hard_rules}\n\n"
                        f"World canon:\n{world_canon}\n\n"
                        f"Recent transcript:\n{recent_transcript}\n\n"
                        f"User message:\n{user_message}\n\n"
                        f"Draft reply:\n{draft_reply}"
                    ),
                ),
            ],
            temperature=0.1,
            max_tokens=500,
        )
        issues = [str(item) for item in payload.get("issues", []) if str(item).strip()]
        revised = str(payload.get("revised_response", "")).strip() or draft_reply
        ok = bool(payload.get("ok", not issues))
        return ContinuityResult(final_reply=revised, applied=(revised != draft_reply or not ok), issues=issues)
