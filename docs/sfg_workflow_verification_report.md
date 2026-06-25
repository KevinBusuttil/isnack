# ISNACK Semi-Finished Goods Workflow — Technical Verification Report

Scope: ISNACK custom app in this repository (`isnack/api/mes_ops.py`, Storekeeper/Operator
hubs, Factory Settings, hooks), the supplied `BOM (4).csv` / `Item (4).csv` /
`Factory Settings.xlsx` / Line-Warehouse-Map screenshot, cross-referenced against official
**ERPNext / Frappe `version-15`** source. Every conclusion was independently traced; nothing
was assumed correct.

Representative data (FG10011 / SFG10001 / SFG10002), verified from the exports:

| Item | Group | Stock UOM | has_batch_no | is_sales_item (Allow Sales) | Item Default Warehouse | Default BOM |
|---|---|---|---|---|---|---|
| FG10011 | Finished Goods | Carton | **1** | 1 | Stores - ISN | BOM-FG10011-002 |
| SFG10001 | Semi-Finished Goods | Kg | **0** | **0** | Semi-finished - ISN | BOM-SFG10001-001 |
| SFG10002 | Semi-Finished Goods | Kg | **0** | **1** | **Stores - ISN** | BOM-SFG10002-001 |

`BOM-FG10011-002` direct components (non-exploded): SFG10001 160 Kg, SFG10002 120 Kg,
PM40011 21 Kg, CR30003 300 Carton. Both SFG rows have `do_not_explode = 0` and carry a
`bom_no`, i.e. they explode to corn grits / water / oil / seasoning.

Line Warehouse Map (screenshot + Factory Settings), `default_semi_finished_warehouse = Semi-finished - ISN`:

| Section | Staging | WIP | Target |
|---|---|---|---|
| CORN MIX | EXT1-STAGING | EXT1-WIP | Semi-finished |
| SLURRY 1 | EXT1-STAGING | EXT1-WIP | Semi-finished |
| CORN EXTRUSION | Semi-finished | EXT1-WIP | Finished Goods |

---

## 1. Executive verdict

**The conclusions are broadly correct and, on the two process-blocking items (3 and 4), are
confirmed against authoritative ERPNext v15 validation paths.** The current configuration
fixes the *output-warehouse* routing for new SFG Work Orders (Conclusions 1–2), but the
**Operator Hub cannot End or Close a non-batch SFG Work Order** (Conclusions 3–4, both P0),
and the parent FG10011 flow **evaluates and consumes the exploded raw materials instead of
the two direct SFG components** at both End WO and Close Production (Conclusions 5–6, P0).
The supporting structural and classification findings (7, 9, 10, 11) are also confirmed.

Verdict: **correct, but requires material code amendments before the intended flow works.**

---

## 2. Conclusion-by-conclusion matrix

