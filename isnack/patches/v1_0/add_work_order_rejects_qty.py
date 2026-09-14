"""Add the Work Order reject-quantity custom field the hub already writes to.

Three places read or write ``custom_rejects_qty`` — the Work Order banner,
``complete_work_order`` and ``_close_single_wo`` — but the field has never
existed on the site. The banner reads it as 0, ``complete_work_order`` swallows
the failure in a bare except, and ``_close_single_wo`` raises Unknown column
*after* the Manufacture Stock Entry has been submitted, leaving the entry posted
and the Work Order stuck short of Completed.

Idempotent: ``create_custom_fields`` updates an existing field in place and only
inserts a missing one, so this is safe to re-run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    if not frappe.db.exists("DocType", "Work Order"):
        return

    create_custom_fields(
        {
            "Work Order": [
                {
                    "fieldname": "custom_rejects_qty",
                    "label": "Rejects Qty",
                    "fieldtype": "Float",
                    "insert_after": "produced_qty",
                    "read_only": 1,
                    "no_copy": 1,
                    "non_negative": 1,
                    "allow_on_submit": 1,
                    "description": (
                        "Rejected output booked at End WO or Close Production. "
                        "Written by the Operator Hub; not editable by hand."
                    ),
                },
            ]
        },
        ignore_validate=True,
    )
