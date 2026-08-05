"""User-facing output.

The MVP UX is deliberately minimal: print a concise summary (KiCad surfaces an
IPC action's stdout in its status/warning area) and open the full web report.
If wxPython happens to be importable, we additionally show a small results
dialog - but wx is never required.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import webbrowser
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .core import RunResult


def _log(msg: str) -> None:
    """Append a line to a debug log so we can see what happened on a button click
    (the plugin's stdout is easy to miss in KiCad)."""
    try:
        from .config import _platform_config_dir

        d = _platform_config_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "last-run.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


# Hold a module-level reference to the wx.App. Without this the app is garbage
# collected right after _try_wx returns, and building any window then fails with
# "The wx.App object must be created first!".
_WX_APP = None


def _try_wx():
    global _WX_APP
    try:
        import wx  # type: ignore
    except Exception:
        return None
    try:
        if wx.GetApp() is None:
            _WX_APP = wx.App()
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

    # Always open the web report first (this is reliable from a KiCad-spawned
    # process); the in-KiCad window is a best-effort extra on top.
    if open_browser and result.report_url:
        try:
            webbrowser.open(result.report_url)
            _log("opened browser report")
        except Exception as e:
            _log(f"browser open failed: {e!r}")

    wx = _try_wx()
    _log(f"wx available: {wx is not None}")
    if wx is not None:
        try:
            _show_dialog(wx, result, text)
            _log("results dialog shown+closed")
        except Exception as e:
            _log("results dialog error:\n" + traceback.format_exc())
            print(f"[ProvenMetal] (results dialog error: {e})", flush=True)


def _show_dialog(wx, result: "RunResult", text: str) -> None:
    title = "ProvenMetal Sourcing" + (f" ({result.ref})" if result.ref else "")
    dlg = wx.Dialog(None, title=title, size=(600, 480),
                    style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP)
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

    # Bring it to the front on macOS, where a window from a subprocess can open
    # behind KiCad.
    def _raise():
        try:
            dlg.Raise()
            dlg.RequestUserAttention()
        except Exception:
            pass

    wx.CallAfter(_raise)
    dlg.ShowModal()
    dlg.Destroy()


def run_with_window(run_fn: "Callable[[Callable[[str], None]], RunResult]") -> None:
    """Open a window immediately, run `run_fn(report)` in a background thread while
    showing live progress, then fill the window with the results.

    `run_fn` takes a `report(msg)` callback and returns a RunResult (or raises).
    Falls back to a plain run + results dialog when wx isn't available.
    """
    wx = _try_wx()
    if wx is None:
        # No GUI: run inline and print/open the report at the end.
        result = run_fn(report)
        show_results(result)
        return

    # ProvenMetal brand palette (defense-grade: black canvas, bone type, one red).
    CANVAS = wx.Colour(10, 10, 10)
    PANEL = wx.Colour(20, 20, 20)
    BONE = wx.Colour(244, 246, 248)
    RED = wx.Colour(255, 0, 33)
    STEEL = wx.Colour(154, 167, 176)
    LINE = wx.Colour(45, 45, 45)
    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icon_48.png")

    def mono(size, bold=False):
        info = wx.FontInfo(size).FaceName("Menlo")
        return wx.Font(info.Bold() if bold else info)

    class _ProgressFrame(wx.Frame):
        def __init__(self):
            super().__init__(
                None, title="ProvenMetal Sourcing", size=(640, 520),
                style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP,
            )
            self.SetBackgroundColour(CANVAS)
            try:
                self.SetIcon(wx.Icon(logo_path, wx.BITMAP_TYPE_PNG))
            except Exception:
                pass
            panel = wx.Panel(self)
            panel.SetBackgroundColour(CANVAS)
            self._panel = panel
            v = wx.BoxSizer(wx.VERTICAL)

            # Header: logo mark + wordmark.
            header = wx.BoxSizer(wx.HORIZONTAL)
            try:
                header.Add(
                    wx.StaticBitmap(panel, bitmap=wx.Bitmap(logo_path, wx.BITMAP_TYPE_PNG)),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14,
                )
            except Exception:
                pass
            tb = wx.BoxSizer(wx.VERTICAL)
            word = wx.StaticText(panel, label="PROVENMETAL")
            word.SetForegroundColour(BONE)
            word.SetFont(mono(16, bold=True))
            sub = wx.StaticText(panel, label="BOM SOURCING")
            sub.SetForegroundColour(STEEL)
            sub.SetFont(mono(9))
            tb.Add(word)
            tb.Add(sub, 0, wx.TOP, 3)
            header.Add(tb, 0, wx.ALIGN_CENTER_VERTICAL)
            v.Add(header, 0, wx.ALL, 18)

            hair = wx.Panel(panel, size=(-1, 1))
            hair.SetBackgroundColour(LINE)
            v.Add(hair, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 18)

            self.status = wx.StaticText(panel, label="Working ...")
            self.status.SetForegroundColour(STEEL)
            self.status.SetFont(mono(12, bold=True))
            v.Add(self.status, 0, wx.ALL, 18)

            self.counts = wx.BoxSizer(wx.HORIZONTAL)
            v.Add(self.counts, 0, wx.LEFT | wx.RIGHT, 18)

            self.gauge = wx.Gauge(panel, range=100)
            v.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 18)

            self.box = wx.TextCtrl(
                panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.BORDER_SIMPLE
            )
            self.box.SetBackgroundColour(PANEL)
            self.box.SetForegroundColour(BONE)
            self.box.SetFont(mono(11))
            v.Add(self.box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 18)

            row = wx.BoxSizer(wx.HORIZONTAL)
            self.open_btn = wx.Button(panel, label="Open report")
            self.open_btn.Disable()
            self.close_btn = wx.Button(panel, id=wx.ID_CLOSE, label="Close")
            row.AddStretchSpacer()
            row.Add(self.open_btn, 0, wx.RIGHT, 8)
            row.Add(self.close_btn, 0)
            v.Add(row, 0, wx.EXPAND | wx.ALL, 18)

            panel.SetSizer(v)
            self._report_url = None
            self.open_btn.Bind(wx.EVT_BUTTON, self._on_open)
            self.close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.Close())
            self.Bind(wx.EVT_CLOSE, self._on_close)
            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda _e: self.gauge.Pulse())
            self._timer.Start(120)
            self.CentreOnScreen()
            self.Raise()
            self.RequestUserAttention()

        def _on_open(self, _evt):
            if self._report_url:
                webbrowser.open(self._report_url)

        def add_line(self, msg):
            self.box.AppendText(msg + "\n")

        def _chip(self, label, value, color):
            t = wx.StaticText(self._panel, label=f"{label} {value}")
            t.SetForegroundColour(color)
            t.SetFont(mono(14, bold=True))
            self.counts.Add(t, 0, wx.RIGHT, 22)

        def finish_ok(self, result):
            self._timer.Stop()
            self.gauge.SetValue(100)
            s = result.summary
            self.status.SetLabel("DONE" + (f"   {result.ref}" if result.ref else ""))
            self.status.SetForegroundColour(BONE)
            self.counts.Clear(delete_windows=True)
            self._chip("PARTS", s.get("total", 0), STEEL)
            self._chip("PASS", s.get("pass", 0), BONE)
            self._chip("REVIEW", s.get("review", 0), STEEL)
            fail = s.get("fail", 0)
            self._chip("FAIL", fail, RED if fail else STEEL)
            self.box.AppendText("\n" + summary_text(result) + "\n")
            self._report_url = result.report_url
            self.open_btn.Enable()
            self._panel.Layout()
            self.Raise()

        def finish_error(self, msg):
            self._timer.Stop()
            self.gauge.SetValue(0)
            self.status.SetLabel("SOMETHING WENT WRONG")
            self.status.SetForegroundColour(RED)
            self.box.AppendText("\nERROR: " + msg + "\n")
            self.Raise()

        def _on_close(self, _evt):
            try:
                self._timer.Stop()
            except Exception:
                pass
            self.Destroy()
            app = wx.GetApp()
            if app:
                app.ExitMainLoop()

    frame = _ProgressFrame()
    frame.Show()

    def worker():
        try:
            res = run_fn(lambda m: wx.CallAfter(frame.add_line, m))
            wx.CallAfter(frame.finish_ok, res)
        except Exception as e:  # noqa: BLE001
            _log("run failed:\n" + traceback.format_exc())
            wx.CallAfter(frame.finish_error, str(e))

    threading.Thread(target=worker, daemon=True).start()
    wx.GetApp().MainLoop()


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
