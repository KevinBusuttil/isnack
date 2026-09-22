# Storekeeper Hub — Delivery Note Batch Scan

The **Delivery Note** button in the Storekeeper Hub toolbar (immediately right of
*PO Receipt*) opens a scanning dialog for a **draft** Delivery Note. The
storekeeper scans the finished-goods QR labels printed from **Operator Hub →
Print Label** as the pallets are loaded, and each label's batch is allocated
against the matching Delivery Note line.

The Delivery Note itself is never edited here. Lines cannot be added, removed or
re-quantified, and **Post does not submit** — it records how far the scan has got
so the work can be picked up again later.

This is separate from the [Delivery Note form scanner](delivery-note-label-scanning.md),
which scans into the Delivery Note *form* and is governed by its own Factory
Settings flags. The two do not share state and should not be used on the same
Delivery Note at the same time.

---

## Why a Serial and Batch Bundle

A line usually needs more than one batch, because a single batch rarely holds
enough stock to cover it. `Delivery Note Item.batch_no` can only carry one, so
the allocation is written as an outward **Serial and Batch Bundle** — one entry
per batch — exactly as ERPNext builds them itself in
`erpnext/controllers/selling_controller.py::get_serial_and_batch_bundle`.

There is one constraint that shapes the whole feature. `SellingController.validate`
runs `set_serial_and_batch_bundle` on **every** save of the Delivery Note, ending
in `SerialandBatchBundle.validate_quantity`: a bundle referenced by
`Delivery Note Item.serial_and_batch_bundle` must total that row's stock quantity,
or the save is rejected. A half-scanned line therefore cannot carry a linked
bundle.

So the bundle is written either way, but the row only points at it once the line
is complete:

| Line state | Bundle | Linked from the row? |
|---|---|---|
| Nothing scanned | none | — |
| Partially allocated | draft bundle, carries `voucher_no` + `voucher_detail_no` | **No** — ERPNext never validates it, so the draft keeps saving normally |
| Fully allocated | same bundle, reused in place | **Yes**, and `batch_no` is cleared with `use_serial_batch_fields` set to 0 |

The bundle is always left in draft. ERPNext submits it itself when the Delivery
Note is submitted (`StockLedgerEntry.on_submit` → `SerialBatchBundle.post_process`).

---

## Scan status

A new read-only custom field, **Delivery Note → Scan Status**
(`custom_scan_status`), records the result of the last Post:

| Value | Meaning |
|---|---|
| *(blank)* / Not Scanned | Never posted from this dialog |
| Partially Scanned | At least one batch-tracked line is short |
| Fully Scanned | Every batch-tracked line is fully allocated |

A **Fully Scanned** Delivery Note is closed to further scanning: it drops out of
the dialog's picker and the server refuses it even if the name is typed by hand.
Anything else can be revisited as often as needed.

Lines that are not batch-tracked (delivery charges and the like) and serialised
items are listed but greyed out — they take no part in the allocation and do not
hold a Delivery Note back from reaching *Fully Scanned*.

---

## Using the dialog

1. **Pick a Delivery Note.** The picker lists draft Delivery Notes that are not
   yet fully scanned, newest first.
