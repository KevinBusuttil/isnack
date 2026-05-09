# Storekeeper Hub & Operator Hub — User Flow Guide

This document explains the operational flow for the Storekeeper Hub and Operator Hub in the iSnack MES experience, based on the current UI and server behaviour.

---

## Relationship Between the Two Hubs

The Storekeeper Hub and Operator Hub form two halves of the same production cycle. The Storekeeper stages materials; the Operator consumes them. The bridge between them is the **stage status** of each Work Order.

```
Production Plan (with posting_date)
        │
        ▼
  Work Order — status: Not Started
        │
  ┌─────────────────────────────────────────────────────────┐
  │  STOREKEEPER HUB                                        │
  │  get_buckets()  → groups WOs by BOM                     │
  │  create_consolidated_transfers()                         │
  │     → Material Transfer SE  (Source → Staging)          │
  │                   stage_status: "Staged"                 │
  └─────────────────────────────────────────────────────────┘
        │  stage_status = "Staged" (all leaf BOM items covered)
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  OPERATOR HUB                                           │
  │  set_work_order_state("Start")                          │
  │     → transfer_staged_to_wip()                          │
  │       → Material Transfer for Manufacture (Staging→WIP) │
  │  scan_material() / manual_load_materials()              │
  │     → Material Consumption for Manufacture              │
  │  end_work_order()                                       │
  │     → custom_production_ended = 1                       │
  │  close_production()                                     │
  │     → Manufacture SE (FG receipt)                       │
  │     → Work Order status = Completed                     │
  └─────────────────────────────────────────────────────────┘
```

**Key rule**: The Operator Hub's **Start** button is disabled until the Storekeeper has staged all required leaf-BOM materials (stage_status = "Staged"). The queue shows each WO's allocation state with a chip: **Allocated**, **Partly Allocated**, or unlabelled (not staged).

---

## Storekeeper Hub

### 1. Start-of-shift setup

Open the **Storekeeper Hub** page and use the top toolbar to set your context before loading data:

- **Factory Section** — links to a `Factory Line` record; filters WOs and staging panels to the chosen production section. Leave blank to see all sections.
- **Source Warehouse** — the warehouse that materials are transferred *from*. Defaults to the ERPNext `Stock Settings → Default Warehouse`.
- **Prod. Plan Posting Date** — filters the WO buckets to only Work Orders linked to Production Plans with this posting date. Defaults to today. This also drives the "Staged (Production Date)" panel.
- **Refresh** — reloads all four panels (Buckets, Staged, Manual Stock Entries, Pallet Tracker).

> **Pallet tagging**: Scanning any barcode in the global scan field (top of the page) that does not match a WO or Stock Entry number sets it as the current **Pallet ID**, which is then attached to transfer remarks for downstream traceability.

---

### 2. Review Work Order buckets (left column)

The left column shows **WO Buckets** — groups of Work Orders that share the same BOM.

- Each bucket displays: item name, item code, BOM number, number of WOs, and total quantity.
- Inside each bucket, individual WO rows show the WO name, planned start date, item/qty, and an allocation status chip:
  - **Allocated** (green chip) — all required leaf-BOM materials are already staged.
  - **Partly Allocated** (amber chip) — some materials have been staged but not all.
  - No chip — nothing has been staged yet.
- A **fully-allocated** bucket (all WOs = Allocated) shows the button as **Fully Allocated** (disabled).
- Individual WO checkboxes let you include or exclude specific WOs before clicking **Select for Allocation**.

---

### 3. Select a bucket and build the Consolidated Pick Cart (centre column)

Clicking **Select for Allocation** on a bucket:

1. Captures the checked WOs into the current selection.
2. Automatically calculates the remaining un-staged quantities across those WOs (BOM requirement minus what is already transferred).
3. Pre-fills the **Consolidated Pick Cart** with one row per item, showing the remaining quantity needed.

You can then refine the cart:

| Action | Description |
|---|---|
| **Scan field** (top of cart) | Scan or type an item barcode/code; a new row is added and its quantity is auto-filled to the consolidated remaining amount. |
| **Add Row** | Adds a blank row for ad-hoc items. |
| **Fill** (per row) | Re-fetches the consolidated remaining quantity for that single item and updates the row. |
| **Fill Cart to Remaining** | Batch-updates all rows in the cart to their current consolidated remaining quantities. |
| **Clear Cart** | Empties the cart. |
| **Batch selector** (gold `...` button) | For batch-tracked items only. Opens a dialog showing all available batches with quantity and expiry date. You assign quantities per batch; the total must equal the cart row quantity. A warning is shown if total available stock is insufficient. When only one batch exists with sufficient stock, its quantity is auto-populated. |

---

### 4. Allocate & create transfers

Click **Allocate & Create Transfers** to post the cart to ERPNext:

