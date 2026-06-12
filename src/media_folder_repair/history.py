from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from media_folder_repair.models import RenameProposal


def default_history_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "media-folder-repair" / "rename-history.jsonl"


class HistoryLog:
    def __init__(self, path: Path | None = None):
        self.path = path or default_history_path()

    def record(self, mounted_path: Path, proposal: RenameProposal, run_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "mounted_path": str(mounted_path),
            "original_absolute_path": str(proposal.source_path),
            "new_absolute_path": str(proposal.target_path),
            "original_basename": proposal.source_path.name,
            "new_basename": proposal.target_name,
            "provider": proposal.provider,
            "model": proposal.model,
            "confidence": proposal.confidence,
            "reason": proposal.reason,
            "profile": proposal.profile,
            "run_id": run_id,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, sort_keys=True) + "\n")
