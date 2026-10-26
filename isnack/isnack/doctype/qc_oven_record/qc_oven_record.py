# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import oven_averages


class QCOvenRecord(Document):
    def validate(self):
        self.avg_zone1_temp, self.avg_zone2_temp, self.avg_moisture = oven_averages(self.readings or [])
        self.out_of_range_count = 0
