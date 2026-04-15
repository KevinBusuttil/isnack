# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCPuffsExtruderRecord(Document):
    def validate(self):
        readings = self.readings or []
        moistures = [r.moisture_content for r in readings if r.moisture_content is not None]
        densities = [r.product_density for r in readings if r.product_density is not None]
        self.avg_moisture = sum(moistures) / len(moistures) if moistures else 0
        self.avg_density = sum(densities) / len(densities) if densities else 0
        self.out_of_range_count = sum(1 for r in readings if (r.moisture_content or 0) > 14)
