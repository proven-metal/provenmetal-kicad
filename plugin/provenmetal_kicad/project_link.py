"""The link between a KiCad project and its ProvenMetal Central project id.

Stored as a sidecar file next to the schematic - `<project>.provenmetal.json` -
so it travels with the project (and can be committed to version control). We
can't stash it inside the schematic because KiCad 9/10 IPC can't write there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SIDECAR_SUFFIX = ".provenmetal.json"


@dataclass
class ProjectLink:
    project_id: str
    ref: Optional[str] = None
    board_count: Optional[int] = None


def sidecar_path(project_dir: Path, project_name: str) -> Path:
    return Path(project_dir) / f"{project_name}{SIDECAR_SUFFIX}"


def load_link(project_dir: Path, project_name: str) -> Optional[ProjectLink]:
    path = sidecar_path(project_dir, project_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    pid = (data.get("projectId") or "").strip()
    if not pid:
        return None
    return ProjectLink(
        project_id=pid,
        ref=data.get("ref"),
        board_count=data.get("boardCount"),
    )


def save_link(project_dir: Path, project_name: str, link: ProjectLink) -> Path:
    path = sidecar_path(project_dir, project_name)
    payload = {"projectId": link.project_id}
    if link.ref:
        payload["ref"] = link.ref
    if link.board_count is not None:
        payload["boardCount"] = link.board_count
    path.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
    return path
