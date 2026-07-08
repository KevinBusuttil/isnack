"""Technician Workload — open work per technician, broken down by urgency."""

import frappe
from frappe.utils import nowdate, getdate, date_diff

from isnack.utils.maintenance import OPEN_STATUSES


def execute(filters=None):
    filters = filters or {}
    today = getdate(nowdate())

    logs = frappe.get_all(
        "Asset Maintenance Log",
        filters={"maintenance_status": ["in", ["Planned", "Overdue"]]},
        fields=["asset_name", "due_date", "custom_operational_status",
                "custom_assigned_technician", "task_assignee_email"],
        limit_page_length=0,
    )

    agg = {}
    for l in logs:
        status = l.custom_operational_status or "Planned"
        if status not in OPEN_STATUSES and status != "Planned":
            continue
        tech = l.custom_assigned_technician or l.task_assignee_email or "(unassigned)"
        row = agg.setdefault(tech, {"technician": tech, "total": 0, "overdue": 0,
                                    "due_7": 0, "in_progress": 0, "waiting_parts": 0})
        row["total"] += 1
        if status == "In Progress":
            row["in_progress"] += 1
        if status == "Waiting for Parts":
            row["waiting_parts"] += 1
        if l.due_date:
            diff = date_diff(getdate(l.due_date), today)
            if diff < 0:
                row["overdue"] += 1
            elif diff <= 7:
                row["due_7"] += 1

    data = sorted(agg.values(), key=lambda r: r["total"], reverse=True)

    columns = [
        {"label": "Technician", "fieldname": "technician", "fieldtype": "Data",
         "width": 220},
        {"label": "Open Total", "fieldname": "total", "fieldtype": "Int", "width": 100},
        {"label": "Overdue", "fieldname": "overdue", "fieldtype": "Int", "width": 90},
        {"label": "Due in 7d", "fieldname": "due_7", "fieldtype": "Int", "width": 90},
        {"label": "In Progress", "fieldname": "in_progress", "fieldtype": "Int",
         "width": 100},
        {"label": "Waiting Parts", "fieldname": "waiting_parts", "fieldtype": "Int",
         "width": 110},
    ]
    return columns, data
