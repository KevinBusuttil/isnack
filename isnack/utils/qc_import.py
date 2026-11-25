# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""QC records entered with Data Import (2026-11): what an import must give.

Records kept on paper are entered in bulk with Frappe's Data Import, which
gives a record what its file holds. ``check_import``, a ``before_validate`` of
every QC record type (doc_events), refuses what would otherwise be recorded
wrong without a word:

- a reading's Time Slot, or a test's Test Time, left blank or its column left
  out: Frappe makes each row an import brings with its defaults, which give a
  Time the time of import (``frappe.model.create_new``); and one given in
  another form than hh:mm (8.30, 0830), which the database reads as seconds;
- a tasting score that is not a number from 0 to 1: Frappe keeps a Rating as
  the fraction of the stars given (4 of 5 stars is 0.8), takes more than 1 as
  full marks and text (4/5, 80%) as none, so stars given as a count would all
  read as full marks, and scores written as text as no stars;
- a field taken off the record type in 2026-11, given to a record not marked
  Earlier Layout: the record type refuses it however it is saved, saying "This
  page is out of date", which an import has no page for: here it is named;
- a tasting row's Overall (stars, before 2026-11), on a record made since: the
  result comes from the five scores, so a sheet giving only the overall would
  read as a Fail;
- a QC Receiving Record of a delivery (Purchase Receipt, Item Code, Batch No)
  that has one already: an import run again, or after deliveries were
  recorded by hand, would record it twice; and one whose Supplier, Item Code
  or Batch No is not the Purchase Receipt's, as the Quality Hub's pickers
  would not offer them.

