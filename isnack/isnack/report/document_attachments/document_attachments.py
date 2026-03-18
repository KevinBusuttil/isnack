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
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    source = filters.get("source")

    site_url = get_url()
    url_expr = f"CASE WHEN f.file_url LIKE 'http%%' THEN f.file_url ELSE CONCAT('{site_url}', f.file_url) END"

    non_si_doctypes = ["Journal Entry", "Landed Cost Voucher", "Purchase Invoice"]
    run_non_si = not source or source in non_si_doctypes
    run_si = not source or source == "Service Invoice"

    parts = []
    values = []

    if run_non_si:
        posting_date_expr = "COALESCE(je.posting_date, pi.posting_date, lcv.posting_date)"

        non_si_conds = []
        non_si_vals = []

        if source:
            non_si_conds.append("f.attached_to_doctype = %s")
            non_si_vals.append(source)
        else:
            placeholders = ", ".join(["%s"] * len(non_si_doctypes))
            non_si_conds.append(f"f.attached_to_doctype IN ({placeholders})")
            non_si_vals.extend(non_si_doctypes)

        if from_date:
            non_si_conds.append(f"{posting_date_expr} >= %s")
            non_si_vals.append(from_date)
        if to_date:
            non_si_conds.append(f"{posting_date_expr} <= %s")
            non_si_vals.append(to_date)

        where_clause = " AND ".join(non_si_conds)

        parts.append(f"""
            SELECT
                f.attached_to_doctype,
                f.attached_to_name,
                {url_expr} AS full_url,
                f.file_name,
                f.is_private,
                {posting_date_expr} AS posting_date,
                f.creation
            FROM `tabFile` f
            LEFT JOIN `tabJournal Entry` je
                ON f.attached_to_doctype = 'Journal Entry' AND f.attached_to_name = je.name
            LEFT JOIN `tabPurchase Invoice` pi
                ON f.attached_to_doctype = 'Purchase Invoice' AND f.attached_to_name = pi.name
            LEFT JOIN `tabLanded Cost Voucher` lcv
                ON f.attached_to_doctype = 'Landed Cost Voucher' AND f.attached_to_name = lcv.name
            WHERE f.attached_to_doctype IS NOT NULL
            AND f.attached_to_name IS NOT NULL
            AND f.is_folder = 0
            AND {where_clause}
        """)
        values.extend(non_si_vals)

    if run_si:
        si_conds = ["f.attached_to_doctype = 'Service Invoice'"]
        si_vals = []

        if from_date or to_date:
            exists_conds = ["sii.parent = f.attached_to_name"]
            if from_date:
                exists_conds.append("sii.`date` >= %s")
                si_vals.append(from_date)
            if to_date:
                exists_conds.append("sii.`date` <= %s")
                si_vals.append(to_date)
            exists_where = " AND ".join(exists_conds)
            si_conds.append(
                f"EXISTS (SELECT 1 FROM `tabService Invoice Items` sii WHERE {exists_where})"
            )

        si_where = " AND ".join(si_conds)

        parts.append(f"""
            SELECT
                f.attached_to_doctype,
                f.attached_to_name,
                {url_expr} AS full_url,
                f.file_name,
                f.is_private,
                (SELECT MIN(sii2.`date`) FROM `tabService Invoice Items` sii2
                    WHERE sii2.parent = f.attached_to_name) AS posting_date,
                f.creation
            FROM `tabFile` f
            WHERE f.attached_to_doctype IS NOT NULL
            AND f.attached_to_name IS NOT NULL
            AND f.is_folder = 0
            AND {si_where}
        """)
        values.extend(si_vals)

    if not parts:
        return []

    union_sql = " UNION ALL ".join(f"({p})" for p in parts)
    final_sql = f"SELECT * FROM ({union_sql}) AS combined ORDER BY posting_date IS NULL ASC, posting_date DESC"

    return frappe.db.sql(final_sql, values)


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
            "label": _("Posting Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 120,
        },
        {
            "label": _("Creation Date"),
            "fieldname": "creation",
            "fieldtype": "Datetime",
            "width": 180,
        },
    ]
