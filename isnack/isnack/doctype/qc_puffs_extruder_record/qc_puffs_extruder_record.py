# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average, oven_averages

# The tables of the layout used before 2026-11, each with its label and the
# table that takes new readings instead.
EARLIER_TABLES = {
    "readings": ("Readings (Earlier Layout)", "Readings"),
    "oven_readings": ("Oven Readings (Earlier Layout)", "Oven Readings"),
}

# The summary fields of each table, shown only when it has rows (depends_on).
SUMMARIES = {
    "puffs_readings": ("avg_moisture_corn_content",),
    "puffs_oven_readings": ("avg_oven_temp", "avg_puffs_oven_moisture"),
    "readings": ("avg_moisture", "avg_density", "out_of_range_count"),
    "oven_readings": ("avg_oven_zone1_temp", "avg_oven_zone2_temp", "avg_oven_moisture"),
}


class QCPuffsExtruderRecord(Document):
    def validate(self):
        self.close_earlier_tables()
        # a corn moisture, oven temperature or oven moisture of 0 is a reading
        # left blank
        readings = self.puffs_readings or []
        self.avg_moisture_corn_content = average(readings, "moisture_corn_content", zero_is_blank=True)
        oven_readings = self.puffs_oven_readings or []
        self.avg_oven_temp = average(oven_readings, "oven_temp", zero_is_blank=True)
        self.avg_puffs_oven_moisture = average(oven_readings, "moisture", zero_is_blank=True)
        self.average_earlier_readings()

    def close_earlier_tables(self):
        """The earlier tables take no new rows. Their rows can be corrected or
        removed on a draft or an amendment, but new readings go in Readings and
        Oven Readings. The form hides Add Row, yet Tab out of the last cell, the
        grid's shortcuts or a paste still add rows: a blank one is dropped, one
        with a value refused."""
        before = None if self.is_new() else self.get_doc_before_save()
        amended = frappe.get_doc(self.doctype, self.amended_from) if self.is_new() and self.amended_from else None
        for fieldname, (label, instead) in EARLIER_TABLES.items():
            rows = list(self.get(fieldname) or [])
            if before is not None:
                kept = {row.name for row in before.get(fieldname) or []}
                added = [row for row in rows if row.name not in kept]
            else:
                # a new record: an amendment brings the rows of the record it amends
                added = rows
            blank = {id(row) for row in added if _is_blank(row)}
            if blank:
                rows = [row for row in rows if id(row) not in blank]
                for idx, row in enumerate(rows, 1):
                    row.idx = idx
                self.set(fieldname, rows)
                added = [row for row in added if id(row) not in blank]
            allowed = len(amended.get(fieldname) or []) if amended else 0
            if len(added) > allowed:
                frappe.throw(
                    _("{0} takes no new rows: remove the new ones and enter new readings in {1}.").format(
                        _(label), _(instead)
                    )
                )

    def average_earlier_readings(self):
        """Readings recorded in the earlier layout (``readings``, ``oven_readings``),
        before the Puffs readings changed (2026-11): averaged as they were."""
        readings = self.readings or []
        self.avg_moisture = average(readings, "moisture_content")
        self.avg_density = average(readings, "product_density")
        self.out_of_range_count = sum(1 for r in readings if (r.moisture_content or 0) > 14)
        self.avg_oven_zone1_temp, self.avg_oven_zone2_temp, self.avg_oven_moisture = oven_averages(
            self.oven_readings or []
        )

    def before_print(self, settings=None):
        """The standard print does not evaluate depends_on: leave out the
        summary of a table without rows, as the form does (in memory only)."""
        for table, fieldnames in SUMMARIES.items():
            if not self.get(table):
                for fieldname in fieldnames:
                    self.set(fieldname, None)


def _is_blank(row):
    """No reading in the row. A 0 reads as none, as Frappe saves a blank number
    as 0; a time is not looked at, as Frappe fills a blank Time with the time
    of the save."""
    return not any(
        row.get(df.fieldname)
        for df in frappe.get_meta(row.doctype).fields
        if df.fieldtype not in no_value_fields and df.fieldtype != "Time"
    )
