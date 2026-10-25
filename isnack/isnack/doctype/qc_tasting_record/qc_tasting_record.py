# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class QCTastingRecord(Document):
    def validate(self):
        # Frappe keeps a Rating as the fraction of stars given (4 of 5 stars is
        # 0.8, clamped to 0..1 on save), while the averages and the pass
        # threshold read in stars: a threshold of 3.0 means 3 stars.
        out_of = stars_out_of()
        # an overall score of 0 is a taster who gave no rating, not a zero
        overall_scores = [flt(s.overall_score) * out_of for s in self.scores or [] if flt(s.overall_score) > 0]
        self.avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0
        self.min_score = min(overall_scores) if overall_scores else 0
        threshold = flt(self.pass_threshold) or 3.0
        self.overall_status = "Pass" if overall_scores and self.avg_overall >= threshold else "Fail"


def stars_out_of() -> int:
    """How many stars the tasting score ratings have (the Rating field's options, 5 by default)."""
    field = frappe.get_meta("QC Tasting Score").get_field("overall_score")
    return cint(field.options if field else 0) or 5
