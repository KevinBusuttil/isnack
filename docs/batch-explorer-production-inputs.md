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
│  │     │    └─ SFG10001   Corn mix · made by MFG-WO-2026-00021 · 180.000 Kg  [Consumed] [Semi-finished]
│  │     │         └─ ▸ Made by [1]          Booked into Semi-finished - ISN since it was last empty
│  │     │              └─ MFG-WO-2026-00021 · 20/08/2026 · SFG10001 [Completed]   Made 180.000 Kg
│  │     │                   └─ ▸ Materials consumed [3]   Stock UOM · whole Work Order   (corn grits, water, oil …)
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

**Batch identity of a consumed row.** The row's own batch when the MES set one; otherwise the Serial and Batch Bundle ERPNext created (BOM remainder rows at Close Production have their batches auto-picked; such a row is split per batch and marked `bundle i/n`); otherwise none. A row without a batch is either a semi-finished item, traced on through the section below, or a raw material kept without batches (water), where the trace ends at the item.

## Semi-finished items

Semi-finished items (SFG10001 corn mix, SFG10002 slurry) carry no batch. Their Work Orders book them into one shared pool, Semi-finished - ISN, and the finished-goods Work Order draws from that pool without recording which run it took. So the Explorer reads the source off the pool's stock ledger instead.

**The rule.** Once the pool's balance falls to zero, nothing booked before that is left. So a draw came from what was booked into the pool after the last time it was empty. Under the consumed item a **Made by** group lists those Work Orders, each with its own Materials consumed, down to its raw-material lots.

* One Work Order is the usual case: that run is the source.
* Several Work Orders mean stock was left over from an earlier run. All of them are listed, and the group hint says the split between them is not recorded. No quantity is apportioned to either.
* Anything else that raised the pool in that window (a Stock Reconciliation, a Material Receipt, a transfer in) is listed too, tagged **Origin not recorded**, with what it added. So the list never looks complete when part of the pool has no known origin.
* If the pool was never at zero before the draw, every earlier receipt is listed and the hint says so. A pool that rarely empties therefore gives a long list.

**What counts as semi-finished.** A consumed item without a batch that some submitted Work Order produces. Batchless raw materials such as water keep "No batch · trace ends here", as does a semi-finished item whose pool shows no receipt at all.

**Quantities.** "Made" on a source Work Order is its whole output. Its Materials consumed are whole-Work-Order totals, as everywhere else on the page; they are not what went into this batch.

**Depth.** A semi-finished item made from another semi-finished item is followed the same way, up to three semi-finished levels, and a Work Order already on the path is not expanded again.

**A limit worth knowing.** The rule reads the books, not the tank. It names the right run as long as each mix is booked into the pool (End WO with "Close Semi-finished WOs at End WO", or Close Production of the SFG line) before the finished-goods run's End WO draws it. A mix used before it was booked is invisible to the ledger at the time of the draw, and the trace would name the stock booked before it. Likewise residue left in a vessel after the books reach zero is not recorded.

## Permissions and load

The nested level appears only for users with read access to Stock Entry. Stock Entries and Batches are filtered with permission-aware list calls before any detail row is read; entries the user may not read are counted in the group hint instead of silently dropped. A batch produced by more than ten Work Orders gets a **Load production inputs** button on the remaining Work Orders instead of loading everything with the page. Saving the exploration to PDF loads those too, so nothing goes to paper unexpanded (see `batch-explorer-pdf-export.md`).

## Code

* `isnack/utils/batch_lineage.py`: the linkage, consumption, bundle-expansion, share and classification rules, and `pool_sources` (the semi-finished pool's ledger). Pure data helpers, no permission logic.
* `isnack/isnack/page/batch_explorer/batch_explorer.py`: roles per Work Order, permission pass, nested group assembly, the Made by level (`_attach_sfg_sources`), the deferred endpoint `get_work_order_inputs`.
* `isnack/isnack/page/batch_explorer/batch_explorer.js` and `.css`: nested groups, tags, evidence lines, neutral quantity chips, filter and deep links. The filter opens every group that holds a match, however deep.
* Tests: `isnack/utils/test_batch_lineage.py`, `isnack/isnack/page/batch_explorer/test_batch_explorer.py`.
