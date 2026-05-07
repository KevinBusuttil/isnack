# Production Plan → Storekeeper Hub → Operator Hub: A Step-by-Step User Guide

This guide walks you through the complete production cycle in iSnack — from the moment a planner creates a Production Plan, through the Storekeeper staging raw materials, to the Operator running the line and recording finished goods. It is written for everyday users: production planners, storekeepers, and machine operators.

---

## 1. Introduction & Overview

Every production run in iSnack follows three stages, each performed by a different role:

| Stage | Role | What happens |
|-------|------|--------------|
| **Production Plan** | Planner | Decides *what* to make and *how much*; generates Work Orders |
| **Storekeeper Hub** | Storekeeper | Picks and stages the raw materials needed for those Work Orders |
| **Operator Hub** | Operator | Runs the machine, records consumption, and closes out finished goods |

The Production Plan is the engine that drives everything. Without it, the Storekeeper Hub has nothing to stage and the Operator Hub has nothing to run.

### How the three stages connect

```
┌─────────────────────────────────┐
│          PLANNER                │
│  Create Production Plan         │
│  (set Posting Date, add items)  │
│  Submit → Make Work Orders      │
└────────────────┬────────────────┘
                 │  Work Orders (Not Started)
                 ▼
┌─────────────────────────────────┐
│        STOREKEEPER HUB          │
│  Filter by Line & Posting Date  │
│  Select WO bucket               │
│  Build Consolidated Pick Cart   │
│  Allocate & Create Transfers    │
│  → Material Transfer SE         │
│     stage_status = "Staged"     │
└────────────────┬────────────────┘
                 │  Materials staged in Staging Warehouse
                 ▼
┌─────────────────────────────────┐
│         OPERATOR HUB            │
│  Set Line & Operator            │
│  Start WO (transfers to WIP)    │
│  Load / scan materials          │
│  End WO → Close Production      │
│  → Manufacture SE (FG receipt)  │
│     Work Order = Completed      │
└─────────────────────────────────┘
```

> **Key rule**: The Operator's **Start** button stays disabled until the Storekeeper has fully staged all required materials. The handoff between the two hubs is automatic — it happens through the Work Order's allocation status.

---

## 2. Stage 1: Creating & Submitting a Production Plan

### Scenario

> You are the production planner. Tomorrow you need to produce:
> - **500 kg** of *Cheese Puffs* (item code `CP-001`)
> - **300 kg** of *Onion Rings* (item code `OR-002`)

### Step-by-step walkthrough

#### Step 1 — Create a new Production Plan

1. In ERPNext, go to **Manufacturing → Production Plan → New Production Plan**.
2. The new plan opens in draft mode.

#### Step 2 — Set the Posting Date

Set the **Posting Date** to tomorrow's date (e.g., `2026-04-11`).

> **⚠️ Warning:** The Posting Date is critical. The Storekeeper Hub filters Work Orders by this exact date. If the Posting Date is wrong, the Storekeeper will not see your Work Orders. Always double-check it before submitting.

#### Step 3 — Add items to the plan

In the **Products for Work Orders** (`po_items`) table, add two rows:

| Item Code | Item Name | Qty | UoM |
|-----------|-----------|-----|-----|
| CP-001 | Cheese Puffs | 500 | kg |
| OR-002 | Onion Rings | 300 | kg |

For each row, also set the **BOM** and **Factory Section** (e.g., `Line A` for Cheese Puffs, `Line B` for Onion Rings).

#### Step 4 — Get sub-assembly items (if applicable)

If any of your items have **sub-assemblies** (e.g., a slurry or pre-mix that is produced in-house), click **Get Sub Assembly Items**. The system looks up each item's BOM tree and adds rows for any semi-finished components that also need Work Orders.

> **Note:** You can skip this step if your BOMs have no in-house sub-assemblies.

#### Step 5 — Submit the Production Plan

Click **Submit**. The plan moves from Draft to Submitted. It now has a name, for example **PP-2026-00042**.

#### Step 6 — Make Work Orders

Click the **Make Work Order** button (top of the Production Plan form).