- The server reads the cart and the selected WOs in **FIFO order** (by `planned_start_date`, then `creation`).
- For each WO it calculates how much of each item is still needed, and creates one `Material Transfer` Stock Entry linked to that WO, moving stock from Source Warehouse to the WO's Staging Warehouse (from Factory Settings → Line Warehouse Map).
- Multi-batch items generate separate Stock Entry Detail rows per batch.
- Created transfers appear in the **Created transfers** results card beneath the cart, with **Open** and **Print** buttons per entry. Print generates one label per item line using the configured print format.

> **Validation**: Batch-managed items must have a batch assigned in the cart before allocation is allowed.

---

### 5. Print Pallet Labels (staging labels)

Click **Print Pallet Labels** in the toolbar to print combined pallet / staging labels:

1. A dialog loads all recent staged Stock Entries (filtered by Factory Section and posting date).
2. Each SE is shown as a card with a checkbox. All are selected by default.
3. Click **Apply** to group and total the items across the selected SEs.
4. Click **Print** to generate one print URL per grouped item row and open them sequentially (via QZ Tray or browser dialog).

---

### 6. Generate Picklist (optional)

Click **Generate Picklist** in the toolbar:

1. A dialog loads the same recent staged SEs with checkboxes.
2. A **Group same items** option (default: on) collapses rows with the same item, batch, and warehouse into a single picklist row.
3. Click **Create Picklist** — the server creates a custom `Picklist` document and opens it immediately.

---

### 7. Quick stock entry actions

The toolbar contains role-controlled stock entry shortcuts (visibility depends on roles configured in **Factory Settings → Stock Entry Button Roles**):

| Button | Purpose |
|---|---|
| **Mat. Transfer** | Open a new Material Transfer SE pre-filled with Source Warehouse as the from-warehouse. |
| **Mat. Issue** | Open a new Material Issue SE pre-filled with Source Warehouse. |
| **Mat. Receipt** | Open a new Material Receipt SE pre-filled with Source Warehouse as the to-warehouse. |
| **PO Receipt** | Open the PO Receipt dialog (see below). |

#### PO Receipt workflow

1. Click **PO Receipt** to open the dialog.
2. Select an open **Purchase Order** (filtered to POs with pending qty > 0).
3. The dialog loads all pending PO items with their pending quantities.
4. Enter **Accepted Qty** and **Rejected Qty** per item. Optionally add a **Batch No** and **Expiry Date** (expiry is required when a batch is provided).
5. Set a **Receipt Date** and optionally a **Rejection Warehouse**.
6. Click **Post Receipt** — the server creates a draft Purchase Receipt tagged with `custom_from_storekeeper_hub = 1`.

---

### 8. Recent activity & tracking (right column)

| Panel | What it shows |
|---|---|
| **Staged (Production Date)** | `Material Transfer` and `Material Transfer for Manufacture` SEs for the selected posting date (or last 24 hours if no date is set). Entries already included in a Picklist are marked. |
| **Recent Manual Stock Entries (Last 24h)** | Non-WO stock moves (Material Transfer, Material Issue, Material Receipt) from the last 24 hours. |
| **Pallet Tracker (Last 24h)** | Material Transfer SEs whose remarks contain `Pallet:` — shows pallet ID and transfer date. |

---

## Operator Hub

### 1. Set operator and line

- Click **Set Line** to select one or more **Factory Sections** from the full list. The selection is multi-select and is persisted in `localStorage` so it survives page refresh.
- Click **Set Operator** to select the current **Employee** (by employee ID or by badge scan).
- The hub loads the **Work Order queue** for the selected lines.
- A **status bar** at the bottom shows the current clock, shift (A/B/C by time of day), and connection state (Online/Offline).
- **Full-screen** and **Hide Header** (kiosk mode) controls are available in the toolbar or via Ctrl+Shift+K.

---

### 2. Select a Work Order

The queue shows all Work Orders for the selected lines that are in status `Not Started`, `In Process`, or `Stopped`. Each entry shows:

- WO name and item name
- Planned quantity
- Factory Section
- Type chip: **FG** (Finished Good) or **SF** (Semi-Finished)
- Allocation chip: **Allocated**, **Partly Allocated**, or none
- Status chip: **Not Started**, **In Process**, **Stopped**

Click any WO to load the **Work Order banner** (item name, batch, FG/SF, qty, actual produced, rejects, status, line) and the **Materials snapshot** (see section 4 below).

---

### 3. Start / Pause / Resume a Work Order

| Button | Enabled when | Action |
|---|---|---|
| **Start** | WO is Allocated + status is Not Started | Sets WO to In Process; automatically runs `transfer_staged_to_wip()` which creates a `Material Transfer for Manufacture` SE moving all staged materials from Staging → WIP. |
| **Pause** | WO is Allocated + In Process | Sets WO to Stopped. |
| **Resume** | WO is Allocated + Stopped | Returns WO to In Process. |

