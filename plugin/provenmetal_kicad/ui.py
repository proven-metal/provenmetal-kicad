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

        # An app must exist for dialogs; reuse one if present, else create it.
        if wx.GetApp() is None:
            wx.App()
        return wx
    except Exception:
        return None


def report(msg: str) -> None:
    print(f"[ProvenMetal] {msg}", flush=True)


def summary_text(result: "RunResult") -> str:
    s = result.summary
    header = "ProvenMetal sourcing"
    if result.ref:
        header = f"{header} ({result.ref})"
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
            lines.append(f"  [{ln.get('verdict', '?').upper()}] {ref}  {part}  {ln.get('reason', '')}")
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

    wx = _try_wx()
    if wx is not None:
        try:
            _show_dialog(wx, result, text)
            return  # the dialog has its own "Open report" button
        except Exception as e:
            print(f"[ProvenMetal] (results dialog error: {e})", flush=True)

    # No GUI available: fall back to opening the web report.
    if open_browser and result.report_url:
        try:
            webbrowser.open(result.report_url)
        except Exception:
            pass


def _show_dialog(wx, result: "RunResult", text: str) -> None:
    title = "ProvenMetal Sourcing" + (f" ({result.ref})" if result.ref else "")
    dlg = wx.Dialog(None, title=title, size=(600, 480),
                    style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    panel = wx.Panel(dlg)
    outer = wx.BoxSizer(wx.VERTICAL)

    s = result.summary
    head = wx.StaticText(
        panel,
        label=f"Parts: {s.get('total', 0)}      Pass: {s.get('pass', 0)}      "
        f"Needs review: {s.get('review', 0)}      Fail: {s.get('fail', 0)}",
    )
    font = head.GetFont()
    font.SetPointSize(font.GetPointSize() + 2)
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    head.SetFont(font)
    outer.Add(head, 0, wx.ALL, 12)

    box = wx.TextCtrl(panel, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
    box.SetFont(wx.Font(wx.FontInfo(11).Family(wx.FONTFAMILY_TELETYPE)))
    outer.Add(box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

    row = wx.BoxSizer(wx.HORIZONTAL)
    open_btn = wx.Button(panel, label="Open report")
    close_btn = wx.Button(panel, id=wx.ID_CLOSE, label="Close")
    row.AddStretchSpacer()
    row.Add(open_btn, 0, wx.RIGHT, 8)
    row.Add(close_btn, 0)
    outer.Add(row, 0, wx.EXPAND | wx.ALL, 12)

    panel.SetSizer(outer)
    open_btn.Bind(wx.EVT_BUTTON, lambda _e: webbrowser.open(result.report_url))
    close_btn.Bind(wx.EVT_BUTTON, lambda _e: dlg.EndModal(wx.ID_CLOSE))
    dlg.ShowModal()
    dlg.Destroy()


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
