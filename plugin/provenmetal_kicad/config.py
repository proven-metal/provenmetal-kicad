"""Plugin configuration + on-disk settings.

The plugin needs exactly ONE required setting: the ProvenMetal Central base URL.
Everything else (Supabase URL + anon key for the login flow) is fetched from
`GET {base_url}/api/kicad/config` at runtime, so the user never pastes Supabase
details.

Settings + cached credentials live in a per-user directory. When running inside
KiCad we prefer the path KiCad hands us (get_plugin_settings_path), which is
stable across upgrades; otherwise we fall back to the platform config dir.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from . import IDENTIFIER

# Where the plugin talks to by default. Override per-install via settings.json or
# the PROVENMETAL_BASE_URL environment variable.
DEFAULT_BASE_URL = "https://central.provenmetal.com"

# Loopback ports the login flow will try (first free wins). These exact URLs must
# be on the Supabase Auth "Redirect URLs" allow-list (see README).
LOOPBACK_PORTS = [53682, 53683, 53684, 8976]

# Default OAuth provider for the login flow (matches the web app).
DEFAULT_OAUTH_PROVIDER = "google"

SETTINGS_FILENAME = "settings.json"


def _platform_config_dir() -> Path:
    """Best-effort per-user config directory, without a platformdirs dependency."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "provenmetal-kicad"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "provenmetal-kicad"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "provenmetal-kicad"


def settings_dir(kicad_supplied: Optional[str] = None) -> Path:
    """Resolve (and create) the directory settings + credentials live in.

    `kicad_supplied` is the path returned by KiCad's get_plugin_settings_path()
    when we're running as an IPC plugin; preferred when available.
    """
    root = Path(kicad_supplied) if kicad_supplied else _platform_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Settings:
    """User-editable settings, persisted as settings.json."""

    base_url: str = DEFAULT_BASE_URL
    oauth_provider: str = DEFAULT_OAUTH_PROVIDER
    # Default number of boards for the build (drives "in stock >= build qty").
    board_count: int = 1
    # Drop Do-Not-Populate parts before sourcing (we don't buy what isn't stuffed).
    exclude_dnp: bool = True
    # Explicit kicad-cli path override; empty = auto-discover.
    kicad_cli_path: str = ""
    # Which schematic field names hold each canonical value. Empty uses the
    # sensible defaults in fields.py. Keys: mpn, manufacturer, lcsc, digikey,
    # mouser. Values are the exact schematic field name in this project.
    field_map: Dict[str, str] = field(default_factory=dict)
    # Source the BOM from an existing CSV instead of the schematic. Some projects
    # keep MPNs in a generated BOM rather than in symbol fields; point this at it.
    # Empty = read the schematic via kicad-cli.
    bom_csv: str = ""
    # KiCad 11+ only: write the sourcing verdict back into each symbol's fields
    # over IPC (e.g. PM_Status, PM_Stock, PM_Lead_Days). Off by default.
    writeback: bool = False
    # Field-name prefix for writeback fields.
    writeback_field_prefix: str = "PM"

    def merged_env(self) -> "Settings":
        """Return a copy with environment-variable overrides applied."""
        env_url = os.environ.get("PROVENMETAL_BASE_URL", "").strip()
        if env_url:
            self.base_url = env_url.rstrip("/")
        else:
            self.base_url = self.base_url.rstrip("/")
        return self


def load_settings(directory: Path) -> Settings:
    path = directory / SETTINGS_FILENAME
    data: Dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    known = {f: data[f] for f in Settings().__dict__ if f in data}
    return Settings(**known).merged_env()


def save_settings(directory: Path, settings: Settings) -> None:
    path = directory / SETTINGS_FILENAME
    path.write_text(json.dumps(asdict(settings), indent=2), "utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
