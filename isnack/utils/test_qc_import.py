# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""What a Data Import of QC records must give (qc_import.py), on records as
the importer makes them (no database)."""

import json
import os
import unittest
from unittest.mock import call, patch

import frappe
from frappe.utils import nowtime

from isnack.isnack.page.quality_hub.quality_hub import QC_DOCTYPES
from isnack.utils import qc_import
from isnack.utils.qc_import import check_import

APP_DIR = os.path.join(os.path.dirname(__file__), "..")
DOCTYPE_DIR = os.path.join(APP_DIR, "isnack", "doctype")


class _Meta:
    """A doctype's fields, read from its JSON."""

    def __init__(self, doctype):
        folder = doctype.lower().replace(" ", "_")
        with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
            self.fields = [frappe._dict(f) for f in json.load(fh)["fields"]]

    def get(self, key, filters=None):
        return [f for f in self.fields if all(f.get(k) == v for k, v in (filters or {}).items())]

    def get_label(self, fieldname):
        return next((f.label for f in self.fields if f.fieldname == fieldname), None)

    def has_field(self, fieldname):
        return any(f.fieldname == fieldname for f in self.fields)


class _Row(frappe._dict):
    pass


class _Doc(frappe._dict):
    """A QC record as the importer makes it: new (inserting), or one it updates
    (``new=False``: its rows saved, but those named in ``added``)."""

    def __init__(self, doctype, new=True, added=(), flags=None, **values):
        super().__init__(doctype=doctype, name="QCX-2026-00009")
        self.meta = _Meta(doctype)
        self.flags = frappe._dict(flags or {})
        if new:
            self.flags.in_insert = True
        for fieldname, value in values.items():
            if isinstance(value, list):
                child = next(f.options for f in self.meta.fields if f.fieldname == fieldname)
                rows = []
                for idx, row in enumerate(value, 1):
                    row = _Row(row, idx=idx, parentfield=fieldname)
                    row.meta = _Meta(child)
                    if new or idx in added:
                        row["__islocal"] = 1
                    rows.append(row)
                value = rows
            self[fieldname] = value

    def is_new(self):
        return bool(self.flags.in_insert)

    def get_all_children(self):
        return [row for f in self.meta.fields if f.fieldtype == "Table" for row in self.get(f.fieldname) or []]


def _importing(in_import=True):
    return patch.dict(frappe.flags, {"in_import": in_import})