iSnack checks whether Work Orders already exist for this plan. If any are found, a warning dialog appears:

> *"Work Orders already exist for some items in this Production Plan. Do you want to create additional Work Orders?"*

Click **Yes** only if you genuinely need duplicates (e.g., split batches). In most cases, click **No** to stop and review the existing WOs first.

When Work Orders are created successfully you'll see a confirmation. The system creates:

| Work Order | Item | Qty | Line |
|------------|------|-----|------|
| WO-2026-00101 | Cheese Puffs (CP-001) | 500 kg | Line A |
| WO-2026-00102 | Onion Rings (OR-002) | 300 kg | Line B |

Each Work Order:
- Inherits the **BOM** from the Production Plan row.
- Is linked back to **PP-2026-00042** via the `production_plan` field.
- Has status **Not Started** and no allocation chip yet.

#### Step 7 — Verify Work Orders were created

On the submitted Production Plan, click **View → Work Orders** to see the list. Confirm that WO-2026-00101 and WO-2026-00102 appear with status `Not Started`.

---

## 3. Stage 2: Storekeeper Hub — Staging Materials

### What the Storekeeper does

The Storekeeper's job is to pick the raw materials listed in each BOM, move them from the main store to the **Staging Warehouse**, and record that transfer in the system. Only then can the Operator start production.

### Step-by-step walkthrough

*(Continuing from Stage 1: Production Plan PP-2026-00042, Posting Date 2026-04-11.)*

#### Step 1 — Open the Storekeeper Hub and set filters

Open **Storekeeper Hub** from the main menu. Set the three filters in the top toolbar:

| Filter | Value (our example) | Why it matters |
|--------|---------------------|----------------|
| **Factory Section** | `Line A` | Shows only the WOs for Line A |
| **Prod. Plan Posting Date** | `2026-04-11` | Matches the Production Plan's Posting Date |
| **Source Warehouse** | `Raw Material Store - IS` | Where materials are picked from |

Click **Refresh**. The left column now shows WO buckets for Line A dated 2026-04-11.

#### Step 2 — Review the WO bucket

You see one bucket:

```
📦  Cheese Puffs (BOM-CP-001-v1)
    1 Work Order  •  500 kg
    └─ WO-2026-00101  |  2026-04-11  |  500 kg  |  [no chip]
```

The `[no chip]` means nothing has been staged yet.

#### Step 3 — Select for Allocation

Check the box next to **WO-2026-00101** and click **Select for Allocation**. The **Consolidated Pick Cart** in the centre column fills automatically with the remaining quantities for each BOM component, for example:

| Item | Required | Already Staged | Remaining |
|------|----------|---------------|-----------|
| Corn Starch | 50 kg | 0 kg | **50 kg** |
| Cheese Powder | 25 kg | 0 kg | **25 kg** |
| Salt | 5 kg | 0 kg | **5 kg** |

> **Tip:** If you have already staged some items on a previous run (e.g., Corn Starch was pre-staged earlier), the *Remaining* column will show the shortfall only. You never over-stage.

#### Step 4 — Assign batches for batch-tracked items

Cheese Powder is batch-tracked. Notice the gold **`...`** button in its cart row. Click it to open the **Batch Selector** dialog:

```
Item: Cheese Powder
────────────────────────────────────────────
Batch        Expiry       Available
────────────────────────────────────────────
CP-B-240901  2026-09-01   30 kg
CP-B-250101  2026-01-01    8 kg
────────────────────────────────────────────
Assign qty per batch (total must = 25 kg):
  CP-B-240901: [25] kg   ← Use the older batch first (FEFO)
  CP-B-250101: [  ] kg
```

Enter quantities that total 25 kg, then click **Confirm**.

> **⚠️ Warning:** You cannot click **Allocate & Create Transfers** until all batch-tracked items in the cart have a batch assigned. The system will block the action and highlight the unassigned row.

#### Step 5 — Allocate & Create Transfers

Click **Allocate & Create Transfers**. The system:

