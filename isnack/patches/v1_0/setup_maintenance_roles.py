"""Create the maintenance roles used by the Operations Hub (idempotent)."""

import frappe

ROLES = [
    "Maintenance Technician",
    "Maintenance Manager",
    "Maintenance Supervisor",
]


def execute():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": role,
                "desk_access": 1,
            }).insert(ignore_permissions=True)
    frappe.db.commit()
