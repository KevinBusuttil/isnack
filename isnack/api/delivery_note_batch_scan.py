# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Storekeeper Hub "Delivery Note" dialog — allocate batches by scanning labels.

The storekeeper opens a *draft* Delivery Note in the hub, scans the finished-goods
labels printed by Operator Hub -> Print Label, and the batch on each label is
allocated against the matching Delivery Note line. Nothing about the Delivery Note
itself changes: lines are never added, removed or re-quantified here. The only
writes are the batch allocation and a scan-status flag.

Why a Serial and Batch Bundle
-----------------------------
One line often needs several batches, because a single batch rarely holds enough
stock to cover it. ``Delivery Note Item.batch_no`` can only carry one, so the
allocation is written as an outward Serial and Batch Bundle — one entry per batch,
quantities negative, exactly as ERPNext builds them itself in
``erpnext/controllers/selling_controller.py::get_serial_and_batch_bundle``.

Why a short bundle is never linked to the row
---------------------------------------------
``SellingController.validate`` runs ``set_serial_and_batch_bundle`` on every save of
the Delivery Note, which ends in ``SerialandBatchBundle.validate_quantity``: a bundle
referenced by ``Delivery Note Item.serial_and_batch_bundle`` must total that row's
stock qty, or the save is thrown out. A half-scanned line therefore *cannot* carry a
linked bundle.

So the bundle is written either way, but the row only points at it once the line is
fully allocated:

* partially allocated -> draft bundle exists, carries ``voucher_no`` and
  ``voucher_detail_no``, and is **not** linked from the row. ERPNext never validates
  it, the Delivery Note keeps saving normally, and the scans survive until the
  storekeeper comes back.
* fully allocated -> the same bundle is linked onto the row, ``batch_no`` is cleared
  and ``use_serial_batch_fields`` is set to 0, which is what ERPNext requires of a
  bundle-backed row.

The bundle is always left in draft. ERPNext submits it itself when the Delivery Note
is submitted (``StockLedgerEntry.on_submit`` -> ``SerialBatchBundle.post_process``).
Posting from this dialog never submits the Delivery Note.

