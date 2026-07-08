"""Overdue Maintenance — open logs past their due date, with days overdue."""

import frappe
from frappe.utils import nowdate, date_diff, getdate


def execute(filters=None):
    filters = filters or {}
    today = nowdate()

    conditions = {
        "maintenance_status": ["in", ["Planned", "Overdue"]],
        "due_date": ["<", today],
    }
    if filters.get("assigned_technician"):
        conditions["custom_assigned_technician"] = filters["assigned_technician"]

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

    for l in logs:
        l["days_overdue"] = date_diff(today, getdate(l.due_date))

    columns = [
        {"label": "Log", "fieldname": "name", "fieldtype": "Link",
         "options": "Asset Maintenance Log", "width": 150},
        {"label": "Asset", "fieldname": "asset_name", "fieldtype": "Link",
         "options": "Asset", "width": 140},
        {"label": "Task", "fieldname": "task", "fieldtype": "Data", "width": 180},
        {"label": "Due Date", "fieldname": "due_date", "fieldtype": "Date",
         "width": 100},
        {"label": "Days Overdue", "fieldname": "days_overdue", "fieldtype": "Int",
         "width": 110},
        {"label": "Op Status", "fieldname": "custom_operational_status",
         "fieldtype": "Data", "width": 130},
        {"label": "Technician", "fieldname": "custom_assigned_technician",
         "fieldtype": "Link", "options": "User", "width": 160},
    ]
    return columns, logs
