# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

# The Quality Hub tabs whose Factory Line the settings restrict (2026-11): each
# settings field and the record types it is for. The Packaging and Weight tab
# records both its checks in one form, which asks for the line once. Receiving
# (QCA) has no factory line; the Oven Record (QCE) is retired.
TAB_FIELDS = {
    "puffs_extruder_lines": ("QC Puffs Extruder Record",),
    "rice_extruder_lines": ("QC Rice Extruder Record",),
    "frying_line_lines": ("QC Frying Line Record",),
    "tasting_lines": ("QC Tasting Record",),
    "packaging_and_weight_lines": ("QC Packaging Check", "QC Weight Check"),
    "metal_detector_lines": ("QC Metal Detector Log",),
}

# Every record type a tab's lines apply to, each once.
RESTRICTED_DOCTYPES = tuple(doctype for doctypes in TAB_FIELDS.values() for doctype in doctypes)

# The production lines each packing line packs for (2026-11): a Work Order is
# planned on the line that makes its product (its BOM's default line), never on
# a packing line, so a check on a packing line offers the Work Orders of the
# lines it packs for as well as its own.
PACKING_FIELD = "packing_lines"


class QualityHubSettings(Document):
    def validate(self):
        # each line once in a tab (the field shows it once)
        for fieldname in TAB_FIELDS:
            seen = set()
            rows = []
            for row in self.get(fieldname) or []:
                key = cstr(row.factory_line).strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    rows.append(row)
            for idx, row in enumerate(rows, 1):
                row.idx = idx
            self.set(fieldname, rows)
        # each packing line and a line it packs for once; a packing line packs
        # for itself already (a row missing either is left to the mandatory check)
        seen = set()
        rows = []
        for row in self.get(PACKING_FIELD) or []:
            key = (_key(row.packing_line), _key(row.production_line))
            if all(key) and (key[0] == key[1] or key in seen):
                continue
            seen.add(key)
            rows.append(row)
        for idx, row in enumerate(rows, 1):
            row.idx = idx
        self.set(PACKING_FIELD, rows)


def tab_field(doctype):
    """The settings field of the tab ``doctype`` is recorded in; None when its
    factory line is not restricted."""
    return next((fieldname for fieldname, doctypes in TAB_FIELDS.items() if doctype in doctypes), None)


def factory_lines(doctype) -> list[str]:
    """The factory lines records of ``doctype`` may be on: those Quality Hub
    Settings gives their tab, each once. An empty list when it gives none:
    any line."""
    fieldname = tab_field(doctype)
    if not fieldname:
        return []
    # the code before the migrate that makes the settings: Frappe has no
    # controller to read them with yet (ImportError)
    if not frappe.db.exists("DocType", "Quality Hub Settings", cache=True):
        return []
    lines, seen = [], set()
    # a line listed twice is read once: merging a listed line into another
    # (Rename, "Merge with existing") rewrites the rows without validate
    for row in frappe.get_cached_doc("Quality Hub Settings").get(fieldname) or []:
        key = cstr(row.factory_line).strip().casefold()
        if key and key not in seen:
            seen.add(key)
            lines.append(row.factory_line)
    return lines


@frappe.whitelist()
def get_factory_lines() -> dict[str, list[str]]:
    """The factory lines each restricted record type may be on, by doctype (an
    empty list: any line). The Quality Hub's dialogs and the records' forms
    offer only those."""
    return {doctype: factory_lines(doctype) for doctype in RESTRICTED_DOCTYPES}


def packing_lines() -> dict[str, list[str]]:
    """The production lines each packing line packs for, by packing line, each
    once (Quality Hub Settings' Packing Lines). Empty before the migrate that
    makes the settings, or the table."""
    if not frappe.db.exists("DocType", "Quality Hub Settings", cache=True):
        return {}
    packs_for, names, seen = {}, {}, set()
    # rows Rename's "Merge with existing" rewrote without validate: read once
    for row in frappe.get_cached_doc("Quality Hub Settings").get(PACKING_FIELD) or []:
        key = (_key(row.packing_line), _key(row.production_line))
        if not all(key) or key[0] == key[1] or key in seen:
            continue
        seen.add(key)
        packing_line = names.setdefault(key[0], cstr(row.packing_line).strip())
        packs_for.setdefault(packing_line, []).append(cstr(row.production_line).strip())
    return packs_for


@frappe.whitelist()
def get_packing_lines() -> dict[str, list[str]]:
    """The production lines each packing line packs for: a record on a packing
    line offers their Work Orders as well as its own, on the Quality Hub's
    dialogs and on the records' forms."""
    return packing_lines()


@frappe.whitelist()
def get_work_order_details(work_order: str) -> dict:
    """The line a Work Order is planned on and the item it makes, for the Quality
    Hub's dialogs and the records' forms: a Work Order the record's line does
    not offer is taken off, and its item fills in a Process record's Product
    Item. Whoever may pick the Work Order may know both: its search lists its
    item. Nothing for a Work Order there is not, or that the user may not pick."""
    if not work_order or not frappe.db.exists("Work Order", work_order):
        return {}
    doc = frappe.get_doc("Work Order", work_order)
    if not (frappe.has_permission("Work Order", "select", doc=doc) or frappe.has_permission("Work Order", "read", doc=doc)):
        return {}
    return {"factory_line": doc.get("custom_factory_line"), "production_item": doc.production_item}


def check_factory_line(doc, method=None):
    """``validate`` of the restricted QC records (doc_events): the Factory Line
    is one Quality Hub Settings gives the record's tab. The Quality Hub and the
    forms offer only those, but a Link takes any line typed in full. An
    amendment keeps the line of the record it amends: the tab may have left it
    since."""
    line = doc.get("factory_line")
    allowed = factory_lines(doc.doctype)
    if not (line and allowed):
        return
    if any(_same(line, other) for other in allowed):
        return
    if doc.get("amended_from") and _same(frappe.db.get_value(doc.doctype, doc.amended_from, "factory_line"), line):
        return
    tab = frappe.get_meta("Quality Hub Settings").get_label(tab_field(doc.doctype))
    frappe.throw(
        _("{0} is not one of the factory lines Quality Hub Settings gives {1}: {2}.").format(
            frappe.bold(line), frappe.bold(_(tab)), ", ".join(frappe.bold(other) for other in allowed)
        ),
        title=_("Factory Line not allowed"),
    )


def _same(one, other) -> bool:
    """The same factory line, case and surrounding spaces aside (as the database
    matches a link)."""
    return _key(one) == _key(other)


def _key(line) -> str:
    """A factory line as the database matches a link: case and surrounding
    spaces aside."""
    return cstr(line).strip().casefold()
