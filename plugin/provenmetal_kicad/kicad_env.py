"""Discover the KiCad project context.

Two paths:
  * connect_ipc()          - when launched as a KiCad IPC action, talk to the
                             running KiCad to learn the open project's directory,
                             name, the kicad-cli path, and the plugin settings
                             path. All kipy imports are lazy so the rest of the
                             package (and the tests) never need it.
  * discover_from_path()   - headless/CLI: resolve a project from a path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import IDENTIFIER


@dataclass
class KicadContext:
    project_dir: Path
    project_name: str
    kicad_cli: Optional[str] = None
    settings_path: Optional[str] = None
    version: Optional[str] = None
    source: str = "cli"  # "ipc" | "cli"
    # The live kipy KiCad client when connected over IPC (used for KiCad 11+
    # writeback). Typed as object so importing this module never needs kipy.
    ipc_client: Optional[object] = None


def _dir_from(candidate: str) -> Optional[Path]:
    if not candidate:
        return None
    p = Path(candidate)
    if p.suffix:  # looks like a file (.kicad_pro / .kicad_pcb)
        return p.parent
    if p.exists() and p.is_dir():
        return p
    return None


def connect_ipc() -> Optional[KicadContext]:
    """Return a KicadContext from the running KiCad, or None if unavailable."""
    try:
        from kipy import KiCad  # type: ignore
    except Exception:
        return None

    try:
        kicad = KiCad()
    except Exception:
        return None

    version = None
    try:
        version = str(kicad.get_version())
    except Exception:
        version = None

    try:
        board = kicad.get_board()
    except Exception:
        # No PCB open. The IPC action lives in the PCB editor, so this shouldn't
        # happen in practice, but degrade gracefully.
        return None

    proj_path = ""
    proj_name = ""
    try:
        project = board.get_project()
        proj_path = getattr(project, "path", "") or ""
        proj_name = getattr(project, "name", "") or ""
    except Exception:
        pass

    board_file = ""
    try:
        board_file = getattr(board, "name", "") or ""
    except Exception:
        board_file = ""

    project_dir = _dir_from(proj_path) or _dir_from(board_file)
    if project_dir is None:
        return None
    if not proj_name:
        proj_name = Path(board_file).stem if board_file else project_dir.name

    kicad_cli = None
    try:
        kicad_cli = kicad.get_kicad_binary_path("kicad-cli") or None
    except Exception:
        kicad_cli = None

    settings_path = None
    try:
        settings_path = kicad.get_plugin_settings_path(IDENTIFIER) or None
    except Exception:
        settings_path = None

    return KicadContext(
        project_dir=project_dir,
        project_name=proj_name,
        kicad_cli=kicad_cli,
        settings_path=settings_path,
        version=version,
        source="ipc",
        ipc_client=kicad,
    )


def discover_from_path(path: str) -> KicadContext:
    """Resolve a project context from a filesystem path (dir or project file)."""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        return KicadContext(project_dir=p.parent, project_name=p.stem)
    project_dir = p
    pros = sorted(project_dir.glob("*.kicad_pro"))
    if pros:
        name = pros[0].stem
    else:
        schs = sorted(project_dir.glob("*.kicad_sch"))
        name = schs[0].stem if schs else project_dir.name
    return KicadContext(project_dir=project_dir, project_name=name)
