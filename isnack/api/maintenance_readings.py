"""Maintenance reading capture."""

import frappe
from frappe import _

from isnack.utils.maintenance import ensure_log_access


@frappe.whitelist()
def add_reading(asset_maintenance_log, reading_type, reading_value, uom=None,
                min_value=None, max_value=None, comments=None):
    """Record a reading against a maintenance log. Flags out-of-range values.

    Out-of-range readings are flagged only (no automatic breakdown is created —
    a technician/manager raises one explicitly if needed)."""
    ensure_log_access(asset_maintenance_log, write=True)
    asset = frappe.db.get_value("Asset Maintenance Log", asset_maintenance_log,
                                "asset_name")
    doc = frappe.get_doc({
        "doctype": "Maintenance Reading",
        "asset_maintenance_log": asset_maintenance_log,
        "asset": asset,
        "reading_type": reading_type,
        "reading_value": frappe.utils.flt(reading_value),
        "uom": uom,
        "min_value": frappe.utils.flt(min_value) if min_value not in (None, "") else None,
        "max_value": frappe.utils.flt(max_value) if max_value not in (None, "") else None,
        "comments": comments,
    })
    doc.insert(ignore_permissions=True)
    return {"ok": True, "name": doc.name, "is_out_of_range": doc.is_out_of_range}


@frappe.whitelist()
def delete_reading(name):
    log = frappe.db.get_value("Maintenance Reading", name, "asset_maintenance_log")
    if not log:
        frappe.throw(_("Reading not found."))
    ensure_log_access(log, write=True)
    frappe.delete_doc("Maintenance Reading", name, ignore_permissions=True)
    return {"ok": True}
