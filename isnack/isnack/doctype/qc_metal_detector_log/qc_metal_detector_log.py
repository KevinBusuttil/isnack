# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCMetalDetectorLog(Document):
    def validate(self):
        tests = self.tests or []
        if tests:
            self.all_tests_passed = 1 if all(t.detected for t in tests) else 0
        else:
            self.all_tests_passed = 0
