from pathlib import Path

from media_folder_repair.config import AppConfig, load_config, save_config
from media_folder_repair.models import RenameMode
from media_folder_repair.scanner import iter_folders


def test_config_load_save_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.lmstudio.model = "local-model"
    config.rename.mode = RenameMode.AUTO

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.provider == "lmstudio"
    assert loaded.lmstudio.base_url == "http://localhost:1234/v1"
    assert loaded.lmstudio.model == "local-model"
    assert loaded.rename.mode == "auto"
    assert ".git" in loaded.scan.skip_names


def test_scanner_skips_hidden_system_and_root(tmp_path: Path) -> None:
    (tmp_path / "Movies").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "Movies" / "Nested").mkdir()

    folders = iter_folders(tmp_path, AppConfig().scan)

    assert tmp_path not in folders
    assert tmp_path / "Movies" in folders
    assert tmp_path / "Movies" / "Nested" in folders
    assert tmp_path / ".hidden" not in folders
    assert tmp_path / ".git" not in folders
