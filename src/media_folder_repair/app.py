from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.worker import Worker, WorkerState
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)

from media_folder_repair.config import AppConfig, load_config, save_config
from media_folder_repair.models import CollisionPolicy, RenameMode
from media_folder_repair.providers.lmstudio import LMStudioProvider
from media_folder_repair.renamer import RenameService


class MountPathScreen(Screen[Path]):
    BINDINGS = [("x", "app.quit", "Exit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="mount-path"):
            yield Label("Mounted path")
            yield Input(placeholder="/Volumes/Media", id="path")
            yield Button("Browse", id="browse")
            yield DirectoryTree(str(Path.home()), id="folder-browser")
            yield Static("", id="error")
            yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#path", Input).focus()
        self.query_one("#folder-browser", DirectoryTree).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self._submit_path()
        elif event.button.id == "browse":
            browser = self.query_one("#folder-browser", DirectoryTree)
            browser.display = not browser.display

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self.query_one("#path", Input).value = str(event.path)
        self.query_one("#error", Static).update("")

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit_path()

    def _submit_path(self) -> None:
        candidate = Path(self.query_one("#path", Input).value).expanduser()
        if not candidate.exists() or not candidate.is_dir():
            self.query_one("#error", Static).update("Path must exist and be a directory.")
            return
        self.dismiss(candidate.resolve())


class MainMenuScreen(Screen[str]):
    BINDINGS = [
        ("1", "choose('repair')", "Repair"),
        ("c", "choose('config')", "Config"),
        ("x", "choose('exit')", "Exit"),
    ]

    def __init__(self, mounted_path: Path):
        super().__init__()
        self.mounted_path = mounted_path

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-menu"):
            yield Static(f"Mounted path: {self.mounted_path}")
            yield Button("Search & Repair Folder Names", id="repair", variant="primary")
            yield Button("Config", id="config")
            yield Button("Exit", id="exit")
        yield Footer()

    def action_choose(self, choice: str) -> None:
        self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id:
            self.dismiss(event.button.id)


class ConfigScreen(Screen[AppConfig]):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config.model_copy(deep=True)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="config"):
            yield Label("LM Studio URL")
            yield Input(value=self.config.lmstudio.base_url, id="base_url")
            yield Label("API key")
            yield Input(value=self.config.lmstudio.api_key or "", password=True, id="api_key")
            yield Label("Model")
            model_options = (
                [(self.config.lmstudio.model, self.config.lmstudio.model)]
                if self.config.lmstudio.model
                else [("Refresh models from LM Studio", "")]
            )
            with Horizontal():
                yield Select(model_options, value=self.config.lmstudio.model, id="model")
                yield Button("Refresh Models", id="refresh_models")
            yield Static("", id="model_status")
            yield Label("Rename mode")
            yield Select(
                [(mode.value, mode.value) for mode in RenameMode],
                value=self.config.rename.mode.value,
                id="mode",
            )
            yield Label("Collision policy")
            yield Select(
                [(policy.value, policy.value) for policy in CollisionPolicy],
                value=self.config.rename.collision_policy.value,
                id="collision",
            )
            yield Label("Default profile")
            yield Select(
                [(name, name) for name in ("movie", "tv", "music", "generic")],
                value=self.config.profile.default,
                id="profile",
            )
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._refresh_models(), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(self.config)
            return
        if event.button.id == "refresh_models":
            self.run_worker(self._refresh_models(), exclusive=False)
            return
        if event.button.id == "save":
            self.config.lmstudio.base_url = self.query_one("#base_url", Input).value
            api_key = self.query_one("#api_key", Input).value.strip()
            self.config.lmstudio.api_key = api_key or None
            model = self.query_one("#model", Select).value
            self.config.lmstudio.model = "" if model is None else str(model).strip()
            if not self.config.lmstudio.model:
                self.query_one("#model_status", Static).update("Choose an LM Studio model before saving.")
                return
            self.config.rename.mode = RenameMode(self.query_one("#mode", Select).value)
            self.config.rename.collision_policy = CollisionPolicy(
                self.query_one("#collision", Select).value
            )
            self.config.profile.default = str(self.query_one("#profile", Select).value)
            save_config(self.config)
            self.dismiss(self.config)

    async def _refresh_models(self) -> None:
        status = self.query_one("#model_status", Static)
        status.update("Loading LM Studio models...")

        config = self.config.lmstudio.model_copy()
        config.base_url = self.query_one("#base_url", Input).value.strip()
        api_key = self.query_one("#api_key", Input).value.strip()
        config.api_key = api_key or None

        try:
            models = await LMStudioProvider(config).list_models()
        except Exception as exc:
            status.update(f"Could not load LM Studio models: {exc}")
            return

        if not models:
            status.update("LM Studio did not report any loaded models.")
            return

        current = str(self.query_one("#model", Select).value or self.config.lmstudio.model)
        if current and current not in models:
            models.insert(0, current)
        selected = current if current in models else models[0]
        self.query_one("#model", Select).set_options([(model, model) for model in models])
        self.query_one("#model", Select).value = selected
        status.update(f"Loaded {len(models)} LM Studio model(s).")


class RepairScreen(Screen[None]):
    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, mounted_path: Path, config: AppConfig):
        super().__init__()
        self.mounted_path = mounted_path
        self.config = config
        self.scan_worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Ready to scan.", id="status")
        yield ProgressBar(total=1, show_eta=False, id="scan-progress")
        table = DataTable(id="results")
        table.add_columns("Status", "Folder", "Target", "Confidence", "Reason")
        yield table
        with Horizontal():
            yield Button("Start Scan", id="start", variant="primary")
            yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.dismiss(None)
        elif event.button.id == "start":
            if self.scan_worker and self.scan_worker.state in {
                WorkerState.PENDING,
                WorkerState.RUNNING,
            }:
                self.scan_worker.cancel()
                self.query_one("#status", Static).update("Canceling scan...")
                return
            self.scan_worker = self.run_worker(self._run_scan(), exclusive=True)

    async def _run_scan(self) -> None:
        start_button = self.query_one("#start", Button)
        start_button.label = "Cancel Scan"
        start_button.variant = "error"
        try:
            self.query_one("#status", Static).update("Scanning folders and asking LM Studio...")
            progress = self.query_one("#scan-progress", ProgressBar)
            progress.update(total=1, progress=0)
            table = self.query_one("#results", DataTable)
            table.clear()
            provider = LMStudioProvider(self.config.lmstudio)
            service = RenameService(self.config, provider)

            async def update_progress(completed: int, total: int, folder: Path) -> None:
                progress.update(total=max(total, 1), progress=completed)
                self.query_one("#status", Static).update(
                    f"Scanning {completed}/{total}: {folder.relative_to(self.mounted_path)}"
                )

            result = await service.run(self.mounted_path, progress_callback=update_progress)
        except asyncio.CancelledError:
            self.query_one("#status", Static).update("Scan canceled.")
            raise
        except Exception as exc:  # Textual status surface, detailed behavior is tested below.
            self.query_one("#status", Static).update(f"Scan failed: {exc}")
            return
        finally:
            start_button.label = "Start Scan"
            start_button.variant = "primary"
            self.scan_worker = None

        rows = result.applied + result.queued + result.skipped
        for item in rows:
            table.add_row(
                item.status.value,
                str(item.source_path),
                str(item.target_path or ""),
                "" if item.proposal is None else f"{item.proposal.confidence:.2f}",
                item.reason,
            )
        self.query_one("#status", Static).update(
            f"Run {result.run_id}: {len(result.applied)} applied, "
            f"{len(result.queued)} queued, {len(result.skipped)} skipped."
        )


class MediaFolderRepairApp(App[None]):
    CSS = """
    Container {
        padding: 1 2;
    }
    Button {
        margin: 1 1 0 0;
    }
    #error {
        color: red;
        height: 1;
    }
    DataTable {
        height: 1fr;
        margin-top: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.mounted_path: Path | None = None

    def on_mount(self) -> None:
        self.run_worker(self._main_flow(), exclusive=True)

    async def _main_flow(self) -> None:
        self.mounted_path = await self.push_screen_wait(MountPathScreen())
        while True:
            choice = await self.push_screen_wait(MainMenuScreen(self.mounted_path))
            if choice == "exit":
                self.exit()
                return
            if choice == "config":
                self.config = await self.push_screen_wait(ConfigScreen(self.config))
            elif choice == "repair":
                await self.push_screen_wait(RepairScreen(self.mounted_path, self.config))


def run() -> None:
    MediaFolderRepairApp().run()


if __name__ == "__main__":
    run()
