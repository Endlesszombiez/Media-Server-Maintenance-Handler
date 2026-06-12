import pytest
import respx
from httpx import ConnectTimeout, Response

from media_folder_repair.config import LMStudioConfig
from media_folder_repair.providers.base import ProviderError
from media_folder_repair.providers.lmstudio import LMStudioProvider


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_parses_valid_structured_json() -> None:
    respx.post("http://localhost:1234/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"should_rename": true, "suggested_name": "Robin Hood - 2026", '
                                '"confidence": 0.93, "reason": "Removed release tags"}'
                            )
                        }
                    }
                ]
            },
        )
    )
    provider = LMStudioProvider(LMStudioConfig(model="test-model"))

    suggestion = await provider.suggest_name("Robin.Hood.2026.1080p-GRP", "movie")

    assert suggestion.should_rename is True
    assert suggestion.suggested_name == "Robin Hood - 2026"
    assert suggestion.confidence == 0.93


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_lists_available_models() -> None:
    respx.get("http://localhost:1234/v1/models").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"id": "second-model"},
                    {"id": "first-model"},
                ]
            },
        )
    )
    provider = LMStudioProvider(LMStudioConfig())

    assert await provider.list_models() == ["first-model", "second-model"]


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_handles_malformed_model_list() -> None:
    respx.get("http://localhost:1234/v1/models").mock(return_value=Response(200, json={}))
    provider = LMStudioProvider(LMStudioConfig())

    with pytest.raises(ProviderError, match="model list"):
        await provider.list_models()


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_handles_malformed_response() -> None:
    respx.post("http://localhost:1234/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    )
    provider = LMStudioProvider(LMStudioConfig(model="test-model"))

    with pytest.raises(ProviderError, match="malformed"):
        await provider.suggest_name("bad", "movie")


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_handles_http_error() -> None:
    respx.post("http://localhost:1234/v1/chat/completions").mock(return_value=Response(500))
    provider = LMStudioProvider(LMStudioConfig(model="test-model"))

    with pytest.raises(ProviderError, match="failed"):
        await provider.suggest_name("bad", "movie")


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_handles_timeout() -> None:
    respx.post("http://localhost:1234/v1/chat/completions").mock(
        side_effect=ConnectTimeout("timeout")
    )
    provider = LMStudioProvider(LMStudioConfig(model="test-model"))

    with pytest.raises(ProviderError, match="timed out"):
        await provider.suggest_name("bad", "movie")
