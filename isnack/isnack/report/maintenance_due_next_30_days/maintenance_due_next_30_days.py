"""Maintenance Due Next 30 Days — upcoming planned maintenance."""

import frappe
from frappe.utils import nowdate, add_days


def execute(filters=None):
    filters = filters or {}
    days = int(filters.get("days") or 30)
    start = nowdate()
    end = add_days(start, days)

    conditions = {
        "maintenance_status": ["in", ["Planned", "Overdue"]],
        "due_date": ["between", [start, end]],
    }
    if filters.get("assigned_technician"):
        conditions["custom_assigned_technician"] = filters["assigned_technician"]
    if filters.get("operational_status"):
        conditions["custom_operational_status"] = filters["operational_status"]

    logs = frappe.get_all(
        "Asset Maintenance Log",
        filters=conditions,
        fields=["name", "asset_name", "task", "maintenance_type", "due_date",
                "custom_operational_status", "custom_assigned_technician"],
        order_by="due_date asc",
    )

    if filters.get("company"):
        assets = set(frappe.get_all("Asset", filters={"company": filters["company"]},
                                    pluck="name"))
        logs = [l for l in logs if l.asset_name in assets]

    columns = [
        {"label": "Log", "fieldname": "name", "fieldtype": "Link",
         "options": "Asset Maintenance Log", "width": 150},
        {"label": "Asset", "fieldname": "asset_name", "fieldtype": "Link",
         "options": "Asset", "width": 140},
        {"label": "Task", "fieldname": "task", "fieldtype": "Data", "width": 180},
        {"label": "Type", "fieldname": "maintenance_type", "fieldtype": "Data",
         "width": 130},
        {"label": "Due Date", "fieldname": "due_date", "fieldtype": "Date",
         "width": 100},
        {"label": "Op Status", "fieldname": "custom_operational_status",
         "fieldtype": "Data", "width": 130},
        {"label": "Technician", "fieldname": "custom_assigned_technician",
         "fieldtype": "Link", "options": "User", "width": 160},
    ]
    return columns, logs
