# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

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


class QCWeightCheck(Document):
    def validate(self):
        earlier_layout.keep_mark(self)
        earlier = earlier_layout.in_earlier_layout(self)
        samples = self.samples or []
        if not earlier:
            self.refuse_retired_values()
            self.require_sample_status()

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
            frappe.throw(_("Status is required in Samples (row {0}).").format(", ".join(missing)))

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
