from __future__ import annotations

import json

import httpx
from pydantic import BaseModel, Field, ValidationError

from media_folder_repair.config import LMStudioConfig
from media_folder_repair.models import ProviderSuggestion
from media_folder_repair.profiles import SYSTEM_PROMPT, build_prompt
from media_folder_repair.providers.base import ProviderError


class _SuggestionPayload(BaseModel):
    should_rename: bool
    suggested_name: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str


class LMStudioProvider:
    name = "lmstudio"

    def __init__(self, config: LMStudioConfig):
        self.config = config
        self.model = config.model

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text
        return str(detail).strip()

    async def list_models(self) -> list[str]:
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                headers=headers,
            ) as client:
                response = await client.get("/models")
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("LM Studio model list request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio model list request failed: {exc}") from exc

        try:
            data = response.json()["data"]
            models = [item["id"] for item in data if isinstance(item.get("id"), str)]
        except (KeyError, TypeError) as exc:
            raise ProviderError("LM Studio returned malformed model list") from exc

        return sorted(models)

    async def suggest_name(self, folder_name: str, profile_prompt: str) -> ProviderSuggestion:
        if not self.config.model:
            raise ProviderError("LM Studio model is not configured")

        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(folder_name, profile_prompt)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                headers=headers,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
                if response.status_code == 400:
                    fallback_payload = dict(payload)
                    fallback_payload.pop("response_format", None)
                    response = await client.post("/chat/completions", json=fallback_payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("LM Studio request timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = self._error_detail(exc.response)
            message = f"LM Studio request failed: {exc}"
            if detail:
                message = f"{message}; response: {detail}"
            raise ProviderError(message) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio request failed: {exc}") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
            raw = json.loads(content) if isinstance(content, str) else content
            parsed = _SuggestionPayload.model_validate(raw)
        except (KeyError, IndexError, json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ProviderError("LM Studio returned malformed structured JSON") from exc

        return ProviderSuggestion(
            should_rename=parsed.should_rename,
            suggested_name=parsed.suggested_name,
            confidence=parsed.confidence,
            reason=parsed.reason,
        )
