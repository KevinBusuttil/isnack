"""Lightweight hooks on ERPNext's Asset Maintenance Log.

We do NOT override the doctype class — only attach validate-time defaults via
doc_events so the operations layer stays upgrade-safe.
"""

import frappe

from isnack.utils.maintenance import derive_operational_status, COMPLETED_STATUSES


def set_operational_defaults(doc, method=None):
    """Ensure every log carries a sensible custom_operational_status.

    One-directional: derives from ERPNext's standard fields only when our field
    is empty or still at a passive default, never clobbering an advanced state.
    """
    if not hasattr(doc, "custom_operational_status"):
        return

    log = {
        "custom_operational_status": doc.get("custom_operational_status"),
        "maintenance_status": doc.get("maintenance_status"),
        "due_date": doc.get("due_date"),
        "custom_assigned_technician": doc.get("custom_assigned_technician"),
    }
    derived = derive_operational_status(log)
    if not doc.get("custom_operational_status"):
        doc.custom_operational_status = derived
    elif doc.get("maintenance_status") == "Cancelled":
        doc.custom_operational_status = "Cancelled"
    elif (doc.get("maintenance_status") == "Completed"
          and doc.custom_operational_status not in COMPLETED_STATUSES
          and doc.custom_operational_status not in ("Cannot Complete", "Skipped")):
        doc.custom_operational_status = "Completed"
