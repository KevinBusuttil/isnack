"""Breakdown / corrective maintenance reporting."""

import frappe
from frappe import _


@frappe.whitelist()
def report_breakdown(asset, description, severity="Medium", issue_type=None,
                     machine_stopped=0, photo=None, linked_asset_maintenance_log=None):
    """Report an asset breakdown from the hub / QR page / task detail."""
    if not frappe.db.exists("Asset", asset):
        frappe.throw(_("Asset {0} not found.").format(asset))
    if not description:
        frappe.throw(_("A description is required."))

    machine_stopped = frappe.parse_json(machine_stopped) if isinstance(
        machine_stopped, str) else machine_stopped

    doc = frappe.get_doc({
        "doctype": "Asset Breakdown",
        "asset": asset,
        "description": description,
        "severity": severity,
        "issue_type": issue_type,
        "machine_stopped": 1 if machine_stopped else 0,
        "photo": photo,
        "linked_asset_maintenance_log": linked_asset_maintenance_log,
        "reported_by": frappe.session.user,
        "status": "Open",
    })
    doc.insert(ignore_permissions=True)
    _notify_managers(doc)
    return {"ok": True, "name": doc.name}


def _notify_managers(doc):
    """Notify maintenance managers of a new (esp. critical) breakdown."""
    recipients = frappe.get_all(
        "Has Role",
        filters={"role": "Maintenance Manager", "parenttype": "User"},
        pluck="parent",
    )
    recipients = [r for r in recipients if frappe.db.get_value("User", r, "enabled")]
    if not recipients:
        return
    subject = _("Breakdown reported: {0} ({1})").format(doc.asset_name or doc.asset,
                                                        doc.severity)
    from frappe.desk.doctype.notification_log.notification_log import (
        enqueue_create_notification,
    )
    enqueue_create_notification(recipients, {
        "type": "Alert",
        "document_type": "Asset Breakdown",
        "document_name": doc.name,
        "subject": subject,
        "from_user": frappe.session.user,
    })
