# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCOvenRecord(Document):
    def validate(self):
        readings = self.readings or []
        z1 = [r.zone_1_temp for r in readings if r.zone_1_temp is not None]
        z2 = [r.zone_2_temp for r in readings if r.zone_2_temp is not None]
        moist = [r.moisture for r in readings if r.moisture is not None]
        self.avg_zone1_temp = sum(z1) / len(z1) if z1 else 0
        self.avg_zone2_temp = sum(z2) / len(z2) if z2 else 0
        self.avg_moisture = sum(moist) / len(moist) if moist else 0
        self.out_of_range_count = 0
