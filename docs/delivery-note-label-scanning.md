# Delivery Note Label Scanning

The **Scan Barcode** field on the Delivery Note understands the QR labels
printed from the Operator Hub (carton and pallet labels, payload
`ITEM_CODE|BATCH_NO|QTY`). Scanning a label sets the batch number on the
matching Delivery Note item row — and, in the default mode, adds the label's
quantity to it — so dispatch can be recorded batch-exactly by scanning the
pallets as they are loaded.

Anything that is not an iSnack label (a plain item barcode, a bare batch
number, a GS1 code without a known GTIN) still goes through ERPNext's
standard barcode lookup, so existing scanning behaviour is unchanged.

---

## Enabling

Factory Settings → **Scanning and Consumption** → *Delivery Note Label
Scanning* column:

| Setting | Default | Meaning |
|---|---|---|
| Enable Delivery Note Label Scanning | Off | Master switch. While off, the Scan Barcode field behaves exactly as stock ERPNext. |
| Delivery Note Scan Quantity Mode | Increment by Label Qty | See modes below. |
| Restrict Scans to Items on the Delivery Note | On | A label for an item that is not on the Delivery Note is rejected with an error instead of adding a new row (recommended for Delivery Notes created from Sales Orders). |

## Quantity modes

- **Increment by Label Qty** — each scan adds the quantity printed in the QR
  (e.g. 66 cartons for a full pallet label) to the matching row. Scanning
  every pallet while loading builds the delivered quantities per batch, and
  any difference against the ordered quantity is immediately visible.
- **Increment by 1** — behaves like a standard ERPNext barcode scan (the
  label is only used to resolve item + batch).
- **Assign Batch Only** — sets the batch on the matching row without touching
  its quantity. A second batch of the same item still creates a new row,
  whose quantity is taken from the label (or left for the user).

## Behaviour details

- **Multiple batches per item** ("batch number or numbers"): ERPNext's
  scanner matches a row only if its batch is empty or equal to the scanned
  one, so a second batch automatically lands on a new row. The Serial and
  Batch Bundle is built by ERPNext at save from the plain batch fields
  (`use_serial_batch_fields` is set by the scanner).
- **Duplicate labels**: every label is one physical carton/pallet, so
  scanning the exact same payload twice on one Delivery Note asks for
  confirmation before applying it again (the memory lasts while the form is
  open).
- **Validation at scan time**: a label whose batch does not exist, belongs
  to a different item, or refers to an unknown item is rejected with a
  specific error message. A batch with no available stock in the source
  warehouse is applied but flagged with an orange warning.
- **Units**: label quantities are in the item's stock UOM; if a row sells in
  a different UOM the scanned quantity is converted via the row's conversion
  factor.
- **Separators**: `~` is accepted as an alias for `|` (some USB scanners emit
  it on non-US keyboard layouts), same as the Operator Hub scan flows.

## Implementation notes

- Server: `isnack/api/delivery_note_scan.py` — a `scan_api` implementation
  for `erpnext.utils.BarcodeScanner`; falls through to
  `erpnext.stock.utils.scan_barcode` for non-label input. Payload parsing is
  shared with the Operator Hub via `isnack/utils/scan.py`.
- Client: `isnack/public/js/delivery_note.js` — a `BarcodeScanner` subclass
  installed on the Delivery Note form's controller in `setup`.
- Tests: `isnack/api/test_delivery_note_scan.py`.