Isolation
---------
Nothing here is imported by, or imports from, the Storekeeper Hub page module, and
no existing endpoint, hook or document class is modified. The Delivery Note is
touched with ``frappe.db.set_value`` only, so the ``doc_events`` that fire on
``Delivery Note.validate`` (pallet calculation and its validation) are not re-run by
a scan and cannot block the storekeeper.
"""

from __future__ import annotations

import inspect

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

from erpnext.stock.doctype.batch.batch import get_batch_qty

from isnack.utils.scan import parse_gs1_or_basic

#: ``Delivery Note.custom_scan_status`` values. A Delivery Note that has never been
#: posted from this dialog stores NULL, which reads as "Not Scanned".
STATUS_NOT_SCANNED = "Not Scanned"
STATUS_PARTIAL = "Partially Scanned"
STATUS_FULL = "Fully Scanned"

SCAN_STATUS_FIELD = "custom_scan_status"

#: Marks the Serial and Batch Bundles this dialog created. Without it there is no
#: way to tell a scan from an allocation ERPNext or a Pick List built, and adopting
#: a foreign bundle would destroy work the storekeeper never scanned.
BUNDLE_OWNER_FIELD = "custom_isnack_dn_scan"

#: Holds what the Delivery Note Item looked like before this dialog took the line
#: over, so clearing the scan puts it back instead of leaving the row with no batch
#: at all. Lives on the bundle because that is what the dialog owns.
BUNDLE_RESTORE_FIELD = "custom_isnack_dn_scan_restore"

#: Fields of the Delivery Note Item this dialog overwrites, and therefore snapshots.
ROW_RESTORE_FIELDS = ("batch_no", "use_serial_batch_fields", "has_item_scanned")

#: Quantities are compared at three decimals, matching the hub's fmt_qty/round_qty.
QTY_PRECISION = 3
QTY_TOLERANCE = 0.001


# ---------------------------------------------------------------------------
# ERPNext version shims
#
# The Serial and Batch Bundle carried posting_date + posting_time for most of v15
# and only later collapsed them into a single posting_datetime. Both shapes are
# live on isnack sites, so the installed schema decides which is written, in the
# same spirit as delivery_note_scan._core_scan probing scan_barcode's signature.
# ---------------------------------------------------------------------------


def _combine_datetime(posting_date, posting_time):
    try:
        from erpnext.stock.utils import get_combine_datetime

        return get_combine_datetime(posting_date, posting_time)
    except Exception:
        return now_datetime()


def _posting_context(doc) -> dict:
    """Everything the posting moment is needed for, resolved once per Delivery Note.

    ``bundle_fields`` go onto a Serial and Batch Bundle; ``qty_kwargs`` go to
    ``get_batch_qty``; ``key`` identifies the moment for the availability memo.

    Availability is judged as of the moment the Delivery Note will actually post,
    because that is what ERPNext validates at submit. On a note with
    ``set_posting_time`` off — the default — the stored posting date and time are
    only "when the draft was last saved":
    ``TransactionBase.validate_posting_time`` overwrites them with ``now()`` on every
    save and at submit. Judging availability at the stored moment would report every
    batch produced since that save as absent, which on this site is most of them,
    because the Delivery Note is raised from the Sales Order before the goods are
    made. So the stored moment is only honoured when the user pinned it.
    """
    if cint(doc.get("set_posting_time")):
        posting_date = doc.get("posting_date")
        posting_time = doc.get("posting_time")
    else:
        now = now_datetime()
        posting_date = now.strftime("%Y-%m-%d")
        posting_time = now.strftime("%H:%M:%S.%f")
    combined = _combine_datetime(posting_date, posting_time)

    meta = frappe.get_meta("Serial and Batch Bundle")
    if meta.has_field("posting_datetime"):
        bundle_fields = {"posting_datetime": combined}
    else:
        bundle_fields = {"posting_date": posting_date, "posting_time": posting_time}

    try:
        params = inspect.signature(get_batch_qty).parameters
    except (TypeError, ValueError):
        params = {}
    if "posting_datetime" in params:
        qty_kwargs = {"posting_datetime": combined}
    elif "posting_date" in params:
        qty_kwargs = {"posting_date": posting_date, "posting_time": posting_time}
    else:
        qty_kwargs = {}

    return {
        "bundle_fields": bundle_fields,
        "qty_kwargs": qty_kwargs,
        "key": str(combined),
        "posting_date": posting_date,
    }


# ---------------------------------------------------------------------------
# Loading and guards
# ---------------------------------------------------------------------------


def _has_scan_status_field() -> bool:
    return bool(frappe.get_meta("Delivery Note").has_field(SCAN_STATUS_FIELD))


def _has_bundle_owner_field() -> bool:
    return bool(frappe.get_meta("Serial and Batch Bundle").has_field(BUNDLE_OWNER_FIELD))


def _has_restore_field() -> bool:
    return bool(frappe.get_meta("Serial and Batch Bundle").has_field(BUNDLE_RESTORE_FIELD))


def _require_custom_fields() -> None:
    """Both custom fields must exist before anything is written.

    Without the status field a Post cannot be remembered, and without the owner
    field the dialog cannot tell its own bundles from ERPNext's — it would adopt and
    overwrite them. Failing loudly beats half-working: the fields ship in
    ``isnack/fixtures/custom_field.json`` and arrive with ``bench migrate``.
    """
    missing = []
    if not _has_scan_status_field():
        missing.append(f"Delivery Note.{SCAN_STATUS_FIELD}")
    if not _has_bundle_owner_field():
        missing.append(f"Serial and Batch Bundle.{BUNDLE_OWNER_FIELD}")
    if missing:
        frappe.throw(
            _(
                "Delivery Note scanning is not installed on this site yet: {0} is "
                "missing. Run bench migrate to sync the iSnack custom fields."
            ).format(", ".join(missing))
        )


def _scan_status(delivery_note: str) -> str:
    """The stored scan status, with NULL normalised to "Not Scanned"."""
    if not _has_scan_status_field():
        return STATUS_NOT_SCANNED
    return (
        frappe.db.get_value("Delivery Note", delivery_note, SCAN_STATUS_FIELD)
        or STATUS_NOT_SCANNED
    )


def _load_delivery_note(delivery_note: str, for_update: bool = False):
    """Fetch a draft Delivery Note the current user may scan into.

    ``for_update`` takes a row lock so two storekeepers posting the same Delivery
    Note at once cannot both allocate the last of a batch.
    """
    _require_custom_fields()

    name = (delivery_note or "").strip()
    if not name:
        frappe.throw(_("Select a Delivery Note first."))

    if not frappe.db.exists("Delivery Note", name):
        frappe.throw(_("Delivery Note {0} does not exist.").format(frappe.bold(name)))

    frappe.has_permission("Delivery Note", "write", doc=name, throw=True)

    if for_update:
        # The app's locking idiom (see isnack.api.mes_ops) — hold the parent row for
        # the rest of the transaction so concurrent posts serialise.
        frappe.db.sql("select name from `tabDelivery Note` where name = %s for update", (name,))

    doc = frappe.get_doc("Delivery Note", name)

    if cint(doc.docstatus) != 0:
        frappe.throw(
            _(
                "Delivery Note {0} is not a draft, so its batches can no longer be scanned."
            ).format(frappe.bold(name))
        )

    # A return moves stock inward with negative line quantities. Every line would
    # read as already covered, and the bundle would need type_of_transaction
    # "Inward" — a different job than scanning pallets onto a truck.
    if cint(doc.get("is_return")):
        frappe.throw(
            _("Delivery Note {0} is a return, which is not scanned from this dialog.").format(
                frappe.bold(name)
            )
        )

    # A fully scanned Delivery Note is still an editable draft. Adding a line, or
    # swapping one for a batch-tracked item, leaves the stored status saying
    # "finished" about a note that now has an unscanned line, so the lock is
    # enforced against what the note looks like now rather than against the flag.
    if _scan_status(name) == STATUS_FULL and not _rows_awaiting_bundle(doc):
        frappe.throw(
            _(
                "Delivery Note {0} is already fully scanned and cannot be reopened for scanning."
            ).format(frappe.bold(name))
        )

    return doc


def _rows_awaiting_bundle(doc) -> list:
    """Batch-tracked lines that carry no bundle at all.

    After a Post that reached Fully Scanned every scannable line is linked to one,
    so a line without a bundle means the note has changed since. That is also what
    brings it back into the picker."""
    items = _item_cache(doc)
    return [
        row
        for row in doc.get("items") or []
        if _row_is_scannable(items.get(row.item_code) or {})
        and not row.get("serial_and_batch_bundle")
    ]


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------


def _row_is_scannable(item: dict) -> bool:
    """Only batch-tracked, non-serialised lines take part in scanning.

    Non-stock lines (delivery charges and the like) and serialised items are listed
    in the dialog but excluded from the allocation and from the completeness test,
    or a Delivery Note carrying one could never reach "Fully Scanned".
    """
    return bool(cint(item.get("has_batch_no"))) and not cint(item.get("has_serial_no"))


def _item_cache(doc) -> dict:
    """``{item_code: {has_batch_no, has_serial_no, stock_uom}}`` for every line."""
    codes = {row.item_code for row in doc.get("items") or [] if row.item_code}
    out = {}
    for code in codes:
        out[code] = (
            frappe.get_cached_value(
                "Item", code, ["has_batch_no", "has_serial_no", "stock_uom"], as_dict=True
            )
            or {}
        )
    return out


def _required_qty(row) -> float:
    """How much the line needs, in stock UOM — what a bundle must total.

    ``validate_quantity`` compares the bundle against ``stock_qty`` whenever it is
    set, so the allocation target is the stock quantity, not the line quantity. The
    label QR also carries stock UOM (cartons), so the two agree without conversion —
    which matters on the lines whose ``uom`` differs from ``stock_uom``.
    """
    stock_qty = flt(row.get("stock_qty"))
    if stock_qty:
        return flt(stock_qty, QTY_PRECISION)
    conversion = flt(row.get("conversion_factor")) or 1.0
    return flt(flt(row.qty) * conversion, QTY_PRECISION)


# ---------------------------------------------------------------------------
# Allocations: the client's working set, normalised server-side
# ---------------------------------------------------------------------------


def _normalise_allocations(raw, doc) -> dict:
    """Sanitise a client allocation map into ``{row_name: {batch_no: qty}}``.

    Rows that are not on this Delivery Note, rows that cannot be scanned, blank
    batches and non-positive quantities are dropped rather than trusted. Repeated
    batches are merged, because a Serial and Batch Bundle may carry a batch only
    once (``validate_duplicate_serial_and_batch_no``).
    """
    if isinstance(raw, str):
        raw = frappe.parse_json(raw or "{}")
    if not isinstance(raw, dict):
        raw = {}

    items = _item_cache(doc)
    scannable = {
        row.name for row in doc.get("items") or [] if _row_is_scannable(items.get(row.item_code) or {})
    }

    out: dict = {}
    for row_name, entries in raw.items():
        if row_name not in scannable or not isinstance(entries, list):
            continue
        merged: dict = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            batch_no = (entry.get("batch_no") or "").strip()
            qty = flt(entry.get("qty"))
            if not batch_no or qty <= 0:
                continue
            merged[batch_no] = flt(merged.get(batch_no, 0.0) + qty, QTY_PRECISION)
        if merged:
            out[row_name] = merged
    return out


def _stored_allocations(doc) -> dict:
    """Read back what a previous Post wrote, as ``{row_name: {batch_no: qty}}``.

    Only bundles this dialog stamped are read. A bundle ERPNext built by itself — a
    Pick List allocation, or one of the legacy drafts already on site — is *not*
    treated as scanned work, because scanning is the act that verifies what is
    physically on the pallet, and restoring one would report an unscanned pallet as
    verified.
    """
    rows = doc.get("items") or []
    if not rows:
        return {}

    # Exactly one bundle per line, even where the line carries debris — summing
    # every bundle found would restore the same quantity twice on a revisit.
    candidates = _owned_bundles(doc.name, [row.name for row in rows])
    by_bundle = {}
    for row in rows:
        names = candidates.get(row.name) or []
        if not names:
            continue
        linked = row.get("serial_and_batch_bundle")
        by_bundle[linked if linked in names else names[0]] = row.name
    if not by_bundle:
        return {}
    entries = frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": ("in", list(by_bundle)), "parenttype": "Serial and Batch Bundle"},
        fields=["parent", "batch_no", "qty"],
    )

    out: dict = {}
    for entry in entries:
        row_name = by_bundle.get(entry.parent)
        batch_no = (entry.batch_no or "").strip()
        if not row_name or not batch_no:
            continue
        # Outward entries are stored negative; the dialog works in positives.
        qty = abs(flt(entry.qty))
        if qty <= 0:
            continue
        row = out.setdefault(row_name, {})
        row[batch_no] = flt(row.get(batch_no, 0.0) + qty, QTY_PRECISION)
    return out


def _as_allocation_payload(working: dict) -> dict:
    return {
        row_name: [{"batch_no": b, "qty": q} for b, q in sorted(batches.items())]
        for row_name, batches in working.items()
    }


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _available_qty(item_code: str, batch_no: str, warehouse: str, posting: dict) -> float:
    """Stock of one batch in one warehouse as of the Delivery Note's posting moment.

    Expired and disabled batches come back as zero — ``get_available_batches``
    filters them out — which is the answer we want, though expiry is reported
    separately so the storekeeper gets a message that names the real problem.

    Memoised for the life of the request: rendering the dialog asks for every
    allocated batch on every line, and each scan re-renders. Draft bundles reserve
    nothing in ERPNext, so nothing this endpoint writes can change the answer
    mid-request.
    """
    if not (item_code and batch_no and warehouse):
        return 0.0

    cache = getattr(frappe.local, "isnack_dn_batch_availability", None)
    if cache is None:
        cache = frappe.local.isnack_dn_batch_availability = {}

    key = (item_code, batch_no, warehouse, posting["key"])
    if key in cache:
        return cache[key]

    try:
        qty = flt(
            get_batch_qty(
                batch_no=batch_no,
                warehouse=warehouse,
                item_code=item_code,
                **posting["qty_kwargs"],
            )
        )
    except Exception:
        frappe.log_error(
            title="Delivery Note batch scan: availability lookup failed",
            message=frappe.get_traceback(),
        )
        qty = 0.0

    cache[key] = qty
    return qty


def _batch_expiry(batch_no: str):
    return frappe.db.get_value("Batch", batch_no, "expiry_date")


def _linked_bundle_batches(doc) -> dict:
    """``{row_name: [{batch_no, qty}]}`` for whatever the lines point at right now.

    Shown in the dialog as "on file" so the storekeeper can see what a Pick List or
    an earlier allocation already put on the line, and therefore what their scans
    are about to replace. It is never counted as scanned work.
    """
    by_bundle = {
        row.get("serial_and_batch_bundle"): row.name
        for row in doc.get("items") or []
        if row.get("serial_and_batch_bundle")
    }
    if not by_bundle:
        return {}

    entries = frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": ("in", list(by_bundle)), "parenttype": "Serial and Batch Bundle"},
        fields=["parent", "batch_no", "qty"],
        order_by="idx asc",
    )

    out: dict = {}
    for entry in entries:
        row_name = by_bundle.get(entry.parent)
        batch_no = (entry.batch_no or "").strip()
        if not row_name or not batch_no:
            continue
        out.setdefault(row_name, []).append(
            {"batch_no": batch_no, "qty": flt(abs(flt(entry.qty)), QTY_PRECISION)}
        )
    return out


# ---------------------------------------------------------------------------
# Payload for the dialog
# ---------------------------------------------------------------------------


def _build_rows(doc, allocations: dict, posting: dict) -> list:
    """The items table the dialog renders, one entry per Delivery Note line."""
    items = _item_cache(doc)
    on_file = _linked_bundle_batches(doc)
    rows = []

    for row in doc.get("items") or []:
        item = items.get(row.item_code) or {}
        scannable = _row_is_scannable(item)
        required = _required_qty(row) if scannable else 0.0
        allocated_map = allocations.get(row.name, {}) if scannable else {}

        batches = []
        allocated = 0.0
        for batch_no, qty in sorted(allocated_map.items()):
            qty = flt(qty, QTY_PRECISION)
            allocated += qty
            batches.append(
                {
                    "batch_no": batch_no,
                    "qty": qty,
                    "expiry_date": _batch_expiry(batch_no),
                    "available_qty": _available_qty(row.item_code, batch_no, row.warehouse, posting),
                }
            )

        allocated = flt(allocated, QTY_PRECISION)
        remaining = flt(required - allocated, QTY_PRECISION)

        reason = ""
        if not scannable:
            if cint(item.get("has_serial_no")):
                reason = _("Serialised item — scan its serial numbers on the Delivery Note instead.")
            else:
                reason = _("Not batch-tracked — nothing to allocate.")

        rows.append(
            {
                "name": row.name,
                "idx": row.idx,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "qty": flt(row.qty, QTY_PRECISION),
                "uom": row.uom,
                "stock_uom": item.get("stock_uom") or row.get("stock_uom"),
                "conversion_factor": flt(row.get("conversion_factor")) or 1.0,
                "warehouse": row.warehouse,
                "required_qty": required,
                "allocated_qty": allocated,
                "remaining_qty": max(remaining, 0.0),
                "batches": batches,
                "preset_batch_no": (row.get("batch_no") or ""),
                "preset_batches": on_file.get(row.name) or [],
                "scannable": 1 if scannable else 0,
                "not_scannable_reason": reason,
                "fully_allocated": 1 if scannable and remaining <= QTY_TOLERANCE else 0,
            }
        )

    return rows


def _derive_status(rows: list) -> str:
    """"Fully Scanned" once every scannable line is covered; nothing scanned at all
    stays "Not Scanned"."""
    scannable = [row for row in rows if row["scannable"]]
    if not scannable:
        return STATUS_NOT_SCANNED
    if all(row["fully_allocated"] for row in scannable):
        return STATUS_FULL
    if any(row["allocated_qty"] > 0 for row in scannable):
        return STATUS_PARTIAL
    return STATUS_NOT_SCANNED


def _state_token(doc) -> str:
    """Identifies the version of the Delivery Note a dialog is working against.

    Every Post writes the scan status onto the Delivery Note, so its ``modified``
    moves; a second dialog still holding the old token is therefore working from a
    picture that no longer exists, and is told to reload rather than allowed to
    overwrite. An edit to the note's lines invalidates it for the same reason.
    """
    return str(doc.get("modified") or "")


def _check_state_token(doc, token, required: bool = False) -> None:
    """Refuse work built on a picture of the Delivery Note that no longer holds.

    ``required`` is set on the write path: a client that simply omits the token
    would otherwise opt straight out of the check. A dialog cached from before this
    shipped hits that, and being told to reopen is the right answer for it too.
    """
    if token in (None, ""):
        if required:
            frappe.throw(
                _(
                    "This dialog is out of date. Close it and reopen Delivery Note {0} "
                    "before posting."
                ).format(frappe.bold(doc.name))
            )
        return
    if str(token) != _state_token(doc):
        frappe.throw(
            _(
                "Delivery Note {0} changed since you opened it — someone else may be "
                "scanning it. Reopen it in the dialog to pick up the current batches."
            ).format(frappe.bold(doc.name))
        )


def _state_payload(doc, allocations: dict, posting: dict) -> dict:
    rows = _build_rows(doc, allocations, posting)
    return {
        "state_token": _state_token(doc),
        "delivery_note": doc.name,
        "customer": doc.customer,
        "customer_name": doc.get("customer_name"),
        "posting_date": doc.posting_date,
        "company": doc.company,
        "set_warehouse": doc.get("set_warehouse"),
        "scan_status": _scan_status(doc.name),
        "pending_status": _derive_status(rows),
        "rows": rows,
        "allocations": _as_allocation_payload(allocations),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_scannable_delivery_notes(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query: draft Delivery Notes still open for scanning.

    A Delivery Note drops off this list the moment it is fully scanned, which is how
    "revisit until fully scanned" is enforced in the picker; the server refuses a
    fully scanned Delivery Note as well, so the rule holds even if the name is typed
    by hand. It comes back if a line is added afterwards, because a fully scanned
    note carries a bundle on every batch-tracked line and a new line does not.

    The query is permission-aware: ``get_match_cond`` applies the caller's User
    Permissions, so the picker cannot disclose the names, customers or posting
    dates of Delivery Notes they are not entitled to see.
    """
    from frappe.desk.reportview import get_match_cond

    # The table is NOT aliased. get_match_cond qualifies its columns with the full
    # table name, which SQL puts out of scope the moment an alias is introduced — an
    # aliased query raises "Unknown column `tabDelivery Note`.`company`" for exactly
    # the restricted users the condition exists to protect, while an Administrator
    # (whose match condition is empty) sees it work. ERPNext's own match-condition
    # queries are unaliased for the same reason.
    conditions = [
        "`tabDelivery Note`.docstatus = 0",
        "ifnull(`tabDelivery Note`.is_return, 0) = 0",
    ]
    params = {"start": cint(start), "page_len": cint(page_len)}

    if frappe.get_meta("Delivery Note").has_field(SCAN_STATUS_FIELD):
        conditions.append(
            f"""(
                ifnull(`tabDelivery Note`.`{SCAN_STATUS_FIELD}`, '') != %(full_status)s
                or exists (
                    select 1
                    from `tabDelivery Note Item` dni
                    inner join `tabItem` it on it.name = dni.item_code
                    where dni.parent = `tabDelivery Note`.name
                        and it.has_batch_no = 1
                        and ifnull(it.has_serial_no, 0) = 0
                        and ifnull(dni.serial_and_batch_bundle, '') = ''
                )
            )"""
        )
        params["full_status"] = STATUS_FULL

    if txt:
        params["txt"] = f"%{txt}%"
        conditions.append(
            "(`tabDelivery Note`.name like %(txt)s"
            " or `tabDelivery Note`.customer like %(txt)s"
            " or `tabDelivery Note`.customer_name like %(txt)s)"
        )

    if filters:
        if isinstance(filters, str):
            filters = frappe.parse_json(filters)
        customer = (filters or {}).get("customer")
        if customer:
            conditions.append("`tabDelivery Note`.customer = %(customer)s")
            params["customer"] = customer
        company = (filters or {}).get("company")
        if company:
            conditions.append("`tabDelivery Note`.company = %(company)s")
            params["company"] = company

    where_clause = " and ".join(conditions)
    match_cond = get_match_cond("Delivery Note")

    return frappe.db.sql(
        f"""
        select
            `tabDelivery Note`.name,
            `tabDelivery Note`.customer_name,
            `tabDelivery Note`.posting_date
        from `tabDelivery Note`
        where {where_clause} {match_cond}
        order by `tabDelivery Note`.posting_date desc, `tabDelivery Note`.name desc
        limit %(start)s, %(page_len)s
        """,
        params,
    )


