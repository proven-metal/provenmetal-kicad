"""Orchestration: extract BOM -> authenticate -> push -> return verdict.

This module has no KiCad/wx dependency; it takes a KicadContext and a reporter
callback, so both the IPC entry and the headless CLI drive the same flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from .config import Settings, load_settings, save_settings, settings_dir
from .kicad_env import KicadContext
from .bom import find_kicad_cli, find_schematic, export_bom, parse_bom_csv
from .grouping import group_rows
from .project_link import load_link, save_link, ProjectLink
from .api import ProvenMetalClient, ApiError
from .auth import build_authenticator

# A reporter shows progress to the user (print, wx, ...). Never required.
Reporter = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


@dataclass
class RunResult:
    project_id: str
    ref: Optional[str]
    report_url: str
    status: str
    summary: Dict[str, int]
    lines: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)
    sourcing_error: Optional[str] = None


def run(
    context: KicadContext,
    *,
    settings: Optional[Settings] = None,
    board_count: Optional[int] = None,
    bom_csv: Optional[str] = None,
    interactive: bool = True,
    report: Reporter = _noop,
) -> RunResult:
    """Execute the full push-and-source flow. Raises on hard failures."""
    sdir = settings_dir(context.settings_path)
    settings = settings or load_settings(sdir)

    client = ProvenMetalClient(settings.base_url)
    report(f"Connecting to ProvenMetal Central ({settings.base_url}) ...")
    config = client.get_config()

    warnings: List[str] = []

    # --- BOM extraction ----------------------------------------------------
    csv_path = bom_csv or settings.bom_csv or None
    if csv_path:
        report(f"Reading BOM from {csv_path} ...")
        extract = parse_bom_csv(csv_path, settings.field_map)
    else:
        report("Locating kicad-cli ...")
        cli = find_kicad_cli(settings.kicad_cli_path or None, context.kicad_cli)
        report("Finding schematic ...")
        sch = find_schematic(context.project_dir, context.project_name)
        report(f"Exporting BOM from {sch.name} ...")
        extract = export_bom(cli, sch, settings.field_map, settings.exclude_dnp)
        if extract.part_columns_missing:
            warnings.append(
                "Couldn't read MPN/manufacturer/LCSC fields from the schematic - "
                "check your field names in the plugin settings (field_map). Sourcing "
                "will be limited to what could be read."
            )

    lines = group_rows(extract.rows, exclude_dnp=settings.exclude_dnp)
    if not lines:
        raise RuntimeError(
            "No orderable parts found in the schematic BOM (every line lacked an "
            "MPN, LCSC code and value, or all were marked DNP)."
        )
    report(f"Found {len(lines)} orderable part(s).")

    # --- Auth --------------------------------------------------------------
    link = load_link(context.project_dir, context.project_name)
    resolved_board_count = (
        board_count
        if board_count is not None
        else (link.board_count if link and link.board_count else settings.board_count)
    )
    resolved_board_count = max(1, int(resolved_board_count))

    report("Signing in to ProvenMetal ...")
    authenticator = build_authenticator(settings, sdir)
    token = authenticator.get_access_token(config, interactive=interactive)

    # --- Push + source -----------------------------------------------------
    report(
        f"Pushing {len(lines)} parts for {resolved_board_count} board(s) and sourcing "
        "(this can take up to a minute) ..."
    )
    def do_push(project_id):
        return client.push_bom(
            token,
            name=context.project_name,
            board_count=resolved_board_count,
            lines=lines,
            project_id=project_id,
            client_version=__version__,
        )

    try:
        resp = do_push(link.project_id if link else None)
    except ApiError as e:
        # The linked project was deleted or is no longer accessible: forget the
        # stale link and create a fresh project instead of failing.
        if link and e.code in ("not-found", "forbidden"):
            report("Linked project is gone; creating a new one ...")
            warnings.append("The previously linked ProvenMetal project no longer exists; a new one was created.")
            resp = do_push(None)
        else:
            raise

    project_id = resp.get("projectId")
    if project_id:
        save_link(
            context.project_dir,
            context.project_name,
            ProjectLink(project_id=project_id, ref=resp.get("ref"), board_count=resolved_board_count),
        )

    summary = resp.get("summary") or {"total": 0, "pass": 0, "review": 0, "fail": 0}
    return RunResult(
        project_id=project_id or "",
        ref=resp.get("ref"),
        report_url=resp.get("reportUrl") or f"{config.app_url}/account/orders/{project_id}",
        status=resp.get("status") or "unknown",
        summary=summary,
        lines=resp.get("lines") or [],
        warnings=warnings,
        sourcing_error=resp.get("sourcingError"),
    )


def set_base_url(new_url: str, kicad_settings_path: Optional[str] = None) -> Settings:
    """Persist a new base URL (used by the CLI --set-base-url)."""
    sdir = settings_dir(kicad_settings_path)
    settings = load_settings(sdir)
    settings.base_url = new_url.rstrip("/")
    save_settings(sdir, settings)
    return settings
