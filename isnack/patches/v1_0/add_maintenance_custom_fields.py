"""Add the Maintenance Operations Hub custom fields to standard ERPNext doctypes.

Idempotent: ``create_custom_fields`` updates existing fields in place and only
inserts missing ones, so the patch is safe to re-run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OPERATIONAL_STATUS_OPTIONS = "\n".join([
    "Planned",
    "Assigned",
    "Acknowledged",
    "In Progress",
    "Waiting for Parts",
    "Waiting for Shutdown",
    "Completed",
    "Completed with Issue",
    "Cannot Complete",
    "Skipped",
    "Cancelled",
    "Overdue",
    "Pending Verification",
    "Verified",
])


def execute():
    if not frappe.db.exists("DocType", "Asset Maintenance Log"):
        # ERPNext (assets) not installed on this site; nothing to do.
        return

    custom_fields = {
        "Asset Maintenance Log": [
            {
                "fieldname": "custom_operations_section",
                "label": "Maintenance Operations",
                "fieldtype": "Section Break",
                "insert_after": "maintenance_status",
                "collapsible": 0,
            },
            {
                "fieldname": "custom_operational_status",
                "label": "Operational Status",
                "fieldtype": "Select",
                "options": OPERATIONAL_STATUS_OPTIONS,
                "insert_after": "custom_operations_section",
                "in_standard_filter": 1,
                "in_list_view": 1,
                "default": "Planned",
            },
            {
                "fieldname": "custom_assigned_technician",
                "label": "Assigned Technician",
                "fieldtype": "Link",
                "options": "User",
                "insert_after": "custom_operational_status",
                "in_standard_filter": 1,
            },
            {
                "fieldname": "custom_estimated_duration_mins",
                "label": "Estimated Duration (mins)",
                "fieldtype": "Int",
                "insert_after": "custom_assigned_technician",
            },
            {
                "fieldname": "custom_col_ops_1",
                "fieldtype": "Column Break",
                "insert_after": "custom_estimated_duration_mins",
            },
            {
                "fieldname": "custom_started_on",
                "label": "Started On",
                "fieldtype": "Datetime",
                "insert_after": "custom_col_ops_1",
                "read_only": 1,
            },
            {
                "fieldname": "custom_completed_on",
                "label": "Completed On",
                "fieldtype": "Datetime",
                "insert_after": "custom_started_on",
                "read_only": 1,
            },
            {
                "fieldname": "custom_safety_warning",
                "label": "Safety Warning",
                "fieldtype": "Small Text",
                "insert_after": "custom_completed_on",
            },
            {
                "fieldname": "custom_completion_section",
                "label": "Completion & Verification",
                "fieldtype": "Section Break",
                "insert_after": "custom_safety_warning",
                "collapsible": 1,
            },
            {
                "fieldname": "custom_completion_notes",
                "label": "Completion Notes",
                "fieldtype": "Small Text",
                "insert_after": "custom_completion_section",
            },
            {
                "fieldname": "custom_requires_verification",
                "label": "Requires Verification",
                "fieldtype": "Check",
                "insert_after": "custom_completion_notes",
            },
            {
                "fieldname": "custom_verified_by",
                "label": "Verified By",
                "fieldtype": "Link",
                "options": "User",
                "insert_after": "custom_requires_verification",
                "read_only": 1,
            },
            {
                "fieldname": "custom_col_ver_1",
                "fieldtype": "Column Break",
                "insert_after": "custom_verified_by",
            },
            {
                "fieldname": "custom_verified_on",
                "label": "Verified On",
                "fieldtype": "Datetime",
                "insert_after": "custom_col_ver_1",
                "read_only": 1,
            },
            {
                "fieldname": "custom_verification_comments",
                "label": "Verification Comments",
                "fieldtype": "Small Text",
                "insert_after": "custom_verified_on",
            },
            {
                "fieldname": "custom_tracking_section",
                "label": "Reminder Tracking",
                "fieldtype": "Section Break",
                "insert_after": "custom_verification_comments",
                "collapsible": 1,
            },
            {
                "fieldname": "custom_checklist_generated",
                "label": "Checklist Generated",
                "fieldtype": "Check",
                "insert_after": "custom_tracking_section",
                "read_only": 1,
            },
            {
                "fieldname": "custom_reminder_stage",
                "label": "Last Reminder Stage",
                "fieldtype": "Data",
                "insert_after": "custom_checklist_generated",
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "fieldname": "custom_last_reminder_on",
                "label": "Last Reminder On",
                "fieldtype": "Date",
                "insert_after": "custom_reminder_stage",
                "read_only": 1,
                "no_copy": 1,
            },
        ],
        "Asset Maintenance Task": [
            {
                "fieldname": "custom_estimated_duration_mins",
                "label": "Estimated Duration (mins)",
                "fieldtype": "Int",
                "insert_after": "maintenance_status",
            },
            {
                "fieldname": "custom_safety_warning",
                "label": "Safety Warning",
                "fieldtype": "Small Text",
                "insert_after": "custom_estimated_duration_mins",
            },
            {
                "fieldname": "custom_requires_verification",
                "label": "Requires Verification",
                "fieldtype": "Check",
                "insert_after": "custom_safety_warning",
            },
        ],
        "Asset": [
            {
                "fieldname": "custom_maintenance_barcode",
                "label": "Maintenance Barcode / QR",
                "fieldtype": "Data",
                "insert_after": "asset_name",
                "unique": 0,
                "description": "Optional code used by the Maintenance Hub scan lookup.",
            },
        ],
    }

    # Only target doctypes that exist on this site.
    custom_fields = {
        dt: fields for dt, fields in custom_fields.items()
        if frappe.db.exists("DocType", dt)
    }
    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()
