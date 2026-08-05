#!/usr/bin/env python3
"""KiCad IPC action entrypoint (referenced by plugin.json).

KiCad launches this as a standalone script in the plugin's virtualenv. We add the
plugin root to sys.path so the package imports resolve, connect to KiCad to learn
the open project, then run the push-and-source flow.
"""

from __future__ import annotations

import os
import sys

# Make `import provenmetal_kicad` work when run as a bare script by KiCad.
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from provenmetal_kicad import ui  # noqa: E402
from provenmetal_kicad.core import run  # noqa: E402
from provenmetal_kicad.kicad_env import connect_ipc  # noqa: E402
from provenmetal_kicad.config import load_settings, settings_dir  # noqa: E402


def main() -> int:
    ui._log("=== button/action invoked ===")
    context = connect_ipc()
    ui._log(f"connect_ipc -> {'ok' if context else 'None'}")
    if context is None:
        ui.show_error(
            "Couldn't connect to KiCad or find the open project. Open a project in "
            "KiCad and try again. (Enable the API in Preferences > Plugins, and note "
            "the schematic editor action requires KiCad 11+; on 9/10 use the PCB "
            "editor toolbar.)"
        )
        return 1

    settings = load_settings(settings_dir(context.settings_path))
    ui._log(f"project={context.project_name} dir={context.project_dir} cli={context.kicad_cli}")

    def run_fn(report):
        report(f"Project: {context.project_name}")
        result = run(context, settings=settings, interactive=True, report=report)
        ui._log(f"run ok: {result.summary}")
        # KiCad 11+: optionally write the verdict back into the schematic symbols.
        if settings.writeback and result.lines:
            try:
                from provenmetal_kicad.writeback import apply_writeback, WritebackUnavailable

                try:
                    apply_writeback(
                        context.ipc_client, result.lines,
                        prefix=settings.writeback_field_prefix, report=report,
                    )
                except WritebackUnavailable as e:
                    report(f"Writeback skipped: {e}")
            except Exception as e:  # never let writeback break the run
                report(f"Writeback skipped: {e}")
        return result

    # Opens a window immediately and shows live progress, then the results.
    ui.run_with_window(run_fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
