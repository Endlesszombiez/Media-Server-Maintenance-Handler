from __future__ import annotations

from typing import Protocol

from media_folder_repair.models import ProviderSuggestion


class ProviderError(RuntimeError):
    pass


class FolderNameProvider(Protocol):
    name: str
    model: str

    async def suggest_name(self, folder_name: str, profile_prompt: str) -> ProviderSuggestion:
        raise NotImplementedError
