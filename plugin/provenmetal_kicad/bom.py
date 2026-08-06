"""Extract a BOM from a KiCad schematic via `kicad-cli sch export bom`.

KiCad 9/10's IPC API can't read the schematic, so we shell out to kicad-cli,
which does the hierarchical expansion, grouping and DNP handling for us. We drive
it with an explicit --fields/--labels pair (see fields.py) so the output columns
are deterministic.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import fields as fieldspec


class KicadCliNotFound(Exception):
    pass


class BomExportError(Exception):
    pass


@dataclass
class BomExtract:
    rows: List[Dict[str, str]]  # coalesced canonical rows
    schematic: Path
    # True when the full field set failed and we fell back to a minimal export
    # (so MPN/manufacturer/LCSC columns are unavailable and the user should check
    # their field mapping).
    part_columns_missing: bool


# Platform fallbacks for locating kicad-cli when it isn't on PATH and KiCad
# didn't tell us over IPC. Best-effort; the IPC path is preferred.
def _default_cli_locations() -> List[str]:
    found: List[str] = []
    if sys.platform == "darwin":
        found.append("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
        # KiCad run from a mounted DMG or a non-standard location.
        found += [str(p) for p in Path("/Volumes").glob("KiCad*/KiCad.app/Contents/MacOS/kicad-cli")]
        found += [str(p) for p in Path("/Applications").glob("KiCad*/KiCad.app/Contents/MacOS/kicad-cli")]
    elif os.name == "nt":
        for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not pf:
                continue
            found.append(str(Path(pf) / "KiCad" / "bin" / "kicad-cli.exe"))
            # Versioned installs: C:\Program Files\KiCad\9.0\bin\kicad-cli.exe
            found += [str(p) for p in Path(pf).glob("KiCad/*/bin/kicad-cli.exe")]
    else:
        found += ["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli", "/opt/kicad/bin/kicad-cli"]
        found += [str(p) for p in Path("/snap/bin").glob("kicad*")]
    return found


def find_kicad_cli(explicit: Optional[str] = None, ipc_path: Optional[str] = None) -> str:
    """Locate the kicad-cli binary.

    Preference: explicit setting -> path from KiCad IPC -> PATH -> platform
    defaults. Raises KicadCliNotFound if none resolve.
    """
    for candidate in (explicit, ipc_path):
        if candidate and Path(candidate).exists():
            return candidate
    which = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
    if which:
        return which
    for candidate in _default_cli_locations():
        if Path(candidate).exists():
            return candidate
    raise KicadCliNotFound(
        "Could not find kicad-cli. Set an explicit path in the plugin settings "
        "(kicad_cli_path) or ensure KiCad 9+ is installed."
    )


def find_schematic(project_dir: Path, project_name: Optional[str] = None) -> Path:
    """Locate the root .kicad_sch for a project directory."""
    project_dir = Path(project_dir)
    if project_name:
        named = project_dir / f"{project_name}.kicad_sch"
        if named.exists():
            return named
    schematics = sorted(project_dir.glob("*.kicad_sch"))
    if not schematics:
        raise BomExportError(
            f"No schematic (.kicad_sch) found in {project_dir}. "
            "If your BOM lives in a CSV, set 'bom_csv' in settings.json to its path."
        )
    # Prefer a schematic whose basename matches a .kicad_pro (the root sheet).
    pros = {p.stem for p in project_dir.glob("*.kicad_pro")}
    for sch in schematics:
        if sch.stem in pros:
            return sch
    return schematics[0]


def _run_cli(cli: str, args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise BomExportError(f"kicad-cli timed out after {timeout}s") from e
    except OSError as e:
        raise BomExportError(f"Failed to run kicad-cli: {e}") from e


def _export_to_csv(cli: str, sch: Path, out: Path, fields_arg: str, labels_arg: str,
                   group_by: str, exclude_dnp: bool) -> subprocess.CompletedProcess:
    args = [
        "sch", "export", "bom",
        "-o", str(out),
        "--fields", fields_arg,
        "--labels", labels_arg,
        "--group-by", group_by,
        # Expand reference ranges into a full list so we can count/split cleanly.
        "--ref-range-delimiter", "",
    ]
    if exclude_dnp:
        args.append("--exclude-dnp")
    args.append(str(sch))
    return _run_cli(cli, args)


def _parse_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [fieldspec.coalesce_row(row) for row in reader]


def parse_bom_csv(path: Path, field_map: Optional[Dict[str, str]] = None) -> BomExtract:
    """Read an EXISTING BOM CSV (any reasonable column layout) instead of the
    schematic. Headers are mapped onto our canonical columns by name.

    Some projects keep MPNs in a generated BOM rather than in symbol fields, so
    this is the path for them (and for CI where a BOM was exported earlier).
    """
    path = Path(path)
    if not path.exists():
        raise BomExportError(f"BOM CSV not found: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [fieldspec.map_csv_row(row, field_map) for row in reader]
    return BomExtract(rows=rows, schematic=path, part_columns_missing=False)


def export_bom(
    cli: str,
    schematic: Path,
    field_map: Optional[Dict[str, str]] = None,
    exclude_dnp: bool = True,
) -> BomExtract:
    """Run the export and return coalesced canonical rows."""
    fields_arg, labels_arg, group_by = fieldspec.build_field_spec(field_map)

    with tempfile.TemporaryDirectory(prefix="pm-kicad-bom-") as tmp:
        out = Path(tmp) / "bom.csv"
        proc = _export_to_csv(cli, schematic, out, fields_arg, labels_arg, group_by, exclude_dnp)

        if proc.returncode != 0 or not out.exists():
            # Fall back to a minimal, always-valid field set so we at least get a
            # BOM (references/value/footprint/qty) even if a requested field name
            # tripped the CLI. The user is told part columns are missing.
            safe_fields = "Reference,Value,Footprint,${QUANTITY},${DNP}"
            safe_labels = "reference,value,footprint,qty,dnp"
            proc2 = _export_to_csv(cli, schematic, out, safe_fields, safe_labels, "Value,Footprint", exclude_dnp)
            if proc2.returncode != 0 or not out.exists():
                detail = (proc2.stderr or proc.stderr or "unknown error").strip()
                raise BomExportError(f"kicad-cli sch export bom failed: {detail}")
            return BomExtract(rows=_parse_csv(out), schematic=schematic, part_columns_missing=True)

        return BomExtract(rows=_parse_csv(out), schematic=schematic, part_columns_missing=False)