| No. | Conclusion | Verdict | Severity | Key evidence | Runtime test needed |
|---:|---|---|---|---|---|
| 1 | New CORN MIX section routes SFG10001 to Semi-finished | **Confirmed** | — (fix works) | `apply_line_warehouses_to_work_order` mes_ops.py:4902-4951; hooks.py:159-161 | Create new WO; assert warehouses |
| 2 | SFG10002 (SLURRY 1) routed to Semi-finished; item default doesn't override | **Confirmed** | P2 (latent default) | same hook; `_warehouses_for_line` 90-116; Item default = Stores | Create new WO; assert fg_warehouse |
| 3 | Close Production requires a batch for non-batch SFGs → cannot close | **Confirmed** | **P0** | operator_hub.js:2720-2726/2785-2799; `close_production` 3549-3551; `_ensure_batch` 494-527 → Batch v15 `item_has_batch_enabled` throws | Close an SFG WO; expect throw |
| 4 | End WO posts SFG consumption with `fg_completed_qty = 0` (invalid) | **Confirmed** | **P0** | `end_work_order` 2495 → `_post_sfg_consumption` 1799; v15 `validate_work_order` se:901-905 throws | End an SFG/FG WO with SFG usage |
| 5 | End WO evaluates an exploded BOM, blocking the parent at tolerance 0 | **Confirmed** | **P0** | `_end_wo_consumption_summary` 2393 → `_get_bom_items_for_quantity` `fetch_exploded=1` 327 | End FG10011 WO at tol 0 |
| 6 | Close Production re-consumes corn grits/water/oil/seasoning | **Confirmed** | **P0** | `_close_single_wo` 3341-3360 (same exploded helper) | Close FG10011; inspect Manufacture SE |
| 7 | Storekeeper UI uses leaf rows; backend allocation uses exploded map | **Confirmed** | P1 | leaf: `_required_leaf_map_for_wo` 66-89 / `_stage_status` 205; exploded: `_required_map_for_wo` 45-64 used by `create_consolidated_transfers` 660 | Allocate FG10011; supply RM row via API |
| 8 | CORN EXTRUSION staging = Semi-finished is workable but mixes purposes | **Confirmed** | P3 | `transfer_staged_to_wip` 1447-1466 (WO-tagged rows only); `_default_sfg_source` 771-789 | Start FG10011; confirm SFG stock not swept |
| 9 | Shared EXT1-WIP → cross-Work-Order consumption risk | **Confirmed (config risk)** | P1 | `_close_single_wo` 3354-3360 (s_warehouse = wip, no reservation) | Two concurrent WOs sharing WIP |
| 10 | SFG classification uses the wrong field (`is_sales_item`) | **Confirmed** | P2 | `_is_fg` 676-678; SFG10002 Allow Sales = 1 | List WOs; SFG10002 shows as FG |
| 11 | Master-data: BOM UOM mismatch; SFG10002 default warehouse | **Confirmed** | P2 | BOM-SFG10001-001 UOM = "Unit" vs stock Kg; SFG10002 default = Stores | Standard WO/MR for these items |

---

## 3. Detailed evidence

### Conclusion 1 — CONFIRMED
`isnack/hooks.py:159-161` registers on **Work Order**:
```python
"before_insert": "isnack.api.mes_ops.apply_line_warehouses_to_work_order",
"validate":      "isnack.api.mes_ops.apply_line_warehouses_to_work_order",
```
`apply_line_warehouses_to_work_order` (mes_ops.py:4902) resolves the line as
`custom_factory_line` → else BOM `custom_default_factory_line` (4918-4923) → else first
operation workstation. `BOM-SFG10001-001` has `custom_default_factory_line = CORN MIX`
(export column "Default Factory Section"). `_warehouses_for_line("CORN MIX")` (90-116)
returns `wip = EXT1-WIP`, `target = Semi-finished`. On **new** docs (`__islocal`) the values
are force-overridden (4940-4951), so a new SFG10001 WO receives
`custom_factory_line = CORN MIX`, `wip_warehouse = EXT1-WIP`, `fg_warehouse = Semi-finished`.
This removes the prior risk of producing SFG10001 into Finished Goods.
**Existing WOs:** the override is gated on `is_new`; on existing Draft docs the code only
*fills empty* fields, and submitted WOs are untouched. So pre-change Work Orders keep their
old warehouses unless recreated. Confirmed.

### Conclusion 2 — CONFIRMED (with a latent default-warehouse caveat)
Same hook routes a new SLURRY 1 WO to `wip = EXT1-WIP`, `fg = Semi-finished`. The Frappe
`validate`/`before_insert` doc-event hooks run **after** the core Work Order controller, and
the `is_new` branch overrides unconditionally, so **SFG10002's Item default warehouse
(`Stores - ISN`) does not override** the line-map `fg_warehouse` for hub-created WOs. The
mismatch remains a latent issue for component source defaults and manual transactions (see
Conclusion 11.2). Confirmed.

### Conclusion 3 — CONFIRMED (P0, deterministic)
Call chain: Operator Hub **Close Production** dialog builds one `Batch No` field per product
group with `reqd:1` **unconditionally** (`operator_hub.js:2720-2726`) and refuses to submit
with an empty/invalid batch (2785-2799), with no `has_batch_no` check. Backend
`close_production` repeats this: `if not bno: frappe.throw("Batch number is required …")`
(mes_ops.py:3549-3551) followed by `_validate_batch_code_format`. `_close_single_wo` then calls
`_ensure_batch(wo.production_item, batch_no)` (3320), which inserts a `Batch`
(mes_ops.py:521-527).

