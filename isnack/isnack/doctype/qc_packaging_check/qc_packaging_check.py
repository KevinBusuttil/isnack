# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCPackagingCheck(Document):
    def validate(self):
        issued = self.qty_issued or 0
        used = self.qty_used or 0
        wasted = self.qty_wasted or 0
        returned = self.qty_returned or 0
        self.variance = issued - used - wasted - returned
        self.variance_acceptable = 1 if abs(self.variance) <= 0.5 else 0
