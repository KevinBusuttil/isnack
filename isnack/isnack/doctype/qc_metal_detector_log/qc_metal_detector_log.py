# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr

from isnack.utils import earlier_layout

# Taken off the log in 2026-11: the calibration certificate (the Metal Detector
# keeps it since, with the Make/Model and calibration dates the log takes from
# it) and each test's sensitivity setting and remarks. The logs made before
# that keep them (earlier_layout), in their Earlier Layout sections.
RETIRED_FIELDS = ("calibration_certificate",)
RETIRED_TEST_FIELDS = ("sensitivity_setting", "test_remarks")


class QCMetalDetectorLog(Document):
    def validate(self):
        earlier_layout.keep_mark(self)
        if not earlier_layout.in_earlier_layout(self):
            self.refuse_retired_values()

        tests = self.tests or []
        if tests:
            self.all_tests_passed = 1 if all(t.detected for t in tests) else 0
        else:
            self.all_tests_passed = 0

    def refuse_retired_values(self):
        """A form loaded before the change (desk, Quality Hub) still offers the
        certificate and each test's sensitivity setting and remarks; a log made
        since would keep them out of sight."""
        holders = [(self, RETIRED_FIELDS)] + [(test, RETIRED_TEST_FIELDS) for test in self.tests or []]
        for holder, fieldnames in holders:
            for fieldname in fieldnames:
                if holder.get(fieldname) and not cstr(holder.get(fieldname)).strip():
                    # nothing said (a stray space or line break): none kept out of sight
                    holder.set(fieldname, None)
        if any(holder.get(fieldname) for holder, fieldnames in holders for fieldname in fieldnames):
            frappe.throw(_("This page is out of date. Reload it and enter the log again."))


def belongs_to_earlier_layout(log, tests=()) -> bool:
    """Whether a log made before 2026-11 (a row or a dict, and its tests) keeps
    the earlier layout: a submitted or cancelled one does, and so does a draft
    holding a calibration certificate or a test's sensitivity setting or
    remarks. A draft with none of them is finished the new way."""
    return (
        cint(log.get("docstatus")) != 0
        or any(cstr(log.get(fieldname)).strip() for fieldname in RETIRED_FIELDS)
        or any(cstr(test.get(fieldname)).strip() for test in tests for fieldname in RETIRED_TEST_FIELDS)
    )
