from pathlib import Path

import pytest

from media_folder_repair.config import AppConfig
from media_folder_repair.history import HistoryLog
from media_folder_repair.models import (
    CollisionPolicy,
    ProviderSuggestion,
    RenameMode,
    RenameProposal,
    RenameStatus,
)
from media_folder_repair.renamer import RenameService, validate_target_name


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, suggestions: dict[str, ProviderSuggestion]):
        self.suggestions = suggestions

    async def suggest_name(self, folder_name: str, profile_prompt: str) -> ProviderSuggestion:
        return self.suggestions[folder_name]


def suggestion(name: str, confidence: float = 0.9) -> ProviderSuggestion:
    return ProviderSuggestion(True, name, confidence, "cleaned")


def test_validation_rejects_unsafe_names(tmp_path: Path) -> None:
    source = tmp_path / "Bad.Name.2026.1080p"
    source.mkdir()

    assert validate_target_name(source, "") == "Suggestion is empty"
    assert "reserved" in validate_target_name(source, "Other/Name")
    assert "matches" in validate_target_name(source, "bad.name.2026.1080p").lower()


@pytest.mark.asyncio
async def test_collision_policy_skip_and_report(tmp_path: Path) -> None:
    source = tmp_path / "Messy.2026.1080p"
    source.mkdir()
    (tmp_path / "Messy - 2026").mkdir()
    config = AppConfig()
    config.rename.mode = RenameMode.AUTO
    config.rename.collision_policy = CollisionPolicy.SKIP_AND_REPORT
    service = RenameService(config, FakeProvider({}), HistoryLog(tmp_path / "history.jsonl"))
    proposal = RenameProposal(source, "Messy - 2026", 0.9, "cleaned", "fake", "model", "movie")

    result = await service.apply_proposal(tmp_path, proposal, "run")

    assert result.status == RenameStatus.SKIPPED
    assert result.reason == "Target already exists"
    assert source.exists()


@pytest.mark.asyncio
async def test_collision_policy_prompt_each_time_manual_name(tmp_path: Path) -> None:
    source = tmp_path / "Messy.2026.1080p"
    source.mkdir()
    (tmp_path / "Messy - 2026").mkdir()
    config = AppConfig()
    config.rename.mode = RenameMode.AUTO
    config.rename.collision_policy = CollisionPolicy.PROMPT_EACH_TIME
    service = RenameService(
        config,
        FakeProvider({}),
        HistoryLog(tmp_path / "history.jsonl"),
        manual_name_chooser=lambda proposal: "Messy Movie - 2026",
    )
    proposal = RenameProposal(source, "Messy - 2026", 0.9, "cleaned", "fake", "model", "movie")

    result = await service.apply_proposal(tmp_path, proposal, "run")

    assert result.status == RenameStatus.APPLIED
    assert not source.exists()
    assert (tmp_path / "Messy Movie - 2026").exists()


@pytest.mark.asyncio
async def test_preview_mode_creates_proposals_without_renaming(tmp_path: Path) -> None:
    source = tmp_path / "Robin.Hood.2026.1080p-GRP"
    source.mkdir()
    config = AppConfig()
    config.rename.mode = RenameMode.PREVIEW
    service = RenameService(
        config,
        FakeProvider({source.name: suggestion("Robin Hood - 2026")}),
        HistoryLog(tmp_path / "history.jsonl"),
    )

    result = await service.run(tmp_path)

    assert len(result.proposals) == 1
    assert result.queued[0].status == RenameStatus.PROPOSED
    assert source.exists()
    assert not (tmp_path / "Robin Hood - 2026").exists()


@pytest.mark.asyncio
async def test_run_reports_scan_progress_per_folder(tmp_path: Path) -> None:
    first = tmp_path / "First.Movie.2026.1080p"
    second = tmp_path / "Second.Movie.2026.1080p"
    first.mkdir()
    second.mkdir()
    config = AppConfig()
    service = RenameService(
        config,
        FakeProvider(
            {
                first.name: suggestion("First Movie - 2026"),
                second.name: suggestion("Second Movie - 2026"),
            }
        ),
        HistoryLog(tmp_path / "history.jsonl"),
    )
    progress: list[tuple[int, int, Path]] = []

    await service.run(
        tmp_path,
        progress_callback=lambda done, total, path: progress.append((done, total, path)),
    )

    assert [(done, total) for done, total, _ in progress] == [(1, 2), (2, 2)]
    assert {path for _, _, path in progress} == {first, second}


@pytest.mark.asyncio
async def test_auto_mode_applies_only_valid_proposals(tmp_path: Path) -> None:
    good = tmp_path / "Good.Movie.2026.1080p"
    bad = tmp_path / "Bad.Movie.2026.1080p"
    good.mkdir()
    bad.mkdir()
    config = AppConfig()
    config.rename.mode = RenameMode.AUTO
    service = RenameService(
        config,
        FakeProvider(
            {
                good.name: suggestion("Good Movie - 2026"),
                bad.name: suggestion("Bad/Movie - 2026"),
            }
        ),
        HistoryLog(tmp_path / "history.jsonl"),
    )

    result = await service.run(tmp_path)

    assert len(result.applied) == 1
    assert (tmp_path / "Good Movie - 2026").exists()
    assert bad.exists()
    assert any(item.status == RenameStatus.SKIPPED for item in result.skipped)


@pytest.mark.asyncio
async def test_hybrid_auto_applies_high_confidence_and_queues_uncertain(tmp_path: Path) -> None:
    high = tmp_path / "High.Movie.2026.1080p"
    low = tmp_path / "Low.Movie.2026.1080p"
    high.mkdir()
    low.mkdir()
    config = AppConfig()
    config.rename.mode = RenameMode.HYBRID
    config.rename.min_confidence_for_hybrid = 0.85
    service = RenameService(
        config,
        FakeProvider(
            {
                high.name: suggestion("High Movie - 2026", 0.9),
                low.name: suggestion("Low Movie - 2026", 0.6),
            }
        ),
        HistoryLog(tmp_path / "history.jsonl"),
    )

    result = await service.run(tmp_path)

    assert len(result.applied) == 1
    assert len(result.queued) == 1
    assert (tmp_path / "High Movie - 2026").exists()
    assert low.exists()


@pytest.mark.asyncio
async def test_history_jsonl_written_after_successful_rename(tmp_path: Path) -> None:
    source = tmp_path / "Robin.Hood.2026.1080p-GRP"
    source.mkdir()
    history_path = tmp_path / "history.jsonl"
    config = AppConfig()
    config.rename.mode = RenameMode.AUTO
    service = RenameService(
        config,
        FakeProvider({source.name: suggestion("Robin Hood - 2026")}),
        HistoryLog(history_path),
    )

    await service.run(tmp_path)

    contents = history_path.read_text(encoding="utf-8")
    assert '"original_basename": "Robin.Hood.2026.1080p-GRP"' in contents
    assert '"new_basename": "Robin Hood - 2026"' in contents
