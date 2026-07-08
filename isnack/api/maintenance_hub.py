"""Whitelisted APIs powering the Technician & Manager Maintenance Hubs.

The operational work item is ERPNext's **Asset Maintenance Log**. This module
reads/writes the standard log plus the ``custom_*`` operational fields, and
keeps ERPNext's standard ``maintenance_status`` consistent so core scheduling
(next due date / last completion) keeps working.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, nowdate, getdate

from isnack.utils.maintenance import (
    OPERATIONAL_STATUSES,
    OPEN_STATUSES,
    OP_PLANNED,
    OP_ASSIGNED,
    OP_ACKNOWLEDGED,
    OP_IN_PROGRESS,
    OP_COMPLETED,
    OP_COMPLETED_ISSUE,
    OP_CANNOT_COMPLETE,
    OP_PENDING_VERIFICATION,
    OP_VERIFIED,
    OP_CANCELLED,
    OP_OVERDUE,
    is_manager,
    ensure_log_access,
    urgency_bucket,
)

LOG_FIELDS = [
    "name",
    "asset_maintenance",
    "asset_name as asset",
    "task",
    "maintenance_type",
    "periodicity",
    "maintenance_status",
    "due_date",
    "completion_date",
    "task_assignee_email",
    "custom_operational_status",
    "custom_assigned_technician",
    "custom_estimated_duration_mins",
    "custom_safety_warning",
    "custom_started_on",
    "custom_completed_on",
    "custom_requires_verification",
    "custom_completion_notes",
]


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------
def _asset_details(asset):
    if not asset:
        return {}
    meta = frappe.get_meta("Asset")
    fields = ["asset_name", "item_code", "item_name", "asset_category", "location"]
    for opt in ("serial_no", "custodian", "custom_maintenance_barcode"):
        if meta.has_field(opt):
            fields.append(opt)
    data = frappe.db.get_value("Asset", asset, fields, as_dict=True) or {}
    return data


def _enrich(log):
    asset = _asset_details(log.get("asset"))
    log["asset_display_name"] = asset.get("asset_name") or log.get("asset")
    log["asset_location"] = asset.get("location")
    log["asset_category"] = asset.get("asset_category")
    log["serial_no"] = asset.get("serial_no")
    log["item_code"] = asset.get("item_code")
    if not log.get("custom_operational_status"):
        log["custom_operational_status"] = OP_PLANNED
    log["bucket"] = urgency_bucket(log)
    # Required spare parts summary (short text for the card).
    parts = frappe.get_all(
        "Maintenance Spare Part",
        filters={"asset_maintenance_log": log["name"], "part_type": "Required"},
        fields=["item_name", "item_code", "required_qty", "available_qty"],
        limit=5,
    )
    log["required_parts"] = parts
    log["required_parts_summary"] = ", ".join(
        f"{p.item_name or p.item_code} x{p.required_qty:g}" for p in parts
    )
    return log


def _logs_for_technician(technician):
    email = frappe.db.get_value("User", technician, "email") or technician
    # OR semantics: assigned via our field OR via ERPNext's task_assignee_email.
    logs = frappe.get_all(
        "Asset Maintenance Log",
        or_filters=[
            ["custom_assigned_technician", "=", technician],
            ["task_assignee_email", "=", email],
        ],
        fields=LOG_FIELDS,
        order_by="due_date asc",
        limit_page_length=0,
    )
    return [_enrich(l) for l in logs]


@frappe.whitelist()
def get_technician_work(technician=None):
    """Return the technician's maintenance work grouped by urgency bucket."""
    user = frappe.session.user
    if technician and technician != user and not is_manager(user):
        frappe.throw(_("Not permitted to view another technician's work."),
                     frappe.PermissionError)
    technician = technician or user

    logs = _logs_for_technician(technician)

    buckets = {
        "overdue": [],
        "due_today": [],
        "next_7_days": [],
        "in_progress": [],
        "waiting_for_parts": [],
        "completed": [],
    }
    for log in logs:
        b = log["bucket"]
        if b == "later":
            continue
        if b in buckets:
            # Only show recently completed (last 7 days) in the completed bucket.
            if b == "completed":
                done = log.get("custom_completed_on") or log.get("completion_date")
                if done and getdate(done) < getdate(frappe.utils.add_days(nowdate(), -7)):
                    continue
            buckets[b].append(log)

    counts = {k: len(v) for k, v in buckets.items()}
    return {
        "technician": technician,
        "buckets": buckets,
        "counts": counts,
        "server_date": nowdate(),
    }


