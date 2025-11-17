import frappe
from frappe.utils import now_datetime, add_to_date


@frappe.whitelist()
def get_quality_hub_data():
    """Return all info the Quality Hub page needs."""
    now = now_datetime()

    checkpoints = frappe.get_all(
        "Lab Checkpoint",
        filters={"disabled": 0},
        fields=[
            "name",
            "checkpoint_name",
            "quality_inspection_template",
            "equipment",
            "frequency_mins",
            "last_inspection",
            "responsible_user",
        ],
    )

    overdue = []
    due_now = []
    upcoming = []

    for cp in checkpoints:
        freq = cp.frequency_mins or 0
        if not freq:
            continue

        last = cp.last_inspection

        if last:
            # minutes until next due
            minutes_since = (now - last).total_seconds() / 60.0
            minutes_to_next = freq - minutes_since
        else:
            # never inspected = due now
            minutes_since = None
            minutes_to_next = 0

        row = {
            "name": cp.name,
            "checkpoint_name": cp.checkpoint_name,
            "equipment": cp.equipment,
            "frequency_mins": freq,
            "last_inspection": last,
            "responsible_user": cp.responsible_user,
            "minutes_to_next": round(minutes_to_next, 1),
            "minutes_since": round(minutes_since, 1)
            if minutes_since is not None
            else None,
        }

        # classify
        if minutes_to_next <= 0:
            overdue.append(row)
        elif minutes_to_next <= 5:  # due within 5 minutes
            due_now.append(row)
        else:
            upcoming.append(row)

    overdue.sort(key=lambda r: r["minutes_to_next"])
    due_now.sort(key=lambda r: r["minutes_to_next"])
    upcoming.sort(key=lambda r: r["minutes_to_next"])

    stats = {
        "overdue_count": len(overdue),
        "due_now_count": len(due_now),
        "completed_last_hour": _get_completed_last_hour(now),
        "open_non_conformances": _get_open_non_conformances(),
    }

    recent_out_of_range = _get_recent_out_of_range_readings()

    return {
        "stats": stats,
        "overdue": overdue,
        "due_now": due_now,
        "upcoming": upcoming,
        "recent_out_of_range": recent_out_of_range,
    }


def _get_completed_last_hour(now):
    """How many Quality Inspections were done in the last hour."""
    one_hour_ago = add_to_date(now, hours=-1)
    return frappe.db.count(
        "Quality Inspection",
        filters={"docstatus": 1, "modified": (">=", one_hour_ago)},
    )


def _get_open_non_conformances():
    """Example: count open non-conformances, adjust doctype/field names to your setup."""
    if not frappe.db.table_exists("Quality Feedback"):
        return 0

    # Or use Non Conformance / Quality Action depending on how you use the module
    return frappe.db.count(
        "Quality Feedback",
        filters={"status": ("!=", "Closed")},
    )


def _get_recent_out_of_range_readings(limit=10, hours=4):
    """
    Simple example: fetch recent Quality Inspection Readings that were rejected.
    Adjust fieldnames / logic to your instance if needed.
    """
    if not frappe.db.table_exists("Quality Inspection Reading"):
        return []

    rows = frappe.db.sql(
        """
        SELECT
            qir.parent AS quality_inspection,
            qir.specification,
            qir.status,
            qi.item_code,
            qi.inspection_type,
            qi.reference_type,
            qi.reference_name,
            qi.modified AS ts
        FROM `tabQuality Inspection Reading` qir
        JOIN `tabQuality Inspection` qi
            ON qi.name = qir.parent
        WHERE
            qi.docstatus = 1
            AND qir.status = "Rejected"
            AND qi.modified >= %(since)s
        ORDER BY qi.modified DESC
        LIMIT %(limit)s
        """,
        {
            "since": add_to_date(now_datetime(), hours=-hours),
            "limit": limit,
        },
        as_dict=True,
    )

    return rows


@frappe.whitelist()
def create_quality_inspection_from_checkpoint(checkpoint):
    """
    Create a draft Quality Inspection from a Lab Checkpoint
    and return its name so the UI can route to it.
    """
    cp = frappe.get_doc("Lab Checkpoint", checkpoint)

    qi = frappe.new_doc("Quality Inspection")
    qi.inspection_type = "In Process"  # or Incoming/Outgoing if needed
    qi.quality_inspection_template = cp.quality_inspection_template
    qi.lab_checkpoint = cp.name
    qi.reference_type = getattr(cp, "reference_type", None)
    qi.reference_name = getattr(cp, "reference_name", None)
    qi.item_code = None  # set if you have a fixed item per checkpoint

    qi.insert(ignore_permissions=True)
    return {"name": qi.name}


def on_quality_inspection_submit(doc, method):
    """Update last_inspection when a lab-linked Quality Inspection is submitted."""
    if not getattr(doc, "lab_checkpoint", None):
        return

    frappe.db.set_value(
        "Lab Checkpoint",
        doc.lab_checkpoint,
        "last_inspection",
        now_datetime(),
        update_modified=False,
    )
