# 📋 Weekly Changelog — May 8–15, 2026

> Repository: [KevinBusuttil/isnack](https://github.com/KevinBusuttil/isnack)

---

## 🏭 Operator Hub Improvements

- **Redesigned action buttons** — The bottom action bar got a full visual overhaul with a cleaner, color-coded palette. Each button group (Start/Resume, Pause, Load, Request More Material, etc.) now has a distinct, intuitive color. Disabled buttons are clearly grayed out, and touch/keyboard interactions feel more responsive.

- **Fixed invisible buttons** — A bug caused some bottom-bar buttons to appear blank (white text on white background) after the restyle. This has been fixed.

- **Enforce BOM consumption before ending a Work Order** — Operators can no longer end a Work Order (WO) if required materials haven't been consumed. A summary table shows what was required, consumed, and what's remaining. Production Managers can override with a written reason if needed.

- **Unified dialog theming** — All dialogs in the Operator Hub now share a consistent look (teal header, themed buttons, semantic color cues) via a shared `.op-dialog` base style.

- **Request More Material scoped to current WO** — When an operator requests more material, the item list is now filtered to only the raw materials needed for the active Work Order. It also pre-fills the quantity shortfall so the operator can see exactly what they're short on.

- **Material Requests now auto-submitted** — Previously, newly created Material Requests were left in "Draft" status and wouldn't show up on the Storekeeper Hub. They are now automatically submitted so they appear immediately.

---

## 🏪 Storekeeper Hub Improvements

- **New "Pending Requests" panel** — Storekeepers can now see all operator-initiated Material Requests directly in their hub, scoped to their factory line. Each request shows the item, Work Order, quantity needed, operator name, and a one-click **Stage** button to fulfil it.

- **Stage dialog with smart filters** — The Stage dialog lets storekeepers pick a source warehouse, quantity, and batch (filtered by warehouse). On confirmation, it creates and submits a stock transfer automatically.

- **Real-time updates** — The Pending Requests panel refreshes automatically when a new request is created or fulfilled — no manual page refresh needed.

- **Fixed: already-transferred MRs no longer shown** — Material Requests that had already been fully transferred were incorrectly still showing up in the Pending Requests panel. This has been fixed with more accurate remaining-quantity calculations.

- **Fixed crash (500 error)** — The Storekeeper Hub was crashing because it referenced a non-existent `mr.notes` field. This is now replaced with a proper Comment-based reason lookup.

- **Improved row layout** — Pending Request rows now display in a cleaner stacked layout with item name, Work Order link, remaining quantity (highlighted in amber), operator name, and action buttons — much easier to scan at a glance.

- **Unified dialog theming** — Similar to the Operator Hub, all Storekeeper Hub dialogs now share a consistent cerulean-blue visual theme.

- **MR fulfilment Stock Entries visible in Staged panel** — Stock Entries created from Material Request fulfilments now correctly appear in the Staged panel, labeled with a small "MR" chip so they're easily distinguishable.

---

## 🔍 Quality Hub Improvements

- **Better dialog layouts** — Quality Hub dialogs (QC Tasting, QC Packaging, QC Receiving) now use a grouped 2-column layout with proper section breaks, making them easier to read and fill out.

- **Readings, Tests & Samples in dedicated sections** — These fields now appear in their own full-width sections within dialogs, rather than being squeezed inline.

- **Consistent theming** — Quality Hub dialogs now align with the same shared color system used across the other hubs.

- **Fixed Quick Links routing** — Quality Hub Quick Links for DocTypes with spaces in their names (e.g., "QC Tasting") were broken. They now correctly navigate using `frappe.set_route`.

- **New QC Receiving Record dialog** — Storekeepers can now create QC Receiving Records directly from the Quality Hub via a dialog, with cascading filters for supplier/item.

---

## ⚙️ Other / Backend

- **End WO tolerance setting** — A new `End WO Tolerance %` field (default 2%) was added to Factory Settings, letting admins configure how much under-consumption is allowed before an End WO is blocked.

- **Storekeeper Hub: End Shift Returns no longer require a factory line** — Fixed a crash where pending End Shift Returns would fail if no factory line was linked.

- **End Shift Return tracking** — Added storekeeper acknowledgement tracking for end-shift material returns.

- **Temporary category field change reverted** — A change to convert a Template Item `category` field into a dropdown select was merged and then reverted (twice), indicating it's still being worked on.

---

*Generated on 2026-05-15*
