# ProvenMetal KiCad Plugin

Sends a KiCad project's BOM to ProvenMetal Central, sources every part against
distributor stock and lead time, and flags anything that is not in stock for the
full build or sourceable within one week.

## How it works

1. Click "Source with ProvenMetal" in KiCad.
2. The plugin reads the BOM (from the schematic, or from a BOM CSV).
3. It signs you in to ProvenMetal in your browser (once) and sends the BOM.
4. The server sources each part and returns a result:
   - pass: in stock for the whole build, or sourceable within a week.
   - review: not enough data to decide (left for manual sourcing).
   - fail: not stocked anywhere, or out of stock with a long lead.
5. You get a summary in KiCad and the full report opens in your browser.

## KiCad versions

Works on KiCad 9, 10, and 11.

- On KiCad 11 the button is in the schematic editor and can write results back
  into symbol fields.
- On KiCad 9 and 10 the button is in the PCB editor (their API is PCB only).

The BOM is always read with `kicad-cli`, which handles hierarchy, units, DNP, and
grouping.

## Install

### Plugin and Content Manager (recommended)

1. In KiCad, open Plugin and Content Manager, click Manage, then add this URL:
   ```
   https://raw.githubusercontent.com/proven-metal/provenmetal-kicad/main/pcm/repository.json
   ```
2. Install "ProvenMetal Sourcing" and restart KiCad.
3. Turn on the API in Preferences, Plugins, "Enable KiCad API".

You can also download the latest
[release zip](https://github.com/proven-metal/provenmetal-kicad/releases/latest)
and use "Install from File".

### Manual install

Copy the `plugin/` directory into your KiCad plugins folder:

- macOS: `~/Documents/KiCad/<version>/plugins/provenmetal_kicad/`
- Windows: `C:\Users\<you>\Documents\KiCad\<version>\plugins\provenmetal_kicad\`
- Linux: `~/.local/share/KiCad/<version>/plugins/provenmetal_kicad/`

KiCad installs the dependencies on first load, then the button appears.

## Settings

The only required setting is the ProvenMetal Central URL, which defaults to
`https://central.provenmetal.com`. Login details are fetched from the server.

Settings live in `settings.json` in the config directory:

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
  "field_map": {                 // set if your schematic uses non-standard names
    "mpn": "Manufacturer Part Number",
    "lcsc": "LCSC Part #"
  },
  "bom_csv": "",                 // read from a BOM CSV instead of the schematic
  "writeback": false,            // KiCad 11+: write results into symbol fields
  "writeback_field_prefix": "PM"
}
```

Common field names are detected automatically: MPN, Manufacturer, LCSC (or
"LCSC Part #"), Digikey, Mouser. Sourcing matches on MPN or LCSC; Digikey and
Mouser numbers are kept as extra data.

The link between a KiCad project and its ProvenMetal project is stored in a
`myproject.provenmetal.json` file next to the schematic. It is safe to commit.

## Sourcing without MPNs

Most schematics do not carry manufacturer part numbers. That is fine. The plugin
sends the value, footprint, and description, and the server sources passives
(resistors, capacitors, inductors, LEDs, and similar) from those. For example
"10 uF 16V X5R 0603" is enough to find a real, in-stock part.

Parts that genuinely cannot be identified (no MPN, LCSC, or usable value) come
back as "review", which is the signal that they need a part number.

If your MPNs live in a generated BOM rather than in the schematic, point the
plugin at that CSV. Headers are matched by name and reference ranges like
`C11-C18` are expanded.

```bash
python -m provenmetal_kicad --project /path/to/project --bom-csv bom.csv --board-count 10
```

## Writeback (KiCad 11)

Set `"writeback": true` to write `PM_Status`, `PM_Stock`, `PM_Lead_Days`,
`PM_Supplier`, and `PM_Checked` onto each symbol after sourcing, matched by
reference, in one undoable commit. This does nothing on KiCad 9 and 10.

## Command line

```bash
python -m provenmetal_kicad --project /path/to/project --board-count 10
python -m provenmetal_kicad --login
python -m provenmetal_kicad --set-base-url https://central.example.com
python -m provenmetal_kicad --logout
```

Run from the `plugin/` directory, or put `plugin/` on `PYTHONPATH`.

## Server (ProvenMetal Central)

The plugin uses these endpoints on ProvenMetal Central:

- `GET /api/kicad/config`: public config for the login flow.
- `POST /api/kicad/bom`: send the BOM, source it, get the result (bearer token).
- `GET /api/kicad/bom/[projectId]`: latest result for a project (bearer token).

Setup on the server:

1. Apply the migration `supabase/shared/0034_kicad_bom_revisions.sql`.
2. Set `NEXT_PUBLIC_SITE_URL`, the Supabase variables, and (for live sourcing)
   `SOURCING_SERVICE_URL` and `SOURCING_SERVICE_HMAC_KEY`. Without the sourcing
   variables the BOM is stored and returned with status "no-sourcing".
3. In Supabase Auth, add these redirect URLs for the plugin login:
   ```
   http://127.0.0.1:53682/callback
   http://127.0.0.1:53683/callback
   http://127.0.0.1:53684/callback
   http://127.0.0.1:8976/callback
   ```

## Develop

Run the tests (no KiCad or network needed):

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Build the PCM package and repository files:

```bash
python build_pcm.py
```

The pure logic (`fields`, `grouping`, `verdict`) has no KiCad or network
dependency. Only `kicad_env`, `ui`, and `entry` touch KiCad.
