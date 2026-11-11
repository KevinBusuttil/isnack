# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

# The scores a taster gives, each a Rating; their Overall % is worked out from them.
CRITERIA = ("appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score")

# The average Overall % a tasting needs to pass: 3 of 5 stars.
PASS_THRESHOLD_PERCENT = 60.0


class QCTastingRecord(Document):
    def validate(self):
        # Overall % of each taster; one who gave no score at all is left out of
        # the average, not counted as 0
        scored = []
        for row in self.scores or []:
            row.overall_percent = overall_percent(row)
            if any(flt(row.get(f)) > 0 for f in CRITERIA):
                scored.append(row.overall_percent)
        self.avg_overall = flt(sum(scored) / len(scored), 2) if scored else 0
        self.min_score = min(scored) if scored else 0
        self.overall_status = "Pass" if scored and self.avg_overall >= PASS_THRESHOLD_PERCENT else "Fail"


def overall_percent(row) -> float:
    """A taster's scores as a percentage of full marks: the stars given on
    Shape, Colour, Smell, Taste and Texture over 5 x 5. A score left blank
    counts as 0.

    Frappe keeps a Rating as the fraction of stars given (4 of 5 stars is 0.8),
    so full marks are a fraction of 1 on each score.
    """
    return flt(sum(min(flt(row.get(f)), 1) for f in CRITERIA) / len(CRITERIA) * 100, 2)


def stars_out_of() -> int:
    """How many stars the tasting score ratings have (the Rating field's options, 5 by default)."""
    field = frappe.get_meta("QC Tasting Score").get_field("appearance_score")
    return cint(field.options if field else 0) or 5