@frappe.whitelist()
def get_task_detail(log):
    """Return full detail for one maintenance log for the task detail screen."""
    ensure_log_access(log)
    doc = frappe.get_doc("Asset Maintenance Log", log)
    data = {f.split(" as ")[-1]: doc.get(f.split(" as ")[0]) for f in LOG_FIELDS}
    data["name"] = doc.name
    data["description"] = doc.get("description")
    data["actions_performed"] = doc.get("actions_performed")

    asset = data.get("asset")
    asset_doc = _asset_details(asset)
    data["asset_detail"] = asset_doc

    # Last & next maintenance from the parent task, if resolvable.
    if doc.get("asset_maintenance") and doc.get("task"):
        task = frappe.db.get_value(
            "Asset Maintenance Task",
            {"parent": doc.asset_maintenance, "maintenance_task": doc.task},
            ["last_completion_date", "next_due_date"],
            as_dict=True,
        )
        if task:
            data["last_completion_date"] = task.last_completion_date
            data["next_due_date"] = task.next_due_date

    data["checklist"] = frappe.get_all(
        "Maintenance Checklist Response",
        filters={"asset_maintenance_log": log},
        fields=["*"],
        order_by="sequence asc",
    )
    data["readings"] = frappe.get_all(
        "Maintenance Reading",
        filters={"asset_maintenance_log": log},
        fields=["name", "reading_type", "reading_value", "uom", "min_value",
                "max_value", "is_out_of_range", "recorded_on", "comments"],
        order_by="recorded_on desc",
    )
    data["spare_parts"] = frappe.get_all(
        "Maintenance Spare Part",
        filters={"asset_maintenance_log": log},
        fields=["name", "part_type", "item_code", "item_name", "required_qty",
                "consumed_qty", "available_qty", "status", "source_warehouse",
                "material_request", "stock_entry"],
        order_by="part_type asc",
    )
    data["breakdowns"] = frappe.get_all(
        "Asset Breakdown",
        filters={"linked_asset_maintenance_log": log},
        fields=["name", "severity", "status", "description", "reported_on"],
    )
    data["attachments"] = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Asset Maintenance Log",
                 "attached_to_name": log},
        fields=["file_name", "file_url", "is_private"],
    )
    return data


# ---------------------------------------------------------------------------
# Technician lifecycle actions
# ---------------------------------------------------------------------------
def _set_status(doc, status, save=True):
    doc.custom_operational_status = status
    if save:
        doc.save(ignore_permissions=True)


@frappe.whitelist()
def start_task(log):
    """Technician starts work: generate checklist, set In Progress."""
    ensure_log_access(log, write=True)
    from isnack.api.maintenance_checklist import ensure_checklist_for_log

    doc = frappe.get_doc("Asset Maintenance Log", log)
    if not doc.get("custom_started_on"):
        doc.custom_started_on = now_datetime()
    doc.custom_operational_status = OP_IN_PROGRESS
    if not doc.get("custom_assigned_technician"):
        doc.custom_assigned_technician = frappe.session.user
    doc.save(ignore_permissions=True)
    ensure_checklist_for_log(log)
    return {"ok": True, "status": OP_IN_PROGRESS}


@frappe.whitelist()
def acknowledge_task(log):
    ensure_log_access(log, write=True)
    doc = frappe.get_doc("Asset Maintenance Log", log)
    if doc.custom_operational_status in (OP_PLANNED, OP_ASSIGNED, OP_OVERDUE):
        _set_status(doc, OP_ACKNOWLEDGED)
    return {"ok": True, "status": doc.custom_operational_status}


def _validate_required_checklist(log):
    """Block completion if required checklist rows are unanswered, or a
    mandatory safety step is not confirmed."""
    rows = frappe.get_all(
        "Maintenance Checklist Response",
        filters={"asset_maintenance_log": log},
        fields=["instruction", "input_type", "required", "is_safety_step",
                "response_value", "pass_fail", "numeric_value", "attachment"],
    )
    missing = []
    for r in rows:
        if not (r.required or r.is_safety_step):
            continue
        answered = bool(
            (r.response_value and str(r.response_value).strip())
            or r.pass_fail
            or (r.numeric_value not in (None, 0) if r.input_type in ("Number", "Reading") else False)
            or r.attachment
        )
        # Safety steps must be explicitly confirmed (Pass / checked).
        if r.is_safety_step and r.pass_fail == "Fail":
            frappe.throw(_("Safety step not satisfied: {0}").format(r.instruction))
        if not answered:
            missing.append(r.instruction or _("(item)"))
    if missing:
        frappe.throw(
            _("Complete these required checklist items first:<br>• {0}").format(
                "<br>• ".join(missing)
            )
        )