@frappe.whitelist()
def get_delivery_note_scan_state(delivery_note: str) -> dict:
    """Open a Delivery Note in the dialog: its lines plus whatever was scanned before."""
    doc = _load_delivery_note(delivery_note)

    # Reaching here with the flag still set means the note changed after it was
    # posted; leave the stored status telling the truth rather than "finished".
    if _scan_status(doc.name) == STATUS_FULL:
        _set_scan_status(doc.name, STATUS_PARTIAL)
        doc.reload()

    posting = _posting_context(doc)
    payload = _state_payload(doc, _stored_allocations(doc), posting)

    if not any(row["scannable"] for row in payload["rows"]):
        frappe.throw(
            _("Delivery Note {0} has no batch-tracked items, so there is nothing to scan.").format(
                frappe.bold(doc.name)
            )
        )

    return payload


@frappe.whitelist()
def scan_label(
    delivery_note: str, code: str, allocations=None, allow_partial=0, state_token=None
) -> dict:
    """Apply one scanned label to the working allocation and hand it back.

    The whole allocation travels with each scan so the server stays the single judge
    of what has been claimed: nothing is persisted until Post, but every rule —
    batch belongs to the item, batch has stock, line still needs quantity — is
    checked here, while the pallet is still in front of the storekeeper.
    """
    doc = _load_delivery_note(delivery_note)
    _check_state_token(doc, state_token)
    posting = _posting_context(doc)
    working = _normalise_allocations(allocations, doc)
    allow_partial = cint(allow_partial)

    raw = (code or "").strip()
    if not raw:
        frappe.throw(_("Nothing was scanned."))

    parsed = parse_gs1_or_basic(raw)
    item_code = (parsed.get("item_code") or "").strip()
    batch_no = (parsed.get("batch_no") or "").strip()
    label_qty = flt(parsed.get("qty") or 0)

    if not item_code:
        frappe.throw(_("Scanned code {0} could not be read as a label.").format(frappe.bold(raw)))

    if not frappe.db.exists("Item", item_code):
        frappe.throw(
            _("Scanned label refers to Item {0}, which does not exist.").format(frappe.bold(item_code))
        )

    # A mixed pallet prints with an empty batch segment by design. There is nothing
    # to allocate from it, so send the storekeeper back to the printer rather than
    # failing later with an error that points nowhere near the label.
    if not batch_no:
        frappe.throw(
            _(
                "Scanned label for Item {0} carries no batch. The batch is assigned at "
                "Close Production — close the Work Order if it is still open, then "
                "reprint the label from the Operator Hub."
            ).format(frappe.bold(item_code))
        )

    if label_qty <= 0:
        frappe.throw(
            _("Scanned label for Item {0} carries no quantity.").format(frappe.bold(item_code))
        )

    batch_item = frappe.db.get_value("Batch", batch_no, "item")
    if not batch_item:
        frappe.throw(
            _("Scanned label refers to Batch {0}, which does not exist.").format(frappe.bold(batch_no))
        )
    if batch_item != item_code:
        frappe.throw(
            _("Scanned label is inconsistent: Batch {0} belongs to Item {1}, not {2}.").format(
                frappe.bold(batch_no), frappe.bold(batch_item), frappe.bold(item_code)
            )
        )

    # Judged against the date the Delivery Note will actually post, which is not the
    # stored one unless the user pinned it — see _posting_context.
    effective_date = posting["posting_date"]
    expiry = _batch_expiry(batch_no)
    if expiry and effective_date and getdate(expiry) < getdate(effective_date):
        frappe.throw(
            _("Batch {0} expired on {1}, before this Delivery Note's posting date {2}.").format(
                frappe.bold(batch_no), frappe.bold(expiry), frappe.bold(effective_date)
            )
        )

    items = _item_cache(doc)
    item = items.get(item_code) or frappe.get_cached_value(
        "Item", item_code, ["has_batch_no", "has_serial_no", "stock_uom"], as_dict=True
    )
    if cint(item.get("has_serial_no")):
        frappe.throw(
            _("Item {0} is serialised and cannot be allocated by label scan.").format(
                frappe.bold(item_code)
            )
        )

    # Candidate lines, in document order — a label spills onto the next line of the
    # same item once the first is covered.
    candidates = [
        row
        for row in doc.get("items") or []
        if row.item_code == item_code and _row_is_scannable(items.get(row.item_code) or {})
    ]
    if not candidates:
        frappe.throw(
            _("Item {0} is not on Delivery Note {1}, or is not batch-tracked.").format(
                frappe.bold(item_code), frappe.bold(doc.name)
            )
        )

    open_rows = []
    for row in candidates:
        allocated = sum(flt(q) for q in (working.get(row.name) or {}).values())
        remaining = flt(_required_qty(row) - allocated, QTY_PRECISION)
        if remaining > QTY_TOLERANCE:
            open_rows.append((row, remaining))

    if not open_rows:
        frappe.throw(
            _("Item {0} is already fully allocated on this Delivery Note.").format(
                frappe.bold(item_code)
            )
        )

    # A Delivery Note can ship one item from two warehouses. The batch was produced
    # into one of them, so only the lines drawing on that warehouse can take it —
    # judging the label against all of them would refuse a scan the first line can
    # fully absorb.
    eligible = [
        (row, remaining)
        for row, remaining in open_rows
        if _available_qty(item_code, batch_no, row.warehouse, posting) > 0
    ]
    if not eligible:
        warehouses = sorted({row.warehouse for row, _r in open_rows})
        frappe.throw(
            _(
                "Batch {0} has no stock in {1}. Scan a label from a batch that is in "
                "the warehouse this Delivery Note ships from."
            ).format(frappe.bold(batch_no), frappe.bold(", ".join(warehouses)))
        )

    total_remaining = flt(sum(remaining for _row, remaining in eligible), QTY_PRECISION)

    # More on the label than the Delivery Note still wants — two pallets of 78 against
    # a line of 150, say. The storekeeper decides: take what is left and set the rest
    # aside, or stop and fix the paperwork.
    apply_qty = label_qty
    if label_qty - total_remaining > QTY_TOLERANCE:
        if not allow_partial:
            return {
                "over_scan": 1,
                "item_code": item_code,
                "batch_no": batch_no,
                "label_qty": label_qty,
                "remaining_qty": total_remaining,
                "stock_uom": item.get("stock_uom"),
                "allocations": _as_allocation_payload(working),
            }
        apply_qty = total_remaining

    # Spread the label over the open lines, in order.
    applied = []
    left = apply_qty
    for row, remaining in eligible:
        if left <= QTY_TOLERANCE:
            break
        take = flt(min(left, remaining), QTY_PRECISION)

        available = _available_qty(item_code, batch_no, row.warehouse, posting)
        claimed = sum(
            flt((working.get(other.name) or {}).get(batch_no, 0.0))
            for other in doc.get("items") or []
            if other.warehouse == row.warehouse
        )
        headroom = flt(available - claimed, QTY_PRECISION)
        if take - headroom > QTY_TOLERANCE:
            frappe.throw(
                _(
                    "Batch {0} only has {1} {2} left in {3}; this Delivery Note already "
                    "claims the rest. Scan a label from another batch for the remaining "
                    "quantity."
                ).format(
                    frappe.bold(batch_no),
                    frappe.bold(flt(max(headroom, 0.0), QTY_PRECISION)),
                    frappe.bold(item.get("stock_uom") or ""),
                    frappe.bold(row.warehouse),
                )
            )

        row_alloc = working.setdefault(row.name, {})
        row_alloc[batch_no] = flt(row_alloc.get(batch_no, 0.0) + take, QTY_PRECISION)
        applied.append({"row": row.name, "idx": row.idx, "qty": take})
        left = flt(left - take, QTY_PRECISION)

    payload = _state_payload(doc, working, posting)
    payload["scan"] = {
        "item_code": item_code,
        "batch_no": batch_no,
        "label_qty": label_qty,
        "applied_qty": flt(apply_qty - max(left, 0.0), QTY_PRECISION),
        "ignored_qty": flt(max(label_qty - apply_qty, 0.0), QTY_PRECISION),
        "stock_uom": item.get("stock_uom"),
        "rows": applied,
    }
    return payload


