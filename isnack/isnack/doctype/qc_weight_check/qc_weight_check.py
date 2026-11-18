# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt

from isnack.utils import earlier_layout

# Taken off the check in 2026-11: the TU1 and TU2 limits and the record's
# Remarks (a check made since has Remarks on each sample), and each sample's
# tare.
RETIRED_FIELDS = ("tu1_limit", "tu2_limit", "remarks")
RETIRED_SAMPLE_FIELDS = ("tare_weight",)

# The checks made before that keep them (earlier_layout) show them, with what
# was worked out from them and the Overall Status entered, in their Earlier
# Layout section.
EARLIER_FIELDS = ("tu1_limit", "tu2_limit", "tu1_failures", "tu2_failures", "overall_status", "remarks")
EARLIER_SAMPLE_FIELDS = ("tare_weight", "net_weight", "in_range")

# Taken off the check after them: the Item Code and Batch No (the Work Order
# names the product). They stay on the doctype, read-only and kept off a
# Duplicate, so a check that holds them (made before, or an amendment or a
# restore of one) shows them and nothing fills them in on a new one.


class QCWeightCheck(Document):
    def validate(self):
        earlier_layout.keep_mark(self)
        earlier = earlier_layout.in_earlier_layout(self)
        samples = self.samples or []
        if not earlier:
            self.refuse_retired_values()
            self.require_sample_status()
            self.require_nominal_weight()
            self.require_sample_figures()

        tu1 = self.tu1_limit or 0
        tu2 = self.tu2_limit or 0
        for s in samples:
            s.net_weight = (s.gross_weight or 0) - (s.tare_weight or 0)
            s.in_range = (1 if s.net_weight >= tu2 else 0) if earlier else 0

        net_weights = [s.net_weight for s in samples if s.net_weight is not None]
        self.sample_count = len(net_weights)
        if net_weights:
            self.average_weight = sum(net_weights) / len(net_weights)
            mean = self.average_weight
            variance = sum((w - mean) ** 2 for w in net_weights) / len(net_weights)
            self.std_deviation = math.sqrt(variance)
            self.min_weight = min(net_weights)
            self.max_weight = max(net_weights)
        else:
            self.average_weight = 0
            self.std_deviation = 0
            self.min_weight = 0
            self.max_weight = 0

        if earlier:
            self.tu1_failures = sum(1 for w in net_weights if w < tu1)
            self.tu2_failures = sum(1 for w in net_weights if w < tu2)
            return
        self.tu1_failures = 0
        self.tu2_failures = 0
        # each sample is judged now; the check's result, for the Quality Hub
        # lists and the Quality Explorer (the form does not show it): Fail when
        # any sample failed
        self.overall_status = sample_result(samples)

    def refuse_retired_values(self):
        """A form loaded before the change (desk, Duplicate, Quality Hub) still
        offers the TU limits, the record's Remarks and the tare; a check made
        since would keep them out of sight."""
        if not cstr(self.remarks).strip():
            # nothing said (a stray space or line break): none kept out of sight
            self.remarks = None
        if any(self.get(fieldname) for fieldname in RETIRED_FIELDS) or any(
            s.get(fieldname) for s in self.samples or [] for fieldname in RETIRED_SAMPLE_FIELDS
        ):
            frappe.throw(_("This page is out of date. Reload it and enter the check again."))

    def require_sample_status(self):
        """Each sample's Status is mandatory on a check made since 2026-11. Not
        on one made before (a draft, an amendment, a restore), which keeps the
        Overall Status it was given: the field is not reqd on the doctype, and
        the form script marks it so on the checks that need it."""
        missing = [str(s.idx or i) for i, s in enumerate(self.samples or [], 1) if not s.get("status")]
        if missing:
            frappe.throw(
                _(
                    "Status is required in Samples (row {0}). If the Samples table has no Status column, "
                    "this page is out of date: reload it and enter the check again."
                ).format(", ".join(missing))
            )

    def require_nominal_weight(self):
        """The Nominal Weight is mandatory (the doctype marks it so) and more
        than 0. Frappe saves a blank number as 0, which its mandatory check lets
        through. Not on a check made before, which keeps its figures as they
        were."""
        if flt(self.nominal_weight) <= 0:
            frappe.throw(_("Nominal Weight (g) must be more than 0."))

    def require_sample_figures(self):
        """Each sample's Sample No and Gross Weight are mandatory (the doctype
        marks them so) and more than 0, as the Nominal Weight is. Not on a check
        made before, whose samples are kept as they were."""
        for fieldname, label in (("sample_no", _("Sample No")), ("gross_weight", _("Gross Weight (g)"))):
            rows = [str(s.idx or i) for i, s in enumerate(self.samples or [], 1) if flt(s.get(fieldname)) <= 0]
            if rows:
                frappe.throw(_("{0} must be more than 0 in Samples (row {1}).").format(label, ", ".join(rows)))

    def before_submit(self):
        # a check is its samples: the Quality Hub asks for one before it saves
        # a check, and a check is not submitted without one, however it is saved
        if not self.samples:
            frappe.throw(_("Add at least one row in Samples to submit the check."))

    def on_trash(self):
        """A draft from before the change, unmarked (it held no limit, Overall
        Status, Remarks or tare), that a check made since could not be (a
        sample without a Status, a Nominal Weight, Sample No or Gross Weight
        left blank) could not be restored once deleted: a restore is saved as a
        new check and cannot fill them in. Its snapshot (taken after this, from
        the document) keeps the earlier layout."""
        if not earlier_layout.in_earlier_layout(self) and not finished_the_new_way(self, self.samples or []):
            self.earlier_layout = 1

    def before_print(self, settings=None):
        # the standard print does not evaluate depends_on, which hides the
        # Earlier Layout on the form: leave its fields out of a check made since
        # (in memory only; Frappe saves a blank number as 0)
        if earlier_layout.in_earlier_layout(self):
            return
        for fieldname in EARLIER_FIELDS:
            self.set(fieldname, None)
        for s in self.samples or []:
            for fieldname in EARLIER_SAMPLE_FIELDS:
                s.set(fieldname, None)


def sample_result(samples) -> str:
    """The check's result from its samples' Status: Fail when any failed, Pass
    when every one passed, none without samples."""
    statuses = [s.get("status") for s in samples]
    if not statuses:
        return ""
    if "Fail" in statuses:
        return "Fail"
    return "Pass" if all(status == "Pass" for status in statuses) else ""


def finished_the_new_way(check, samples=()) -> bool:
    """Whether a check (a row or a dict) is all a check made since must be: each
    sample with a Status, a Sample No and a Gross Weight above 0, and the
    Nominal Weight above 0. A draft from before that is not cannot be restored
    as one made since."""
    return flt(check.get("nominal_weight")) > 0 and all(
        s.get("status") and flt(s.get("sample_no")) > 0 and flt(s.get("gross_weight")) > 0 for s in samples
    )


def belongs_to_earlier_layout(check, samples=()) -> bool:
    """Whether a check made before 2026-11 (a row or a dict) keeps the earlier
    layout: a submitted or cancelled one does, keeping the result it was given,
    and so does a draft holding a TU limit, an Overall Status, Remarks or a
    sample's tare. A draft with none of it is finished the new way."""
    return (
        cint(check.get("docstatus")) != 0
        or any(flt(check.get(f)) for f in ("tu1_limit", "tu2_limit"))
        or any((check.get(f) or "").strip() for f in ("overall_status", "remarks"))
        or any(flt(s.get("tare_weight")) for s in samples)
    )