@frappe.whitelist()
def complete_task(log, completion_notes=None, with_issue=0, issue_detail=None):
    """Technician marks the task complete (optionally with an issue).

    Enforces required checklist/safety items. Updates the operational status and
    keeps ERPNext's standard maintenance_status = Completed so core scheduling
    (next due date) advances.
    """
    ensure_log_access(log, write=True)
    with_issue = frappe.parse_json(with_issue) if isinstance(with_issue, str) else with_issue
    _validate_required_checklist(log)

    doc = frappe.get_doc("Asset Maintenance Log", log)
    doc.custom_completed_on = now_datetime()
    if completion_notes:
        doc.custom_completion_notes = completion_notes
    note = completion_notes or ""
    if with_issue and issue_detail:
        note = (note + "\n\nISSUE: " + issue_detail).strip()
    if note:
        doc.actions_performed = (doc.get("actions_performed") or "") + "\n" + note

    requires_verification = doc.get("custom_requires_verification")
    if requires_verification:
        doc.custom_operational_status = OP_PENDING_VERIFICATION
    elif with_issue:
        doc.custom_operational_status = OP_COMPLETED_ISSUE
    else:
        doc.custom_operational_status = OP_COMPLETED

    # Advance ERPNext core: physical work is done.
    doc.maintenance_status = "Completed"
    if not doc.get("completion_date"):
        doc.completion_date = nowdate()
    doc.save(ignore_permissions=True)
    return {"ok": True, "status": doc.custom_operational_status}


@frappe.whitelist()
def cannot_complete(log, reason):
    """Technician cannot complete the task; records reason, leaves ERPNext open."""
    ensure_log_access(log, write=True)
    if not reason:
        frappe.throw(_("A reason is required."))
    doc = frappe.get_doc("Asset Maintenance Log", log)
    doc.custom_operational_status = OP_CANNOT_COMPLETE
    doc.custom_completion_notes = reason
    doc.actions_performed = (doc.get("actions_performed") or "") + \
        "\n\nUNABLE TO COMPLETE: " + reason
    doc.save(ignore_permissions=True)
    return {"ok": True, "status": OP_CANNOT_COMPLETE}


# ---------------------------------------------------------------------------
# Manager actions
# ---------------------------------------------------------------------------
def _ensure_manager():
    if not is_manager(frappe.session.user):
        frappe.throw(_("Only maintenance managers can perform this action."),
                     frappe.PermissionError)


@frappe.whitelist()
def reassign_task(log, technician, due_date=None):
    _ensure_manager()
    doc = frappe.get_doc("Asset Maintenance Log", log)
    doc.custom_assigned_technician = technician
    email = frappe.db.get_value("User", technician, "email") or technician
    doc.task_assignee_email = email
    if due_date:
        doc.due_date = getdate(due_date)
    if doc.custom_operational_status in (OP_PLANNED, "", None):
        doc.custom_operational_status = OP_ASSIGNED
    doc.save(ignore_permissions=True)

    # Create a Frappe ToDo so the technician sees it in their assignments.
    # Best-effort: a duplicate/existing assignment must not fail the reassign.
    try:
        from frappe.desk.form.assign_to import add as assign_add
        assign_add({
            "assign_to": [technician],
            "doctype": "Asset Maintenance Log",
            "name": log,
            "description": _("Maintenance task assigned to you."),
        })
    except Exception:
        frappe.clear_last_message()
    return {"ok": True, "technician": technician}


@frappe.whitelist()
def set_operational_status(log, status, comment=None):
    _ensure_manager()
    if status not in OPERATIONAL_STATUSES:
        frappe.throw(_("Invalid status: {0}").format(status))
    doc = frappe.get_doc("Asset Maintenance Log", log)
    doc.custom_operational_status = status
    if comment:
        doc.actions_performed = (doc.get("actions_performed") or "") + \
            f"\n[{frappe.session.user}] {status}: {comment}"
    if status == OP_CANCELLED:
        doc.maintenance_status = "Cancelled"
    doc.save(ignore_permissions=True)
    return {"ok": True, "status": status}


@frappe.whitelist()
def verify_task(log, comments=None):
    _ensure_manager()
    doc = frappe.get_doc("Asset Maintenance Log", log)
    doc.custom_operational_status = OP_VERIFIED
    doc.custom_verified_by = frappe.session.user
    doc.custom_verified_on = now_datetime()
    if comments:
        doc.custom_verification_comments = comments
    doc.save(ignore_permissions=True)
    return {"ok": True, "status": OP_VERIFIED}


