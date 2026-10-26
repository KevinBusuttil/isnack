# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import oven_averages


class QCPuffsExtruderRecord(Document):
    def validate(self):
        readings = self.readings or []
        moistures = [r.moisture_content for r in readings if r.moisture_content is not None]
        densities = [r.product_density for r in readings if r.product_density is not None]
        self.avg_moisture = sum(moistures) / len(moistures) if moistures else 0
        self.avg_density = sum(densities) / len(densities) if densities else 0
        self.out_of_range_count = sum(1 for r in readings if (r.moisture_content or 0) > 14)
        self.avg_oven_zone1_temp, self.avg_oven_zone2_temp, self.avg_oven_moisture = oven_averages(
            self.oven_readings or []
        )
