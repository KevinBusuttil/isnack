"""Backfill custom_operational_status on existing Asset Maintenance Logs.

Maps ERPNext's standard maintenance_status to a sensible operational status so
that pre-existing logs surface correctly in the Maintenance Hub. Idempotent:
only fills logs whose operational status is still empty.
"""

import frappe
from frappe.utils import getdate, nowdate


def execute():
    if not frappe.db.exists("DocType", "Asset Maintenance Log"):
        return
    if not frappe.db.has_column("Asset Maintenance Log", "custom_operational_status"):
        return

    logs = frappe.get_all(
        "Asset Maintenance Log",
        filters=[["custom_operational_status", "in", ["", None]]],
        fields=["name", "maintenance_status", "due_date", "custom_assigned_technician"],
    )

    for log in logs:
        status = _derive(log)
        frappe.db.set_value(
            "Asset Maintenance Log", log.name,
            "custom_operational_status", status, update_modified=False,
        )
    frappe.db.commit()


def _derive(log):
    std = (log.get("maintenance_status") or "").strip()
    if std == "Completed":
        return "Completed"
    if std == "Cancelled":
        return "Cancelled"
    due = log.get("due_date")
    if due and getdate(due) < getdate(nowdate()):
        return "Overdue"
    if log.get("custom_assigned_technician"):
        return "Assigned"
    return "Planned"
