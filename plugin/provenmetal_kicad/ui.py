"""User-facing output.

The MVP UX is deliberately minimal: print a concise summary (KiCad surfaces an
IPC action's stdout in its status/warning area) and open the full web report.
If wxPython happens to be importable, we additionally show a small results
dialog - but wx is never required.
"""

from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import RunResult


def _try_wx():
    try:
        import wx  # type: ignore

        # An app must exist for dialogs; reuse KiCad's if present.
        if wx.App.Get() is None:
            wx.App(False)
        return wx
    except Exception:
        return None


def report(msg: str) -> None:
    print(f"[ProvenMetal] {msg}", flush=True)


def summary_text(result: "RunResult") -> str:
    s = result.summary
    header = "ProvenMetal sourcing"
    if result.ref:
        header = f"{header} \u2014 {result.ref}"
    lines = [
        header,
        f"Parts: {s.get('total', 0)}   Pass: {s.get('pass', 0)}   "
        f"Needs review: {s.get('review', 0)}   Fail: {s.get('fail', 0)}",
    ]
    if result.status == "no-sourcing":
        lines.append("Note: sourcing service not configured on the server - BOM stored, not sourced.")
    elif result.status == "degraded":
        lines.append("Note: sourcing was degraded (timed out) - some lines may need a re-check.")
    if result.sourcing_error:
        lines.append(f"Sourcing note: {result.sourcing_error}")
    for w in result.warnings:
        lines.append(f"Warning: {w}")
    # Lead with the worst offenders.
    flagged = [ln for ln in result.lines if ln.get("verdict") in ("fail", "review")]
    if flagged:
        lines.append("")
        lines.append("Needs attention:")
        for ln in flagged[:15]:
            ref = ln.get("reference") or ln.get("lineKey") or "?"
            part = ln.get("mpn") or ln.get("lcsc") or ln.get("lineKey") or "?"
            lines.append(f"  [{ln.get('verdict', '?').upper()}] {ref}  {part}  \u2014 {ln.get('reason', '')}")
        if len(flagged) > 15:
            lines.append(f"  ... and {len(flagged) - 15} more")
    else:
        lines.append("All parts are in stock or sourceable within a week.")
    lines.append("")
    lines.append(f"Full report: {result.report_url}")
    return "\n".join(lines)


def show_results(result: "RunResult", open_browser: bool = True) -> None:
    text = summary_text(result)
    print(text, flush=True)

    if open_browser and result.report_url:
        try:
            webbrowser.open(result.report_url)
        except Exception:
            pass

    wx = _try_wx()
    if wx is None:
        return
    try:
        style = wx.OK | wx.ICON_INFORMATION
        if any(ln.get("verdict") == "fail" for ln in result.lines):
            style = wx.OK | wx.ICON_WARNING
        dlg = wx.MessageDialog(None, text, "ProvenMetal Sourcing", style)
        dlg.ShowModal()
        dlg.Destroy()
    except Exception:
        pass


def show_error(message: str) -> None:
    print(f"[ProvenMetal] ERROR: {message}", flush=True)
    wx = _try_wx()
    if wx is None:
        return
    try:
        dlg = wx.MessageDialog(None, message, "ProvenMetal - Error", wx.OK | wx.ICON_ERROR)
        dlg.ShowModal()
        dlg.Destroy()
    except Exception:
        pass
