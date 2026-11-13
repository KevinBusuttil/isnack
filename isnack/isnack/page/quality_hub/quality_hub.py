import frappe
from frappe import _
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

# Record types no longer kept: oven readings are taken on the extruder records
# (QCB, QCC) since 2026-10. Their old records stay readable (Quality Explorer,
# desk); the hub neither offers, counts nor expects new ones.
RETIRED_QC_CODES = {"QCE"}

QC_DIALOG_CONFIG = {
    "QC Receiving Record": {},
    # Puffs and Rice have their own readings since 2026-11; their earlier
    # tables (readings, oven_readings) take no new rows
    "QC Puffs Extruder Record": {
        "child_table_field": "puffs_readings",
        "child_doctype": "QC Puffs Extruder Reading",
        "optional_child_tables": {"puffs_oven_readings": "QC Puffs Oven Reading"},
    },
    "QC Rice Extruder Record": {
        "child_table_field": "rice_readings",
        "child_doctype": "QC Rice Extruder Reading",
        "optional_child_tables": {"rice_oven_readings": "QC Rice Oven Reading"},
    },
    "QC Frying Line Record": {
        "child_table_field": "readings",
        "child_doctype": "QC Frying Reading",
    },
    "QC Tasting Record": {
        "child_table_field": "scores",
        "child_doctype": "QC Tasting Score",
    },
    "QC Packaging Check": {},
    "QC Metal Detector Log": {
        "child_table_field": "tests",
        "child_doctype": "QC Metal Detector Test",
    },
    "QC Weight Check": {
        "child_table_field": "samples",
        "child_doctype": "QC Weight Sample",
    },
}


def _hub_doctypes():
    """The record types the hub expects every day: all but the retired ones."""
    return {code: doctype for code, doctype in QC_DOCTYPES.items() if code not in RETIRED_QC_CODES}


def _day_records(doctype, date):
    """The user's records of ``doctype`` for ``date``, as ``(shift, docstatus)`` rows.

    ``None`` when the user may not read the doctype. Read with get_list, so the
    counts built on it agree with the record lists the user can open.
    """
    if not frappe.has_permission(doctype, "read"):
        return None
    if not frappe.db.table_exists(doctype):
        return []
    return frappe.get_list(
        doctype,
        filters={"record_date": date},
        fields=["shift", "docstatus"],
        limit_page_length=0,
    )


@frappe.whitelist()
def get_qc_record_summary(date=None):
    """Return counts of QC records per DocType for the given date, grouped by status.

    A DocType the user may not read comes back with ``hidden`` set and no counts.
    """
    target_date = date or today()
    result = {}

    for code, doctype in _hub_doctypes().items():
        rows = _day_records(doctype, target_date)
        result[code] = {
            "doctype": doctype,
            "total": len(rows or []),
            "submitted": sum(1 for r in rows or [] if r.docstatus == 1),
            "draft": sum(1 for r in rows or [] if r.docstatus == 0),
            "hidden": rows is None,
        }

    return result


@frappe.whitelist()
def get_completion_matrix(date=None):
    """Return a shift × doctype matrix showing completion status for the given date.

    Cells are ``submitted``, ``draft``, ``not_started``, or ``hidden`` for a
    DocType the user may not read.
    """
    target_date = date or today()
    shifts = ["Morning", "Afternoon", "Night"]
    matrix = {shift: {} for shift in shifts}
    doctypes = _hub_doctypes()

    for code, doctype in doctypes.items():
        rows = _day_records(doctype, target_date)
        for shift in shifts:
            if rows is None:
                matrix[shift][code] = "hidden"
                continue
            statuses = {r.docstatus for r in rows if r.shift == shift}
            if 1 in statuses:
                matrix[shift][code] = "submitted"
            elif 0 in statuses:
                matrix[shift][code] = "draft"
            else:
                matrix[shift][code] = "not_started"

    return {"matrix": matrix, "date": target_date, "doctypes": doctypes}


