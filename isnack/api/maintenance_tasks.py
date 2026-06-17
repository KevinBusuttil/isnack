"""Scheduled (cron) jobs for the Maintenance Operations Hub.

All jobs are idempotent. Reminder de-duplication is tracked per log via
``custom_reminder_stage`` (the rule that last fired) and
``custom_last_reminder_on`` (the date it fired), so re-running the scheduler on
the same day never re-sends the same reminder.
"""

import frappe
from frappe.utils import nowdate, getdate, date_diff

from isnack.utils.maintenance import (
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    OP_OVERDUE,
    OP_PLANNED,
    OP_ASSIGNED,
    OP_ACKNOWLEDGED,
    OP_COMPLETED,
)

OPEN_LOG_FIELDS = [
    "name", "asset_name as asset", "task", "maintenance_type", "due_date",
    "maintenance_status", "custom_operational_status", "custom_assigned_technician",
    "task_assignee_email", "custom_reminder_stage", "custom_last_reminder_on",
]


def _open_logs():
    """Logs that still represent open maintenance work."""
    return frappe.get_all(
        "Asset Maintenance Log",
        filters=[
            ["maintenance_status", "in", ["Planned", "Overdue"]],
            ["due_date", "is", "set"],
        ],
        fields=OPEN_LOG_FIELDS,
        limit_page_length=0,
    )


def _is_open(log):
    status = log.get("custom_operational_status") or OP_PLANNED
    return status not in TERMINAL_STATUSES


def _role_users(role):
    users = frappe.get_all("Has Role",
                           filters={"role": role, "parenttype": "User"},
                           pluck="parent")
    return [u for u in users if frappe.db.get_value("User", u, "enabled")
            and u not in ("Administrator", "Guest")]


def _recipients_for_rule(log, rule):
    recipients = set()
    if rule.notify_technician:
        tech = log.get("custom_assigned_technician") or log.get("task_assignee_email")
        if tech and frappe.db.exists("User", tech):
            recipients.add(tech)
    if rule.notify_maintenance_manager:
        recipients.update(_role_users("Maintenance Manager"))
    if rule.notify_operations_manager:
        ops = _role_users("Operations Manager") or _role_users("Maintenance Manager")
        recipients.update(ops)
    return list(recipients)


def _send(log, rule, recipients, subject):
    if not recipients:
        return
    channel = rule.notification_channel or "Notification Log"
    if channel in ("Notification Log", "Both"):
        from frappe.desk.doctype.notification_log.notification_log import (
            enqueue_create_notification,
        )
        enqueue_create_notification(recipients, {
            "type": "Alert",
            "document_type": "Asset Maintenance Log",
            "document_name": log["name"],
            "subject": subject,
        })
    if channel in ("Email", "Both"):
        emails = [frappe.db.get_value("User", u, "email") or u for u in recipients]
        try:
            frappe.sendmail(recipients=emails, subject=subject,
                            message=subject + "<br>" + frappe.utils.get_url_to_form(
                                "Asset Maintenance Log", log["name"]))
        except Exception:
            frappe.log_error(frappe.get_traceback(),
                             "Maintenance reminder email failed")


def _mark_sent(log, rule):
    frappe.db.set_value("Asset Maintenance Log", log["name"], {
        "custom_reminder_stage": rule.name,
        "custom_last_reminder_on": nowdate(),
    }, update_modified=False)


def _already_sent_today(log, rule):
    last_on = log.get("custom_last_reminder_on")
    return (log.get("custom_reminder_stage") == rule.name
            and last_on and getdate(last_on) == getdate(nowdate()))