Only in an import (``frappe.flags.in_import``): whether a time was left blank,
on the rows it makes (a new record's, or the new rows of a record it updates);
the rest on the record as the import leaves it. A row is named by its place in
the record's table ("this record's row 2"), not by the file's line, which the
Import Log gives.
"""

import datetime
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, escape_html, now_datetime

from isnack.isnack.doctype.qc_metal_detector_log import qc_metal_detector_log
from isnack.isnack.doctype.qc_packaging_check import qc_packaging_check
from isnack.isnack.doctype.qc_weight_check import qc_weight_check
from isnack.utils import earlier_layout

# frappe.utils.nowtime(), which an import gives a new row's Time it is not
# given, when it reads the file: a time of this form, to the millionth of a
# second, from the last hours, is the import's own
_TIME_OF_IMPORT = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{6}")
_AN_IMPORT_TAKES = datetime.timedelta(hours=2)

# a time as a file gives it (a CSV's as typed, an XLSX cell's as read): h:mm,
# hh:mm:ss, hh:mm:ss.f
_A_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?")


def check_import(doc, method=None):
    """``before_validate`` of the QC record types (doc_events), in a Data Import."""
    if not frappe.flags.in_import or doc.flags.ignore_validate:
        return
    new = bool(doc.flags.in_insert or doc.is_new())
    # (an import updating a record gives it the rows of its file; a row it
    # keeps may hold the time it was saved at, so only a new row's is the import's)
    check_times(doc, doc.get_all_children(), new=new)
    check_ratings(doc, [doc, *doc.get_all_children()])
    if doc.get("amended_from"):
        # an amendment keeps the layout of the record it amends (earlier_layout)
        return
    refuse_retired_values(doc)
    if new and doc.doctype == "QC Tasting Record":
        refuse_the_overall_stars(doc)
    if new and doc.doctype == "QC Receiving Record":
        refuse_a_delivery_not_on_its_receipt(doc)
        refuse_a_second_record(doc)


def check_times(doc, rows, new=True):
    """The Times an import gives a record's rows. Left blank on a row the import
    made (a new record's, or a new row of one it updates), a Time holds the time
    of import, which Frappe gave it: refused as missing, as the paper gives each
    reading its time; so is one holding only a space (an XLSX cell). Given in
    another form than hh:mm (8.30, 0830, 8:30 PM), the database would read it
    as seconds, or refuse it in its own words: refused, naming the value, on
    every row (a row an import keeps holds a time from the database, not text,
    unless the file gives it one)."""
    now = now_datetime()
    missing = {}
    for row in rows:
        made = new or bool(row.get("__islocal"))
        for df in row.meta.get("fields", {"fieldtype": "Time"}):
            value = row.get(df.fieldname)
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or (made and _TIME_OF_IMPORT.fullmatch(text) and _of_this_import(text, now)):
                missing.setdefault(df.label, {}).setdefault(row.parentfield, []).append(str(row.idx))
            elif not _is_a_time(text):
                frappe.throw(
                    _("{0} in {1} is {2}: give a time as hh:mm, as 08:30.").format(
                        _(df.label), _where(doc, row.parentfield, [row.idx]), escape_html(value)
                    ),
                    title=_("Time"),
                )
    if missing:
        frappe.throw(
            " ".join(
                _("{0} is required in {1}.").format(
                    _(label), _(" and in ").join(_where(doc, table, idxs) for table, idxs in tables.items())
                )
                for label, tables in missing.items()
            ),
            title=_("Missing Value"),
        )


def _of_this_import(text, now) -> bool:
    """Whether a time to the millionth of a second is the import's own: within
    the time an import takes, before now (across midnight too)."""
    hour, minute, second = text.split(":")
    second, micro = second.split(".")
    try:
        at = now.replace(hour=int(hour), minute=int(minute), second=int(second), microsecond=int(micro))
    except ValueError:
        return False  # no time of day (25:00): not Frappe's
    if at > now + datetime.timedelta(minutes=1):
        at -= datetime.timedelta(days=1)
    return datetime.timedelta(minutes=-1) <= now - at <= _AN_IMPORT_TAKES


def _is_a_time(text) -> bool:
    match = _A_TIME.fullmatch(text)
    return bool(match) and int(match[1]) < 24 and int(match[2]) < 60 and int(match[3] or 0) < 60


def check_ratings(doc, holders):
    """A Rating (a tasting score) that is not a number from 0 to 1. Frappe
    keeps a Rating as the fraction of the stars given (4 of 5 stars is 0.8): it
    takes more than 1 as full marks, and text (4/5, 80%, 4 stars, a date Excel
    made of 4/5) as no stars. A whole number is not read as stars: 1 would
    still be full marks, and the paper may score otherwise (1 the best of 4)."""
    for holder in holders:
        for df in holder.meta.get("fields", {"fieldtype": "Rating"}):
            value = holder.get(df.fieldname)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            number = _number(value)
            if number is not None and 0 <= number <= 1:
                continue
            stars = cint(df.options) or 5
            where = _(df.label)
            if holder is not doc:
                where = _("{0} in {1}").format(where, _where(doc, holder.parentfield, [holder.idx]))
            frappe.throw(
                _("{0} is {1}: an import gives a score as a number, the fraction of the {2} stars given (1 star is {3}, {2} stars are 1).").format(
                    where, escape_html(cstr(value)), stars, f"{1 / stars:g}"
                ),
                title=_("Score"),
            )


def _number(value):
    """``value`` as a number, when it is one, or text of one; else None."""
    if isinstance(value, bool | datetime.date | datetime.time | datetime.timedelta):
        return None
    try:
        return float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None


def _where(doc, table, idxs) -> str:
    """A table's rows, by their place in the record's table: the Import Log
    gives the file's lines."""
    idxs = [str(idx) for idx in idxs]
    return (_("{0} (this record's row {1})") if len(idxs) == 1 else _("{0} (this record's rows {1})")).format(
        _(doc.meta.get_label(table)), ", ".join(idxs)
    )


def refuse_retired_values(doc):
    """A field taken off the record type in 2026-11, given to a record not
    marked Earlier Layout: named. The record type refuses it however it is
    saved, with "This page is out of date", which an import has no page for."""
    retired = _retired_fields(doc.doctype)
    if not retired or earlier_layout.in_earlier_layout(doc):
        return
    given = []
    for table, fieldnames in retired.items():
        holders = [doc] if table is None else list(doc.get(table) or [])
        for holder in holders:
            for fieldname in fieldnames:
                # (a 0, as Frappe saves a blank number, or a stray space is none)
                if not holder.get(fieldname) or not cstr(holder.get(fieldname)).strip():
                    continue
                label = _(holder.meta.get_label(fieldname))
                if holder is not doc:
                    label = _("{0} in {1}").format(label, _where(doc, table, [holder.idx]))
                given.append(label)
    if given:
        frappe.throw(
            _("{0}: not recorded on a record made since 2026-11. Leave them blank, or, for a record from before, set {1} to 1.").format(
                ", ".join(given), _(doc.meta.get_label("earlier_layout"))
            ),
            title=_("Not Recorded Since 2026-11"),
        )


def refuse_the_overall_stars(doc):
    """A tasting row's Overall (stars, before 2026-11) on a record made since:
    taken off in 2026-11, when the result came to be worked out from the five
    scores, and kept out of sight; a sheet giving only the overall would read as
    a Fail. A 0 is none (Frappe saves a blank Rating as 0)."""
    rows = [row for row in doc.get("scores") or [] if (_number(row.get("overall_score")) or 0) > 0]
    if rows:
        frappe.throw(
            _("{0} in {1}: not recorded since 2026-11, when the result came to be worked out from the five scores. Leave it blank and give each score instead.").format(
                _(rows[0].meta.get_label("overall_score")), _where(doc, "scores", [row.idx for row in rows])
            ),
            title=_("Not Recorded Since 2026-11"),
        )


def refuse_a_delivery_not_on_its_receipt(doc):
    """A QC Receiving Record checks a delivery of its Purchase Receipt: the
    receipt submitted and of its Supplier, the Item Code on it, and the Batch
    No that item's on it (on its row, or in its row's bundle or rejected
    bundle), as the Quality Hub's pickers offer them (the receipt by supplier,
    the item by receipt, the batch by receipt and item:
    quality_hub.get_batches_for_receiving). A save does not check them."""
    receipt = doc.get("purchase_receipt")
    if not receipt:
        return
    held = frappe.db.get_value("Purchase Receipt", receipt, ["supplier", "docstatus"], as_dict=True)
    if not held:
        return  # (Frappe's link check refuses it)
    item, batch = doc.get("item_code"), cstr(doc.get("batch_no")).strip()
    if held.docstatus != 1:
        wrong = _("{0} is not submitted").format(frappe.bold(receipt))
    elif doc.get("supplier") and doc.supplier != held.supplier:
        wrong = _("{0} is {1}'s, not {2}'s").format(
            frappe.bold(receipt), escape_html(held.supplier), escape_html(doc.supplier)
        )
    elif item and not frappe.db.exists("Purchase Receipt Item", {"parent": receipt, "item_code": item}):
        wrong = _("{0} is not on {1}").format(escape_html(item), frappe.bold(receipt))
    elif item and batch and not _batch_received(receipt, item, batch):
        wrong = _("batch {0} is not {1}'s on {2}").format(escape_html(batch), escape_html(item), frappe.bold(receipt))
    else:
        return
    frappe.throw(
        _("This delivery is not on its Purchase Receipt: {0}. Give the receipt's own supplier, item and batch, as the Quality Hub offers them.").format(wrong),
        title=_("Not on the Purchase Receipt"),
    )


def _batch_received(receipt, item, batch) -> bool:
    """Whether ``batch`` is ``item``'s on ``receipt``: on the receipt's row, or
    in the row's Serial and Batch Bundle, or its rejected bundle."""
    return bool(
        frappe.db.sql(
            """select 1 from `tabPurchase Receipt Item` pri
            left join `tabSerial and Batch Entry` sbe
                on sbe.parent in (pri.serial_and_batch_bundle, pri.rejected_serial_and_batch_bundle)
            where pri.parent = %(receipt)s and pri.item_code = %(item)s
                and (pri.batch_no = %(batch)s or sbe.batch_no = %(batch)s)
            limit 1""",
            {"receipt": receipt, "item": item, "batch": batch},
        )
    )


def refuse_a_second_record(doc):
    """A delivery (its Purchase Receipt, Item Code and Batch No) has one QC
    Receiving Record: an import does not record it again, whether an earlier
    import or someone in the Quality Hub recorded it. A cancelled record does
    not count. (The three are mandatory: a record without one is refused
    for it, later.)"""
    batch = cstr(doc.get("batch_no")).strip()
    if not (doc.get("purchase_receipt") and doc.get("item_code") and batch):
        return
    filters = {
        "purchase_receipt": doc.purchase_receipt,
        "item_code": doc.item_code,
        "batch_no": batch,
        "docstatus": ["<", 2],
    }
    if doc.name:
        filters["name"] = ["!=", doc.name]
    recorded = frappe.get_all("QC Receiving Record", filters=filters, pluck="name", order_by="name asc", limit=1)
    if recorded:
        delivery = ", ".join((doc.purchase_receipt, doc.item_code, _("batch {0}").format(batch)))
        frappe.throw(
            _("{0} already records this delivery ({1}): an import does not record it again.").format(
                frappe.bold(recorded[0]), escape_html(delivery)
            ),
            title=_("Already Recorded"),
        )


def _retired_fields(doctype):
    """The fields taken off ``doctype`` in 2026-11: {None (the record) or a
    table: fieldnames}."""
    return {
        "QC Packaging Check": {None: qc_packaging_check.RETIRED_FIELDS},
        "QC Weight Check": {None: qc_weight_check.RETIRED_FIELDS, "samples": qc_weight_check.RETIRED_SAMPLE_FIELDS},
        "QC Metal Detector Log": {
            None: qc_metal_detector_log.RETIRED_FIELDS,
            "tests": qc_metal_detector_log.RETIRED_TEST_FIELDS,
        },
    }.get(doctype, {})