# ---------------------------------------------------------------------------
# QR / barcode asset lookup
# ---------------------------------------------------------------------------
@frappe.whitelist()
def lookup_asset(code):
    """Resolve a scanned/typed code to an Asset and return its maintenance view.

    Resolution order: direct Asset name → custom_maintenance_barcode →
    serial_no (if present). Returns asset detail, open logs, recent history,
    open breakdowns and attached documents.
    """
    code = (code or "").strip()
    if not code:
        frappe.throw(_("No code provided."))

    asset = None
    if frappe.db.exists("Asset", code):
        asset = code
    else:
        meta = frappe.get_meta("Asset")
        if meta.has_field("custom_maintenance_barcode"):
            asset = frappe.db.get_value(
                "Asset", {"custom_maintenance_barcode": code}, "name")
        if not asset and meta.has_field("serial_no"):
            asset = frappe.db.get_value("Asset", {"serial_no": code}, "name")
    if not asset:
        return {"found": False, "code": code}

    open_logs = frappe.get_all(
        "Asset Maintenance Log",
        filters={"asset_name": asset},
        or_filters=[
            ["custom_operational_status", "in", list(OPEN_STATUSES)],
            ["maintenance_status", "in", ["Planned", "Overdue"]],
        ],
        fields=LOG_FIELDS,
        order_by="due_date asc",
    )
    history = frappe.get_all(
        "Asset Maintenance Log",
        filters={"asset_name": asset, "maintenance_status": "Completed"},
        fields=["name", "maintenance_type", "task", "completion_date",
                "custom_operational_status"],
        order_by="completion_date desc",
        limit=10,
    )
    breakdowns = frappe.get_all(
        "Asset Breakdown",
        filters={"asset": asset, "status": ["not in", ["Resolved", "Cancelled"]]},
        fields=["name", "severity", "status", "description", "reported_on"],
    )
    documents = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Asset", "attached_to_name": asset},
        fields=["file_name", "file_url"],
    )
    return {
        "found": True,
        "asset": asset,
        "asset_detail": _asset_details(asset),
        "open_logs": [_enrich(l) for l in open_logs],
        "history": history,
        "breakdowns": breakdowns,
        "documents": documents,
    }


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_manager_dashboard(company=None, view="this_week"):
    """KPI counts + work lists for the Manager Hub."""
    _ensure_manager()
    today = nowdate()
    week = frappe.utils.add_days(today, 7)
    month = frappe.utils.add_days(today, 30)

    def count(filters, or_filters=None):
        return len(frappe.get_all("Asset Maintenance Log", filters=filters,
                                  or_filters=or_filters, fields=["name"],
                                  limit_page_length=0))

    open_status = list(OPEN_STATUSES)
    kpis = {
        "overdue": count(
            [["custom_operational_status", "=", OP_OVERDUE]],
        ) or count([["maintenance_status", "=", "Overdue"]]),
        "due_today": count([["due_date", "=", today],
                            ["maintenance_status", "in", ["Planned", "Overdue"]]]),
        "due_this_week": count([["due_date", "between", [today, week]],
                                ["maintenance_status", "in", ["Planned", "Overdue"]]]),
        "unassigned": count([["maintenance_status", "in", ["Planned", "Overdue"]],
                             ["custom_assigned_technician", "in", ["", None]]]),
        "waiting_for_parts": count(
            [["custom_operational_status", "=", "Waiting for Parts"]]),
        "pending_verification": count(
            [["custom_operational_status", "=", OP_PENDING_VERIFICATION]]),
        "critical_breakdowns": len(frappe.get_all(
            "Asset Breakdown",
            filters={"severity": "Critical",
                     "status": ["not in", ["Resolved", "Cancelled"]]},
            fields=["name"])),
    }

    # Work list for the active view.
    view_filters = {
        "today": [["due_date", "=", today]],
        "this_week": [["due_date", "between", [today, week]]],
        "next_30": [["due_date", "between", [today, month]]],
    }.get(view, [["due_date", "between", [today, week]]])

    logs = frappe.get_all(
        "Asset Maintenance Log", filters=view_filters, fields=LOG_FIELDS,
        order_by="due_date asc", limit_page_length=0)
    logs = [_enrich(l) for l in logs]

    return {"kpis": kpis, "logs": logs, "view": view, "server_date": today}


@frappe.whitelist()
def get_technicians():
    """Return users holding the Maintenance Technician role (for assignment)."""
    rows = frappe.get_all(
        "Has Role",
        filters={"role": "Maintenance Technician", "parenttype": "User"},
        fields=["parent as user"],
    )
    out = []
    for r in rows:
        full = frappe.db.get_value("User", r.user, "full_name") or r.user
        if frappe.db.get_value("User", r.user, "enabled"):
            out.append({"user": r.user, "full_name": full})
    return out
