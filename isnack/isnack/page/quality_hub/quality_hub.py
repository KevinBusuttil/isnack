import frappe
from frappe.utils import now_datetime, add_to_date, today


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


def on_qc_record_submit(doc, method):
    """Update last_inspection on Lab Checkpoint when a QC record is submitted."""
    factory_line = getattr(doc, "factory_line", None)
    if not factory_line:
        return

    if not frappe.db.table_exists("Lab Checkpoint"):
        return

    checkpoints = frappe.get_all(
        "Lab Checkpoint",
        filters={"disabled": 0, "factory_line": factory_line},
        fields=["name"],
    )

    for cp in checkpoints:
        frappe.db.set_value(
            "Lab Checkpoint",
            cp.name,
            "last_inspection",
            now_datetime(),
            update_modified=False,
        )


# ─────────────────────────────────────────────────────────────
# New API endpoints for QC Record tabs
# ─────────────────────────────────────────────────────────────

QC_DOCTYPES = {
    "QCA": "QC Receiving Record",
    "QCB": "QC Puffs Extruder Record",
    "QCC": "QC Rice Extruder Record",
    "QCD": "QC Frying Line Record",
    "QCE": "QC Oven Record",
    "QCF": "QC Tasting Record",
    "QCG": "QC Packaging Check",
    "QCH": "QC Metal Detector Log",
    "QCI": "QC Weight Check",
}


@frappe.whitelist()
def get_qc_record_summary(date=None):
    """Return counts of QC records per DocType for the given date, grouped by status."""
    target_date = date or today()
    result = {}

    for code, doctype in QC_DOCTYPES.items():
        if not frappe.db.table_exists(f"tab{doctype}"):
            result[code] = {"total": 0, "submitted": 0, "draft": 0}
            continue

        total = frappe.db.count(doctype, filters={"record_date": target_date})
        submitted = frappe.db.count(
            doctype, filters={"record_date": target_date, "docstatus": 1}
        )
        draft = frappe.db.count(
            doctype, filters={"record_date": target_date, "docstatus": 0}
        )
        result[code] = {
            "doctype": doctype,
            "total": total,
            "submitted": submitted,
            "draft": draft,
        }

    return result


@frappe.whitelist()
def get_completion_matrix(date=None):
    """Return a shift × doctype matrix showing completion status for the given date."""
    target_date = date or today()
    shifts = ["Morning", "Afternoon", "Night"]
    matrix = {}

    for shift in shifts:
        matrix[shift] = {}
        for code, doctype in QC_DOCTYPES.items():
            if not frappe.db.table_exists(f"tab{doctype}"):
                matrix[shift][code] = "not_started"
                continue

            submitted = frappe.db.count(
                doctype,
                filters={"record_date": target_date, "shift": shift, "docstatus": 1},
            )
            if submitted:
                matrix[shift][code] = "submitted"
                continue

            draft = frappe.db.count(
                doctype,
                filters={"record_date": target_date, "shift": shift, "docstatus": 0},
            )
            matrix[shift][code] = "draft" if draft else "not_started"

    return {"matrix": matrix, "date": target_date, "doctypes": QC_DOCTYPES}


@frappe.whitelist()
def get_qc_records(doctype, filters=None, limit=20):
    """Generic method to fetch QC records for the list views in each tab."""
    import json

    if doctype not in QC_DOCTYPES.values():
        frappe.throw(f"Invalid QC DocType: {doctype}")

    if not frappe.db.table_exists(f"tab{doctype}"):
        return []

    parsed_filters = {}
    if filters:
        if isinstance(filters, str):
            parsed_filters = json.loads(filters)
        else:
            parsed_filters = filters

    # Base fields available on all QC doctypes
    fields = [
        "name",
        "record_date",
        "shift",
        "factory_line",
        "work_order",
        "operator_name",
        "qc_inspector",
        "status",
        "overall_status",
        "docstatus",
        "modified",
    ]

    # Filter out fields not present in the doctype
    meta = frappe.get_meta(doctype)
    available_fieldnames = {f.fieldname for f in meta.fields}
    available_fieldnames.update({"name", "docstatus", "modified"})
    fields = [f for f in fields if f in available_fieldnames]

    records = frappe.get_all(
        doctype,
        filters=parsed_filters,
        fields=fields,
        order_by="record_date desc, modified desc",
        limit=int(limit),
    )

    return records