The banner and queue refresh automatically after each state change.

---

### 4. Materials snapshot

After selecting a WO, the **Materials** panel shows a live breakdown:

| Column | Source |
|---|---|
| Required | BOM × WO qty |
| Transferred | `Material Transfer for Manufacture` SEs for this WO |
| Consumed | `Material Consumption for Manufacture` SEs for this WO |
| Remaining | Required − Transferred − Consumed |

Below the table, the **Scan History** panel lists the 12 most-recent consumption entries (item code, batch, qty, UoM).

---

### 5. Load / scan materials

Click **Load Materials** to open scan mode:

- The barcode scanner field is kept focused (re-focused every 1.5 seconds).
- Scan raw material, semi-finished, or packaging barcodes (GS1 AI-128 or plain `ITEM|BATCH|QTY` format).
- Each scan validates the item against the **Allowed Item Groups** list, checks BOM membership (packaging items bypass this check), checks over-consumption against the configured threshold (default 150%), verifies available stock in the WIP warehouse, and posts a `Material Consumption for Manufacture` SE.
- Duplicate scans are blocked within the duplicate-scan TTL window (default 45 seconds).
- The **scan history dialog** shows each scan with timestamp, status (success/fail), item code, and quantity.
- Sound feedback: success tone on OK, error tone on failure.
- The materials snapshot refreshes automatically on a successful scan.

---

### 5a. Manual Load materials

Click **Manual Load** for situations without a barcode scanner:

1. Select an **Item Code** (filtered to items from the WO's BOM that have stock in the WIP warehouse).
2. The item **Description** auto-populates.
3. Select an optional **Batch No** (filtered to batches in the WIP warehouse for the selected item).
4. **Required Qty** shows the BOM/planned requirement for this item on the current Work Order.
5. **Remaining Qty** shows `max(required - already consumed for this WO, 0)` — use this as the primary decision aid.
6. **Available Qty in WIP** shows the quantity in the WIP warehouse for that batch/item.
7. Enter **Qty** (must not exceed Available Qty in WIP when a batch is specified). Remaining Qty is informational and does not block entry above it (the server's over-consumption threshold still applies).
8. Click **Add** to add the row. Repeat for additional items.
9. Click **Post Consumption** — the server creates a single `Material Consumption for Manufacture` SE covering all rows, validating BOM membership and the over-consumption threshold.
10. The materials snapshot refreshes on success.

---

### 6. Request more material

Click **Request More Material** to ask the Storekeeper for extra stock:

- Select **Item**, enter **Qty**, and choose a **Reason** (Evaporation/Wastage, Overweight Spec, Machine Loss, Short Pick, Other).
- Submitting creates a `Material Request` in ERPNext.

---

### 7. Return materials (per Work Order)

Click **Return Materials** to send unused materials from WIP back to staging:

- Add rows by scanning or typing item codes, entering qty and optional batch.
- Click **Post Returns** — the server creates a `Material Transfer` SE from WIP Warehouse back to Staging Warehouse for this WO.

---

### 8. End Shift Return (WIP return without a Work Order)

Click **End Shift Return** to return all remaining WIP inventory at end of shift:

1. If multiple lines are selected, a dialog asks which line to return WIP from.
2. The server queries the WIP warehouse for the chosen line (all items and batches with qty > 0).
3. A table shows each item with its available qty, a **Return Qty** input, and a batch badge.
4. Use the **Select All** checkbox or per-row checkboxes to bulk-clear quantities, or enter individual quantities.
5. A summary footer shows item count and total quantity.
6. Click **Post Return** — the server creates a `Material Transfer` SE from WIP Warehouse → Return Warehouse (or Staging Warehouse if no return warehouse configured), tagged with `custom_is_end_shift_return = 1` and `custom_return_received_by_storekeeper = 0`.
7. A Material Return Note is printed automatically (via QZ Tray or browser dialog).
8. The Stock Entry appears in **Storekeeper Hub → Pending End Shift Returns** until the storekeeper clicks **Received**, which sets `custom_return_received_by_storekeeper = 1`.

---

### 9. Label printing — FG carton labels (FG Work Orders only)

Click **Print Label** (enabled only for FG Work Orders with an operator and line set):

1. The hub checks that `Factory Settings.default_fg_label_print_format` is configured; an error is shown if not.
2. The server returns all **ended FG Work Orders** for the current lines, grouped by production item.
3. A dialog shows a grid with one row per item: item code, description, default UOM, carton qty (editable), pallet type (filtered to allowed pallet UOMs from Factory Settings), and pallet qty (auto-calculated from the Item's UOM conversion factor, or manually overrideable).
4. Click **Print Labels** — for each row with a pallet type and qty, the server creates a `Label Record` audit document and returns a print URL. Labels are opened sequentially.

#### Label History

Click **Label History** (enabled only for FG Work Orders) to view all labels ever printed for the current WO:

- Table shows: label record name, quantity, item, batch, template, and creation date.
- **Reprint** — re-opens the print dialog for that label record.
- **Split** — enter comma-separated quantities (e.g. `10,5,5`) to create separate label records and print each.

#### QZ Tray / silent printing

Both Print Label and Label History use the same print routing:
- If `Factory Settings.enable_silent_printing = 1` and a printer is configured: sends the HTML label to the printer via QZ Tray WebSocket (62 × 84 mm, HTML format).
- Falls back to `window.open(printUrl, '_blank')` if QZ Tray is not available.

---

### 10. End Work Order

Click **End WO** (enabled when WO is not already ended) to mark production as physically complete *without yet creating the FG Stock Entry*:

1. The server fetches **semi-finished (SFG) components** — BOM items that have their own active sub-BOM (e.g. slurry, rice mix), excluding Packaging and Backflush groups.
2. If any SFG components exist, a dialog shows one qty field per component for the operator to enter actual usage.
3. On submit:
   - If SFG usage was entered, a `Material Consumption for Manufacture` SE is posted consuming those items from the SFG warehouse.
   - The Work Order is flagged `custom_production_ended = 1`.
4. The WO moves out of the active queue and awaits **Close Production**.

---

### 11. Close Production

Click **Close Production** (requires operator + at least one line set) to complete all ended Work Orders for the current lines in one batch:

1. The server loads all WOs with `custom_production_ended = 1` for the selected lines.
2. The dialog shows:
   - A list of the ended WOs.
   - **Total Good Qty** (required) and **Total Reject Qty**.
   - **Batch No** (required, format: 3 letters + dash + 3 digits, e.g. `CGB-151`; validated both client-side and server-side).
   - **Packaging Materials Used** — one qty field per packaging item that appears on any of the ended WOs' BOMs (filtered to Packaging Item Groups from Factory Settings).
3. Validation rules are applied from `Factory Settings.close_production_validation_mode`:
   - **No Validation** — proceeds immediately.
   - **All WOs on Line Must Be Ended** — throws if any non-completed WO on the line has not been ended.
   - **Minimum Number of WOs** — throws if fewer than the configured minimum are ended.
4. On submit:
   - Quantities are **split proportionally** across ended WOs by each WO's individual qty.
   - For each WO a `Manufacture` Stock Entry is created (FG receipt + BOM material consumption from WIP) using the proportional good and reject quantities.
   - Packaging consumption is posted.
   - Work Order status is set to `Completed`, and `custom_production_ended` is cleared.

> **Batch code format**: iSnack uses a 7-character code (`YYM-DDS`). `YY` = year encoded as two letters (A=0…J=9, so 2026 → CG), `M` = month as letter (A=Jan…L=Dec), `DD` = two-digit day, `S` = sequence digit. Example: `CGB-151` = 26 Feb 15, batch 1.

---

## Factory Settings reference (IT administrators)

All hub behaviour is controlled by the **Factory Settings** Single doctype (System Manager access only).

| Field | Purpose |
|---|---|
| `line_warehouse_map` | Per-line mapping: Staging, WIP, Target (FG), and Return warehouses. Used by both hubs to route all stock movements. |
| `allowed_item_groups` | Global allowlist: only items in these groups can be scanned/consumed in the Operator Hub. |
| `packaging_item_groups` | Items in these groups bypass the BOM membership check during scan and are included in the Close Production packaging section. |
| `backflush_item_groups` | Excluded from SFG detection (not offered in End WO dialog). |
| `stock_entry_button_roles` | Roles permitted to see Mat. Transfer / Mat. Issue / Mat. Receipt buttons in the Storekeeper Hub toolbar. |
| `scan_dup_ttl_sec` | Seconds before a duplicate barcode scan is allowed again (default: 45). |
| `material_overconsumption_threshold` | Maximum % over BOM requirement before scan/manual-load is blocked (default: 150%). |
| `close_production_validation_mode` | No Validation / All WOs on Line Must Be Ended / Minimum Number of WOs. |
| `close_production_min_wo_count` | Minimum ended WO count for the "Minimum Number" mode. |
| `pallet_uom_options` | Allowed pallet types (e.g. EURO 1, EURO 4) shown in the Operator Hub pallet label dialog. |
| `default_fg_label_print_format` | Print format for FG carton labels in Operator Hub. |
| `default_label_print_format` | Print format for per-item staging labels in Storekeeper Hub. |
| `default_collective_label_print_format` | Print format for combined pallet labels in Storekeeper Hub. |
| `enable_silent_printing` | When checked, labels are sent directly to the printer via QZ Tray instead of opening a browser dialog. |
| `default_label_printer` | Default printer name passed to QZ Tray. |