Authoritative v15 block — `erpnext/stock/doctype/batch/batch.py`:
```python
def validate(self):
    self.item_has_batch_enabled()
def item_has_batch_enabled(self):
    if frappe.db.get_value("Item", self.item, "has_batch_no") == 0:
        frappe.throw(_("The selected item cannot have Batch"))
```
SFG10001/SFG10002 have `has_batch_no = 0`, so `Batch.insert()` throws **"The selected item
cannot have Batch"**, caught and re-raised as *"Failed to close production for …"*.
**An SFG Work Order cannot be closed through the Operator Hub.** Confirmed.

### Conclusion 4 — CONFIRMED (P0, deterministic)
`end_work_order` (mes_ops.py:2461) calls `_post_sfg_consumption(wo, sfg_rows, 0)` (2495). That
function (1778) builds a Stock Entry with
`purpose = "Material Consumption for Manufacture"`, `work_order = wo.name`,
`fg_completed_qty = 0` (1797-1799), appends the SFG rows, then `insert()` + `submit()`.

Authoritative v15 block — `stock_entry.py` `validate()` (runs on insert *and* submit) calls
`validate_work_order()`:
```python
if (self.purpose == "Manufacture" or self.purpose == "Material Consumption for Manufacture") and self.work_order:
    if not self.fg_completed_qty:
        frappe.throw(_("For Quantity (Manufactured Qty) is mandatory"))   # se15.py:901-905
```
`fg_completed_qty = 0` is falsy → **throws "For Quantity (Manufactured Qty) is mandatory"**.
No ISNACK override bypasses this (the SE is a normal `insert()`/`submit()`; `ignore_permissions`
does not skip `validate`). So whenever SFG usage is recorded at End WO, End WO fails.
(Note: the *mandatory* check some references attribute to `get_items()` is **not** on this
path — `_post_sfg_consumption` builds rows manually — but `validate_work_order` is, and it is
the real blocker. Verified in source.) Confirmed.

### Conclusion 5 — CONFIRMED (P0)
`get_end_wo_summary` (2446) → `_end_wo_consumption_summary` (2369) → `bom_items =
_get_bom_items_for_quantity(wo.bom_no, wo.qty)` (2393). `_get_bom_items_for_quantity`
(309) calls `get_bom_items_as_dict(..., fetch_exploded=1, ...)` — **hardcoded explosion**
(327). For FG10011 this yields the leaves corn grits, water, oil, seasoning, film, cartons;
SFG10001/SFG10002 are *replaced* by their leaves (both `do_not_explode = 0`).
`sfg_codes` comes from `get_sfg_components_for_wo` (1730), which lists `SFG10001`/`SFG10002`
— none of which appear in the exploded list, so the `is_sfg` exclusion never matches the raw
materials. With `End WO Tolerance % = 0`, the unconsumed corn grits / water / oil / seasoning
score `status = "short"` → `shortfalls > 0` → `can_end = False` → the operator is blocked
(only a Production Manager can override with a written reason, 2525-2538).
The custom helper ignores `Work Order.use_multi_level_bom` entirely (it always explodes),
which is the deterministic defect regardless of how Production Plan set the flag on the parent.
Confirmed.

### Conclusion 6 — CONFIRMED (P0; final outcome runtime-dependent)
`_close_single_wo` (3239) builds the FG10011 **Manufacture** Stock Entry and, at 3341, calls
the **same** `_get_bom_items_for_quantity(wo.bom_no, total_production_qty)` (exploded). The
loop (3343-3360) appends consumption rows for every non-packaging leaf — corn grits, water,
oil, seasoning — with `s_warehouse = wip_wh` (EXT1-WIP). The two SFG items are *absent* from
the exploded list, so the Manufacture entry **does not consume SFG10001/SFG10002 at all** and
instead requests their underlying raw materials a second time. Deterministic: the SE requests
`corn grits + water + oil + seasoning` from EXT1-WIP. Outcome depends on stock state and the
Allow-Negative-Stock setting:
- those leaves are **not** in EXT1-WIP (they were consumed inside the SFG Work Orders, whose
  output went to Semi-finished) → with negative stock **disallowed**, `submit()` fails with a
  negative-stock error;
