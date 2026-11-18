# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr

from isnack.utils import earlier_layout

# Taken off the log in 2026-11: the calibration certificate (the Metal Detector
# keeps it since, with the Make/Model and calibration dates the log takes from
# it), the corrective action, and each test's sensitivity setting and remarks.
# The logs made before that keep them (earlier_layout), in their Earlier Layout
# sections.
RETIRED_FIELDS = ("calibration_certificate", "corrective_action")
RETIRED_TEST_FIELDS = ("sensitivity_setting", "test_remarks")

# What the log takes from the Metal Detector picked (fetch_from).
DETECTOR_FIELDS = ("detector_make_model", "last_calibration_date", "next_calibration_date")


class QCMetalDetectorLog(Document):
    def validate(self):
        earlier_layout.keep_mark(self)
        if not earlier_layout.in_earlier_layout(self):
            self.refuse_retired_values()
            self.require_detector_and_tests()
        self.check_metal_detector()
        self.check_detector_on_line()
        self.keep_details_verified_under()

        tests = self.tests or []
        if tests:
            self.all_tests_passed = 1 if all(t.detected for t in tests) else 0
        else:
            self.all_tests_passed = 0

    def refuse_retired_values(self):
        """A form loaded before the change (desk, Quality Hub) still offers the
        certificate, the corrective action and each test's sensitivity setting
        and remarks; a log made since would keep them out of sight."""
        holders = [(self, RETIRED_FIELDS)] + [(test, RETIRED_TEST_FIELDS) for test in self.tests or []]
        for holder, fieldnames in holders:
            for fieldname in fieldnames:
                if holder.get(fieldname) and not cstr(holder.get(fieldname)).strip():
                    # nothing said (a stray space or line break): none kept out of sight
                    holder.set(fieldname, None)
        if any(holder.get(fieldname) for holder, fieldnames in holders for fieldname in fieldnames):
            frappe.throw(_("This page is out of date. Reload it and enter the log again."))

    def require_detector_and_tests(self):
        """The Metal Detector ID, and each test's Test Time and Test Piece Type,
        are mandatory on a log made since 2026-11. Not on one made before (a
        draft, an amendment, a restore), which keeps what it recorded: the
        fields are not reqd on the doctype, and the form script marks them so
        on the logs that need them."""
        if not cstr(self.metal_detector_id).strip():
            frappe.throw(_("Metal Detector ID is required."))
        # (the labels are translated only when one is missing)
        for fieldname, label in (("test_time", "Test Time"), ("test_piece_type", "Test Piece Type")):
            rows = [str(t.idx or i) for i, t in enumerate(self.tests or [], 1) if not cstr(t.get(fieldname)).strip()]
            if rows:
                frappe.throw(_("{0} is required in Tests (row {1}).").format(_(label), ", ".join(rows)))

    def before_submit(self):
        # a log is its tests: the Quality Hub asks for one before it saves a
        # log, and a log is not submitted without one, however it is saved
        if not self.tests:
            frappe.throw(_("Add at least one row in Tests to submit the log."))

    def on_trash(self):
        """A draft from before the change, unmarked (it held no certificate,
        corrective action or test sensitivity or remarks), that a log made
        since could not be (no Metal Detector ID, a test without a time or a
        test piece type) could not be restored once deleted: a restore is saved
        as a new log and cannot fill them in. Its snapshot (taken after this,
        from the document) keeps the earlier layout."""
        if not earlier_layout.in_earlier_layout(self) and not finished_the_new_way(self, self.tests or []):
            self.earlier_layout = 1

    def check_metal_detector(self):
        """The Metal Detector ID names a Metal Detector. Frappe does not check a
        Link that fields are fetched from (v15): it reads the record's values,
        and when there is none it fetches nothing and says nothing, keeping
        whatever Make/Model and dates were sent (a page loaded before the
        change, the API, a draft whose ID could not be made a detector)."""
        if self.metal_detector_id and not frappe.db.exists("Metal Detector", self.metal_detector_id):
            frappe.throw(
                _("Could not find Metal Detector: {0}. Pick the metal detector again.").format(
                    frappe.bold(self.metal_detector_id)
                ),
                frappe.LinkValidationError,
            )

    def check_detector_on_line(self):
        """The Metal Detector picked is used on the log's factory line (one of
        its Factory Lines). The Quality Hub and the form offer only those, but
        a Link takes any detector typed in full. An amendment keeps the
        detector and line of the log it amends, as it keeps its calibration:
        the detector may have moved to another line since."""
        if not (self.metal_detector_id and self.factory_line):
            return
        if frappe.db.exists(
            "Metal Detector Factory Line",
            {
                "parenttype": "Metal Detector",
                "parentfield": "factory_lines",
                "parent": self.metal_detector_id,
                "factory_line": self.factory_line,
            },
        ):
            return
        if self.amended_from:
            amended = frappe.db.get_value(
                self.doctype, self.amended_from, ["metal_detector_id", "factory_line"], as_dict=True
            )
            if (
                amended
                and _same_id(amended.metal_detector_id, self.metal_detector_id)
                and _same_id(amended.factory_line, self.factory_line)
            ):
                return
        frappe.throw(
            _("Metal Detector {0} is not used on {1}. Pick a metal detector on that line, or add {1} to the Factory Lines of {0}.").format(
                frappe.bold(self.metal_detector_id), frappe.bold(self.factory_line)
            ),
            title=_("Not on this line"),
        )

    def keep_details_verified_under(self):
        """An amendment of the same detector keeps the Make/Model and calibration
        dates the log it amends was verified under: Frappe fetches the
        detector's current ones each time a draft is saved, the amendment's
        too, until it is submitted. Another detector picked on it gives that
        detector's."""
        if not (self.amended_from and self.metal_detector_id):
            return
        amended = frappe.db.get_value(
            self.doctype, self.amended_from, ["metal_detector_id", *DETECTOR_FIELDS], as_dict=True
        )
        if amended and _same_id(amended.metal_detector_id, self.metal_detector_id):
            for fieldname in DETECTOR_FIELDS:
                self.set(fieldname, amended.get(fieldname))


def _same_id(one, other) -> bool:
    """The same Metal Detector ID (or Factory Line), case and surrounding
    spaces aside (a log made before 2026-11 may spell it otherwise than its
    detector)."""
    return cstr(one).strip().casefold() == cstr(other).strip().casefold()


def finished_the_new_way(log, tests=()) -> bool:
    """Whether a log (a row or a dict, and its tests) is all a log made since
    must be: a Metal Detector ID, and each test with a Test Time and a Test
    Piece Type. A draft from before that is not cannot be restored as one made
    since."""
    return bool(cstr(log.get("metal_detector_id")).strip()) and all(
        cstr(test.get("test_time")).strip() and cstr(test.get("test_piece_type")).strip() for test in tests
    )


def belongs_to_earlier_layout(log, tests=()) -> bool:
    """Whether a log made before 2026-11 (a row or a dict, and its tests) keeps
    the earlier layout: a submitted or cancelled one does, and so does a draft
    holding a calibration certificate, a corrective action or a test's
    sensitivity setting or remarks. A draft with none of them is finished the
    new way."""
    return (
        cint(log.get("docstatus")) != 0
        or any(cstr(log.get(fieldname)).strip() for fieldname in RETIRED_FIELDS)
        or any(cstr(test.get(fieldname)).strip() for test in tests for fieldname in RETIRED_TEST_FIELDS)
    )