1. Processes the cart in **FIFO order** — Work Orders are serviced by planned start date (earliest first), then by creation date. This ensures the most urgent WOs are staged first when multiple WOs share the same pool of materials.
2. Creates one **Material Transfer Stock Entry** per Work Order, moving the items from the Source Warehouse to the Staging Warehouse for Line A.
3. Updates WO-2026-00101's `stage_status` to **Staged**.

The **Created transfers** card below the cart shows the result:

```
✅  SE-00201  |  WO-2026-00101  |  [Open]  [Print]
```

Back in the bucket panel, the WO chip turns green:

```
📦  Cheese Puffs (BOM-CP-001-v1)
    └─ WO-2026-00101  |  [● Allocated]
```

#### What "Partly Allocated" looks like

If the Storekeeper had allocated *only* Corn Starch (50 kg) but not Cheese Powder or Salt, the chip would instead show amber:

```
└─ WO-2026-00101  |  [◑ Partly Allocated]
```

The Operator's **Start** button would remain disabled until all materials are staged (chip = Allocated).

#### Step 6 — (Optional) Print Pallet Labels

Click **Print Pallet Labels** in the toolbar to print combined pallet/staging labels for the staged items. A dialog shows all recent staged Stock Entries; select the ones you want and click **Print**.

#### Step 7 — (Optional) Generate a Picklist

Click **Generate Picklist** → **Create Picklist** to produce a picking document for the warehouse team, listing exactly which items, batches, and quantities to pull from the shelves.

---

## 4. Stage 3: Operator Hub — Producing Finished Goods

### What the Operator does

The Operator's job is to run the machine, record which materials were actually consumed, and report the final output (good qty, rejects, batch code).

### Step-by-step walkthrough

*(Continuing from Stage 2: WO-2026-00101 is now fully staged.)*

#### Step 1 — Open the Operator Hub and set your context

Open **Operator Hub** from the main menu.

- Click **Set Line** → select `Line A`.
- Click **Set Operator** → select your employee record (or scan your badge).

The Work Order queue loads. You see:

```
WO-2026-00101  |  Cheese Puffs  |  500 kg  |  Line A
[● Allocated]  [Not Started]
```

#### Step 2 — Start the Work Order

Click **WO-2026-00101** to load its banner, then click **Start**.

The system automatically runs a **Material Transfer for Manufacture**, moving all staged materials from the Staging Warehouse into the **WIP (Work-In-Progress) Warehouse** for Line A:

```
SE-00202  |  Staging Warehouse → WIP Line A
  Corn Starch     50 kg
  Cheese Powder   25 kg  (Batch CP-B-240901)
  Salt             5 kg
```

The WO status changes to **In Process**.

#### Step 3 — Load / scan materials

As you feed raw materials into the machine, record each one:

**Option A — Barcode scan (preferred)**

Click **Load Materials**. The scan field is automatically focused. Scan the barcode on each sack or container. Each successful scan:
- Validates the item against the BOM and configured allowed item groups.
- Checks that you are not consuming more than 150% of the BOM requirement (configurable in Factory Settings).
- Creates a **Material Consumption for Manufacture** Stock Entry.
- Plays a success tone.

**Option B — Manual Load**

Click **Manual Load** if you do not have a scanner:
1. Select Item Code (e.g., `Corn Starch`).
2. Select Batch No if applicable.
3. Review **Required Qty**, **Remaining Qty** and **Available Qty in WIP** to decide how much to load.
4. Enter Qty (e.g., `50`).
5. Click **Add**, then repeat for each item.
6. Click **Post Consumption** to save all rows at once.

The **Materials** panel updates in real time:

| Item | Required | Transferred | Consumed | Remaining |
|------|----------|------------|---------|-----------|
| Corn Starch | 50 kg | 50 kg | 50 kg | 0 kg |
| Cheese Powder | 25 kg | 25 kg | 25 kg | 0 kg |
| Salt | 5 kg | 5 kg | 5 kg | 0 kg |

#### Step 4 — Pause and Resume (optional)

If the line stops for a break or an unplanned reason:

- Click **Pause** → WO status changes to **Stopped**.
- When you are ready to continue, click **Resume** → WO returns to **In Process**.

