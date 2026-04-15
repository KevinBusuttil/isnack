# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCReceivingRecord(Document):
    def validate(self):
        if (self.arrival_temperature is not None and
                self.acceptable_range_min is not None and
                self.acceptable_range_max is not None):
            self.temp_pass = 1 if self.acceptable_range_min <= self.arrival_temperature <= self.acceptable_range_max else 0