@frappe.whitelist()
def post_delivery_note_scan(
    delivery_note: str, allocations=None, cleared_rows=None, state_token=None
) -> dict:
    """Write the scanned batches onto the Delivery Note and record the scan status.

    The Delivery Note is *not* submitted. Fully allocated lines end up pointing at
    their bundle; partially allocated lines keep theirs unlinked so the draft still
    saves. Everything is validated again here — the client's map is a proposal, not
    a fact.

    A line is only emptied when the storekeeper says so, through ``cleared_rows``.
    Absence from ``allocations`` is never read as "delete this": a dialog left open
    in another tab would otherwise wipe work someone else had already posted.
    """
    doc = _load_delivery_note(delivery_note, for_update=True)
    _check_state_token(doc, state_token, required=True)
    posting = _posting_context(doc)
    working = _normalise_allocations(allocations, doc)

    # What a previous Post of this dialog left behind. Only these rows may have
    # their bundle torn down — a bundle this dialog never wrote (a Pick List
    # allocation, or one of the legacy drafts on site) is not ours to delete.
    previous = _stored_allocations(doc)

    if isinstance(cleared_rows, str):
        cleared_rows = frappe.parse_json(cleared_rows or "[]")
    cleared = {name for name in (cleared_rows or []) if name in previous}

    items = _item_cache(doc)
    rows_by_name = {row.name: row for row in doc.get("items") or []}

    # Structural problems are refused outright; a batch that has since been drawn
    # down elsewhere is only reported. ERPNext itself lets a draft bundle exceed
    # current stock (draft bundles reserve nothing), and refusing here would strand
    # work the storekeeper has already physically done.
    warnings = []
    for row_name, batches in working.items():
        row = rows_by_name[row_name]
        required = _required_qty(row)
        total = flt(sum(flt(q) for q in batches.values()), QTY_PRECISION)
        if total - required > QTY_TOLERANCE:
            frappe.throw(
                _("Row {0} ({1}): {2} allocated but only {3} is required.").format(
                    row.idx, frappe.bold(row.item_code), total, required
                )
            )
        for batch_no, qty in sorted(batches.items()):
            batch_item = frappe.db.get_value("Batch", batch_no, "item")
            if batch_item != row.item_code:
                frappe.throw(
                    _("Row {0}: Batch {1} does not belong to Item {2}.").format(
                        row.idx, frappe.bold(batch_no), frappe.bold(row.item_code)
                    )
                )
            available = _available_qty(row.item_code, batch_no, row.warehouse, posting)
            if flt(qty) - available > QTY_TOLERANCE:
                warnings.append(
                    _(
                        "Row {0}: Batch {1} now shows {2} in {3}, less than the {4} allocated. "
                        "The Delivery Note will not submit until this is resolved."
                    ).format(
                        row.idx,
                        batch_no,
                        flt(available, QTY_PRECISION),
                        row.warehouse,
                        flt(qty, QTY_PRECISION),
                    )
                )

    linked, partial, cleared_count = 0, 0, 0
    for row in doc.get("items") or []:
        if not _row_is_scannable(items.get(row.item_code) or {}):
            continue

        batches = working.get(row.name) or {}
        if not batches:
            if row.name in cleared and _clear_row_bundle(doc, row):
                cleared_count += 1
            continue

        bundle_name = _sync_bundle(doc, row, batches, posting)
        required = _required_qty(row)
        total = flt(sum(flt(q) for q in batches.values()), QTY_PRECISION)

        if required - total <= QTY_TOLERANCE:
            _link_bundle_to_row(row, bundle_name, batches)
            linked += 1
        else:
            _unlink_bundle_from_row(doc, row)
            partial += 1

    status = _derive_status(_build_rows(doc, working, posting))
    if status == STATUS_FULL and warnings:
        # The allocation is complete but will not submit as it stands. Fully Scanned
        # is a one-way door — the Delivery Note leaves the picker and every endpoint
        # refuses it — so a note the code has just reported as unshippable is held at
        # Partially Scanned, where the storekeeper can still re-scan the line.
        status = STATUS_PARTIAL
    _set_scan_status(doc.name, status)

    doc.reload()
    payload = _state_payload(doc, working, posting)
    payload["posted"] = {
        "status": status,
        "linked_rows": linked,
        "partial_rows": partial,
        "cleared_rows": cleared_count,
        "warnings": warnings,
    }
    return payload


