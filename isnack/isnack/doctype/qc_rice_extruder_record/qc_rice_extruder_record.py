# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average
from isnack.utils import earlier_readings

# The tables of the layout used before 2026-11, each with its label and the
# table that takes new readings instead.
EARLIER_TABLES = {
    "readings": ("Readings (Earlier Layout)", "Readings"),
    "oven_readings": ("Oven Readings (Earlier Layout)", "Oven / Slurry Readings"),
}

# The summary fields of each table, shown only when it has rows (depends_on).
SUMMARIES = {
    "rice_readings": ("avg_moisture_corn_content",),
    "rice_oven_readings": ("avg_oven_temp", "avg_rice_oven_moisture"),
    "readings": ("avg_moisture", "avg_density", "out_of_range_count"),
    "oven_readings": ("avg_oven_zone1_temp", "avg_oven_zone2_temp", "avg_oven_moisture"),
}


class QCRiceExtruderRecord(Document):
    def validate(self):
        self.close_earlier_tables()
        # a corn moisture, oven temperature or oven moisture of 0 is a reading
        # left blank
        readings = self.rice_readings or []
        self.avg_moisture_corn_content = average(readings, "moisture_corn_content", zero_is_blank=True)
        oven_readings = self.rice_oven_readings or []
        self.avg_oven_temp = average(oven_readings, "oven_temp", zero_is_blank=True)
        self.avg_rice_oven_moisture = average(oven_readings, "moisture", zero_is_blank=True)
        self.average_earlier_readings()

    def close_earlier_tables(self):
        earlier_readings.close_tables(self, EARLIER_TABLES)

    def average_earlier_readings(self):
        earlier_readings.set_averages(self)

    def before_print(self, settings=None):
        earlier_readings.leave_out_empty_summaries(self, SUMMARIES)
