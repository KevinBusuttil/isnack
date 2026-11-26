# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from isnack.utils import earlier_layout

# Taken off the check in 2026-11: the film used and the material reconciliation.
RETIRED_FIELDS = ("film_type", "film_batch", "qty_issued", "qty_used", "qty_returned")

# The checks made before that keep them (earlier_layout) show them, with the
# variance worked out from them, in their Earlier Layout section. A check made
# since records neither, only the Qty Wasted.
EARLIER_FIELDS = RETIRED_FIELDS + ("variance", "variance_acceptable")

# What a check made since judges the packaging on (2026-11): its Overall Status
# is Pass only when all four are ticked, otherwise Fail.
CHECKS = ("print_quality_ok", "seal_integrity_ok", "label_correct", "artwork_matches")


class QCPackagingCheck(Document):
    def validate(self):
        self.keep_earlier_layout()
        if not self.in_earlier_layout():
            for fieldname in RETIRED_FIELDS:
                if isinstance(self.get(fieldname), str) and not self.get(fieldname).strip():
                    # nothing said (a stray space or line break): none kept out of sight
                    self.set(fieldname, None)
            if any(self.get(fieldname) for fieldname in RETIRED_FIELDS):
                # a form loaded before the change (desk, Duplicate, Quality Hub)
                # still offers them; the check would keep them out of sight
                frappe.throw(_("This page is out of date. Reload it and enter the check again."))
            # no material reconciliation, so no variance to judge: the four
            # checks give the result
            self.variance = 0
            self.variance_acceptable = 0
            self.overall_status = checks_result(self)
            return
        # a check made before is judged on its variance, as it was
        self.overall_status = None
        issued = self.qty_issued or 0
        used = self.qty_used or 0
        wasted = self.qty_wasted or 0
        returned = self.qty_returned or 0
        self.variance = issued - used - wasted - returned
        self.variance_acceptable = 1 if abs(self.variance) <= 0.5 else 0

    def in_earlier_layout(self) -> bool:
        return earlier_layout.in_earlier_layout(self)

    def keep_earlier_layout(self):
        earlier_layout.keep_mark(self)

    def before_print(self, settings=None):
        # the standard print does not evaluate depends_on, which hides the
        # Earlier Layout on the form: leave its fields out of a check made since
        # (in memory only; Frappe saves a blank number as 0)
        if not self.in_earlier_layout():
            for fieldname in EARLIER_FIELDS:
                self.set(fieldname, None)


def checks_result(check) -> str:
    """A check made since's Overall Status (a doc, a row or a dict): Pass when
    Print Quality OK, Seal Integrity OK, Packet Label Correct and Artwork
    Matches are all ticked, otherwise Fail."""
    return "Pass" if all(cint(check.get(fieldname)) for fieldname in CHECKS) else "Fail"


def belongs_to_earlier_layout(check) -> bool:
    """Whether a check made before 2026-11 (a row or a dict) keeps the earlier
    layout: a submitted or cancelled one does, keeping the result it was given,
    and so does a draft holding film or reconciliation. A draft with none of it
    is finished the new way."""
    return cint(check.get("docstatus")) != 0 or any(
        flt(check.get(f)) if f.startswith("qty_") else (check.get(f) or "").strip() for f in RETIRED_FIELDS
    )
