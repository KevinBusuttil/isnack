# Storekeeper Hub & Operator Hub — User Flow Guide

This document explains the operational flow for the Storekeeper Hub and Operator Hub in the iSnack MES experience, based on the current UI and server behavior.

## Storekeeper Hub flow

### 1. Start-of-shift setup
- **Open the Storekeeper Hub** page and use the top toolbar filters.
- **Choose a Factory Line** to target the current production line.
- **Choose a Source Warehouse** to control where the stock transfers/issue/receipt will pull from.
- **Optional: Set a Pallet ID** to tag transfers with a pallet reference for downstream tracking.
- Use **Refresh** to reload the latest WOs and staging data.

### 2. Review work order buckets (same BOM)
- The left column shows **WO Buckets** grouped by the same BOM.
- Selecting a bucket drives which Work Orders are available for consolidated picking.

### 3. Build the consolidated pick cart
- In the center column, use the **Consolidated Pick Cart** to gather items to stage:
  - Scan item barcodes or type item codes in the scan field.
  - Add manual rows for ad‑hoc items or missing scans.
  - Adjust quantities, batches, and notes if needed.
- The cart acts as a single staging list across multiple WOs.

### 4. Allocate & create transfers
- Click **Allocate & Create Transfers** to distribute cart quantities across selected WOs.
- Allocation uses FIFO by WO start time to keep staging fair and consistent.
- Transfers created from the allocation appear in the “Created transfers” results card.

### 5. Generate picklist (optional)
- Use **Generate Picklist** to create a picklist for selected Stock Entries.
- This is typically used by the stock team to speed up picking/issuing.

### 6. Quick stock entry actions
From the toolbar:
- **Mat. Transfer** → create a manual transfer stock entry.
- **Mat. Issue** → issue materials manually (non‑WO).
- **Mat. Receipt** → receive materials manually.
- **PO Receipt** → create purchase receipt entries from a PO.

### 7. Recent activity & tracking (right column)
- **Staged Today** shows the recent staged transfers.
- **Recent Manual Stock Entries (Last 24h)** summarizes manual stock moves.
- **Pallet Tracker (Last 24h)** shows the latest pallet-related transfers.

## Operator Hub flow

### 1. Set operator & line
- Use **Set Operator** to select the current Employee.
- Use **Set Line** to select one or more Factory Lines.
- The hub then loads the **Assigned Work Orders** queue for those lines.

### 2. Select a Work Order
- Click any WO in the queue to load the **Current Work Order** banner.
- The hub will also load the **Materials snapshot**, showing:
  - Required vs. transferred vs. consumed quantities.
  - Remaining quantities and recent issue/transfer history.

### 3. Start / Pause / Resume a Work Order
- **Start** is enabled only when the WO is fully staged (Allocated).
- **Pause** becomes **Resume** if the WO is in “Stopped” status.
- Status updates refresh the banner and queue automatically.

### 4. Load / scan materials
- Click **Load Materials** to open scan mode.
- Scan raw/semi-finished/packaging barcodes to log consumption.
- The scan history panel shows recent scan results and updates the materials snapshot.

### 5. Request more material
- **Request More Material** opens a form to request extra items (with reason).
- Submitting this generates a material request for the Storekeeper.

### 6. Return materials (per WO)
- **Return Materials** lets operators scan items, add quantities, and post returns back to inventory.

### 7. End shift return (WIP)
- **End Shift Return** retrieves WIP inventory for the selected line.
- Operators enter quantities to return and post the WIP return in bulk.

### 8. Label printing (FG only)
- **Print Label** creates a carton label for finished goods.
- **Label History** lists previously printed labels and allows:
  - Reprinting.
  - Splitting labels into multiple quantities.
- When enabled, the hub uses **QZ Tray** for silent printing; otherwise it falls back to browser dialogs.

### 9. Close / End Work Order
- **Close / End** completes the WO with good and reject quantities.
- If semi‑finished components are required, operators enter actual usage, and the system consumes them from the SFG warehouse.

---

If you need additional screenshots or training materials for either hub, let me know and I can extend this document.
