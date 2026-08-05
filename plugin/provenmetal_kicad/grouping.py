"""Turn raw (coalesced) BOM rows into orderable lines for the push.

kicad-cli already groups references, but we re-consolidate by our stable
line_key (mpn || lcsc || value) so the result is deterministic regardless of how
the CLI grouped, and so two rows that resolve to the same orderable part merge
cleanly.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# Truthy spellings kicad-cli's ${DNP} generated field can produce.
_DNP_TRUE = {"1", "true", "yes", "dnp", "x", "y"}

# Placeholder strings that mean "no value" - some BOM generators write these into
# MPN/manufacturer columns for un-sourced or bare-pad parts (e.g. test points).
_PLACEHOLDERS = {"", "-", "--", "\u2014", "\u2013", "n/a", "na", "tbd", "?", "none"}


def _clean(value: str) -> str:
    v = (value or "").strip()
    return "" if v.lower() in _PLACEHOLDERS else v


def _is_truthy(value: str) -> bool:
    return (value or "").strip().lower() in _DNP_TRUE


# A reference range token like "C11-C18" or "C11-18" (same prefix on both ends).
_RANGE_RE = re.compile(r"^([A-Za-z]+)(\d+)\s*-\s*([A-Za-z]*)(\d+)$")


def _expand_token(token: str) -> List[str]:
    """Expand a reference range ("C11-C18" -> C11..C18); pass anything else through."""
    m = _RANGE_RE.match(token)
    if not m:
        return [token]
    prefix, start_s, end_prefix, end_s = m.groups()
    if end_prefix and end_prefix != prefix:
        return [token]  # mismatched prefixes - not a real range
    start, end = int(start_s), int(end_s)
    if end < start or end - start > 100000:
        return [token]
    return [f"{prefix}{n}" for n in range(start, end + 1)]


def _split_refs(value: str) -> List[str]:
    if not value:
        return []
    # References may be comma/whitespace separated and may contain ranges (R1-R4)
    # when the source kept them (e.g. a hand-generated BOM CSV). Expand ranges so
    # the reference list matches the quantity and writeback can match symbols.
    out: List[str] = []
    for raw in re.split(r"[,\s]+", value.strip()):
        tok = raw.strip()
        if tok:
            out.extend(_expand_token(tok))
    return out


def _int_or(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def line_key_for(row: Dict[str, str]) -> Optional[str]:
    """Stable per-line identity, mirroring the server (mpn || lcsc || value)."""
    for key in ("mpn", "lcsc", "value"):
        v = _clean(row.get(key, ""))
        if v:
            return v.lower()
    return None


def group_rows(rows: List[Dict[str, str]], exclude_dnp: bool = True) -> List[Dict[str, object]]:
    """Consolidate coalesced rows into orderable snapshot lines.

    Returns a list of dicts shaped for POST /api/kicad/bom `lines[]`.
    """
    merged: Dict[str, Dict[str, object]] = {}

    for row in rows:
        if exclude_dnp and _is_truthy(row.get("dnp", "")):
            continue
        key = line_key_for(row)
        if key is None:
            # Nothing orderable on this row (no MPN, LCSC or value) - skip it.
            continue

        refs = _split_refs(row.get("reference", ""))
        qty = _int_or(row.get("qty", ""), len(refs) or 1)
        qty = max(1, qty)

        if key not in merged:
            merged[key] = {
                "line_key": key,
                "references": list(refs),
                "mpn": _clean(row.get("mpn", "")) or None,
                "manufacturer": _clean(row.get("manufacturer", "")) or None,
                "lcsc": _clean(row.get("lcsc", "")) or None,
                "value": _clean(row.get("value", "")) or None,
                "footprint": _clean(row.get("footprint", "")) or None,
                "description": _clean(row.get("description", "")) or None,
                "quantity_per_board": qty,
                "digikey": _clean(row.get("digikey", "")) or None,
                "mouser": _clean(row.get("mouser", "")) or None,
            }
        else:
            existing = merged[key]
            # Union references (preserve order, drop dupes).
            seen = set(existing["references"])  # type: ignore[arg-type]
            for r in refs:
                if r not in seen:
                    existing["references"].append(r)  # type: ignore[attr-defined]
                    seen.add(r)
            existing["quantity_per_board"] = int(existing["quantity_per_board"]) + qty  # type: ignore[arg-type]
            # Fill any field the first occurrence lacked.
            for fldname in ("mpn", "manufacturer", "lcsc", "value", "footprint", "description", "digikey", "mouser"):
                if not existing.get(fldname):
                    val = _clean(row.get(fldname, ""))
                    if val:
                        existing[fldname] = val

    # Stable output order: by first reference, then line_key.
    def sort_key(line: Dict[str, object]):
        refs = line["references"]  # type: ignore[index]
        first = refs[0] if refs else ""  # type: ignore[index]
        return (str(first), str(line["line_key"]))

    return sorted(merged.values(), key=sort_key)
