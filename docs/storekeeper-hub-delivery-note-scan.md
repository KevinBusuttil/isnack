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
| Fully allocated | same bundle, reused in place | **Yes** — see [Putting a line back](#putting-a-line-back) for what that writes on the row |

The bundle is always left in draft. ERPNext submits it itself when the Delivery
Note is submitted (`StockLedgerEntry.on_submit` → `SerialBatchBundle.post_process`).

---

## Which bundles the dialog owns

A draft Delivery Note routinely already carries a Serial and Batch Bundle that
ERPNext or a Pick List built — every draft on the current site does. The dialog
must never mistake one of those for its own work, so each bundle it creates is
stamped with a hidden custom field, **Serial and Batch Bundle →
`custom_isnack_dn_scan`**.

Only stamped bundles are read back, rewritten or deleted. Anything else is
display-only: its batches appear in the Batch column as *On file* so the
storekeeper can see what is already on the line, and the dialog leaves it alone.
The consequence is deliberate — an allocation that was never scanned is never
reported as verified, and a scan never destroys one.

Only a stamped bundle is detached from its row, too. A line whose bundle the
dialog does not own is left linked even when the scan is short — nulling it would
strip a complete allocation off the row and leave it with neither a batch nor a
bundle, which the app's own Delivery Note pallet validator then rejects on every
later save.

### Putting a line back

Linking a bundle overwrites three fields on the Delivery Note Item, so what they
were is snapshotted onto the stamped bundle first
(`custom_isnack_dn_scan_restore`) and restored when the scan is cleared:

| Field | While the dialog owns the line | On Clear |
|---|---|---|
| `batch_no` | the single allocated batch, or blank when the line is split across several | whatever it was before |
| `use_serial_batch_fields` | `0`, which is what a bundle-backed row needs | whatever it was before |
| `has_item_scanned` | `1`, which keeps the Delivery Note form's own scanner from re-quantifying a line this dialog owns | whatever it was before |

Keeping a single batch on the row matters: ERPNext's `BarcodeScanner` matcher
reads a blank `batch_no` as "any batch will do", so blanking it unconditionally
would turn a bundle-backed row into a catch-all for the form scanner.

All three custom fields ship in `isnack/fixtures/custom_field.json`. If the scan
status or the ownership stamp is missing the dialog refuses to open and says to
run `bench migrate`, rather than half-working; the restore point degrades quietly,
since a line with no snapshot is simply left alone on Clear.

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

The lock is checked against the note, not against the flag. A fully scanned
Delivery Note is still an editable draft, so a line added afterwards would
otherwise leave the flag claiming "finished" about something nobody has scanned
and lock the note out for good. A note that has reached *Fully Scanned* carries a
bundle on every batch-tracked line, so a line without one means the note has
changed since: it reappears in the picker, reopens, and its stored status is
corrected on the way in.

Lines that are not batch-tracked (delivery charges and the like) and serialised
items are listed but greyed out — they take no part in the allocation and do not
hold a Delivery Note back from reaching *Fully Scanned*.

Two cases deliberately never reach *Fully Scanned*:

- A **return** Delivery Note (`is_return`) is refused outright. Its lines carry
  negative quantities, which would read as already covered, and its bundle would
  need to be inward — a different job than scanning pallets onto a truck.
- A note whose allocation is **short of stock** is held at *Partially Scanned*
  even when every line is covered, because *Fully Scanned* is a one-way door and
  a note that cannot submit must stay re-scannable.

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
- the batch has not expired before the note's effective posting date;
- the batch has stock in the line's warehouse **as of the moment the note will
  post**, which is what ERPNext validates at submit (see *Warehouse, UOM and
  posting date* below);
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
shortfall, the Delivery Note will not submit until it is resolved, and the note
is held at *Partially Scanned* so it can be re-scanned.

### Two dialogs on one Delivery Note

Every payload carries a **state token** — the Delivery Note's `modified` stamp.
A Post writes the scan status onto the note, so the token moves; a second dialog
still holding the old one is told to reload rather than allowed to overwrite. An
edit to the note's own lines invalidates it for the same reason. Post *requires*
the token — omitting it would opt straight out of the check — so a dialog cached
from before this shipped is asked to reopen, which is the right answer for it too.

Separately, a line is only emptied when the storekeeper presses **Clear**: the
Post names the rows to clear explicitly. Absence from the allocation map never
means "delete", so a dialog left open in another tab cannot wipe work posted in
the meantime.

---

## Revisiting a Delivery Note

Reopening a **Partially Scanned** Delivery Note restores what the last Post wrote,
by reading back the bundles this dialog owns.

A bundle the dialog never wrote — a Pick List allocation, or one of the legacy
drafts already on site — is deliberately *not* counted as scanned work, because
scanning is the act that verifies what is physically on the pallet. Such batches
are shown in the Batch column as *On file* so the storekeeper can see what their
scans are about to replace, and the dialog never deletes them on its own.

Each line's **Clear** button drops that line's scans so a mis-scan can be undone;
it takes effect on the next Post, which is allowed even when clearing is the only
thing left to record.

---

## Warehouse, UOM and posting date

- **One bundle, one warehouse.** ERPNext stamps the bundle's warehouse onto every
  entry, so a line is always allocated from its own warehouse.
- **Quantities are in stock UOM.** The label QR carries cartons, and a bundle is
  measured in stock UOM, so the two agree without conversion. A line whose `uom`
  differs from its `stock_uom` shows both, and the allocation target is the line's
  `stock_qty`.
- **One label, one warehouse.** A Delivery Note can ship one item from two
  warehouses. A label is applied to the lines whose warehouse actually holds that
  batch; the others are left for a label from their own stock, rather than
  vetoing the scan.
- **Availability follows the moment the note will post**, not the moment stored
  on the draft. With `Edit Posting Date and Time` off — the ERPNext default —
  `TransactionBase.validate_posting_time` rewrites the stored posting date and
  time with `now()` on every save and at submit, so the stored values are only
  "when the draft was last saved". Judging availability against them would hide
  every batch produced since, which here is most of them, because the Delivery
  Note is raised from the Sales Order before the goods are made. The stored
  moment is honoured only when the user pinned it.

---

## Permissions

Every endpoint checks `write` permission on the Delivery Note itself
(`frappe.has_permission("Delivery Note", "write", doc=..., throw=True)`), so the
dialog grants nothing the user could not already do on the document. The button
is not role-gated in the toolbar, matching *PO Receipt*.

The picker query is permission-aware in its own right: it carries frappe's
`get_match_cond("Delivery Note")` and the standard
`@frappe.validate_and_sanitize_search_inputs` decorator, so it cannot disclose the
names, customers or posting dates of Delivery Notes outside the caller's User
Permissions — the write check on open would refuse those notes, but only after the
metadata had already been listed.

---

## Implementation

| Piece | Where |
|---|---|
| Backend | `isnack/api/delivery_note_batch_scan.py` |
| Tests | `isnack/api/test_delivery_note_batch_scan.py` |
| Button | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.html` (`.dn-scan`) |
| Dialog | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.js` (*Delivery Note Scan Dialog*) |
| Styling | `isnack/isnack/page/storekeeper_hub/storekeeper_hub.css` (`.dn-scan-dialog`) |
| Custom fields | `isnack/fixtures/custom_field.json` (`Delivery Note-custom_scan_status`, `Serial and Batch Bundle-custom_isnack_dn_scan`, `Serial and Batch Bundle-custom_isnack_dn_scan_restore`) |

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
