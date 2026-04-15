# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCFryingLineRecord(Document):
    def validate(self):
        readings = self.readings or []
        oil_temps = [r.oil_temperature for r in readings if r.oil_temperature is not None]
        moistures = [r.product_moisture for r in readings if r.product_moisture is not None]
        self.avg_oil_temperature = sum(oil_temps) / len(oil_temps) if oil_temps else 0
        self.avg_product_moisture = sum(moistures) / len(moistures) if moistures else 0
        self.out_of_range_count = 0  # placeholder for future spec-based logic
