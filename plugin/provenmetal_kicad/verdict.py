"""Client-side mirror of the server verdict rule (src/lib/kicad/verdict.ts).

The server is authoritative and returns a `verdict` per line, so the plugin
normally just displays what it gets. This mirror exists for local re-computation
(offline display of a cached result, tests, and defensive fallback if an older
server omitted the field). Keep it in lock-step with the TypeScript version.
"""

from __future__ import annotations

from typing import Dict, List, Optional

SOURCEABLE_WITHIN_DAYS = 7


def verdict_for(
    source_status: Optional[str],
    stock: Optional[int],
    lead_time_days: Optional[int],
    required_qty: int,
) -> str:
    """Return 'pass' | 'review' | 'fail' for one line."""
    required_qty = max(1, required_qty)
    in_stock = stock is not None and stock >= required_qty
    sourceable = lead_time_days is not None and lead_time_days <= SOURCEABLE_WITHIN_DAYS

    if in_stock or sourceable:
        return "pass"
    if source_status == "unmatched":
        return "fail"
    no_data = stock is None and lead_time_days is None
    if source_status == "manual" or source_status is None or no_data:
        return "review"
    return "fail"


def summarize(verdicts: List[str]) -> Dict[str, int]:
    summary = {"total": len(verdicts), "pass": 0, "review": 0, "fail": 0}
    for v in verdicts:
        if v in summary:
            summary[v] += 1
    return summary