@frappe.whitelist()
def get_qc_records(doctype, filters=None, limit=20):
    """Generic method to fetch QC records for the list views in each tab."""
    import json

    if doctype not in QC_DOCTYPES.values():
        frappe.throw(f"Invalid QC DocType: {doctype}")

    if not frappe.has_permission(doctype, "read"):
        raise frappe.PermissionError(f"Not permitted to read {doctype}.")

    if not frappe.db.table_exists(doctype):
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
        "supplier",
        "item_code",
        "batch_no",
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

    # get_list, not get_all: the user's User Permissions apply to the lists too
    records = frappe.get_list(
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
    doc = _new_qc_record(doctype, payload, submit)
    doc.insert()
    if cint(submit):
        doc.submit()

    return _record_summary(doc)


# The Packaging and Weight tab's form records a packaging check and a weight
# check together (or either on its own).
COMBINED_DOCTYPES = ("QC Packaging Check", "QC Weight Check")


@frappe.whitelist()
def create_qc_records(details=None, records=None, submit=False):
    """Create the records of the Packaging and Weight tab's form: the Record
    Details they share (``details``, written to each) and each record's own
    values (``records``: ``[{"doctype": ..., "payload": {...}}]``, at most one
    packaging check and one weight check).

    All are inserted before any is submitted. If one fails, none is kept: the
    request rolls back, and so does the savepoint when called from elsewhere.
    """
    details = frappe.parse_json(details) if details else {}
    records = frappe.parse_json(records) if records else []
    if not isinstance(details, dict):
        frappe.throw("Record Details must be a JSON object.")
    if not isinstance(records, list) or not records:
        frappe.throw(_("Tick the Packaging Check, the Weight Check or both."))
    doctypes = [record.get("doctype") if isinstance(record, dict) else None for record in records]
    if any(doctype not in COMBINED_DOCTYPES for doctype in doctypes) or len(set(doctypes)) != len(doctypes):
        frappe.throw(_("This form records one packaging check and one weight check at most."))

    savepoint = "create_qc_records"
    frappe.db.savepoint(savepoint)
    try:
        docs = []
        for record in records:
            payload = frappe.parse_json(record.get("payload")) if record.get("payload") else {}
            if not isinstance(payload, dict):
                frappe.throw("Payload must be a JSON object.")
            docs.append(_new_qc_record(record["doctype"], {**payload, **details}, submit))
        for doc in docs:
            doc.insert()
        if cint(submit):
            for doc in docs:
                doc.submit()
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise

    return [_record_summary(doc) for doc in docs]


@frappe.whitelist()
def get_work_order_product(work_order=None):
    """The item a Work Order makes, which the Packaging and Weight form fills
    in as the weight check's Item Code. None when the user may not read the
    Work Order: they pick the item themselves."""
    if not work_order or not frappe.has_permission("Work Order", "read", doc=work_order):
        return None
    return frappe.db.get_value("Work Order", work_order, "production_item")


def _record_summary(doc):
    return {
        "name": doc.name,
        "doctype": doc.doctype,
        "docstatus": doc.docstatus,
        "record_date": getattr(doc, "record_date", None),
        "shift": getattr(doc, "shift", None),
        "overall_status": getattr(doc, "overall_status", None),
    }


def _new_qc_record(doctype, payload, submit):
    """A QC record of ``doctype`` built from a Quality Hub dialog's ``payload``,
    its child rows appended; not yet saved."""
    if doctype not in QC_DIALOG_CONFIG:
        frappe.throw(f"Dialog creation is not supported for {doctype}.")

    config = QC_DIALOG_CONFIG[doctype]
    data = frappe.parse_json(payload) if payload else {}
    if not isinstance(data, dict):
        frappe.throw("Payload must be a JSON object.")

    meta = frappe.get_meta(doctype)
    # (fieldname, child doctype, needs a row): the record's own table, then any optional ones
    tables = []
    if config.get("child_table_field"):
        tables.append((config["child_table_field"], config["child_doctype"], True))
    for fieldname, child_doctype in config.get("optional_child_tables", {}).items():
        tables.append((fieldname, child_doctype, False))

    child_rows = {}
    for fieldname, _child_doctype, _required in tables:
        rows = data.pop(fieldname, []) or []
        if not isinstance(rows, list):
            frappe.throw(f"{frappe.bold(fieldname)} must be a list of rows.")
        child_rows[fieldname] = rows

    # rows for a table the dialog no longer fills (the extruders' earlier readings): a
    # page loaded before it changed. Say so, rather than drop them and ask for rows
    if any(df.fieldtype == "Table" and df.fieldname not in child_rows and data.get(df.fieldname) for df in meta.fields):
        frappe.throw("This page is out of date. Reload it and enter the record again.")

    allowed_parent_fields = {
        df.fieldname: df.fieldtype for df in meta.fields if df.fieldtype != "Table" and df.fieldname
    }
    # the record is the doctype checked above: a payload's "doctype" is not taken

    doc_data = {"doctype": doctype}
    for fieldname, value in data.items():
        if fieldname in allowed_parent_fields and _keep_value(allowed_parent_fields[fieldname], value):
            doc_data[fieldname] = value

    if not doc_data.get("status") and not cint(submit):
        doc_data["status"] = "Draft"

    doc = frappe.get_doc(doc_data)

    for fieldname, child_doctype, required in tables:
        appended_rows = _append_child_rows(doc, fieldname, child_doctype, child_rows[fieldname])
        if required and not appended_rows:
            label = meta.get_label(fieldname) or fieldname.replace("_", " ").title()
            frappe.throw(f"At least one row is required in {frappe.bold(label)}.")

    return doc


def _append_child_rows(doc, fieldname, child_doctype, rows):
    """Append the dialog's rows that hold a value to ``doc``'s ``fieldname``
    table; how many it appended."""
    child_meta = frappe.get_meta(child_doctype)
    allowed_child_fields = {
        df.fieldname: df.fieldtype for df in child_meta.fields if df.fieldtype != "Table" and df.fieldname
    }

    appended_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw("Each child row must be a JSON object.")

        clean_row = {
            child_field: value
            for child_field, value in row.items()
            if child_field in allowed_child_fields and _keep_value(allowed_child_fields[child_field], value)
        }
        if _is_non_empty_row(clean_row):
            doc.append(fieldname, clean_row)
            appended_rows += 1
    return appended_rows


def _is_blank(value):
    return value in (None, "", [])


def _keep_value(fieldtype, value):
    """A field the dialog left blank arrives as "": leave it unset, as the desk
    form would, rather than hand the controllers a string where they expect a
    number (sum() over a reading column). A blank Select stays blank: unset,
    Frappe would fill in its first option, which nobody picked."""
    return not _is_blank(value) or (fieldtype == "Select" and value == "")


def _is_non_empty_row(row):
    for value in row.values():
        if value in (None, "", []):
            continue
        return True
    return False


@frappe.whitelist()
def get_items_for_purchase_receipt(doctype, txt, searchfield, start, page_len, filters=None):
    """Link field query: return items present in a given Purchase Receipt."""
    import json

    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = filters or {}

    purchase_receipt = filters.get("purchase_receipt")

    conditions = []
    params = {"start": int(start or 0), "page_len": int(page_len or 20)}

    if purchase_receipt:
        conditions.append("pri.parent = %(purchase_receipt)s")
        params["purchase_receipt"] = purchase_receipt

    if txt:
        conditions.append("(pri.item_code LIKE %(txt)s OR pri.item_name LIKE %(txt)s)")
        params["txt"] = f"%{txt}%"

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return frappe.db.sql(
        f"""
        SELECT DISTINCT pri.item_code, pri.item_name
        FROM `tabPurchase Receipt Item` pri
        {where}
        ORDER BY pri.item_code
        LIMIT %(start)s, %(page_len)s
        """,
        params,
    )


@frappe.whitelist()
def get_batches_for_receiving(doctype, txt, searchfield, start, page_len, filters=None):
    """Link field query: return batches for a given Purchase Receipt (and optional item)."""
    import json

    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = filters or {}

    purchase_receipt = filters.get("purchase_receipt")
    item_code = filters.get("item_code")

    conditions = ["b.disabled = 0"]
    params = {"start": int(start or 0), "page_len": int(page_len or 20)}

    if purchase_receipt:
        # the batch is on the receipt row itself, or (v15's default) in the
        # row's Serial and Batch Bundle, or in its rejected bundle when the
        # goods were rejected at receipt
        conditions.append(
            "("
            "EXISTS ("
            "SELECT 1 FROM `tabPurchase Receipt Item` pri"
            " WHERE pri.parent = %(purchase_receipt)s"
            " AND pri.batch_no = b.name"
            ")"
            " OR EXISTS ("
            "SELECT 1 FROM `tabPurchase Receipt Item` pri"
            " JOIN `tabSerial and Batch Entry` sbe"
            " ON sbe.parent IN (pri.serial_and_batch_bundle, pri.rejected_serial_and_batch_bundle)"
            " WHERE pri.parent = %(purchase_receipt)s"
            " AND sbe.batch_no = b.name"
            ")"
            ")"
        )
        params["purchase_receipt"] = purchase_receipt

    if item_code:
        conditions.append("b.item = %(item_code)s")
        params["item_code"] = item_code

    if txt:
        conditions.append("b.name LIKE %(txt)s")
        params["txt"] = f"%{txt}%"

    where = "WHERE " + " AND ".join(conditions)

    return frappe.db.sql(
        f"""
        SELECT b.name, b.item
        FROM `tabBatch` b
        {where}
        ORDER BY b.name
        LIMIT %(start)s, %(page_len)s
        """,
        params,
    )
