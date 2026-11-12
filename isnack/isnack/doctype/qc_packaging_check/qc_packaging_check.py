# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

# Taken off the check in 2026-11: the film used and the material reconciliation.
RETIRED_FIELDS = ("film_type", "film_batch", "qty_issued", "qty_used", "qty_returned")

# The checks made before that keep them (earlier_layout) show them, with the
# variance worked out from them, in their Earlier Layout section. A check made
# since records neither, only the Qty Wasted.
EARLIER_FIELDS = RETIRED_FIELDS + ("variance", "variance_acceptable")


class QCPackagingCheck(Document):
    def validate(self):
        self.keep_earlier_layout()
        if not self.in_earlier_layout():
            if any(self.get(fieldname) for fieldname in RETIRED_FIELDS):
                # a form loaded before the change (desk, Duplicate, Quality Hub)
                # still offers them; the check would keep them out of sight
                frappe.throw(_("This page is out of date. Reload it and enter the check again."))
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

    def in_earlier_layout(self) -> bool:
        # until the migrate adds the mark, every check is one made before
        return bool(cint(self.get("earlier_layout"))) if self.meta.has_field("earlier_layout") else True

    def keep_earlier_layout(self):
        """The mark is set by the patch and carried by Amend, never cleared. A
        form loaded before the migrate does not know it and sends none: keep the
        one the saved check, or the check amended, has."""
        if self.get("earlier_layout") or not self.meta.has_field("earlier_layout"):
            return
        if self.is_new():
            kept = self.amended_from and frappe.db.get_value(self.doctype, self.amended_from, "earlier_layout")
        else:
            before = self.get_doc_before_save()
            kept = before and before.get("earlier_layout")
        if cint(kept):
            self.earlier_layout = 1

    def before_print(self, settings=None):
        # the standard print does not evaluate depends_on, which hides the
        # Earlier Layout on the form: leave its fields out of a check made since
        # (in memory only; Frappe saves a blank number as 0)
        if not self.in_earlier_layout():
            for fieldname in EARLIER_FIELDS:
                self.set(fieldname, None)


def belongs_to_earlier_layout(check) -> bool:
    """Whether a check made before 2026-11 (a row or a dict) keeps the earlier
    layout: a submitted or cancelled one does, keeping the result it was given,
    and so does a draft holding film or reconciliation. A draft with none of it
    is finished the new way."""
    return cint(check.get("docstatus")) != 0 or any(
        flt(check.get(f)) if f.startswith("qty_") else (check.get(f) or "").strip() for f in RETIRED_FIELDS
    )
