# ProvenMetal KiCad Plugin — Specification

A KiCad plugin that reads a project's BOM, pushes it to **ProvenMetal Central**, has
it sourced server-side (via the "Bob" sourcing service), and reports whether every
part is **in stock somewhere or sourceable within one week** — so long-lead parts
get flagged proactively and the BOM can be pre-sourced.

---

## 1. Goal & scope

- Extract the BOM from a KiCad **schematic** (the canonical BOM source).
- Push it to ProvenMetal Central over an authenticated API.
- Central sources each line through Bob (Digikey / Mouser / LCSC identity), then
  computes a per-line **verdict**.
- Pull the verdict back and show a pass / needs-review / fail summary in the plugin,
  with a link to the full web report.

**MVP is display-only** (no writeback into the schematic — see §3).

---

## 2. Confirmed product decisions

| Area          | Decision |
|---------------|----------|
| KiCad target  | **9+**, primary target **KiCad 11** (schematic IPC). IPC plugin via PCM. |
| Action scope  | `schematic` + `pcb` — appears in the schematic editor on 11, PCB editor on 9/10. |
| BOM source    | Schematic via `kicad-cli sch export bom` (robust on all versions), **or** an existing BOM CSV (`--bom-csv` / `bom_csv`) for projects that keep MPNs outside the schematic. |
| Backend       | Talk to **provenmetal-central** only (never Bob directly). |
| Auth          | Loopback **PKCE → Supabase user JWT**; bearer auth on `/api/kicad/*`. |
| Data flow     | Push BOM → server sources via Bob → pull verdict back. |
| Writeback     | **KiCad 11+**: opt-in write of `PM_Status`/`PM_Stock`/`PM_Lead_Days`/`PM_Supplier`/`PM_Checked` into symbol user-fields via IPC. Not possible on 9/10. |
| Part identity | MPN (+manufacturer) or LCSC for sourcing; Digikey/Mouser PNs are metadata. |
| Revisions     | New immutable **BOM snapshot per push** (`cen_kicad_bom_revisions`). |
| "In stock"    | `stock >= required build qty` (qty/board × boardCount). |
| Repos         | Plugin in `provenmetal-kicad`; API changes in `provenmetal-central`. |

### Why BOM reading stays on `kicad-cli` even on KiCad 11
KiCad 11 adds a schematic IPC API, but `kicad-cli sch export bom` still does the
hierarchical instance expansion, multi-unit consolidation, DNP/exclude-from-BOM
handling and grouping for us — reimplementing that over raw IPC symbol reads
would be worse, not better. KiCad 11's schematic IPC is used for the thing it is
uniquely good at: **writing results back** into symbols. Reading over IPC remains
a possible future path but is not required.

---

## 3. IPC capability by KiCad version (why the design looks like this)

| Capability                 | KiCad 9 / 10 | KiCad 11 |
|----------------------------|:------------:|:--------:|
| IPC in the PCB editor      | ✅ | ✅ |
| IPC in the schematic editor| ❌ | ✅ |
| Read schematic symbols/fields via IPC | ❌ | ✅ |
| Write schematic symbols/fields via IPC | ❌ | ✅ |
| Headless / file export via IPC | ❌ | ✅ |

Design consequences:

1. **BOM reading** goes through `kicad-cli sch export bom` on every version (it does
   the hierarchy/units/DNP/grouping work; see §2). The action still uses IPC to find
   the open project and register the toolbar button.
2. **Action placement**: scopes are `["schematic","pcb"]`. On KiCad 11 the button
   appears in the **schematic editor** (where the BOM lives); on 9/10 it appears in
   the **PCB editor** (schematic scope is ignored there).
3. **Writeback** (§5a) uses the KiCad 11 schematic IPC to set metadata fields on
   symbols. It is opt-in and a no-op on 9/10 (reported, never fatal).

---

## 4. Architecture

