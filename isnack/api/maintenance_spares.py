"""Spare-part planning & consumption for maintenance logs.

Stock movements are never created silently: ``create_material_request`` and
``create_material_issue`` build **draft** documents and return their names for
the user to review and submit in ERPNext.
"""

import frappe
from frappe import _

from isnack.utils.maintenance import ensure_log_access, is_manager


def _log_asset_company(log):
    asset = frappe.db.get_value("Asset Maintenance Log", log, "asset_name")
    company = frappe.db.get_value("Asset", asset, "company") if asset else None
    return asset, company


@frappe.whitelist()
def add_spare_part(asset_maintenance_log, item_code, part_type="Required",
                   required_qty=0, consumed_qty=0, source_warehouse=None):
    ensure_log_access(asset_maintenance_log, write=True)
    asset, _company = _log_asset_company(asset_maintenance_log)
    doc = frappe.get_doc({
        "doctype": "Maintenance Spare Part",
        "asset_maintenance_log": asset_maintenance_log,
        "asset": asset,
        "part_type": part_type,
        "item_code": item_code,
        "required_qty": frappe.utils.flt(required_qty),
        "consumed_qty": frappe.utils.flt(consumed_qty),
        "source_warehouse": source_warehouse,
        "status": "Consumed" if part_type == "Consumed" else "Required",
    })
    doc.insert(ignore_permissions=True)
    return {"ok": True, "name": doc.name, "available_qty": doc.available_qty}


@frappe.whitelist()
def delete_spare_part(name):
    log = frappe.db.get_value("Maintenance Spare Part", name, "asset_maintenance_log")
    if not log:
        frappe.throw(_("Spare part not found."))
    ensure_log_access(log, write=True)
    frappe.delete_doc("Maintenance Spare Part", name, ignore_permissions=True)
    return {"ok": True}


@frappe.whitelist()
def create_material_request(asset_maintenance_log):
    """Create a DRAFT Material Request for required parts that are short on stock.

    Returns the draft name; the user reviews and submits it in ERPNext."""
    ensure_log_access(asset_maintenance_log, write=True)
    asset, company = _log_asset_company(asset_maintenance_log)

    parts = frappe.get_all(
        "Maintenance Spare Part",
        filters={"asset_maintenance_log": asset_maintenance_log,
                 "part_type": "Required",
                 "status": ["in", ["Required", "Requested"]]},
        fields=["name", "item_code", "required_qty", "available_qty"],
    )
    short = [p for p in parts if (p.required_qty or 0) > (p.available_qty or 0)]
    if not short:
        return {"ok": False, "message": _("No required parts are short on stock.")}

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Transfer"
    if company:
        mr.company = company
    for p in short:
        qty = (p.required_qty or 0) - (p.available_qty or 0)
        mr.append("items", {
            "item_code": p.item_code,
            "qty": qty,
            "schedule_date": frappe.utils.add_days(frappe.utils.nowdate(), 1),
        })
    mr.insert(ignore_permissions=True)

    for p in short:
        frappe.db.set_value("Maintenance Spare Part", p.name,
                            {"material_request": mr.name, "status": "Requested"})
    return {"ok": True, "material_request": mr.name,
            "url": f"/app/material-request/{mr.name}"}


@frappe.whitelist()
def create_material_issue(asset_maintenance_log):
    """Create a DRAFT Stock Entry (Material Issue) for consumed spare parts.

    Returns the draft name. The user reviews and submits it in ERPNext, so no
    stock transaction happens without confirmation."""
    ensure_log_access(asset_maintenance_log, write=True)
    asset, company = _log_asset_company(asset_maintenance_log)

    parts = frappe.get_all(
        "Maintenance Spare Part",
        filters={"asset_maintenance_log": asset_maintenance_log,
                 "part_type": "Consumed",
                 "consumed_qty": [">", 0],
                 "stock_entry": ["in", ["", None]]},
        fields=["name", "item_code", "consumed_qty", "source_warehouse"],
    )
    if not parts:
        return {"ok": False, "message": _("No consumed parts to issue.")}

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    if company:
        se.company = company
    for p in parts:
        row = {"item_code": p.item_code, "qty": p.consumed_qty}
        if p.source_warehouse:
            row["s_warehouse"] = p.source_warehouse
        se.append("items", row)
    se.insert(ignore_permissions=True)

    for p in parts:
        frappe.db.set_value("Maintenance Spare Part", p.name,
                            "stock_entry", se.name)
    return {"ok": True, "stock_entry": se.name,
            "url": f"/app/stock-entry/{se.name}"}