No stock movements happen on Pause or Resume.

#### Step 5 — Request more material (if needed)

If you run short — for example, the machine spilled some Cheese Powder:

1. Click **Request More Material**.
2. Select **Item**: `Cheese Powder`.
3. Enter **Qty**: `3` kg.
4. Select a **Reason**: `Machine Loss`.
5. Click **Submit**.

A **Material Request** is sent to the Storekeeper, who will see it and stage the extra amount. You do not need to restart the WO.

#### Step 6 — Return unused materials (if needed)

If you loaded too much Corn Starch and have 2 kg left over at the machine:

1. Click **Return Materials**.
2. Add a row: `Corn Starch`, qty `2`.
3. Click **Post Returns**.

A **Material Transfer** SE moves the 2 kg from WIP back to the Staging Warehouse.

#### Step 7 — End the Work Order

When the machine has finished processing the batch:

1. Click **End WO**.
2. If the BOM contains **semi-finished components** (e.g., a slurry produced in-house), a dialog appears asking for the actual quantities used. Enter each one and click **Submit**.
3. The Work Order is flagged as production-ended and disappears from the active queue.

> **Note:** Clicking End WO does **not** yet create the Finished Goods stock entry. That happens in the next step, Close Production.

#### Step 8 — Close Production

When all Work Orders on the line have been ended, click **Close Production**.

A dialog appears:

```
Ended Work Orders:
  • WO-2026-00101  Cheese Puffs  500 kg

Total Good Qty:     [490] kg
Total Reject Qty:   [ 10] kg
Batch No:           [CGB-151]

Packaging Materials Used:
  Bag 500g  ×  [980] pcs
```

Fill in the fields:

| Field | Example value | Notes |
|-------|--------------|-------|
| Total Good Qty | `490` kg | Actual good output |
| Total Reject Qty | `10` kg | Damaged / off-spec product |
| Batch No | `CGB-151` | 7-character iSnack batch code (see tip below) |
| Packaging Materials | `980` pcs | Bags, cartons, etc. from the BOM |

Click **Submit**. The system:
- Creates a **Manufacture Stock Entry** (FG receipt into the Finished Goods warehouse, BOM material consumption from WIP).
- Splits quantities proportionally across ended WOs.
- Sets Work Order WO-2026-00101 to **Completed**.

> **Tip — Batch code format:** iSnack uses a 7-character code `YYM-DDS`. Letters represent numbers: A=0, B=1 … J=9. Example: `CGB-151` → year 26 (`CG`), month Feb (`B`), day 15, batch sequence 1. So `CGB-151` = 26 February 15, first batch of the day.

#### Step 9 — Print FG labels

After Close Production, click **Print Label** to print carton or pallet labels for the finished goods:

1. A dialog shows the produced item with quantity and pallet type.
2. Confirm carton qty and pallet type.
3. Click **Print Labels** — labels open automatically for printing (via QZ Tray if configured, or browser dialog).

---

## 5. End-to-End Example Summary

The table below summarises the entire flow for the Cheese Puffs example in a single "cheat sheet":

| Step | Who | Action | ERPNext Document Created | Result |
|------|-----|--------|--------------------------|--------|
| 1 | Planner | Create Production Plan; set Posting Date 2026-04-11; add CP-001 500 kg & OR-002 300 kg | **Production Plan PP-2026-00042** | Plan in draft |
| 2 | Planner | Submit the Production Plan | — | Plan approved |
| 3 | Planner | Click Make Work Order | **WO-2026-00101** (Cheese Puffs, 500 kg, Line A) **WO-2026-00102** (Onion Rings, 300 kg, Line B) | WOs ready; status = Not Started |
| 4 | Storekeeper | Open Storekeeper Hub; filter Line A, date 2026-04-11; select WO-2026-00101; assign Cheese Powder batch CP-B-240901 | — | Cart filled with Corn Starch 50 kg, Cheese Powder 25 kg, Salt 5 kg |
| 5 | Storekeeper | Click Allocate & Create Transfers | **Material Transfer SE-00201** (Raw Material Store → Staging Line A) | WO-2026-00101 stage_status = Staged; chip = Allocated (green) |
| 6 | Operator | Open Operator Hub; set Line A; click WO-2026-00101; click Start | **Material Transfer for Manufacture SE-00202** (Staging → WIP Line A) | WO status = In Process |
| 7 | Operator | Scan / manually load Corn Starch 50 kg, Cheese Powder 25 kg, Salt 5 kg | **Material Consumption for Manufacture SE-00203, SE-00204, SE-00205** | Materials snapshot = fully consumed |
| 8 | Operator | Click End WO | — | WO flagged as production-ended |
| 9 | Operator | Click Close Production; enter Good Qty 490 kg, Reject 10 kg, Batch CGB-151, Bags 980 pcs | **Manufacture Stock Entry SE-00206** | WO-2026-00101 = Completed; FG received into stock |
| 10 | Operator | Click Print Label | **Label Record LR-00301** | Carton / pallet labels printed |