```
KiCad (PCB editor)
  └─ IPC plugin action "Source with ProvenMetal"  (Python, kicad-python + plugin.json)
       1. discover project path (IPC, with CWD/arg fallbacks)
       2. kicad-cli sch export bom  ->  rows (Reference, Value, Footprint, MPN, Mfr, LCSC, Qty, DNP)
       3. group rows -> orderable lines (line_key), drop DNP
       4. OAuth: loopback PKCE login -> Supabase user JWT (cached, refreshed)
       5. POST BOM  -> provenmetal-central /api/kicad/bom  (Bearer JWT)
             central: create/find design, upsert cen_bom_lines, source via Bob,
                      compute verdict, snapshot revision
       6. show verdict dialog + "Open report"

provenmetal-central (new /api/kicad/* surface)
  - GET  /api/kicad/config              (public) supabase url + anon key for PKCE
  - POST /api/kicad/bom                 (bearer) push + source + verdict (round trip)
  - GET  /api/kicad/bom/[projectId]     (bearer) latest verdict + lines (re-fetch)
  reuses: createOrder, syncBomLines, deriveSourceFields, the Bob service-client,
          insertSourceRun, and the existing account/orders/[id] report page.
```

---

## 5. Verdict logic (server-side, authoritative)

Per line, after Bob returns `stock` + `lead_time_days`:

- `required_qty  = quantity_per_board × boardCount`
- `in_stock      = stock != null && stock >= required_qty`
- `sourceable_1w = lead_time_days != null && lead_time_days <= 7`
- `PASS  = in_stock || sourceable_1w`
- `REVIEW = !PASS && (source_status == 'manual' || (stock == null && lead_time_days == null && status != 'unmatched'))`  — unknown data
- `FAIL  = otherwise` — unmatched, or out of stock with a long/unknown lead

A project passes overall when every non-DNP, non-customer-supplied line is `PASS`.

Note: this is **stricter** than central's existing `derive.ts` (84-day risk
threshold). The 1-week rule is specific to this plugin and lives in
`src/lib/kicad/verdict.ts`.

---

## 5a. Writeback (KiCad 11+, opt-in)

After a push, if `writeback` is enabled and the running KiCad exposes the schematic
IPC API, the plugin writes invisible metadata fields onto each symbol (matched by
reference), inside a single undoable commit:

```
PM_Status     pass | review | fail
PM_Stock      units at the best offer's supplier
PM_Lead_Days  lead time (days)
PM_Supplier   digikey | mouser | ...
PM_Checked    ISO date of the run
```

Prefix is configurable (`writeback_field_prefix`, default `PM`). On KiCad 9/10 this
is skipped with a message. Implemented in `writeback.py` via `begin_commit` →
`get_symbols` → set `user_fields` → `update_items` → `push_commit`.

## 6. API contract

### `GET /api/kicad/config`  (public)
```json
{ "supabaseUrl": "https://xxxx.supabase.co", "supabaseAnonKey": "sb_publishable_...",
  "appUrl": "https://central.provenmetal.com" }
```

### `POST /api/kicad/bom`  (Authorization: Bearer <supabase access token>)
```jsonc
{
  "projectId": "uuid | null",       // null on first push -> creates a design
  "name": "FlightControllerV1",
  "boardCount": 10,
  "clientVersion": "0.1.0",
  "lines": [{
    "line_key": "stm32h743vit6",    // mpn || lcsc || value, lowercased
    "references": ["U1"],
    "mpn": "STM32H743VIT6",
    "manufacturer": "STMicroelectronics",
    "lcsc": "C123",
    "value": "MCU",
    "footprint": "LQFP-100",
    "quantity_per_board": 1,
    "digikey": "497-...",           // metadata only (not a sourcing key)
    "mouser": "511-..."             // metadata only
  }]
}
```
Response:
```jsonc
{
  "projectId": "uuid",
  "revisionId": "uuid",
  "reportUrl": "https://central.../account/orders/<id>",
  "status": "sourced" | "degraded" | "no-sourcing",
  "summary": { "total": 42, "pass": 39, "review": 2, "fail": 1 },
  "lines": [{
    "line_key": "stm32h743vit6", "reference": "U1", "mpn": "STM32H743VIT6",
    "verdict": "pass|review|fail", "reason": "...",
    "stock": 1200, "leadTimeDays": 0, "requiredQty": 10,
    "supplier": "mouser", "unitPriceCents": 812.5,
    "sourceStatus": "matched"
  }]
}
```

