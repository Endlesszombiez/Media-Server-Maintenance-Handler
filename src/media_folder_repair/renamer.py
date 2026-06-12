from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from media_folder_repair.config import AppConfig
from media_folder_repair.history import HistoryLog
from media_folder_repair.models import (
    CollisionPolicy,
    ProviderSuggestion,
    RenameMode,
    RenameProposal,
    RenameResult,
    RenameStatus,
    RepairRunResult,
)
from media_folder_repair.providers.base import FolderNameProvider, ProviderError
from media_folder_repair.scanner import iter_folders

ManualNameChooser = Callable[[RenameProposal], Awaitable[str | None] | str | None]
ProgressCallback = Callable[[int, int, Path], Awaitable[None] | None]

RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_target_name(source_path: Path, suggested_name: str | None) -> str | None:
    if suggested_name is None:
        return "Suggestion is empty"
    name = suggested_name.strip()
    if not name:
        return "Suggestion is empty"
    if RESERVED_CHARS.search(name):
        return "Suggestion contains reserved characters or path separators"
    if name in {".", ".."}:
        return "Suggestion is not a valid folder name"
    if len(name.encode("utf-8")) > 240:
        return "Suggestion is too long"
    if unicodedata.normalize("NFC", name).casefold() == unicodedata.normalize(
        "NFC", source_path.name
    ).casefold():
        return "Suggestion matches existing name"
    target = source_path.with_name(name)
    try:
        target.parent.resolve().relative_to(source_path.parent.resolve())
    except ValueError:
        return "Suggestion targets a path outside the current parent"
    return None


def proposal_from_suggestion(
    path: Path,
    suggestion: ProviderSuggestion,
    provider: FolderNameProvider,
    profile: str,
) -> RenameProposal | None:
    if not suggestion.should_rename or not suggestion.suggested_name:
        return None
    return RenameProposal(
        source_path=path,
        target_name=suggestion.suggested_name.strip(),
        confidence=suggestion.confidence,
        reason=suggestion.reason,
        provider=provider.name,
        model=provider.model,
        profile=profile,
    )


class RenameService:
    def __init__(
        self,
        config: AppConfig,
        provider: FolderNameProvider,
        history: HistoryLog | None = None,
        manual_name_chooser: ManualNameChooser | None = None,
    ):
        self.config = config
        self.provider = provider
        self.history = history or HistoryLog()
        self.manual_name_chooser = manual_name_chooser

    async def collect_proposals(
        self,
        mounted_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[RenameProposal], list[RenameResult]]:
        proposals: list[RenameProposal] = []
        skipped: list[RenameResult] = []
        profile_name = self.config.profile.default
        prompt = self.config.profile_prompt(profile_name)
        progress = progress_callback or _noop_progress
        folders = iter_folders(mounted_path, self.config.scan)
        for index, folder in enumerate(folders, start=1):
            try:
                suggestion = await self.provider.suggest_name(folder.name, prompt)
            except ProviderError as exc:
                skipped.append(
                    RenameResult(folder, None, RenameStatus.SKIPPED, str(exc), proposal=None)
                )
                continue
            proposal = proposal_from_suggestion(folder, suggestion, self.provider, profile_name)
            if proposal is None:
                skipped.append(
                    RenameResult(
                        folder,
                        None,
                        RenameStatus.SKIPPED,
                        suggestion.reason,
                        proposal=None,
                    )
                )
            else:
                proposals.append(proposal)
            await _maybe_await(progress(index, len(folders), folder))
        return proposals, skipped

    async def run(
        self,
        mounted_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> RepairRunResult:
        run_id = str(uuid.uuid4())
        mounted = mounted_path.expanduser().resolve()
        proposals, skipped = await self.collect_proposals(mounted, progress_callback)

        if self.config.rename.mode == RenameMode.PREVIEW:
            queued = [
                RenameResult(
                    proposal.source_path,
                    proposal.target_path,
                    RenameStatus.PROPOSED,
                    "Preview mode",
                    proposal,
                )
                for proposal in proposals
            ]
            return RepairRunResult(run_id, proposals, [], queued, skipped)

        applied: list[RenameResult] = []
        queued: list[RenameResult] = []
        for proposal in proposals:
            if (
                self.config.rename.mode == RenameMode.HYBRID
                and proposal.confidence < self.config.rename.min_confidence_for_hybrid
            ):
                queued.append(
                    RenameResult(
                        proposal.source_path,
                        proposal.target_path,
                        RenameStatus.QUEUED_FOR_REVIEW,
                        "Below hybrid confidence threshold",
                        proposal,
                    )
                )
                continue
            result = await self.apply_proposal(mounted, proposal, run_id)
            if result.status == RenameStatus.APPLIED:
                applied.append(result)
            else:
                skipped.append(result)

        return RepairRunResult(run_id, proposals, applied, queued, skipped)

    async def apply_proposal(self, mounted_path: Path, proposal: RenameProposal, run_id: str) -> RenameResult:
        validation_error = validate_target_name(proposal.source_path, proposal.target_name)
        if validation_error:
            return RenameResult(
                proposal.source_path,
                None,
                RenameStatus.SKIPPED,
                validation_error,
                proposal,
            )

        target_path = proposal.target_path
        if target_path.exists():
            if self.config.rename.collision_policy == CollisionPolicy.PROMPT_EACH_TIME:
                manual = await _maybe_await(
                    self.manual_name_chooser(proposal) if self.manual_name_chooser else None
                )
                if manual:
                    manual_error = validate_target_name(proposal.source_path, manual)
                    manual_proposal = RenameProposal(
                        proposal.source_path,
                        manual.strip(),
                        proposal.confidence,
                        proposal.reason,
                        proposal.provider,
                        proposal.model,
                        proposal.profile,
                    )
                    if manual_error:
                        return RenameResult(
                            proposal.source_path,
                            manual_proposal.target_path,
                            RenameStatus.SKIPPED,
                            manual_error,
                            manual_proposal,
                        )
                    if manual_proposal.target_path.exists():
                        return RenameResult(
                            proposal.source_path,
                            manual_proposal.target_path,
                            RenameStatus.SKIPPED,
                            "Target already exists",
                            manual_proposal,
                        )
                    proposal = manual_proposal
                    target_path = proposal.target_path
                else:
                    return RenameResult(
                        proposal.source_path,
                        proposal.target_path,
                        RenameStatus.SKIPPED,
                        "Target already exists",
                        proposal,
                    )
            else:
                return RenameResult(
                    proposal.source_path,
                    target_path,
                    RenameStatus.SKIPPED,
                    "Target already exists",
                    proposal,
                )

        proposal.source_path.rename(target_path)
        self.history.record(mounted_path, proposal, run_id)
        return RenameResult(
            proposal.source_path,
            target_path,
            RenameStatus.APPLIED,
            "Renamed",
            proposal,
        )


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


def _noop_progress(_: int, __: int, ___: Path) -> None:
    return None
