# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A QC record kept in the layout it was made in.

When fields come off a QC record (the Packaging Check's film and material
reconciliation, the Weight Check's TU limits, tare and overall status, both in
2026-11), the records made before keep what they recorded, in an Earlier
Layout section shown when their hidden ``earlier_layout`` mark is set. A patch
sets the mark (``mark_records``, ``mark_deleted_documents``); Amend carries it;
nothing clears it.
"""

import json

import frappe
from frappe.utils import cint


def in_earlier_layout(doc) -> bool:
    """Whether ``doc`` keeps the earlier layout. Until the migrate adds the
    mark, every record is one made before."""
    if not doc.meta.has_field("earlier_layout"):
        return True
    return bool(cint(doc.get("earlier_layout")))


def keep_mark(doc):
    """A form loaded before the migrate does not know the mark and sends none:
    keep the one the saved record, or the record amended, has."""
    if doc.get("earlier_layout") or not doc.meta.has_field("earlier_layout"):
        return
    if doc.is_new():
        kept = doc.amended_from and frappe.db.get_value(doc.doctype, doc.amended_from, "earlier_layout")
    else:
        before = doc.get_doc_before_save()
        kept = before and before.get("earlier_layout")
    if cint(kept):
        doc.earlier_layout = 1


def mark_records(doctype, names):
    """Mark ``names`` of ``doctype``. A plain update leaves their ``modified``
    (and so their version history) alone."""
    if names:
        frappe.db.sql(
            f"update `tab{doctype}` set earlier_layout = 1 where name in %(names)s", {"names": tuple(names)}
        )


def mark_deleted_documents(doctype, belongs):
    """Mark the records of ``doctype`` deleted before, whose snapshot
    ``belongs`` (a function of the snapshot's data) to the earlier layout, so a
    restore brings them back as they were."""
    for deleted in frappe.get_all(
        "Deleted Document", filters={"deleted_doctype": doctype, "restored": 0}, fields=["name", "data"]
    ):
        data = json.loads(deleted.data)
        if belongs(data):
            data["earlier_layout"] = 1
            frappe.db.set_value("Deleted Document", deleted.name, "data", frappe.as_json(data), update_modified=False)
