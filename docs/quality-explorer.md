# Quality Explorer

The Quality Explorer (`/app/quality-explorer`) is the Batch Explorer's counterpart for QC records. Pick a batch or a Work Order and it lists every QC record (QCA–QCI) that belongs to it, says how each one belongs, and shows which record types are missing. Save as PDF prints the whole thing as the quality dossier of that batch or Work Order, for an FSSC 22000 audit or a customer complaint.

It is linked from the Factory workspace (Hubs card) and from the Quality Hub's Reports & Trends quick links. Deep links:

- `/app/quality-explorer/Batch/<batch>`
- `/app/quality-explorer/Work Order/<work-order>`

## What the auditor sees

```
Batch AAO-007 · FG10005 · Salted Crisps 50g · Manufactured 20-10-2026
  8 QC records · 7 submitted · 1 draft · 1 failed · 2 Work Orders · 2 ingredient batches

Record coverage   QCA 1 · QCB 1 · QCC 0 · QCD 2 · QCF — · QCG 1 · QCH 1 · QCI 2
                  (green: submitted · amber: drafts only · red: a record failed · grey: none)

Batch · AAO-007
├─ Receiving (QCA) [1]
│  └─ QCA-2026-00031 [Ingredient]      Accepted  Submitted  Anna Borg
│        RM10001 consumed by MFG-WO-2026-00118
├─ Puffs Extruder (QCB) [1]
│  └─ QCB-2026-00210 [Semi-finished run]   Pass   Submitted
│        MFG-WO-2026-00118 made SFG10001 for MFG-WO-2026-00121
├─ Frying Line (QCD) [2]               (records of the producing Work Order)
├─ Weight (QCI) [2]                    [This batch] [Work Order]   Marginal / Fail
├─ ▸ Work Orders [2]                   MFG-WO-2026-00121 [Made this batch] · 6 QC records
│                                      MFG-WO-2026-00118 [Semi-finished run] · 1 QC record
└─ ▸ Ingredient batches [2]            RAA-101 · 1 QC record
                                       RAB-220 [No receiving record] · 0 QC records
```

Each record shows its result (Overall Status; "All tests passed" for a metal detector log, "Variance acceptable" for a packaging check), Draft or Submitted, the operator and the QC inspector. Clicking a record opens it; clicking a Work Order or an ingredient batch explores that one in turn.

## Which records belong

A QC record names a batch (`batch_no`: receiving, tasting, weight checks), a Work Order (`work_order`: every type but receiving), or both. The explorer collects the batches and Work Orders the subject stands for and reads every record that names one of them:

| Exploring | Batches | Work Orders |
|---|---|---|
| a Batch | the batch | the Work Orders that produced it (from the stock ledger, by the Batch Explorer's rules) and any Work Order the batch's own QC records name |
| a Work Order | the finished-goods batches its Manufacture entries made | the Work Order |
| both, below them | the raw-material batches those Work Orders consumed | the runs that made a semi-finished item they consumed |

The ingredient level uses the same lineage as the Batch Explorer's production inputs (`isnack/utils/batch_lineage.py`): consumed rows of submitted Manufacture and Material Consumption entries, and for a semi-finished item without a batch, the runs booked into its pool since it was last empty, down to three semi-finished levels. The ingredients of at most 10 producing Work Orders are traced; the page says so when there were more.

A Work Order that consumed the explored batch is downstream of it and is not included. Cancelled records are left out; drafts are shown and counted separately.

An ingredient batch with no receiving record gets a **No receiving record** tag: a raw-material lot went into the product without a goods-inward inspection on file.

## Permissions

The page itself is open to desk users, like the Batch Explorer. Exploring a batch needs read on that batch; exploring a Work Order needs read on that Work Order. Both are checked on the document, so User Permissions apply to a direct call or a shared link too, not only to the pickers.

The Oven record (QCE) is retired: oven readings are on the extruder records (QCB, QCC) now, so the coverage strip lists QCE only when the batch or Work Order has an old Oven record, never as missing.

A record type the user may not read shows as "—" in the coverage strip and is named under the summary. Within a type, records a User Permission keeps from the user (on a line, an item, a supplier) are not shown but are counted: the summary says how many are hidden, a type whose only records are hidden reads "—" rather than "No record", a Work Order or batch in the trace groups says "+N hidden" next to its record count, and an ingredient whose receiving record is hidden is not flagged **No receiving record**. A Work Order that only a hidden record names still has its other records looked up. Nothing on the page claims a record is missing when the user simply may not see it.

Tracing ingredients needs Stock Entry read, as on the Batch Explorer; without it the records of the batch and its Work Orders are still listed and the page says the ingredients were not traced. When some of a Work Order's Stock Entries are hidden by permissions, the page says the ingredients may be incomplete.

The URL always names the subject on screen (`/app/quality-explorer/Batch/<batch>`), so Back, refresh and a shared link open the same dossier, and Back to the bare `/app/quality-explorer` empties the page. A link or a typed name that spells it in another case (`fg10005-001` for `FG10005-001`) opens the batch once and takes its stored name, without adding a step to Back, whatever the user does while it loads. A picker checks its value with the server again when it loses focus; a click on a trace leaf or a link that lands before that check returns still opens what was clicked, and the picker follows the URL.

## Files

- `isnack/isnack/page/quality_explorer/quality_explorer.py`: `get_quality_records(batch_no=None, work_order=None)`
- `isnack/isnack/page/quality_explorer/quality_explorer.js` / `.css`: the page
- `isnack/isnack/page/quality_explorer/test_quality_explorer.py`: unit tests (pure mocks)