---

## 6. Tips & Troubleshooting

### "Why can't I see my Work Orders in the Storekeeper Hub?"

Check the two most common filter issues:

1. **Factory Section** — make sure you have selected the correct line (e.g., `Line A`). If this field is blank, you will see WOs for all lines, which can be confusing on a busy day.
2. **Prod. Plan Posting Date** — this must exactly match the **Posting Date** on the Production Plan. If the planner set the Posting Date to tomorrow but you have today's date in the filter, you will see nothing.

After correcting the filters, click **Refresh**.

---

### "Why is the Start button disabled in the Operator Hub?"

The **Start** button only becomes active when the Work Order's allocation chip shows **Allocated** (green). Check:

- Did the Storekeeper run the allocation for this WO yet? If the chip shows **Partly Allocated** (amber), some materials are still missing.
- If the chip shows nothing at all, no staging has been done yet for this WO.

Ask the Storekeeper to open the Storekeeper Hub, find the WO bucket, complete the cart, and click **Allocate & Create Transfers**.

---

### "What happens if I scan the wrong item?"

The system validates every scan before posting it. If you scan an item that:

- **Is not in the BOM** — you will hear an error tone and see the message *"Item is not a BOM component for this Work Order."* The scan is rejected and nothing is posted.
- **Belongs to a disallowed item group** — same rejection. Allowed item groups are configured in Factory Settings.
- **Would push consumption above the over-consumption threshold** (default 150% of BOM qty) — the scan is rejected with an over-consumption warning.

No stock movement is created for a rejected scan. Simply scan the correct item.

---

### "What if I need to use more material than the BOM specifies?"

The **over-consumption threshold** controls how much extra you can record beyond the BOM requirement. The default is **150%** — meaning you can consume up to 1.5× the BOM quantity before the system blocks further consumption.

If your process regularly requires more than this, ask your IT administrator or factory manager to adjust the threshold in **Factory Settings → Over-consumption Threshold**. The setting applies per line.

---

### "I submitted the wrong quantity in Close Production. What do I do?"

Close Production creates submitted Stock Entries. Once submitted, they cannot be edited directly. Contact your supervisor or system administrator to cancel and re-create the relevant Manufacture Stock Entry. The Work Order will be re-opened to **Completed = 0** after the cancellation so that Close Production can be run again with the correct quantities.

---

### "The Batch Selector shows insufficient stock. What do I do?"

If the **Batch Selector** dialog shows a warning that the total available stock across all batches is less than the required cart quantity:

1. Check with the Storekeeper whether a Purchase Receipt for that item is pending.
2. If stock has physically arrived but is not yet in the system, ask the Storekeeper to post a **PO Receipt** from the Storekeeper Hub toolbar.
3. If the shortage is genuine, contact your purchasing team to arrange an urgent delivery or consider reducing the production quantity.

---

### "I forgot to Return Materials before running Close Production. What do I do?"

Contact your system administrator. They can manually create a **Material Transfer** Stock Entry to move the remaining items from the WIP Warehouse back to the appropriate warehouse. Alternatively, use the **End Shift Return** button in the Operator Hub if the shift has ended and the WIP warehouse still has unaccounted stock.
