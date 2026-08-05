# ProvenMetal KiCad Plugin

Push a KiCad project's BOM to **ProvenMetal Central**, source it against
distributor stock and lead time, and flag any part that isn't **in stock (for the
full build quantity) or sourceable within one week** — so long-lead parts surface
before they bite.

See [`SPEC.md`](./SPEC.md) for the full design and rationale.

---

## How it works

1. You click **Source with ProvenMetal** in the KiCad PCB editor toolbar.
2. The plugin reads the schematic BOM via `kicad-cli sch export bom`.
3. It signs you in to ProvenMetal (browser-based, one time) and pushes the BOM.
4. The server sources every line and returns a per-part verdict:
   - **pass** — in stock for the whole build, or sourceable within a week
   - **needs review** — couldn't get a confident answer (left for manual sourcing)
   - **fail** — not stocked anywhere, or out of stock with a long lead
5. You get a summary in KiCad and the full report opens in your browser.

> **KiCad version note.** Requires **KiCad 9+**; **KiCad 11** is the best
> experience. On KiCad 11 the action appears in the **schematic editor** and can
> optionally write results back into symbol fields over IPC. On KiCad 9/10 the
> action appears in the **PCB editor** (their IPC API is PCB-only) and reads the
> schematic through `kicad-cli`; writeback is unavailable there. BOM reading uses
> `kicad-cli` on every version because it handles hierarchy, units, DNP and
> grouping better than raw symbol reads.

---

## Install (users)

### Via the Plugin & Content Manager (recommended)
Once published to a PCM repository:
1. KiCad → **Plugin and Content Manager**.
2. Add the ProvenMetal repository (URL provided by your admin) if it isn't listed.
3. Install **ProvenMetal Sourcing** and restart KiCad.
4. Enable the IPC API: **Preferences → Plugins → “Enable KiCad API”** (KiCad 9+).

### Manual install (internal/testing)
Copy the `plugin/` directory into your KiCad IPC plugins folder:
- macOS: `~/Documents/KiCad/<version>/plugins/provenmetal_kicad/`
- Windows: `C:\Users\<you>\Documents\KiCad\<version>\plugins\provenmetal_kicad\`
- Linux: `~/.local/share/KiCad/<version>/plugins/provenmetal_kicad/`

KiCad creates a managed virtualenv and installs `requirements.txt` on first load.
The action appears once that finishes.

---

## Configure

The only required setting is the ProvenMetal Central base URL (default
`https://central.provenmetal.com`). Everything else (Supabase login details) is
fetched from the server.

Settings live in `settings.json` in the plugin's config directory:
- macOS: `~/Library/Application Support/provenmetal-kicad/`
- Linux: `~/.config/provenmetal-kicad/`
- Windows: `%APPDATA%\provenmetal-kicad\`

```jsonc
{
  "base_url": "https://central.provenmetal.com",
  "oauth_provider": "google",
  "board_count": 10,
  "exclude_dnp": true,
  "kicad_cli_path": "",          // set only if auto-discovery fails
  "field_map": {                 // only if your schematic uses non-standard names
    "mpn": "Manufacturer Part Number",
    "lcsc": "LCSC Part #"
  },
  "bom_csv": "",                 // source from a BOM CSV instead of the schematic
  "writeback": false,            // KiCad 11+: write results into symbol fields
  "writeback_field_prefix": "PM"
}
```

Standard schematic field names are auto-detected: `MPN`, `Manufacturer`, `LCSC` /
`LCSC Part #`, `Digikey`, `Mouser`. Digikey/Mouser part numbers are stored as
metadata — sourcing matches on **MPN** or **LCSC** only.

### Sourcing from a BOM CSV
If your MPNs live in a generated BOM rather than in symbol fields, point the plugin
at the CSV (headers are auto-mapped by name; reference ranges like `C11-C18` are
expanded):

```bash
python -m provenmetal_kicad --project /path/to/project --bom-csv bom.csv --board-count 10
```

### Writeback (KiCad 11+)
Set `"writeback": true` to write `PM_Status`, `PM_Stock`, `PM_Lead_Days`,
`PM_Supplier` and `PM_Checked` back onto each symbol after sourcing (matched by
reference, in one undoable commit). No-op on KiCad 9/10.

The link between your KiCad project and its ProvenMetal project is stored in a
sidecar `myproject.provenmetal.json` next to the schematic (safe to commit).

---

## Headless / CLI (dev & CI)

```bash
python -m provenmetal_kicad --project /path/to/kicad/project --board-count 10
python -m provenmetal_kicad --login          # sign in and exit
python -m provenmetal_kicad --set-base-url https://central.example.com
python -m provenmetal_kicad --logout
```

Run from the `plugin/` directory (or with `plugin/` on `PYTHONPATH`).

---

## Server requirements (ProvenMetal Central)

The plugin talks to the `/api/kicad/*` surface added to `provenmetal-central`:

1. Apply migration `supabase/shared/0034_kicad_bom_revisions.sql` (by hand, per
   that repo's convention).
2. Set the usual env: `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPABASE_URL`,
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, and — for live
   sourcing — `SOURCING_SERVICE_URL` + `SOURCING_SERVICE_HMAC_KEY` (without them
   the BOM is stored and returned with `status: "no-sourcing"`).
3. In Supabase Auth → **URL Configuration → Redirect URLs**, allow the loopback
   URLs the login flow uses:
   ```
   http://127.0.0.1:53682/callback
   http://127.0.0.1:53683/callback
   http://127.0.0.1:53684/callback
   http://127.0.0.1:8976/callback
   ```

Endpoints:
- `GET  /api/kicad/config` — public bootstrap (Supabase URL + anon key).
- `POST /api/kicad/bom` — push + source + verdict (Bearer JWT).
- `GET  /api/kicad/bom/[projectId]` — latest verdict (Bearer JWT).

---

## Develop / test

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Pure logic (`fields`, `grouping`, `verdict`) is tested without KiCad or network.
`kicad_env`, `ui`, and `entry` are the only modules that touch KiCad/wx.

---

## Package for PCM

`metadata.json` is the PCM manifest. Build a package by zipping `plugin/` (with
`metadata.json` at the archive root alongside it per the PCM layout) and validate
with the kicad-python tooling:

```bash
python -m kipy.packaging validate <path-to-package-or-zip>
```

`download_url` / `download_sha256` / `download_size` / `install_size` in
`metadata.json` are filled in at publish time by the repository build.

---

## Limitations (MVP)

- Display-only; no writeback into the schematic (KiCad 9/10 limitation).
- The action is on the **PCB editor** toolbar (no schematic toolbar on 9/10).
- Sourcing runs synchronously (up to ~60s) during the push; a progress line is
  printed and, if wxPython is available, a results dialog is shown.
- `kicad-cli` must be discoverable (auto-detected; override with `kicad_cli_path`).
