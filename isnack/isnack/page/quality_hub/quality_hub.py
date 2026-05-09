import frappe
from frappe.utils import cint
from frappe.utils import now_datetime, add_to_date, today


@frappe.whitelist()
def get_quality_hub_data():
    """Return all info the Quality Hub page needs."""
    now = now_datetime()

    stats = {
        "completed_last_hour": _get_completed_last_hour(now),
        "open_non_conformances": _get_open_non_conformances(),
    }

    recent_out_of_range = _get_recent_out_of_range_readings()

    return {
        "stats": stats,
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
    """Count open Non Conformance records."""
    if not frappe.db.table_exists("Non Conformance"):
        return 0

    return frappe.db.count(
        "Non Conformance",
        filters={"status": "Open"},
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

QC_DIALOG_DOCTYPES = {
    "QC Puffs Extruder Record": {
        "child_table_field": "readings",
        "child_doctype": "QC Extruder Reading",
    },
    "QC Rice Extruder Record": {
        "child_table_field": "readings",
        "child_doctype": "QC Extruder Reading",
    },
    "QC Frying Line Record": {
        "child_table_field": "readings",
        "child_doctype": "QC Frying Reading",
    },
    "QC Oven Record": {
        "child_table_field": "readings",
        "child_doctype": "QC Oven Reading",
    },
    "QC Tasting Record": {
        "child_table_field": "scores",
        "child_doctype": "QC Tasting Score",
    },
    "QC Metal Detector Log": {
        "child_table_field": "tests",
        "child_doctype": "QC Metal Detector Test",
    },
    "QC Weight Check": {
        "child_table_field": "samples",
        "child_doctype": "QC Weight Sample",
    },
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


@frappe.whitelist()
def create_qc_record(doctype, payload=None, submit=False):
    """Create supported QC records, including child-table rows, from Quality Hub dialogs."""
    if doctype not in QC_DIALOG_DOCTYPES:
        frappe.throw(f"Dialog creation is not supported for {doctype}.")

    config = QC_DIALOG_DOCTYPES[doctype]
    data = frappe.parse_json(payload) if payload else {}
    if not isinstance(data, dict):
        frappe.throw("Payload must be a JSON object.")

    meta = frappe.get_meta(doctype)
    child_fieldname = config["child_table_field"]
    child_doctype = config["child_doctype"]
    child_rows = data.pop(child_fieldname, []) or []

    if not isinstance(child_rows, list):
        frappe.throw(f"{frappe.bold(child_fieldname)} must be a list of rows.")

    allowed_parent_fields = {
        df.fieldname for df in meta.fields if df.fieldtype != "Table" and df.fieldname
    }
    allowed_parent_fields.add("doctype")

    doc_data = {"doctype": doctype}
    for fieldname, value in data.items():
        if fieldname in allowed_parent_fields:
            doc_data[fieldname] = value

    if not doc_data.get("status"):
        doc_data["status"] = "Submitted" if cint(submit) else "Draft"

    doc = frappe.get_doc(doc_data)

    child_meta = frappe.get_meta(child_doctype)
    allowed_child_fields = {
        df.fieldname for df in child_meta.fields if df.fieldname and df.fieldtype != "Table"
    }

    appended_rows = 0
    for row in child_rows:
        if not isinstance(row, dict):
            frappe.throw("Each child row must be a JSON object.")

        clean_row = {
            fieldname: value
            for fieldname, value in row.items()
            if fieldname in allowed_child_fields
        }
        if _row_has_values(clean_row):
            doc.append(child_fieldname, clean_row)
            appended_rows += 1

    if not appended_rows:
        label = meta.get_label(child_fieldname) or child_fieldname.replace("_", " ").title()
        frappe.throw(f"At least one row is required in {frappe.bold(label)}.")

    doc.insert()
    if cint(submit):
        doc.submit()

    return {
        "name": doc.name,
        "doctype": doc.doctype,
        "docstatus": doc.docstatus,
        "record_date": getattr(doc, "record_date", None),
        "shift": getattr(doc, "shift", None),
        "overall_status": getattr(doc, "overall_status", None),
    }


def _row_has_values(row):
    for value in row.values():
        if value in (None, "", []):
            continue
        return True
    return False
