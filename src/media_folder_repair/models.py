from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RenameMode(StrEnum):
    PREVIEW = "preview"
    AUTO = "auto"
    HYBRID = "hybrid"


class CollisionPolicy(StrEnum):
    SKIP_AND_REPORT = "skip_and_report"
    PROMPT_EACH_TIME = "prompt_each_time"


class RenameStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    SKIPPED = "skipped"
    QUEUED_FOR_REVIEW = "queued_for_review"


@dataclass(frozen=True)
class ProviderSuggestion:
    should_rename: bool
    suggested_name: str | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class RenameProposal:
    source_path: Path
    target_name: str
    confidence: float
    reason: str
    provider: str
    model: str
    profile: str

    @property
    def target_path(self) -> Path:
        return self.source_path.with_name(self.target_name)


@dataclass(frozen=True)
class RenameResult:
    source_path: Path
    target_path: Path | None
    status: RenameStatus
    reason: str
    proposal: RenameProposal | None = None


@dataclass(frozen=True)
class RepairRunResult:
    run_id: str
    proposals: list[RenameProposal]
    applied: list[RenameResult]
    queued: list[RenameResult]
    skipped: list[RenameResult]
