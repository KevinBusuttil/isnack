# Copyright (c) 2025, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_url


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_data(filters):
    conditions = ""
    values = []

    all_doctypes = ["Journal Entry", "Landed Cost Voucher", "Purchase Invoice", "Service Invoice"]

    source = filters.get("source")
    if source:
        conditions += " AND f.attached_to_doctype = %s"
        values.append(source)
    else:
        placeholders = ", ".join(["%s"] * len(all_doctypes))
        conditions += f" AND f.attached_to_doctype IN ({placeholders})"
        values.extend(all_doctypes)

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    if from_date:
        conditions += " AND f.creation >= %s"
        values.append(from_date)
    if to_date:
        conditions += " AND f.creation <= %s"
        values.append(f"{to_date} 23:59:59")

    site_url = get_url()

    sql = f"""
        SELECT
            f.attached_to_doctype,
            f.attached_to_name,
            CASE
                WHEN f.file_url LIKE 'http%%' THEN f.file_url
                ELSE CONCAT('{site_url}', f.file_url)
            END AS full_url,
            f.file_name,
            f.is_private,
            f.creation
        FROM `tabFile` f
        WHERE f.attached_to_doctype IS NOT NULL
        AND f.attached_to_name IS NOT NULL
        AND f.is_folder = 0
        {conditions}
        ORDER BY f.creation DESC
    """

    data = frappe.db.sql(sql, values)
    return data


def get_columns():
    return [
        {
            "label": _("Attached To DocType"),
            "fieldname": "attached_to_doctype",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": _("Attached To Name"),
            "fieldname": "attached_to_name",
            "fieldtype": "Dynamic Link",
            "options": "attached_to_doctype",
            "width": 200,
        },
        {
            "label": _("File URL"),
            "fieldname": "full_url",
            "fieldtype": "Data",
            "width": 400,
        },
        {
            "label": _("File Name"),
            "fieldname": "file_name",
            "fieldtype": "Data",
            "width": 250,
        },
        {
            "label": _("Is Private"),
            "fieldname": "is_private",
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "label": _("Creation Date"),
            "fieldname": "creation",
            "fieldtype": "Datetime",
            "width": 180,
        },
    ]
