# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average, oven_averages


class QCPuffsExtruderRecord(Document):
    def validate(self):
        readings = self.puffs_readings or []
        self.avg_moisture_corn_content = average(readings, "moisture_corn_content")
        oven_readings = self.puffs_oven_readings or []
        self.avg_oven_temp = average(oven_readings, "oven_temp")
        self.avg_puffs_oven_moisture = average(oven_readings, "moisture")
        self.average_earlier_readings()

    def average_earlier_readings(self):
        """Readings recorded in the earlier layout (``readings``, ``oven_readings``),
        read only since the Puffs readings changed (2026-11): averaged as they were."""
        readings = self.readings or []
        self.avg_moisture = average(readings, "moisture_content")
        self.avg_density = average(readings, "product_density")
        self.out_of_range_count = sum(1 for r in readings if (r.moisture_content or 0) > 14)
        self.avg_oven_zone1_temp, self.avg_oven_zone2_temp, self.avg_oven_moisture = oven_averages(
            self.oven_readings or []
        )
