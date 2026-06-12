# Media Server Maintenance Handler

`media-sm` is an installable Python terminal app for maintaining mounted media libraries from one app-like TUI. The first included tool is folder name repair, and the project is structured so additional media maintenance tools can be added behind the same mount-path chooser, config system, provider layer, and history/audit foundation.

## Current Tooling

### Search & Repair Folder Names

Recursively scans folders under the selected mounted path, asks LM Studio for cleaner basename-only folder names, validates each suggestion, and renames folders according to the configured safety mode.

The current workflow supports:

- Mounted path selection at app start, with typing or an interactive folder browser.
- Main menu navigation with arrow keys, Enter, and shortcuts.
- LM Studio through its OpenAI-compatible API.
- Naming profiles for movie, TV, music, and generic folders.
- Rename modes: `preview`, `auto`, and `hybrid`.
- Collision policies: `skip_and_report` and `prompt_each_time`.
- JSONL history logging for every successful rename.
- Safety validation before any filesystem rename.
- Scan progress tracking while each folder is processed.

## Planned Tool Areas

This project is intended to grow beyond folder repair. Future tools can be added as separate menu workflows while reusing the same application shell.

Possible next tool categories:

- Library cleanup: find empty folders, duplicate folders, orphaned metadata, and leftover sample/artifact files.
- Media organization: normalize naming by profile, identify uncertain titles, and prepare review queues.
- Integrity checks: detect broken folder structures, missing expected files, and suspiciously small media files.
- Provider-backed metadata helpers: use local AI providers to explain or classify messy media folders.
- Undo and audit tools: expose history review and undo-last-run flows built from the existing JSONL rename log.

## Installation

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Or use the included installer:

```bash
./install.sh
```

Launch the app:

```bash
.venv/bin/media-sm
```

Or use the included launcher:

```bash
./run.sh
```

## App Flow

On launch, `media-sm` asks for a mounted working path. You can type the path manually or use `Browse` to select a folder. The app validates that the path exists and is a directory, then opens the main menu.

Current menu:

- `Search & Repair Folder Names`
- `Config`
- `Exit`

Keyboard shortcuts:

- `1`: open Search & Repair Folder Names
- `C`: open Config
- `X`: exit

## Configuration

Config is stored at:

```text
~/.config/media-folder-repair/config.toml
```

Current fields include:

- `provider`: defaults to `lmstudio`
- `lmstudio.base_url`: defaults to `http://localhost:1234/v1`
- `lmstudio.api_key`: optional
- `lmstudio.model`: selected LM Studio model id, populated from LM Studio's `/v1/models` endpoint in the Config screen
- `lmstudio.timeout_seconds`: request timeout
- `rename.mode`: `preview`, `auto`, or `hybrid`
- `rename.collision_policy`: `skip_and_report` or `prompt_each_time`
- `rename.min_confidence_for_hybrid`: confidence threshold for hybrid mode
- `scan.skip_hidden`: skip hidden folders by default
- `scan.skip_names`: names such as `.git`, `__pycache__`, `.venv`, `node_modules`, and `.cache`
- `profile.default`: default naming profile
- `profiles`: prompt text for movie, TV, music, and generic naming

## Folder Repair Safety Model

The folder repair tool treats provider responses as untrusted suggestions. Before renaming, each suggestion must pass validation:

- No path separators.
- Not empty.
- Not identical after normalization.
- No reserved/problematic filesystem characters.
- Practical filename length.
- Basename-only rename within the current parent folder.
- Collision policy check before applying.

The v1 implementation never moves folders across parents and does not auto-append suffixes.

## Rename Modes

`preview` collects proposals and shows them without renaming anything.

`auto` applies validated suggestions automatically and skips invalid or colliding suggestions.

`hybrid` applies suggestions at or above `rename.min_confidence_for_hybrid` and queues lower-confidence suggestions for review.

## History

Every successful rename is written to:

```text
~/.local/state/media-folder-repair/rename-history.jsonl
```

Each entry includes timestamp, mounted path, original path, new path, original basename, new basename, provider, model, confidence, reason, profile, and run id.

This history is intentionally designed as the foundation for a future `Undo Last Run` tool.

## Development

Run tests:

```bash
.venv/bin/python -m pytest
```

Compile/import smoke check:

```bash
.venv/bin/python -m compileall -q src tests
```

Project layout:

```text
src/media_folder_repair/
  app.py                 Textual app shell and screens
  config.py              Config defaults, load/save, validation
  scanner.py             Recursive folder discovery and skip rules
  profiles.py            Naming profile prompts
  renamer.py             Proposal validation, collisions, rename execution
  history.py             JSONL history log
  providers/base.py      Provider protocol
  providers/lmstudio.py  LM Studio OpenAI-compatible provider
tests/                   Focused unit tests
```

## Adding New Tools

New maintenance tools should plug into the existing app shell instead of becoming separate scripts.

Recommended pattern:

- Add domain logic in a plain service module.
- Keep filesystem-changing behavior testable without the TUI.
- Add a Textual screen or menu workflow in `app.py`.
- Reuse `AppConfig` where settings are shared.
- Write audit/history entries for destructive actions.
- Add focused temp-directory tests for filesystem behavior.
