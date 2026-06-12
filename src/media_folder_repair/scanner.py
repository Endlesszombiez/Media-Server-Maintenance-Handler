from __future__ import annotations

from pathlib import Path

from media_folder_repair.config import ScanConfig


def iter_folders(root: Path, config: ScanConfig) -> list[Path]:
    mounted = root.expanduser().resolve()
    if not mounted.exists() or not mounted.is_dir():
        raise NotADirectoryError(f"{mounted} is not a directory")

    folders: list[Path] = []
    for path in mounted.rglob("*"):
        if not path.is_dir():
            continue
        relative_parts = path.relative_to(mounted).parts
        if any(part in config.skip_names for part in relative_parts):
            continue
        if config.skip_hidden and any(part.startswith(".") for part in relative_parts):
            continue
        folders.append(path)
    return folders