- with negative stock **allowed**, ERPNext consumes phantom/unrelated stock → double material
  consumption, duplicated manufacturing cost, and incorrect FG valuation.
Confirmed defect; pass/fail is the only runtime-dependent part.

### Conclusion 7 — CONFIRMED (P1)
Two different requirement maps exist:
- **Leaf** (`tabBOM Item where bom_no = ''`): `_required_leaf_map_for_wo` (66-89), used by
  `_stage_status` (205) and `_remaining_leaf_map_for_wo` (160). For FG10011 the leaf set is
  **PM40011 + CR30003 only** (packaging) — so the UI/stage status naturally propose packaging.
- **Exploded** (`tabBOM Explosion Item`): `_required_map_for_wo` (45-64) →
  `_remaining_map_for_wo` (143), used by `create_consolidated_transfers` at line 660 (and the
  per-item allocation at 1506). For FG10011 this includes corn grits / water / oil / seasoning.

Therefore: the UI proposes packaging only, but the **allocation backend** still recognises the
SFG raw materials as FG10011 requirements; an API- or manually-supplied corn-grits row is
allocated against FG10011; and staged status can read inconsistently versus what allocation
believes is required. Confirmed.

### Conclusion 8 — CONFIRMED (P3)
`transfer_staged_to_wip` (1393) reads only staged rows whose source `Material Transfer`
`remarks LIKE '%WO: <wo>%'` and `t_warehouse = staging_wh` (1447-1466). It does **not** sweep
arbitrary stock present in the staging warehouse. So pre-existing SFG inventory sitting in
`Semi-finished - ISN` is **not** auto-moved into WIP when FG10011 starts; only packaging
explicitly staged for FG10011 moves. SFG consumption sources from
`_default_sfg_source` = Factory Settings `default_semi_finished_warehouse` (771-789), which is
independent of the CORN EXTRUSION staging warehouse. **Recommendation:** changing CORN
EXTRUSION staging to `EXT1-STAGING - ISN` is cleaner and does **not** break direct SFG
consumption. Confirmed.

### Conclusion 9 — CONFIRMED (configuration risk, P1)
CORN MIX, SLURRY 1 and CORN EXTRUSION share `EXT1-WIP`. The Close-Production Manufacture entry
appends consumption rows with `s_warehouse = wip_wh` and **no batch and no per-WO reservation**
(3354-3360); SFGs are non-batch, so there is no batch isolation either. ERPNext selects stock
by physical availability and valuation (FIFO), not by which WO transferred it. Consequently one
Work Order's Close can consume stock that a different Work Order transferred into the shared
WIP. Not a hard code bug, but a real risk that materialises with concurrent WOs on a shared
WIP — classify as **configuration risk**.

### Conclusion 10 — CONFIRMED (P2)
`_is_fg` (676-678): `return bool(frappe.db.get_value("Item", item_code, "is_sales_item"))`.
SFG10002 has `is_sales_item = 1` (Allow Sales) while its Item Group is *Semi-Finished Goods*,
so it is classified **FG** (used at 1010, 1032, 1167 for the hub WO `type`, and at 3687 to gate
FG-only post-close behaviour). SFG10001 (`is_sales_item = 0`) is classified SF — so two items
of the same production role classify differently. **Recommended basis:** Item Group
(`Semi-Finished Goods`), or the "has its own active+default BOM" heuristic already used by
`get_sfg_components_for_wo` (1758-1764), both of which are present and reliable in the current
data model. Confirmed.

### Conclusion 11 — CONFIRMED (P2, mostly standard/manual impact)
1. **BOM UOM:** `BOM-SFG10001-001` carries BOM UOM **"Unit"** (export "Item UOM") while
   SFG10001's stock UOM is **Kg** (and the parent consumes it as 160 Kg). The hub consumes in
   stock UOM (`fetch_qty_in_stock_uom=True`, and `stock_uom` everywhere), so this mostly
   distorts the BOM's own per-unit rate and standard/manual Work-Order qty UOM rather than the
   hub's deterministic consumption. Should be corrected to Kg.
2. **SFG10002 default warehouse = `Stores - ISN`**, inconsistent with `Semi-finished - ISN`
   (SFG10001 is correctly `Semi-finished - ISN`). Hub-created WOs override `fg_warehouse` via
   the line map, so hub output is still correct; the inconsistency affects component source
   defaults, Material Requests and manual stock transactions.
