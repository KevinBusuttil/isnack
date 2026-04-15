# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCTastingRecord(Document):
    def validate(self):
        scores = self.scores or []
        overall_scores = [s.overall_score for s in scores if s.overall_score is not None]
        self.avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0
        self.min_score = min(overall_scores) if overall_scores else 0
        threshold = self.pass_threshold or 3.0
        self.overall_status = "Pass" if self.avg_overall >= threshold else "Fail"
