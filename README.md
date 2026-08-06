# ProvenMetal Sourcing for KiCad

A KiCad plugin that checks your BOM against real distributor stock and lead time,
and flags any part that is not in stock or sourceable within a week.

You click one button in KiCad. The plugin reads your BOM, sends it to ProvenMetal,
and shows each part as pass, needs review, or fail, with a link to the full report.

## What you need

- KiCad 9, 10, or 11.
- A ProvenMetal account (sign in with Google the first time; it is free).
- Parts identified by an MPN, or by a value plus a description (for passives).
  Parts with no usable identity come back as "needs review".

## Install

In KiCad, open the **Plugin and Content Manager**, click **Manage**, and add this
repository URL:

```
https://raw.githubusercontent.com/proven-metal/provenmetal-kicad/main/pcm/repository.json
```

Then install **ProvenMetal Sourcing** and restart KiCad.

Prefer a file? Download the latest
[release zip](https://github.com/proven-metal/provenmetal-kicad/releases/latest)
and use **Install from File** in the Plugin and Content Manager.

One time, turn on the API: **Settings > Plugins > Enable KiCad API** (on macOS,
Settings is Cmd+comma), then restart KiCad.

## Use

1. Open your project. On KiCad 11 the button is in the schematic editor. On KiCad
   9 and 10 it is in the PCB editor toolbar (their API is PCB only).
2. Click **Source with ProvenMetal**.
3. Sign in the first time (a browser tab opens). It is remembered after that.
4. A window shows progress, then the results: pass, needs review, and fail counts,
   the parts that need attention, and an **Open report** button.

## What gets sent

The plugin sends your BOM lines (references, value, footprint, MPN, manufacturer,
LCSC, and any Digi-Key or Mouser numbers), the project name, and your board count.
It does not upload your schematic or layout. Sourcing matches on MPN or LCSC;
Digi-Key and Mouser numbers are stored as extra data.

## Reading the results

- **Pass**: in stock for the whole build, or sourceable within a week.
- **Needs review**: no confident answer yet. Usually a missing part number, or a
  net label or test point that is not a real part.
- **Fail**: not stocked anywhere, or out of stock with a long lead.

## Settings (optional)

Settings live in `settings.json` in the config folder:

- macOS: `~/Library/Application Support/provenmetal-kicad/`
- Linux: `~/.config/provenmetal-kicad/`
- Windows: `%APPDATA%\provenmetal-kicad\`

```jsonc
{
  "board_count": 10,             // how many boards you plan to build
  "exclude_dnp": true,           // skip Do-Not-Populate parts
  "kicad_cli_path": "",          // set only if the plugin cannot find kicad-cli
  "field_map": {                 // set if your fields use non-standard names
    "mpn": "Manufacturer Part Number"
  },
  "bom_csv": "",                 // read from a BOM CSV instead of the schematic
  "writeback": false             // KiCad 11: write results back into symbol fields
}
```

Standard field names are detected automatically: MPN, Manufacturer, LCSC (or
"LCSC Part #"), Digikey, Mouser, and Description.

### Source from a BOM CSV

If your part numbers live in a generated BOM rather than in the schematic, set
`bom_csv` in settings.json to the CSV path, then click the button as usual.
Headers are matched by name and reference ranges like `C11-C18` are expanded.

### Writeback (KiCad 11)

Set `"writeback": true` to write the result onto each symbol as `PM_Status`,
`PM_Stock`, `PM_Lead_Days`, and `PM_Supplier`. This does nothing on KiCad 9 and 10.

## Troubleshooting

- **No button after installing.** The plugin's Python environment has to build
  first. Open Settings > Plugins, right-click ProvenMetal Sourcing, and choose
  Recreate Plugin Environment. Make sure Enable KiCad API is on, then restart.
- **Clicking does nothing, or an error.** A log of the last run is written to the
  config folder above as `last-run.log`. Open an issue and paste it.
- **Cannot find kicad-cli.** Set `kicad_cli_path` in settings to the full path of
  your `kicad-cli` binary.

## For contributors

```
python -m unittest discover -s tests -p "test_*.py" -v   # tests, no KiCad needed
python build_pcm.py                                       # build the PCM package
```

The pure logic (fields, grouping, verdict) has no KiCad or network dependency.
The plugin ships no third-party Python dependencies beyond the KiCad API bindings.

## License

MIT.
