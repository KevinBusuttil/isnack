# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average


class QCFryingLineRecord(Document):
    def validate(self):
        # an oil temperature or moisture of 0 is a reading left blank (Frappe
        # saves a blank Float as 0), as on the extruder records: left out of
        # the average, so saving again or submitting gives the same one
        readings = self.readings or []
        self.avg_oil_temperature = average(readings, "oil_temperature", zero_is_blank=True)
        self.avg_product_moisture = average(readings, "product_moisture", zero_is_blank=True)
        self.out_of_range_count = 0  # placeholder for future spec-based logic