3. Net: these are master-data hygiene issues that chiefly affect **standard ERPNext / manual**
   transactions, not the deterministic hub path. Confirmed.

---

## 4. Corrected end-to-end process

**Current actual behaviour (FG10011):**
- Storekeeper UI suggests packaging only (leaf map) — correct in spirit; backend allocation can
  still bind exploded RMs to FG10011 (C7).
- Start → only FG10011-tagged staged packaging moves Semi-finished → EXT1-WIP (C8); SFG stock
  stays put.
- End WO → if SFG usage entered, the `fg_completed_qty = 0` consumption SE **throws** (C4); if
  not entered, the exploded gate **blocks** at tolerance 0 (C5).
- Close Production → requires a batch even for SFGs (C3 blocks SFG WOs); for FG10011 the
  Manufacture SE re-requests corn grits/water/oil/seasoning from WIP (C6).

**Recommended corrected behaviour:**
- **SFG10001 / SFG10002 WOs:** End WO posts consumption with a correct non-zero
  `fg_completed_qty` (the produced SFG qty); Close Production books a Manufacture SE **without**
  a batch (item is non-batch), output into `Semi-finished - ISN`.
- **FG10011 WO:** End WO and Close evaluate the **direct** BOM (respect
  `use_multi_level_bom = 0`), so the parent consumes **SFG10001 + SFG10002 + packaging** and
  never re-consumes the four SFG raw materials. SFG consumption may be posted directly from
  `Semi-finished - ISN` (Work-Order-linked Material Consumption) with a valid `fg_completed_qty`;
  a separate transfer of SFG into WIP is not required.
- **Warehouses:** keep CORN MIX / SLURRY 1 → Semi-finished; optionally move CORN EXTRUSION
  staging to `EXT1-STAGING` (C8). Consider per-line WIP to remove the shared-WIP risk (C9).
- **Batch:** only FG10011 (and other `has_batch_no = 1` items) carry/require a batch.
- **Valuation:** with the direct-BOM fix, FG10011 cost = SFG10001 + SFG10002 + packaging,
  with no duplicated raw-material cost.

---

## 5. Minimal code correction plan (ordered by priority)

1. **(P0) Respect `Work Order.use_multi_level_bom`.** Add a flag to
   `_get_bom_items_for_quantity(bom_no, qty, exploded=None)` and pass
   `exploded = bool(wo.use_multi_level_bom)` from `_end_wo_consumption_summary` (2393) and
   `_close_single_wo` (3341). For FG10011 (`use_multi_level_bom = 0`) this lists the direct SFG
   components, fixing both the End WO gate (C5) and the Close double-consumption (C6) at once.
   *Impact:* the parent then expects SFG10001/SFG10002 to be consumed — pair with step 2.
2. **(P0) Non-zero, semantic `fg_completed_qty` for SFG consumption.** In
   `_post_sfg_consumption`, pass the produced quantity (or the WO qty being ended) instead of
   `0` (callers at 2495). Satisfies v15 `validate_work_order` (se:901-905). Affects
   `end_work_order` and `_post_sfg_consumption`.
3. **(P0) Conditional batch handling.** Gate the batch requirement on
   `Item.has_batch_no`: in `operator_hub.js` build the per-group `Batch No` field with
   `reqd: g.has_batch_no` and skip the batch validations when false; in `close_production`
   only require/validate `bno` when the group's `production_item` has `has_batch_no = 1`; in
   `_close_single_wo` only `_ensure_batch`/assign batch when `has_batch`. Unblocks SFG closing
   (C3) without enabling batches on SFGs.
4. **(P1) Prevent SFG and its raw materials both being consumed.** Falls out of step 1; add a
   guard so a parent WO with sub-assembly components never appends exploded leaves of an item
   that has its own BOM.
5. **(P1) Make Storekeeper requirement maps consistent.** Use the same leaf-vs-exploded basis
   for display, stage status, cart and allocation (`create_consolidated_transfers` 660 /
   `_required_map_for_wo`). For direct-component FGs, allocate against leaf requirements.
