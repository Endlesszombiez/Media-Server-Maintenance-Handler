from __future__ import annotations

SYSTEM_PROMPT = """You repair media folder basenames.
Return only JSON with keys:
should_rename: boolean
suggested_name: string or null
confidence: number from 0 to 1
reason: short string

Rules:
- Rename only the folder basename, never include a parent path.
- Remove release tags such as resolution, codec, source, group, and punctuation noise.
- Preserve meaningful title and year when identifiable.
- Avoid guessing missing years unless clearly present.
- Return should_rename=false if the existing name is already clean or uncertain.
"""


def build_prompt(folder_name: str, profile_prompt: str) -> str:
    return f"{profile_prompt}\n\nFolder basename: {folder_name!r}"