# ---------------------------------------------------------------------------
# Serial and Batch Bundle writes
# ---------------------------------------------------------------------------


def _owned_bundles(delivery_note: str, row_names: list) -> dict:
    """``{row_name: bundle name}`` for the bundles *this dialog* wrote.

    Ownership is the whole point. A Delivery Note line routinely already carries a
    draft bundle that ERPNext or a Pick List built — every draft on the uploaded
    site database does — and adopting one would mean the first scan silently wiped a
    complete allocation nobody asked to change. So only bundles stamped with
    ``custom_isnack_dn_scan`` are ever read back, rewritten or deleted here;
    everything else is display-only (see :func:`_linked_bundle_batches`).

    A line can still end up with more than one stamped bundle if an earlier version
    left debris, so the choice is made deterministically — whichever the row points
    at, else the oldest — and never by summing them.
    """
    if not row_names or not _has_bundle_owner_field():
        return {}

    rows = frappe.get_all(
        "Serial and Batch Bundle",
        filters={
            "voucher_type": "Delivery Note",
            "voucher_no": delivery_note,
            "voucher_detail_no": ("in", row_names),
            "docstatus": 0,
            "is_cancelled": 0,
            BUNDLE_OWNER_FIELD: 1,
        },
        fields=["name", "voucher_detail_no"],
        order_by="creation asc",
    )

    candidates: dict = {}
    for row in rows:
        candidates.setdefault(row.voucher_detail_no, []).append(row.name)
    return candidates


