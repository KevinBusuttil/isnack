"""Shared helpers and constants for the Maintenance Operations Hub.

This layer sits on top of ERPNext's standard Asset Maintenance module. The
operational work item is the **Asset Maintenance Log**; we add a parallel
``custom_operational_status`` field rather than overloading ERPNext's standard
``maintenance_status`` (which ERPNext's own scheduler/controllers rely on).
"""

import frappe
from frappe.utils import getdate, nowdate, date_diff

# ---------------------------------------------------------------------------
# Operational statuses (custom_operational_status on Asset Maintenance Log)
# ---------------------------------------------------------------------------
OP_PLANNED = "Planned"
OP_ASSIGNED = "Assigned"
OP_ACKNOWLEDGED = "Acknowledged"
OP_IN_PROGRESS = "In Progress"
OP_WAITING_PARTS = "Waiting for Parts"
OP_WAITING_SHUTDOWN = "Waiting for Shutdown"
OP_COMPLETED = "Completed"
OP_COMPLETED_ISSUE = "Completed with Issue"
OP_CANNOT_COMPLETE = "Cannot Complete"
OP_SKIPPED = "Skipped"
OP_CANCELLED = "Cancelled"
OP_OVERDUE = "Overdue"
OP_PENDING_VERIFICATION = "Pending Verification"
OP_VERIFIED = "Verified"

OPERATIONAL_STATUSES = [
    OP_PLANNED,
    OP_ASSIGNED,
    OP_ACKNOWLEDGED,
    OP_IN_PROGRESS,
    OP_WAITING_PARTS,
    OP_WAITING_SHUTDOWN,
    OP_COMPLETED,
    OP_COMPLETED_ISSUE,
    OP_CANNOT_COMPLETE,
    OP_SKIPPED,
    OP_CANCELLED,
    OP_OVERDUE,
    OP_PENDING_VERIFICATION,
    OP_VERIFIED,
]

# Statuses that represent "the technician is done touching this work item".
TERMINAL_STATUSES = {
    OP_COMPLETED,
    OP_COMPLETED_ISSUE,
    OP_CANNOT_COMPLETE,
    OP_SKIPPED,
    OP_CANCELLED,
    OP_VERIFIED,
}

# Statuses that still count as "open work" for a technician/manager.
OPEN_STATUSES = {
    OP_PLANNED,
    OP_ASSIGNED,
    OP_ACKNOWLEDGED,
    OP_IN_PROGRESS,
    OP_WAITING_PARTS,
    OP_WAITING_SHUTDOWN,
    OP_OVERDUE,
    OP_PENDING_VERIFICATION,
}

# Statuses considered "completed by technician, awaiting/after verification".
COMPLETED_STATUSES = {
    OP_COMPLETED,
    OP_COMPLETED_ISSUE,
    OP_PENDING_VERIFICATION,
    OP_VERIFIED,
}

MAINTENANCE_TECHNICIAN_ROLE = "Maintenance Technician"
MAINTENANCE_MANAGER_ROLE = "Maintenance Manager"
MAINTENANCE_SUPERVISOR_ROLE = "Maintenance Supervisor"

MANAGER_ROLES = {
    MAINTENANCE_MANAGER_ROLE,
    MAINTENANCE_SUPERVISOR_ROLE,
    "System Manager",
}


# ---------------------------------------------------------------------------
# Role / permission helpers
# ---------------------------------------------------------------------------
def get_user_roles(user=None):
    return set(frappe.get_roles(user or frappe.session.user))


def is_manager(user=None):
    return bool(get_user_roles(user) & MANAGER_ROLES)


def assigned_technician(log_name):
    """Return the technician currently assigned to a maintenance log."""
    return frappe.db.get_value(
        "Asset Maintenance Log", log_name, "custom_assigned_technician"
    )


def ensure_log_access(log_name, write=False):
    """Server-side guard for technician-facing actions.

    Managers/supervisors may touch any log. A technician may only touch a log
    that is assigned to them. Raises ``frappe.PermissionError`` otherwise.
    """
    user = frappe.session.user
    if is_manager(user):
        return
    if assigned_technician(log_name) == user:
        return
    frappe.throw(
        frappe._("You are not assigned to this maintenance task."),
        frappe.PermissionError,
    )


# ---------------------------------------------------------------------------
# Status derivation / sync
# ---------------------------------------------------------------------------
def derive_operational_status(log):
    """Derive a sensible operational status from ERPNext's standard fields.

    Used as a one-directional fallback so that logs created by ERPNext (which
    only sets ``maintenance_status``) still surface correctly in the hub.
    Never overrides a status the operations layer has already advanced.
    """
    current = (log.get("custom_operational_status") or "").strip()
    std = (log.get("maintenance_status") or "").strip()

    # Respect any explicit operational status that is "further along".
    if current and current not in (OP_PLANNED, OP_OVERDUE, ""):
        return current

    if std == "Cancelled":
        return OP_CANCELLED
    if std == "Completed":
        return OP_COMPLETED if current not in COMPLETED_STATUSES else current

    # Open work: derive urgency from due date.
    due = log.get("due_date")
    if due and getdate(due) < getdate(nowdate()):
        return OP_OVERDUE
    if log.get("custom_assigned_technician"):
        return current or OP_ASSIGNED
    return current or OP_PLANNED


def urgency_bucket(log):
    """Classify an open log into a technician-hub bucket."""
    status = log.get("custom_operational_status") or OP_PLANNED
    if status in (OP_WAITING_PARTS,):
        return "waiting_for_parts"
    if status in (OP_IN_PROGRESS, OP_ACKNOWLEDGED, OP_WAITING_SHUTDOWN):
        return "in_progress"
    if status in COMPLETED_STATUSES or status in (OP_CANNOT_COMPLETE, OP_SKIPPED):
        return "completed"

    due = log.get("due_date")
    if not due:
        return "next_7_days"
    diff = date_diff(getdate(due), getdate(nowdate()))
    if diff < 0 or status == OP_OVERDUE:
        return "overdue"
    if diff == 0:
        return "due_today"
    if diff <= 7:
        return "next_7_days"
    return "later"