6. **(P2) Classification.** Replace `_is_fg` (676) with an Item-Group test
   (`item_group == "Semi-Finished Goods"` → SF) or the existing "has own default BOM" heuristic.
7. **(P2) Master data.** Fix `BOM-SFG10001-001` UOM to Kg; set SFG10002 Item default warehouse
   to `Semi-finished - ISN`.
8. **(P3) Warehouses.** Move CORN EXTRUSION staging to `EXT1-STAGING`; evaluate per-line WIP to
   remove the shared-WIP cross-consumption risk (C9). Idempotency for End/Close is already
   present (`_submitted_mtfm_qty`, `_submitted_manufacture_qty`, WO row locks) and should be
   preserved.

---

## 6. Test plan (expected Stock Entries / states)

1. **SFG10001 new WO warehouse:** create WO from `BOM-SFG10001-001`; assert
   `custom_factory_line = CORN MIX`, `wip = EXT1-WIP`, `fg_warehouse = Semi-finished`.
2. **SFG10002 new WO warehouse:** create WO from `BOM-SFG10002-001`; assert `wip = EXT1-WIP`,
   `fg_warehouse = Semi-finished` (and confirm Item default `Stores` did **not** win).
3. **Non-batch SFG Close (pre-fix = bug):** End + Close an SFG10001 WO. *Current:* throws "The
   selected item cannot have Batch". *Post-fix:* Manufacture SE, no batch, output to
   Semi-finished, WO Completed.
4. **FG10011 End WO with direct SFG usage (pre-fix = bug):** *Current:* `_post_sfg_consumption`
   throws "For Quantity (Manufactured Qty) is mandatory" (or, with no SFG usage, the exploded
   gate blocks at tol 0). *Post-fix:* Material Consumption SE for SFG10001/SFG10002 from
   Semi-finished with non-zero `fg_completed_qty`; End succeeds.
5. **FG10011 Close without RM double-consumption:** *Post-fix:* Manufacture SE consumes
   SFG10001 + SFG10002 + packaging only; assert corn grits/water/oil/seasoning are **absent**.
6. **Partial production / 7. Reject qty:** close with good < planned and with rejects; assert
   proportional split, scrap row carries FG batch, WIP residue handled.
7. **Repeated submission:** double-click Start/End/Close; assert no duplicate MTFM/Manufacture
   (idempotency guards 3249-3270, WO locks).
8. **Insufficient SFG stock:** End FG10011 with SFG stock below required; assert clear shortfall
   behaviour, no negative phantom consumption.
9. **Concurrent WOs sharing WIP (C9):** two WOs, shared EXT1-WIP; confirm whether one can
   consume the other's transferred stock.
10. **Pre-change existing WO:** a WO created before the CORN MIX config keeps its old
    warehouses (no retro-update).

---

## 7. Final risk ranking

- **P0 — process blocked / accounting corruption:**
  C3 (non-batch SFG cannot Close), C4 (zero `fg_completed_qty` blocks End WO),
  C5 (exploded gate blocks FG10011 End WO), C6 (FG10011 Close re-consumes SFG raw materials).
- **P1 — serious operational inconsistency:**
  C7 (leaf-vs-exploded requirement maps), C9 (shared-WIP cross-WO consumption risk).
- **P2 — control / classification / master-data:**
  C2 latent default, C10 (`is_sales_item` classification), C11 (BOM UOM, SFG10002 default wh).
- **P3 — usability / maintainability:**
  C8 (CORN EXTRUSION staging mixes purposes — workable, cleaner if moved).

### Notes on certainty
- **Static/deterministic:** warehouse routing (1, 2), the batch throw (3), the
  `fg_completed_qty` throw (4), the hardcoded explosion (5, 6, 7), the WO-tagged staging move
  (8), and the classification field (10) are all certain from code + v15 source.
- **Runtime-dependent:** the *final* outcome of C6 (hard negative-stock failure vs. silent
  double consumption) and C9 depend on Allow-Negative-Stock and live stock/concurrency.
- **Data-dependent:** C11.1 assumes the export's BOM UOM ("Unit") reflects the live BOM.
- Line numbers are from the current files and may shift after edits; function names and
  surrounding logic are stated so they remain locatable.
