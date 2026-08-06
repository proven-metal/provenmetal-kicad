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
    ui.reset_log()
    ui._log("=== action invoked ===")
    try:
        context = connect_ipc()
        ui._log(f"connect_ipc -> {'ok' if context else 'None'}")
        if context is None:
            ui.show_error(
                "Couldn't find an open KiCad project.\n\n"
                "Open your board in the PCB editor (or the schematic on KiCad 11), "
                "then click the button again.\n\n"
                "If nothing happens at all, turn on the API in Settings > Plugins > "
                "Enable KiCad API and restart KiCad."
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
    except Exception as e:  # last-resort guard: never exit silently
        import traceback
        ui._log("fatal:\n" + traceback.format_exc())
        ui.show_error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
