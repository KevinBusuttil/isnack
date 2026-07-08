"""Maintenance Compliance — on-time completion rate per maintenance type.

For completed logs in the period, compares completion_date against due_date to
compute on-time vs late, plus a compliance percentage.
"""

import frappe
from frappe.utils import add_months, nowdate, getdate, date_diff


def execute(filters=None):
    filters = filters or {}
    to_date = filters.get("to_date") or nowdate()
    from_date = filters.get("from_date") or add_months(to_date, -3)

    logs = frappe.get_all(
        "Asset Maintenance Log",
        filters={
            "maintenance_status": "Completed",
            "completion_date": ["between", [from_date, to_date]],
        },
        fields=["asset_name", "maintenance_type", "due_date", "completion_date"],
        limit_page_length=0,
    )

    if filters.get("company"):
        assets = set(frappe.get_all("Asset", filters={"company": filters["company"]},
                                    pluck="name"))
        logs = [l for l in logs if l.asset_name in assets]

    agg = {}
    for l in logs:
        key = l.maintenance_type or "(none)"
        row = agg.setdefault(key, {"maintenance_type": key, "completed": 0,
                                   "on_time": 0, "late": 0})
        row["completed"] += 1
        if l.due_date and l.completion_date:
            if date_diff(getdate(l.completion_date), getdate(l.due_date)) <= 0:
                row["on_time"] += 1
            else:
                row["late"] += 1
        else:
            row["on_time"] += 1

    data = []
    for row in agg.values():
        row["compliance_pct"] = round(
            100.0 * row["on_time"] / row["completed"], 1) if row["completed"] else 0
        data.append(row)
    data.sort(key=lambda r: r["compliance_pct"])

    columns = [
        {"label": "Maintenance Type", "fieldname": "maintenance_type",
         "fieldtype": "Data", "width": 200},
        {"label": "Completed", "fieldname": "completed", "fieldtype": "Int",
         "width": 100},
        {"label": "On Time", "fieldname": "on_time", "fieldtype": "Int", "width": 90},
        {"label": "Late", "fieldname": "late", "fieldtype": "Int", "width": 80},
        {"label": "Compliance %", "fieldname": "compliance_pct",
         "fieldtype": "Percent", "width": 120},
    ]
    return columns, data