def _find_row_bundle(delivery_note: str, row_name: str, linked: str | None = None):
    """The one bundle this dialog owns for a line, linked from the row or not.

    Reused rather than replaced on every Post: re-allocating by creating a second
    bundle is what left the orphaned drafts already visible on site. Returns None
    when the dialog has never written one for this line — a bundle it did not write
    is never adopted.
    """
    names = _owned_bundles(delivery_note, [row_name]).get(row_name) or []
    if not names:
        return None
    if linked and linked in names:
        return linked
    return names[0]


def _sync_bundle(doc, row, batches: dict, posting: dict) -> str:
    """Create or rewrite the draft outward bundle holding a line's scanned batches.

    Quantities are written positive; ``SerialandBatchBundle.set_is_outward`` flips
    them negative on save, which is the sign the stock ledger expects. The warehouse
    is stamped on every entry because ERPNext's availability validation at submit
    reads it there.
    """
    entries = [
        {"batch_no": batch_no, "qty": flt(qty, QTY_PRECISION), "warehouse": row.warehouse}
        for batch_no, qty in sorted(batches.items())
    ]

    bundle_name = _find_row_bundle(doc.name, row.name, row.get("serial_and_batch_bundle"))
    if bundle_name:
        bundle = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        bundle.set("entries", [])
        for entry in entries:
            bundle.append("entries", entry)
        bundle.item_code = row.item_code
        bundle.company = doc.company
        bundle.warehouse = row.warehouse
        bundle.voucher_detail_no = row.name
        bundle.type_of_transaction = "Outward"
        bundle.update(posting["bundle_fields"])
        bundle.flags.ignore_permissions = True
        bundle.save()
        return bundle.name

    payload = {
        "doctype": "Serial and Batch Bundle",
        "company": doc.company,
        "item_code": row.item_code,
        "warehouse": row.warehouse,
        "voucher_type": "Delivery Note",
        "voucher_no": doc.name,
        "voucher_detail_no": row.name,
        "type_of_transaction": "Outward",
        "entries": entries,
        # Stamps this bundle as the dialog's own; nothing else is ever rewritten
        # or deleted by it.
        BUNDLE_OWNER_FIELD: 1,
    }
    payload.update(posting["bundle_fields"])

    # Captured before the line is touched, so a later Clear can undo it exactly.
    if _has_restore_field():
        payload[BUNDLE_RESTORE_FIELD] = frappe.as_json(_row_snapshot(row))

    bundle = frappe.get_doc(payload)
    bundle.flags.ignore_permissions = True
    bundle.insert()
    return bundle.name


