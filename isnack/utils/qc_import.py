# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""QC records entered with Data Import (2026-11): what an import must give.

Records kept on paper are entered in bulk with Frappe's Data Import, which
gives a record what its file holds. ``check_import``, a ``before_validate`` of
every QC record type (doc_events), refuses what would otherwise be recorded
wrong without a word:

- a reading's Time Slot, or a test's Test Time, left blank or its column left
  out: Frappe makes each row an import brings with its defaults, which give a
  Time the time of import (``frappe.model.create_new``);
- a tasting score above 1: Frappe keeps a Rating as the fraction of the stars
  given (4 of 5 stars is 0.8) and takes more than 1 as full marks, so stars
  given as a count would all read as full marks;
- a field taken off the record type in 2026-11, given to a record not marked
  Earlier Layout: the record type refuses it however it is saved, saying "This
  page is out of date", which an import has no page for: here it is named;
- a QC Receiving Record of a delivery (Purchase Receipt, Item Code, Batch No)
  that has one already: an import run again, or after deliveries were
  recorded by hand, would record it twice.

Only in an import (``frappe.flags.in_import``), and only on what it brings in:
a new record, or the new rows of a record it updates.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, escape_html, flt

from isnack.isnack.doctype.qc_metal_detector_log import qc_metal_detector_log
from isnack.isnack.doctype.qc_packaging_check import qc_packaging_check
from isnack.isnack.doctype.qc_weight_check import qc_weight_check
from isnack.utils import earlier_layout

# frappe.utils.nowtime(), which an import gives a new row's Time: a time read
# from a file has no millionths of a second (a CSV's as typed, an XLSX cell's to
# the second)
_TIME_OF_IMPORT = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{6}")


def check_import(doc, method=None):
    """``before_validate`` of the QC record types (doc_events), in a Data Import."""
    if not frappe.flags.in_import or doc.flags.ignore_validate:
        return
    new = bool(doc.flags.in_insert or doc.is_new())
    # (a row a record keeps may hold the time it was saved at: only new rows)
    require_times(doc, [row for row in doc.get_all_children() if new or row.get("__islocal")])
    # (an import updating a record gives it the rows of its file)
    check_ratings(doc, [doc, *doc.get_all_children()])
    if doc.get("amended_from"):
        # an amendment keeps the layout of the record it amends (earlier_layout)
        return
    refuse_retired_values(doc)
    if new and doc.doctype == "QC Receiving Record":
        refuse_a_second_record(doc)


def require_times(doc, rows):
    """A Time left blank on a row the import made reads as the time of import,
    which Frappe gave it: refused, as the paper gives each reading its time."""
    for row in rows:
        for df in row.meta.get("fields", {"fieldtype": "Time"}):
            value = row.get(df.fieldname)
            if isinstance(value, str) and _TIME_OF_IMPORT.fullmatch(value.strip()):
                missing = [
                    str(other.idx)
                    for other in rows
                    if other.parentfield == row.parentfield
                    and isinstance(other.get(df.fieldname), str)
                    and _TIME_OF_IMPORT.fullmatch(other.get(df.fieldname).strip())
                ]
                frappe.throw(
                    _("{0} is required in {1} (row {2}).").format(
                        _(df.label), _(doc.meta.get_label(row.parentfield)), ", ".join(missing)
                    ),
                    title=_("Missing Value"),
                )


def check_ratings(doc, holders):
    """A Rating (a tasting score) outside 0 to 1: stars given as a count.
    Frappe keeps a Rating as the fraction of the stars given (4 of 5 stars is
    0.8) and takes more than 1 as full marks. A whole number is not read as
    stars: 1 would still be full marks, and the paper may score otherwise (1
    the best of 4)."""
    for holder in holders:
        for df in holder.meta.get("fields", {"fieldtype": "Rating"}):
            value = flt(holder.get(df.fieldname))
            if 0 <= value <= 1:
                continue
            stars = cint(df.options) or 5
            where = _(df.label)
            if holder is not doc:
                where = _("{0} in {1} (row {2})").format(where, _(doc.meta.get_label(holder.parentfield)), holder.idx)
            frappe.throw(
                _("{0} is {1}: an import gives a score as the fraction of the {2} stars given (1 star is {3}, {2} stars are 1).").format(
                    where, escape_html(cstr(holder.get(df.fieldname))), stars, f"{1 / stars:g}"
                ),
                title=_("Score"),
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
                    label = _("{0} in {1} (row {2})").format(label, _(doc.meta.get_label(table)), holder.idx)
                given.append(label)
    if given:
        frappe.throw(
            _("{0}: not recorded on a record made since 2026-11. Leave them blank, or, for a record from before, set {1} to 1.").format(
                ", ".join(given), _(doc.meta.get_label("earlier_layout"))
            ),
            title=_("Not Recorded Since 2026-11"),
        )


def refuse_a_second_record(doc):
    """A delivery (its Purchase Receipt, Item Code and Batch No) has one QC
    Receiving Record: an import does not record it again, whether an earlier
    import or someone in the Quality Hub recorded it. A cancelled record does
    not count."""
    if not (doc.get("purchase_receipt") and doc.get("item_code")):
        return
    batch = cstr(doc.get("batch_no")).strip()
    filters = {
        "purchase_receipt": doc.purchase_receipt,
        "item_code": doc.item_code,
        "batch_no": batch or ["is", "not set"],
        "docstatus": ["<", 2],
    }
    if doc.name:
        filters["name"] = ["!=", doc.name]
    recorded = frappe.get_all("QC Receiving Record", filters=filters, pluck="name", order_by="name asc", limit=1)
    if recorded:
        delivery = ", ".join(filter(None, (doc.purchase_receipt, doc.item_code, batch and _("batch {0}").format(batch))))
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
