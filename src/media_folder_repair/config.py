from __future__ import annotations

import os
import tomllib
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from media_folder_repair.models import CollisionPolicy, RenameMode


DEFAULT_SKIP_NAMES = [".git", "__pycache__", ".venv", "node_modules", ".cache"]


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "media-folder-repair" / "config.toml"


class LMStudioConfig(BaseModel):
    base_url: str = "http://localhost:1234/v1"
    api_key: str | None = None
    model: str = ""
    timeout_seconds: float = 60


class RenameConfig(BaseModel):
    mode: RenameMode = RenameMode.PREVIEW
    collision_policy: CollisionPolicy = CollisionPolicy.SKIP_AND_REPORT
    min_confidence_for_hybrid: float = Field(default=0.85, ge=0, le=1)


class ScanConfig(BaseModel):
    skip_hidden: bool = True
    skip_names: list[str] = Field(default_factory=lambda: list(DEFAULT_SKIP_NAMES))


class ProfileConfig(BaseModel):
    prompt: str


class ProfilesConfig(BaseModel):
    movie: ProfileConfig = ProfileConfig(
        prompt=(
            "Clean movie folder names to the format 'Title - Year' when the year is clearly "
            "present. Remove release tags, resolution, codec, source, group names, and "
            "punctuation noise. Do not guess missing years."
        )
    )
    tv: ProfileConfig = ProfileConfig(
        prompt="Clean TV folder names while preserving show title and season/episode meaning."
    )
    music: ProfileConfig = ProfileConfig(
        prompt="Clean music folder names while preserving artist, album, and year when present."
    )
    generic: ProfileConfig = ProfileConfig(
        prompt="Clean folder names conservatively. Preserve meaningful words and avoid guesses."
    )


class DefaultProfileConfig(BaseModel):
    default: str = "movie"


class AppConfig(BaseModel):
    provider: str = "lmstudio"
    lmstudio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    rename: RenameConfig = Field(default_factory=RenameConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    profile: DefaultProfileConfig = Field(default_factory=DefaultProfileConfig)
    profiles: ProfilesConfig = Field(default_factory=ProfilesConfig)

    def profile_prompt(self, name: str | None = None) -> str:
        profile_name = name or self.profile.default
        profile = getattr(self.profiles, profile_name, self.profiles.generic)
        return profile.prompt


def _to_toml(value: object, prefix: str = "") -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    lines: list[str] = []
    scalars: dict[str, object] = {}
    nested: dict[str, object] = {}
    for key, item in dict(value).items():
        if isinstance(item, dict):
            nested[key] = item
        else:
            scalars[key] = item
    for key, item in scalars.items():
        lines.append(f"{key} = {_toml_literal(item)}")
    for key, item in nested.items():
        section = f"{prefix}.{key}" if prefix else key
        lines.append("")
        lines.append(f"[{section}]")
        lines.append(_to_toml(item, section))
    return "\n".join(line for line in lines if line is not None)


def _toml_literal(value: object) -> str:
    if isinstance(value, Enum):
        return _toml_literal(value.value)
    if isinstance(value, str):
        return repr(value).replace("\\'", "'")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    if value is None:
        return "''"
    return str(value)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    if not config_path.exists():
        return AppConfig()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if data.get("lmstudio", {}).get("api_key") == "":
        data["lmstudio"]["api_key"] = None
    return AppConfig.model_validate(data)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_to_toml(config) + "\n", encoding="utf-8")
    return config_path
