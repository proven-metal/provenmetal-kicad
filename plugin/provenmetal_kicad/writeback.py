"""Write sourcing results back into schematic symbol fields over IPC.

KiCad 11+ only: the IPC schematic API can read and modify symbols. We add a small
set of invisible metadata fields to each symbol (default prefix ``PM``):

    PM_Status     pass | review | fail
    PM_Stock      units available at the best offer's supplier
    PM_Lead_Days  lead time in days
    PM_Supplier   digikey | mouser | ...
    PM_Checked    ISO date of this run

Best-effort and non-fatal: any failure (older KiCad without the schematic API,
no schematic open, a symbol that won't update) is caught and reported, never
raised - the sourcing result is already saved server-side regardless.

All kipy imports are lazy so importing this module never requires KiCad.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Callable, Dict, List, Optional

Reporter = Callable[[str], None]


class WritebackUnavailable(Exception):
    """Raised when the running KiCad can't do schematic writeback (pre-11)."""


def _split_refs(value: str) -> List[str]:
    if not value:
        return []
    return [p for p in (p.strip() for p in re.split(r"[,\s]+", value)) if p]


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _set_user_field(SchematicField, fields: list, name: str, value: str) -> None:
    """Set (or add) a user field by name on a symbol's user_fields list."""
    for f in fields:
        try:
            if f.name == name:
                f.text.value = value
                f.visible = False
                return
        except Exception:
            continue
    field = SchematicField()
    field.name = name
    field.text.value = value
    try:
        field.visible = False
        field.show_name = False
    except Exception:
        pass
    fields.append(field)


def apply_writeback(
    ipc_client: Any,
    result_lines: List[Dict[str, Any]],
    prefix: str = "PM",
    report: Reporter = lambda _m: None,
) -> int:
    """Write verdicts back onto the open schematic's symbols. Returns the number
    of symbols updated. Raises WritebackUnavailable on a pre-11 KiCad."""
    if ipc_client is None:
        raise WritebackUnavailable("No KiCad IPC connection for writeback.")

    try:
        from kipy.schematic_types import SchematicField  # type: ignore
    except Exception as e:  # pragma: no cover - depends on installed kipy
        raise WritebackUnavailable(f"kipy schematic types unavailable: {e}") from e

    try:
        schematic = ipc_client.get_schematic()
    except Exception as e:
        raise WritebackUnavailable(
            "This KiCad build has no schematic API - writeback needs KiCad 11+."
        ) from e

    # Map each individual reference to its result line.
    ref_to_line: Dict[str, Dict[str, Any]] = {}
    for line in result_lines:
        for ref in _split_refs(_fmt(line.get("reference"))):
            ref_to_line[ref] = line

    today = datetime.date.today().isoformat()
    commit = schematic.begin_commit()
    updated: list = []
    try:
        for sym in schematic.get_symbols():
            try:
                ref = sym.reference_field.text.value
            except Exception:
                continue
            line = ref_to_line.get(ref)
            if not line:
                continue
            fields = list(sym.user_fields)
            _set_user_field(SchematicField, fields, f"{prefix}_Status", _fmt(line.get("verdict")))
            _set_user_field(SchematicField, fields, f"{prefix}_Stock", _fmt(line.get("stock")))
            _set_user_field(SchematicField, fields, f"{prefix}_Lead_Days", _fmt(line.get("leadTimeDays")))
            _set_user_field(SchematicField, fields, f"{prefix}_Supplier", _fmt(line.get("supplier")))
            _set_user_field(SchematicField, fields, f"{prefix}_Checked", today)
            sym.user_fields = fields
            updated.append(sym)

        if updated:
            schematic.update_items(updated)
            schematic.push_commit(commit, "ProvenMetal sourcing results")
        else:
            schematic.drop_commit(commit)
    except Exception as e:
        try:
            schematic.drop_commit(commit)
        except Exception:
            pass
        report(f"Writeback failed: {e}")
        return 0

    report(f"Wrote sourcing results into {len(updated)} symbol(s).")
    return len(updated)