class TestTimes(unittest.TestCase):
    """Frappe makes each row an import brings with its defaults, which give a
    Time the time of import."""

    def test_a_time_left_blank_is_refused(self):
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": "08:00"}, {"time_slot": nowtime(), "oil_temp": 176}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Time Slot is required in Readings \(row 2\)"):
            check_import(doc)
        doc = _Doc("QC Metal Detector Log", tests=[{"test_time": nowtime()}, {"test_time": nowtime()}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Test Time is required in Tests \(row 1, 2\)"):
            check_import(doc)

    def test_a_time_given_is_taken(self):
        # as a CSV gives it, as typed; an XLSX cell, to the second
        for time in ("08:00", "8:05", "08:00:00", "23:59:59", "07:30:00.5"):
            doc = _Doc("QC Puffs Extruder Record", puffs_readings=[{"time_slot": time}], puffs_oven_readings=[{"time_slot": time}])
            with _importing():
                check_import(doc)

    def test_only_on_the_rows_an_import_brings(self):
        # a row a record keeps may hold the time it was saved at
        doc = _Doc("QC Rice Extruder Record", new=False, added=(2,), rice_readings=[{"time_slot": nowtime()}, {"time_slot": "09:00"}])
        with _importing():
            check_import(doc)
        doc = _Doc("QC Rice Extruder Record", new=False, added=(2,), rice_readings=[{"time_slot": "09:00"}, {"time_slot": nowtime()}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"in Readings \(row 2\)"):
            check_import(doc)

    def test_only_in_an_import(self):
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": nowtime()}])
        with _importing(False):
            check_import(doc)
        # nor when told not to check, as Frappe does
        with _importing():
            check_import(_Doc("QC Frying Line Record", flags={"ignore_validate": 1}, readings=[{"time_slot": nowtime()}]))

    def test_every_time_on_a_qc_record_is_on_a_row(self):
        # the record types hold no Time of their own: an import fills in none
        for doctype in QC_DOCTYPES.values():
            self.assertEqual(_Meta(doctype).get("fields", {"fieldtype": "Time"}), [], doctype)


class TestScores(unittest.TestCase):
    """Frappe keeps a Rating as the fraction of the stars given, and takes more
    than 1 as full marks."""

    def test_stars_given_as_a_count_are_refused(self):
        doc = _Doc("QC Tasting Record", scores=[{"appearance_score": 0.8}, {"appearance_score": 0.6, "taste_score": 3}])
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError,
            r"Taste in Scores \(row 2\) is 3: an import gives a score as the fraction of the 5 stars given \(1 star is 0\.2, 5 stars are 1\)",
        ):
            check_import(doc)
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Shape in Scores \(row 1\) is -0.2"):
            check_import(_Doc("QC Tasting Record", scores=[{"appearance_score": -0.2}]))

    def test_a_fraction_is_taken(self):
        doc = _Doc("QC Tasting Record", scores=[{f: v for f, v in zip(("appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score"), (0, 0.2, 0.5, 1, None))}])
        with _importing():
            check_import(doc)

    def test_on_the_rows_of_a_record_updated_too(self):
        # an import updating a record gives it the rows of its file
        doc = _Doc("QC Tasting Record", new=False, scores=[{"texture_score": 4}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Texture in Scores \(row 1\) is 4"):
            check_import(doc)


class TestRetiredFields(unittest.TestCase):
    """A field taken off in 2026-11, given to a record made since: the record
    type says "This page is out of date"; an import names it."""

    def test_they_are_named(self):
        doc = _Doc("QC Packaging Check", film_type="BOPP", qty_issued=120, qty_used=0)
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError, r"Film Type, Qty Issued: not recorded on a record made since 2026-11\. Leave them blank, or, for a record from before, set Earlier Layout to 1"
        ):
            check_import(doc)
        doc = _Doc("QC Weight Check", remarks="All fine", samples=[{"gross_weight": 45}, {"gross_weight": 46, "tare_weight": 1.2}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Remarks, Tare Weight \(g\) in Samples \(row 2\): not recorded"):
            check_import(doc)
        doc = _Doc("QC Metal Detector Log", corrective_action="Re-tested", tests=[{"test_time": "08:00", "test_remarks": "ok"}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Corrective Action, .* in Tests \(row 1\): not recorded"):
            check_import(doc)

    def test_a_record_from_before_keeps_them(self):
        for doc in (
            _Doc("QC Packaging Check", earlier_layout=1, film_type="BOPP", qty_issued=120),
            _Doc("QC Weight Check", earlier_layout=1, tu1_limit=40, samples=[{"tare_weight": 1.2}]),
            _Doc("QC Metal Detector Log", earlier_layout=1, calibration_certificate="CERT-1", tests=[{"test_time": "08:00", "sensitivity_setting": "3"}]),
        ):
            with _importing():
                check_import(doc)

    def test_none_given_is_none_refused(self):
        # a 0, as Frappe saves a blank number, or a stray space
        doc = _Doc("QC Packaging Check", film_type=" ", qty_issued=0, qty_used=0, qty_returned=0, remarks="Fine")
        with _importing():
            check_import(doc)


class TestASecondReceivingRecord(unittest.TestCase):
    """A delivery has one QC Receiving Record: an import run again, or after it
    was recorded by hand, does not record it twice."""

    def _doc(self, **values):
        return _Doc("QC Receiving Record", purchase_receipt="MAT-PRE-2026-00106", item_code="CR30002", **values)

    def test_a_delivery_recorded_is_refused(self):
        with _importing(), patch("frappe.get_all", return_value=["QCA-2026-00001"]) as get_all, self.assertRaisesRegex(
            frappe.ValidationError,
            r"QCA-2026-00001.* already records this delivery \(MAT-PRE-2026-00106, CR30002, batch C125212363\): an import does not record it again",
        ):
            check_import(self._doc(batch_no="C125212363"))
        # (a message translated may read the translations too)
        looked_up = [c for c in get_all.call_args_list if c.args[:1] == ("QC Receiving Record",)]
        self.assertEqual(len(looked_up), 1)
        self.assertEqual(
            looked_up[0],
            call(
            "QC Receiving Record",
            filters={
                "purchase_receipt": "MAT-PRE-2026-00106",
                "item_code": "CR30002",
                "batch_no": "C125212363",
                "docstatus": ["<", 2],
                "name": ["!=", "QCX-2026-00009"],
            },
            pluck="name",
            order_by="name asc",
            limit=1,
            ),
        )

    def test_one_not_recorded_is_taken(self):
        with _importing(), patch("frappe.get_all", return_value=[]) as get_all:
            check_import(self._doc())
        # an item without a batch: the record of the receipt's item without one
        self.assertEqual(get_all.call_args.kwargs["filters"]["batch_no"], ["is", "not set"])

    def test_only_a_new_record_in_an_import(self):
        with patch("frappe.get_all") as get_all:
            with _importing():
                check_import(self._doc(new=False, batch_no="C125212363"))
                check_import(self._doc(amended_from="QCA-2026-00001", batch_no="C125212363"))
                check_import(_Doc("QC Receiving Record", item_code="CR30002"))  # no receipt
            with _importing(False):
                check_import(self._doc(batch_no="C125212363"))
        get_all.assert_not_called()


class TestTheHooks(unittest.TestCase):
    def test_every_record_type_is_checked_first(self):
        hooks = {}
        with open(os.path.join(APP_DIR, "hooks.py")) as fh:
            exec(compile(fh.read(), "hooks.py", "exec"), hooks)
        path = f"{qc_import.__name__}.{check_import.__name__}"
        self.assertEqual(path, "isnack.utils.qc_import.check_import")
        checked = [doctype for doctype, events in hooks["doc_events"].items() if path in (events.get("before_validate") or [])]
        self.assertEqual(sorted(checked), sorted(QC_DOCTYPES.values()))
        for doctype in checked:
            # before the Operator is looked up: a delivery recorded already says so first
            self.assertEqual(hooks["doc_events"][doctype]["before_validate"][0], path, doctype)
