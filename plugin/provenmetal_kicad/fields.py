"""Mapping between KiCad schematic fields and our canonical BOM columns.

We drive `kicad-cli sch export bom` with an explicit `--fields`/`--labels` pair,
so the OUTPUT header names are always our labels regardless of how the source
schematic named its fields. That makes CSV parsing deterministic: we just read
the labelled columns.

The only thing that varies per project is WHICH schematic field holds each value
(e.g. "MPN" vs "Manufacturer Part Number", "LCSC" vs "LCSC Part #"). We request a
few well-known candidates per canonical column and coalesce them, and the user
can pin exact names via Settings.field_map.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Canonical columns we care about, in a stable order. `description` matters even
# when there's no MPN: Bob classifies + parametric-searches passives from the
# value + description ("10 uF 16V X5R 0603"), so it's a first-class sourcing input.
CANONICAL = ["reference", "value", "footprint", "mpn", "manufacturer", "lcsc", "digikey", "mouser", "description", "qty", "dnp"]

# For each canonical column, the schematic field name(s) to request. Generated
# fields use ${...}. Multiple entries become multiple labelled columns that we
# coalesce left-to-right (first non-empty wins). Order matters: the user's pinned
# name (from field_map) is inserted first by build_field_spec().
DEFAULT_CANDIDATES: Dict[str, List[str]] = {
    "reference": ["Reference"],
    "value": ["Value"],
    "footprint": ["Footprint"],
    "mpn": ["MPN", "Manufacturer Part Number", "MFR#", "Mfr Part #", "Part Number"],
    "manufacturer": ["Manufacturer", "Mfr", "MFN", "Mfg"],
    "lcsc": ["LCSC", "LCSC Part #", "LCSC Part Number", "JLCPCB Part #"],
    "digikey": ["Digikey", "Digi-Key", "DigiKey Part Number", "DK Part #"],
    "mouser": ["Mouser", "Mouser Part Number", "Mouser #"],
    "description": ["Description", "Desc", "Comment", "Comments"],
    "qty": ["${QUANTITY}"],
    "dnp": ["${DNP}"],
}

# Fields kicad-cli should group references under. Kept to always-present fields
# plus the MPN/LCSC candidates so distinct parts don't merge; our own grouping
# (grouping.py) is the authority and re-consolidates by line_key regardless.
GROUP_BY_CANONICAL = ["value", "footprint", "mpn", "lcsc"]


def _labelled(canonical: str, index: int) -> str:
    """A unique, safe label for the Nth candidate of a canonical column."""
    return canonical if index == 0 else f"{canonical}__{index}"


def build_field_spec(field_map: Dict[str, str] | None = None) -> Tuple[str, str, str]:
    """Return (fields_arg, labels_arg, group_by_arg) for kicad-cli.

    `field_map` pins exact schematic field names per canonical column; a pinned
    name is tried first, then the defaults.
    """
    field_map = field_map or {}
    fields: List[str] = []
    labels: List[str] = []

    for canonical in CANONICAL:
        candidates = list(DEFAULT_CANDIDATES[canonical])
        pinned = (field_map.get(canonical) or "").strip()
        if pinned and pinned not in candidates:
            candidates.insert(0, pinned)
        for i, cand in enumerate(candidates):
            fields.append(cand)
            labels.append(_labelled(canonical, i))

    group_fields: List[str] = []
    for canonical in GROUP_BY_CANONICAL:
        pinned = (field_map.get(canonical) or "").strip()
        if pinned:
            group_fields.append(pinned)
        # Add the first default candidate too (harmless if the field is absent).
        first = DEFAULT_CANDIDATES[canonical][0]
        if not first.startswith("${") and first not in group_fields:
            group_fields.append(first)

    return ",".join(fields), ",".join(labels), ",".join(group_fields)


def canonical_labels() -> List[str]:
    """All labels emitted by build_field_spec, so the CSV reader knows the columns."""
    labels: List[str] = []
    for canonical in CANONICAL:
        n = len(DEFAULT_CANDIDATES[canonical])
        # +1 for a possibly-pinned name; parser tolerates missing labels anyway.
        for i in range(n + 1):
            labels.append(_labelled(canonical, i))
    return labels


# ---------------------------------------------------------------------------
# CSV import: map an arbitrary BOM CSV's headers onto our canonical columns.
# Used when sourcing from an existing BOM file rather than the schematic.
# ---------------------------------------------------------------------------

def _build_header_aliases() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    # Every candidate schematic field name is also a plausible CSV header.
    for canonical, candidates in DEFAULT_CANDIDATES.items():
        for cand in candidates:
            key = cand.strip("${}").strip().lower()
            if key:
                aliases.setdefault(key, canonical)
    # Extra common CSV spellings not covered by the schematic candidates.
    aliases.update(
        {
            "reference": "reference",
            "references": "reference",
            "refs": "reference",
            "ref": "reference",
            "designator": "reference",
            "designators": "reference",
            "reference(s)": "reference",
            "value": "value",
            "val": "value",
            "footprint": "footprint",
            "package": "footprint",
            "description": "description",
            "desc": "description",
            "comment": "description",
            "comments": "description",
            "qty": "qty",
            "quantity": "qty",
            "qnty": "qty",
            "quantity per pcb": "qty",
            "part number": "mpn",
            "part#": "mpn",
            "part no": "mpn",
            "mfr part #": "mpn",
            "manufacturer part #": "mpn",
            "dnp": "dnp",
            "do not populate": "dnp",
            "exclude from bom": "dnp",
        }
    )
    return aliases


HEADER_ALIASES = _build_header_aliases()


def resolve_header(header: str, field_map: Dict[str, str] | None = None) -> str | None:
    """Return the canonical column a CSV header maps to (or None if unknown)."""
    field_map = field_map or {}
    low = (header or "").strip().lower()
    for canonical, name in field_map.items():
        if (name or "").strip().lower() == low:
            return canonical
    return HEADER_ALIASES.get(low)


def map_csv_row(raw: Dict[str, str], field_map: Dict[str, str] | None = None) -> Dict[str, str]:
    """Project one CSV row (header -> value) onto canonical columns.

    First non-empty value wins when several headers map to the same canonical.
    Always returns every canonical key (missing ones as "").
    """
    out: Dict[str, str] = {c: "" for c in CANONICAL}
    for header, value in raw.items():
        canonical = resolve_header(header, field_map)
        if canonical is None:
            continue
        v = (value or "").strip()
        if v and not out[canonical]:
            out[canonical] = v
    return out


def coalesce_row(raw: Dict[str, str]) -> Dict[str, str]:
    """Collapse the labelled columns of one CSV row into canonical values.

    For each canonical column, take the first non-empty of its labelled variants
    (`mpn`, `mpn__1`, `mpn__2`, ...).
    """
    out: Dict[str, str] = {}
    for canonical in CANONICAL:
        value = ""
        # Try up to a generous number of variants; stop when neither exists.
        for i in range(0, 12):
            key = _labelled(canonical, i)
            if key not in raw:
                if i == 0:
                    continue
                # No more variants for this canonical.
                if i > len(DEFAULT_CANDIDATES[canonical]):
                    break
                continue
            candidate = (raw.get(key) or "").strip()
            if candidate:
                value = candidate
                break
        out[canonical] = value
    return out