def _link_bundle_to_row(row, bundle_name: str, batches: dict) -> None:
    """Point a fully allocated line at its bundle.

    ``use_serial_batch_fields`` has to be off, and a *multi-batch* allocation has
    to clear ``batch_no``: ERPNext refuses a row carrying both a bundle and a
    conflicting legacy batch (``validate_serial_nos_and_batches_with_bundle``).
    When one batch covers the line it is left on the row instead, which keeps the
    Delivery Note form's own scanner matching that row by batch rather than
    treating a blank one as "any batch will do".

    ``has_item_scanned`` is set for the same reason: ERPNext's BarcodeScanner
    excludes an already-scanned row from its matcher, so a line this dialog owns
    can no longer be picked up and re-quantified from the Delivery Note form.
    """
    single_batch = next(iter(batches)) if len(batches) == 1 else ""
    frappe.db.set_value(
        "Delivery Note Item",
        row.name,
        {
            "serial_and_batch_bundle": bundle_name,
            "use_serial_batch_fields": 0,
            # Blanked to the empty string rather than NULL, matching every
            # bundle-backed row already on site.
            "batch_no": single_batch,
            "has_item_scanned": 1,
        },
    )


def _unlink_bundle_from_row(doc, row) -> None:
    """Leave a partly scanned line without a bundle link.

    A bundle that does not cover the whole line would fail
    ``SerialandBatchBundle.validate_quantity`` on the next save of the Delivery
    Note, so the work is parked in the unlinked bundle instead.

    Only a bundle this dialog owns is ever detached. Nulling a foreign one would
    strip a pre-existing allocation off the row and leave it with neither a batch
    nor a bundle, which the app's own Delivery Note pallet validator then rejects
    on every later save.
    """
    linked = row.get("serial_and_batch_bundle")
    if not linked:
        return
    if linked not in (_owned_bundles(doc.name, [row.name]).get(row.name) or []):
        return
    _restore_row(row, _restore_point(linked))
    frappe.db.set_value("Delivery Note Item", row.name, "serial_and_batch_bundle", None)