### `GET /api/kicad/bom/[projectId]`  (bearer)
Returns the same `{ summary, lines, reportUrl, revisionId, updatedAt }` for the
latest state, for re-opening the plugin without re-sourcing.

---

## 7. Data model — `cen_kicad_bom_revisions` (migration 0034)

Immutable snapshot per push (audit trail). One row per successful push.

| column          | type        | notes |
|-----------------|-------------|-------|
| id              | uuid pk     | |
| order_id        | uuid fk     | cen_orders(id) on delete cascade |
| account_id      | uuid fk     | cen_accounts(id) — for RLS convenience |
| created_by      | uuid        | auth.users(id) |
| client_version  | text        | plugin version |
| board_count     | int         | |
| line_count      | int         | |
| lines           | jsonb       | the submitted BOM lines (immutable) |
| summary         | jsonb       | `{ total, pass, review, fail }` after sourcing |
| status          | text        | 'sourced' \| 'degraded' \| 'no-sourcing' |
| source_run_id   | uuid        | fk cen_source_runs(id), nullable |
| created_at      | timestamptz | default now() |

- RLS: `authenticated` SELECT via `is_cen_order_member(order_id)`; all writes
  service-role. Mirrors `cen_source_runs`.

---

## 8. Plugin layout (`provenmetal-kicad/`)

```
plugin/                         # the KiCad plugin package (ships in PCM zip)
  plugin.json                   # IPC plugin + action metadata (schema v1)
  requirements.txt              # kicad-python, requests, keyring
  provenmetal_kicad/
    __init__.py
    entry.py                    # IPC action entrypoint (argv/env from KiCad)
    config.py                   # base URL + cached config, paths
    bom.py                      # kicad-cli discovery + sch export bom + parse
    grouping.py                 # rows -> orderable lines (line_key, DNP)
    fields.py                   # field-name mapping (MPN/Mfr/LCSC/Digikey/Mouser)
    auth.py                     # loopback PKCE Supabase login + token cache
    api.py                      # ProvenMetal Central HTTP client
    project_link.py             # <project>.provenmetal.json sidecar
    ui.py                       # wx dialogs: progress + results
    cli.py                      # headless entrypoint (dev/CI): python -m provenmetal_kicad
tests/
  test_grouping.py
  test_fields.py
  test_verdict.py               # mirrors server verdict for local display
metadata.json                   # PCM package metadata
resources/icon.png              # toolbar icon (24x24 / 64x64)
README.md
```

---

## 9. Milestones

1. **Backend**: migration 0034, verdict lib, bearer auth, `POST /kicad/bom`,
   `GET /kicad/bom/[id]`, `GET /kicad/config`.
2. **Plugin core**: IPC action + `kicad-cli` BOM extraction + field mapping + grouping.
3. **Auth**: loopback PKCE + token storage.
4. **Round trip**: push → verdict dialog → open report.
5. **Packaging**: PCM metadata + install docs.

**Stretch:** schematic/footprint writeback, per-project thresholds, revision diff,
headless CI push (KiCad 11).

---

## 10. Known risks / assumptions

- `kicad-cli` location varies by OS/install — robust discovery + a manual override
  setting.
- Bob sources on MPN/LCSC only; parts lacking both come back `review`/`fail`.
- The IPC action lives in the **PCB editor** (no schematic toolbar in 9/10).
- Sourcing runs synchronously (~up to 60s) inside `POST /api/kicad/bom`; the plugin
  shows a progress dialog. Requires `SOURCING_SERVICE_URL` +
  `SOURCING_SERVICE_HMAC_KEY` configured on central; without them the push still
  stores the BOM and returns `status: "no-sourcing"`.
