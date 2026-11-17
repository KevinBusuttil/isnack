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


def tab_field(doctype):
    """The settings field of the tab ``doctype`` is recorded in; None when its
    factory line is not restricted."""
    return next((fieldname for fieldname, doctypes in TAB_FIELDS.items() if doctype in doctypes), None)


def factory_lines(doctype) -> list[str]:
    """The factory lines records of ``doctype`` may be on: those Quality Hub
    Settings gives their tab. An empty list when it gives none: any line."""
    fieldname = tab_field(doctype)
    if not fieldname:
        return []
    try:
        settings = frappe.get_cached_doc("Quality Hub Settings")
    except frappe.DoesNotExistError:
        # the code before the migrate that makes the settings
        return []
    return [row.factory_line for row in settings.get(fieldname) or [] if row.factory_line]


@frappe.whitelist()
def get_factory_lines() -> dict[str, list[str]]:
    """The factory lines each restricted record type may be on, by doctype (an
    empty list: any line). The Quality Hub's dialogs and the records' forms
    offer only those."""
    return {doctype: factory_lines(doctype) for doctype in RESTRICTED_DOCTYPES}


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
    return cstr(one).strip().casefold() == cstr(other).strip().casefold()
