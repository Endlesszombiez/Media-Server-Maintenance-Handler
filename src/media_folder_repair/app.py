from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static

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
            yield Static("", id="error")
            yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#path", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self._submit_path()

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
            yield Input(value=self.config.lmstudio.model, id="model")
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(self.config)
            return
        if event.button.id == "save":
            self.config.lmstudio.base_url = self.query_one("#base_url", Input).value
            api_key = self.query_one("#api_key", Input).value.strip()
            self.config.lmstudio.api_key = api_key or None
            self.config.lmstudio.model = self.query_one("#model", Input).value.strip()
            self.config.rename.mode = RenameMode(self.query_one("#mode", Select).value)
            self.config.rename.collision_policy = CollisionPolicy(
                self.query_one("#collision", Select).value
            )
            self.config.profile.default = str(self.query_one("#profile", Select).value)
            save_config(self.config)
            self.dismiss(self.config)


class RepairScreen(Screen[None]):
    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, mounted_path: Path, config: AppConfig):
        super().__init__()
        self.mounted_path = mounted_path
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Ready to scan.", id="status")
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
            self.run_worker(self._run_scan(), exclusive=True)

    async def _run_scan(self) -> None:
        self.query_one("#status", Static).update("Scanning folders and asking LM Studio...")
        table = self.query_one("#results", DataTable)
        table.clear()
        provider = LMStudioProvider(self.config.lmstudio)
        service = RenameService(self.config, provider)
        try:
            result = await service.run(self.mounted_path)
        except Exception as exc:  # Textual status surface, detailed behavior is tested below.
            self.query_one("#status", Static).update(f"Scan failed: {exc}")
            return

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