2. **Scan.** Put the cursor in the scan box and scan pallets. The payload is the
   standard iSnack label `ITEM_CODE|BATCH_NO|QTY`, with the quantity in cartons
   (the item's stock UOM).
3. **Watch the lines fill.** Each line shows its allocated batches as chips —
   `BBB-114 ×78` — so a split line reads at a glance. A row turns amber when it
   is partly covered and green when it is complete.
4. **Post.** The batches are written and the scan status is recorded. The
   Delivery Note stays a draft.

### Worked example

`MAT-DN-2026-00011` asks for 300 cartons of `FG10011`, and no single batch holds
300. Two production runs printed labels on *EUR 2 Pallet x 78*, so each 150-carton
batch printed as two pallets:

```
FG10011|BBB-114|78    →  78/300   [BBB-114×78]              Partially Scanned
FG10011|BBB-114|72    → 150/300   [BBB-114×150]             Partially Scanned
FG10011|BBB-113|78    → 228/300   [BBB-113×78, BBB-114×150] Partially Scanned
FG10011|BBB-113|72    → 300/300   [BBB-113×150, BBB-114×150] Fully Scanned
```

Post writes one bundle for that line with two entries, `BBB-113 -150` and
`BBB-114 -150` (ERPNext flips the sign for outward movements).

---

## What the dialog checks, and when

At **scan time**, while the pallet is still in the storekeeper's hands:

- the item exists and is on this Delivery Note — a label for something else is
  refused rather than adding a line;
- the batch exists and belongs to that item;
- the batch has not expired before the Delivery Note's posting date;
- the batch has stock in the line's warehouse **as of the Delivery Note's posting
  date and time**, which is what ERPNext validates at submit;
- the batch still has enough left after everything this Delivery Note already
  claims of it — this is what pushes the storekeeper onto a second batch;
- the label carries a batch. A mixed pallet prints with an empty batch segment
  (`FG10011||150`) by design; those are refused with a reprint message.

Two cases ask instead of refusing:

- **Over-scan** — the label carries more than the line still needs (two 78-carton
  pallets against a line of 150). The dialog offers to take what is left and set
  the rest aside.
- **Duplicate label** — two identical pallets print byte-identical QR payloads, so
  a repeated payload is ambiguous rather than wrong. The dialog asks before
  applying it again.

At **Post time** everything is validated again — the client's map is a proposal,
not a fact. Allocating more than a line requires is refused. A batch that has
*lost* stock since it was scanned is only **reported**, not refused: ERPNext lets
a draft bundle exceed current stock (draft bundles reserve nothing), and refusing
would strand work already done on the floor. The warning names the line and the
shortfall, and the Delivery Note will not submit until it is resolved.

---

## Revisiting a Delivery Note

Reopening a **Partially Scanned** Delivery Note restores what the last Post wrote,
by reading back the bundles this dialog owns.

A bundle the dialog never wrote — a Pick List allocation, or one of the legacy
drafts already on site — is deliberately *not* counted as scanned work, because
scanning is the act that verifies what is physically on the pallet. Such batches
are shown in the Batch column as *On file* so the storekeeper can see what their
scans are about to replace, and the dialog never deletes them on its own.

Each line's **Clear** button drops that line's scans so a mis-scan can be undone.

---

## Warehouse, UOM and posting date

- **One bundle, one warehouse.** ERPNext stamps the bundle's warehouse onto every
  entry, so a line is always allocated from its own warehouse.
- **Quantities are in stock UOM.** The label QR carries cartons, and a bundle is
  measured in stock UOM, so the two agree without conversion. A line whose `uom`
  differs from its `stock_uom` shows both, and the allocation target is the line's
  `stock_qty`.
- **Availability follows the posting date.** If the Delivery Note is backdated
  before the batch was produced, the batch reads as unavailable here — which is
  what would have happened at submit anyway, surfaced early with a message that
  names the date.

---

## Permissions

Every endpoint checks `write` permission on the Delivery Note itself
(`frappe.has_permission("Delivery Note", "write", doc=..., throw=True)`), so the
dialog grants nothing the user could not already do on the document. The button
is not role-gated in the toolbar, matching *PO Receipt*.

---

## Implementation

| Piece | Where |
|---|---|
| Backend | `isnack/api/delivery_note_batch_scan.py` |
| Tests | `isnack/api/test_delivery_note_batch_scan.py` |
| Button | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.html` (`.dn-scan`) |
| Dialog | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.js` (*Delivery Note Scan Dialog*) |
| Styling | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.css` (`.dn-scan-dialog`) |
| Custom field | `isnack/fixtures/custom_field.json` (`Delivery Note-custom_scan_status`) |

Endpoints, all whitelisted on `isnack.api.delivery_note_batch_scan`:

- `get_scannable_delivery_notes` — the picker's Link query;
- `get_delivery_note_scan_state` — the dialog's payload for one Delivery Note;
- `scan_label` — validates one label and returns the updated allocation;
- `post_delivery_note_scan` — writes the bundles and the scan status.

Nothing here imports the Storekeeper Hub page module, and every change to an
existing file is additive, so existing Storekeeper Hub behaviour is untouched. The
Delivery Note is written with `frappe.db.set_value` only, which keeps the
`doc_events` on `Delivery Note.validate` (pallet calculation and its validation)
from re-running mid-scan and blocking the storekeeper.

### Compatibility note

`Serial and Batch Bundle` carried `posting_date` + `posting_time` for most of
ERPNext v15 and only later collapsed them into `posting_datetime`. Both schemas
are live on isnack sites, so the code reads the installed meta and writes whichever
exists — the same defensive idiom `delivery_note_scan._core_scan` uses for
`scan_barcode`'s signature.
