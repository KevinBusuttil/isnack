# Batch Explorer: production inputs drill-down

The Batch Explorer (`/app/batch-explorer/<batch>`) lists every transaction a batch took part in. For a finished-goods batch it now also shows, under each Work Order that produced the batch, what went into it: the raw materials and raw-material batches consumed, and every Stock Entry the MES booked against that Work Order. This is the drill-down an auditor needs to go from a finished-goods lot back to raw-material lots and, one click further, to their Purchase Receipts and suppliers.

## What the auditor sees

```
Batch · AAO-007
├─ Work Order [2]
│  ├─ MFG-WO-2026-00027 · 21/08/2026 · FG10005 [Completed]
│  │     This batch: 193 Carton · Work Order output: 193 Carton · 100 %
│  │     ├─ ▸ Materials consumed [4]        Stock UOM · whole Work Order
│  │     │    ├─ RAW-0412   RM20003 · Corn grits    155.365 Kg  [Consumed]     ← opens the explorer for RAW-0412
│  │     │    │     MAT-STE-2026-00098 · Material Consumption for Manufacture · 21/08/2026 · WIP-L1 · 120.000
│  │     │    │     MAT-STE-2026-00123 · Manufacture · 21/08/2026 · WIP-L1 · 35.365
│  │     │    └─ SFG10001   Corn mix · 180.000 Kg  [Consumed] [No batch · trace ends here]
│  │     ├─ ▸ Work Order stock entries [6]   (no quantities; tagged Staging, To WIP, Consumption, Return, Surplus, Manufacture)
│  │     └─ ▸ Not effective [1]              (draft or cancelled entries, name only)
│  └─ MFG-WO-2026-00028 · 25/08/2026 · FG10005 [Completed] [Shared output]
│        This batch: 267 Carton · Work Order output: 300 Carton · 89 %
├─ Stock Entry [2]  460.000                  (unchanged: how much of this batch each voucher moved)
└─ Delivery Note / Sales Order …            (unchanged)
```

On a raw-material batch page the Work Orders that consumed it get a nested **Produced** group with the finished-goods batches they made, so the chain can be walked in both directions.

## Rules

**Which Work Orders get the drill-down.** A Work Order is a *producer* of the batch when a finished-item row of its Stock Entries carries the batch, a *consumer* when a consumed row carries it, and a mere *handler* when it only transferred it. Producers get the three nested groups, consumers get **Produced**, handlers get nothing.

**Which Stock Entries belong to a Work Order.** Everything the MES writes:

| Entry | Found through |
|---|---|
| Staging transfer, Material Request fulfilment, Material Transfer for Manufacture, Material Consumption for Manufacture, Manufacture, return to staging | `Stock Entry.work_order` |
| Surplus staged from a consolidated pick | `Surplus Originating Work Order` child table (legacy rows: `custom_originating_work_order`) |
| Surplus swept from staging into WIP | `custom_surplus_wip_transfer` on the surplus entry it emptied (legacy sweeps: the exact remark the MES writes) |

End-shift WIP returns reference a line, never a Work Order, and are not shown. Manual desk Stock Entries on a batch appear only as ordinary top-level vouchers.

**What counts as consumed.** The same rule ERPNext uses for `Work Order Item.consumed_qty` and the Customs Export Traceability Report applies: a submitted Manufacture or Material Consumption for Manufacture entry, a row that is neither the finished item nor scrap, with a source warehouse. Staging transfers, transfers for manufacture and returns are chain of custody, not usage, and are listed without quantities. Note that the Operator Hub's own "Consumed" figure counts Material Consumption for Manufacture entries only; the BOM remainder booked inside the Manufacture entry at Close Production is consumption too and is included here.

**Quantities.** Material quantities are positive, in the material's stock UOM, for the *whole* Work Order. They are never apportioned to the batch. When a Work Order produced more than this batch it is tagged **Shared output**, its note shows the share, and the materials hint says so. The top-level groups keep their meaning: a node quantity there is how much of *this* batch the voucher moved, and the totals and the transaction count derive from those nodes only.

**Batch identity of a consumed row.** The row's own batch when the MES set one; otherwise the Serial and Batch Bundle ERPNext created (BOM remainder rows at Close Production and semi-finished rows have their batches auto-picked; such a row is split per batch and marked `bundle i/n`); otherwise none, and the trace ends at the item.

## Permissions and load

The nested level appears only for users with read access to Stock Entry. Stock Entries and Batches are filtered with permission-aware list calls before any detail row is read; entries the user may not read are counted in the group hint instead of silently dropped. A batch produced by more than ten Work Orders gets a **Load production inputs** button on the remaining Work Orders instead of loading everything with the page.

## Code

* `isnack/utils/batch_lineage.py`: the linkage, consumption, bundle-expansion, share and classification rules. Pure data helpers, no permission logic.
* `isnack/isnack/page/batch_explorer/batch_explorer.py`: roles per Work Order, permission pass, nested group assembly, the deferred endpoint `get_work_order_inputs`.
* `isnack/isnack/page/batch_explorer/batch_explorer.js` and `.css`: nested groups, tags, evidence lines, neutral quantity chips, filter and deep links.
* Tests: `isnack/utils/test_batch_lineage.py`, `isnack/isnack/page/batch_explorer/test_batch_explorer.py`.
