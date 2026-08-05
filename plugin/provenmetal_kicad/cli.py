"""Headless CLI for dev / CI: `python -m provenmetal_kicad`.

Runs the same flow as the IPC action but resolves the project from a path instead
of a running KiCad. Useful for testing the end-to-end push without launching the
GUI (and, on KiCad 11+, as the basis for a CI push).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, ui
from .config import load_settings, save_settings, settings_dir
from .core import run
from .kicad_env import discover_from_path
from .auth import build_authenticator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="provenmetal-kicad",
        description="Push a KiCad project's BOM to ProvenMetal Central and source it.",
    )
    p.add_argument("--version", action="version", version=f"provenmetal-kicad {__version__}")
    p.add_argument("--project", default=os.getcwd(), help="Path to the KiCad project directory or a project file (default: cwd).")
    p.add_argument("--bom-csv", default=None, help="Source the BOM from this CSV instead of the schematic (for projects that keep MPNs in a generated BOM).")
    p.add_argument("--board-count", type=int, default=None, help="Number of boards for the build (overrides the saved default).")
    p.add_argument("--base-url", default=None, help="ProvenMetal Central base URL for this run (does not persist).")
    p.add_argument("--set-base-url", default=None, help="Persist a new default base URL and exit.")
    p.add_argument("--login", action="store_true", help="Sign in (opens a browser) and exit.")
    p.add_argument("--logout", action="store_true", help="Clear the saved credentials and exit.")
    p.add_argument("--no-open", action="store_true", help="Don't open the web report in a browser.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    sdir = settings_dir()
    settings = load_settings(sdir)
    if args.base_url:
        settings.base_url = args.base_url.rstrip("/")

    if args.set_base_url:
        settings.base_url = args.set_base_url.rstrip("/")
        save_settings(sdir, settings)
        print(f"Base URL set to {settings.base_url}")
        return 0

    if args.logout:
        build_authenticator(settings, sdir).logout()
        print("Signed out.")
        return 0

    if args.login:
        from .api import ProvenMetalClient

        config = ProvenMetalClient(settings.base_url).get_config()
        build_authenticator(settings, sdir).get_access_token(config, interactive=True)
        print("Signed in.")
        return 0

    try:
        context = discover_from_path(args.project)
    except Exception as e:
        ui.show_error(f"Couldn't resolve a KiCad project from {args.project}: {e}")
        return 1

    try:
        result = run(
            context,
            settings=settings,
            board_count=args.board_count,
            bom_csv=args.bom_csv,
            interactive=True,
            report=ui.report,
        )
    except Exception as e:
        ui.show_error(str(e))
        return 1

    ui.show_results(result, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