def _process(kind):
    """kind = 'before' | 'after'."""
    rules = frappe.get_all(
        "Maintenance Escalation Rule",
        filters={"enabled": 1},
        fields=["name", "company", "days_before_due", "days_after_due",
                "notify_technician", "notify_maintenance_manager",
                "notify_operations_manager", "notification_channel",
                "repeat_daily_until_resolved"],
    )
    if not rules:
        return

    today = getdate(nowdate())
    logs = _open_logs()

    for log in logs:
        if not _is_open(log):
            continue
        diff = date_diff(getdate(log["due_date"]), today)  # >0 future, <0 past

        for rule in rules:
            matched = False
            if kind == "before" and diff >= 0:
                # Due-today rule has both zero; before-rules use days_before_due.
                if rule.days_before_due and diff == rule.days_before_due:
                    matched = True
                elif (not rule.days_before_due and not rule.days_after_due
                      and diff == 0):
                    matched = True
            elif kind == "after" and diff < 0:
                if rule.days_after_due and abs(diff) == rule.days_after_due:
                    matched = True
                elif rule.repeat_daily_until_resolved and rule.days_after_due \
                        and abs(diff) >= rule.days_after_due:
                    matched = True
            if not matched:
                continue
            if _already_sent_today(log, rule):
                continue

            recipients = _recipients_for_rule(log, rule)
            when = (f"due in {diff} day(s)" if diff > 0
                    else ("due today" if diff == 0 else f"overdue by {abs(diff)} day(s)"))
            subject = frappe._("Maintenance {0}: {1} — {2}").format(
                when, log.get("asset") or "", log.get("task") or log["name"])
            _send(log, rule, recipients, subject)
            _mark_sent(log, rule)
            # One rule per log per run is enough; stop at the first match.
            break

    frappe.db.commit()


def send_upcoming_maintenance_reminders():
    """Daily: notify about maintenance due soon / today."""
    _process("before")


def escalate_overdue_maintenance():
    """Daily: notify/escalate overdue maintenance."""
    _process("after")


def check_required_spare_parts():
    """Daily: refresh availability of required parts and flag shortages."""
    parts = frappe.get_all(
        "Maintenance Spare Part",
        filters={"part_type": "Required", "status": ["in", ["Required", "Requested"]]},
        fields=["name", "item_code", "source_warehouse", "required_qty",
                "asset_maintenance_log"],
        limit_page_length=0,
    )
    shortages = {}
    for p in parts:
        if not (p.item_code and p.source_warehouse):
            continue
        avail = frappe.db.get_value(
            "Bin", {"item_code": p.item_code, "warehouse": p.source_warehouse},
            "actual_qty") or 0
        frappe.db.set_value("Maintenance Spare Part", p.name, "available_qty",
                            avail, update_modified=False)
        if (p.required_qty or 0) > avail:
            shortages.setdefault(p.asset_maintenance_log, 0)
            shortages[p.asset_maintenance_log] += 1
    frappe.db.commit()
    return {"logs_with_shortages": len(shortages)}


def sync_operational_statuses():
    """Daily: keep custom_operational_status consistent with ERPNext core.

    - Open logs past their due date become Overdue.
    - Logs ERPNext marked Completed (e.g. via the standard form) but whose
      operational status is still open become Completed.
    """
    today = getdate(nowdate())

    overdue_candidates = frappe.get_all(
        "Asset Maintenance Log",
        filters=[
            ["maintenance_status", "in", ["Planned", "Overdue"]],
            ["due_date", "<", nowdate()],
            ["custom_operational_status", "in",
             [OP_PLANNED, OP_ASSIGNED, OP_ACKNOWLEDGED, ""]],
        ],
        pluck="name",
    )
    for name in overdue_candidates:
        frappe.db.set_value("Asset Maintenance Log", name,
                            "custom_operational_status", OP_OVERDUE,
                            update_modified=False)

    completed_candidates = frappe.get_all(
        "Asset Maintenance Log",
        filters=[
            ["maintenance_status", "=", "Completed"],
            ["custom_operational_status", "in",
             [OP_PLANNED, OP_ASSIGNED, OP_ACKNOWLEDGED, OP_OVERDUE, ""]],
        ],
        pluck="name",
    )
    for name in completed_candidates:
        frappe.db.set_value("Asset Maintenance Log", name,
                            "custom_operational_status", OP_COMPLETED,
                            update_modified=False)

    frappe.db.commit()
    return {"overdue": len(overdue_candidates), "completed": len(completed_candidates)}
