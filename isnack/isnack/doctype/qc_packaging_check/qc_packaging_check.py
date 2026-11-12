# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document

# Recorded on the checks made before 2026-11 (earlier_layout), in their Earlier
# Layout section: the film used and the material reconciliation. A check made
# since records neither, only the Qty Wasted.
EARLIER_FIELDS = (
    "film_type",
    "film_batch",
    "qty_issued",
    "qty_used",
    "qty_returned",
    "variance",
    "variance_acceptable",
)


class QCPackagingCheck(Document):
    def validate(self):
        if not self.earlier_layout:
            # no material reconciliation, so no variance to judge
            self.variance = 0
            self.variance_acceptable = 0
            return
        issued = self.qty_issued or 0
        used = self.qty_used or 0
        wasted = self.qty_wasted or 0
        returned = self.qty_returned or 0
        self.variance = issued - used - wasted - returned
        self.variance_acceptable = 1 if abs(self.variance) <= 0.5 else 0

    def before_print(self, settings=None):
        # the standard print does not evaluate depends_on, which hides the
        # Earlier Layout on the form: leave its fields out of a check made since
        # (in memory only; Frappe saves a blank number as 0)
        if not self.earlier_layout:
            for fieldname in EARLIER_FIELDS:
                self.set(fieldname, None)
