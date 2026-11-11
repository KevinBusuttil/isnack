# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Readings kept in an extruder record's earlier layout.

The Puffs (QCB) and Rice (QCC) Extruder Records took their readings in the
shared QC Extruder Reading and QC Oven Reading until 2026-11, when each got
tables of its own. Their earlier tables (``readings``, ``oven_readings``) keep
the rows recorded in them, in an Earlier Readings section shown only when they
have rows: those rows can be corrected or removed on a draft or an amendment,
but the tables take no new rows.
"""

import frappe
from frappe import _
from frappe.model import no_value_fields

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average, oven_averages


def set_averages(doc):
    """The averages of the earlier tables, as they were computed before 2026-11."""
    readings = doc.readings or []
    doc.avg_moisture = average(readings, "moisture_content")
    doc.avg_density = average(readings, "product_density")
    doc.out_of_range_count = sum(1 for r in readings if (r.moisture_content or 0) > 14)
    doc.avg_oven_zone1_temp, doc.avg_oven_zone2_temp, doc.avg_oven_moisture = oven_averages(doc.oven_readings or [])


def close_tables(doc, tables):
    """Keep new rows out of the earlier ``tables`` ({fieldname: (label, label
    of the table that takes new readings)}).

    The form hides Add Row (cannot_add_rows), yet Tab out of the last cell, the
    grid's shortcuts or a paste still add rows: a blank one is dropped, one with
    a value refused. A row is new when the record saved has no row of its name;
    on a new record every row is, and an amendment may keep as many as the
    record it amends.
    """
    before = None if doc.is_new() else doc.get_doc_before_save()
    amended = frappe.get_doc(doc.doctype, doc.amended_from) if doc.is_new() and doc.amended_from else None
    for fieldname, (label, instead) in tables.items():
        rows = list(doc.get(fieldname) or [])
        if before is not None:
            kept = {row.name for row in before.get(fieldname) or []}
            added = [row for row in rows if row.name not in kept]
        else:
            added = rows
        blank = {id(row) for row in added if _is_blank(row)}
        if blank:
            rows = [row for row in rows if id(row) not in blank]
            for idx, row in enumerate(rows, 1):
                row.idx = idx
            doc.set(fieldname, rows)
            added = [row for row in added if id(row) not in blank]
        allowed = len(amended.get(fieldname) or []) if amended else 0
        if len(added) > allowed:
            frappe.throw(
                _("{0} takes no new rows: remove the new ones and enter new readings in {1}.").format(
                    _(label), _(instead)
                )
            )


def leave_out_empty_summaries(doc, summaries):
    """For print: blank the summary fields of each table without rows
    ({table: (summary fieldnames)}), in memory only. The standard print does
    not evaluate depends_on, which hides them on the form."""
    for table, fieldnames in summaries.items():
        if not doc.get(table):
            for fieldname in fieldnames:
                doc.set(fieldname, None)


def _is_blank(row):
    """No reading in the row. A 0 reads as none, as Frappe saves a blank number
    as 0; a time is not looked at, as Frappe fills a blank Time with the time
    of the save."""
    return not any(
        row.get(df.fieldname)
        for df in frappe.get_meta(row.doctype).fields
        if df.fieldtype not in no_value_fields and df.fieldtype != "Time"
    )