def _clear_row_bundle(doc, row) -> bool:
    """Drop this dialog's own bundle for a line the storekeeper cleared.

    Only a stamped bundle is ever deleted, and without ``force``: frappe's link
    checks still run, so a bundle something else has come to reference is refused
    rather than silently removed.
    """
    bundle_name = _find_row_bundle(doc.name, row.name, row.get("serial_and_batch_bundle"))
    if not bundle_name:
        return False
    restore = _restore_point(bundle_name)
    if row.get("serial_and_batch_bundle") == bundle_name:
        frappe.db.set_value("Delivery Note Item", row.name, "serial_and_batch_bundle", None)
    _restore_row(row, restore)
    frappe.delete_doc("Serial and Batch Bundle", bundle_name, ignore_permissions=True)
    return True


def _row_snapshot(row) -> dict:
    """The row fields this dialog is about to overwrite, as they are now.

    ``batch_no`` is kept verbatim because the column is nullable and the site
    distinguishes NULL from the empty string; the two flags are coerced, since their
    columns are NOT NULL and restoring a None would fail the write.
    """
    return {
        "batch_no": row.get("batch_no"),
        "use_serial_batch_fields": cint(row.get("use_serial_batch_fields")),
        "has_item_scanned": cint(row.get("has_item_scanned")),
    }


def _restore_point(bundle_name: str) -> dict:
    """What the line looked like before the dialog took it over, if recorded."""
    if not _has_restore_field():
        return {}
    raw = frappe.db.get_value(
        "Serial and Batch Bundle", bundle_name, BUNDLE_RESTORE_FIELD
    )
    if not raw:
        return {}
    try:
        snapshot = frappe.parse_json(raw)
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    return {k: v for k, v in snapshot.items() if k in ROW_RESTORE_FIELDS}


def _restore_row(row, snapshot: dict) -> None:
    """Put back the fields the dialog overwrote when it linked the bundle.

    Without this a Clear leaves the line with neither the batch it arrived with
    nor a bundle, which is worse than never having scanned it.
    """
    if not snapshot:
        return
    frappe.db.set_value("Delivery Note Item", row.name, snapshot)


def _set_scan_status(delivery_note: str, status: str) -> None:
    if not frappe.get_meta("Delivery Note").has_field(SCAN_STATUS_FIELD):
        return
    frappe.db.set_value("Delivery Note", delivery_note, SCAN_STATUS_FIELD, status)
