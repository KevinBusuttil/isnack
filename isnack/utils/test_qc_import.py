# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""What a Data Import of QC records must give (qc_import.py), on records as
the importer makes them (no database)."""

import contextlib
import datetime
import json
import os
import unittest
from decimal import Decimal
from unittest.mock import call, patch

import frappe

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


# the clock while an import runs, and the time it gives a row's Time left blank
# (frappe.utils.nowtime(), taken as it read the file, a moment before)
NOW = datetime.datetime(2026, 11, 25, 10, 0, 0)
LEFT_BLANK = "09:59:58.204611"


@contextlib.contextmanager
def _importing(in_import=True, now=NOW):
    with patch.dict(frappe.flags, {"in_import": in_import}), patch.object(qc_import, "now_datetime", return_value=now):
        yield


class TestTimes(unittest.TestCase):
    """Frappe makes each row an import brings with its defaults, which give a
    Time the time of import."""

    def test_a_time_left_blank_is_refused(self):
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": "08:00"}, {"time_slot": LEFT_BLANK, "oil_temp": 176}])
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError, r"^Time Slot is required in Readings \(this record's row 2\)\.$"
        ):
            check_import(doc)
        doc = _Doc("QC Metal Detector Log", tests=[{"test_time": LEFT_BLANK}, {"test_time": "09:59:58.204655"}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Test Time is required in Tests \(this record's rows 1, 2\)\."):
            check_import(doc)

    def test_every_table_is_named(self):
        doc = _Doc(
            "QC Puffs Extruder Record",
            puffs_readings=[{"time_slot": "08:00"}, {"time_slot": LEFT_BLANK}],
            puffs_oven_readings=[{"time_slot": LEFT_BLANK}],
        )
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError,
            r"Time Slot is required in Readings \(this record's row 2\) and in Oven / Slurry Readings \(this record's row 1\)\.",
        ):
            check_import(doc)

    def test_across_midnight(self):
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": "23:59:59.917311"}])
        with _importing(now=datetime.datetime(2026, 11, 26, 0, 0, 3)), self.assertRaisesRegex(frappe.ValidationError, "is required"):
            check_import(doc)

    def test_a_time_given_is_taken(self):
        # as a CSV gives it, as typed; an XLSX cell, as read (to a fraction of a second too)
        for time in ("08:00", "8:05", "08:00:00", "23:59:59", "07:30:00.5", "07:30:00.500000", "00:00"):
            doc = _Doc("QC Puffs Extruder Record", puffs_readings=[{"time_slot": time}], puffs_oven_readings=[{"time_slot": time}])
            with _importing():
                check_import(doc)

    def test_a_time_in_another_form_is_refused(self):
        # the database would read 8.30 as 8.3 seconds, or refuse it in its own words
        for time in ("8.30", "0830", "8:30 PM", "24:00", "12:60", "8h30"):
            doc = _Doc("QC Frying Line Record", readings=[{"time_slot": "08:00"}, {"time_slot": time}])
            with _importing(), self.assertRaisesRegex(
                frappe.ValidationError, rf"^Time Slot in Readings \(this record's row 2\) is {time}: give a time as hh:mm, as 08:30\.$"
            ):
                check_import(doc)

    def test_only_on_the_rows_an_import_brings(self):
        # a row a record keeps may hold the time it was saved at
        doc = _Doc("QC Rice Extruder Record", new=False, added=(2,), rice_readings=[{"time_slot": LEFT_BLANK}, {"time_slot": "09:00"}])
        with _importing():
            check_import(doc)
        doc = _Doc("QC Rice Extruder Record", new=False, added=(2,), rice_readings=[{"time_slot": "09:00"}, {"time_slot": LEFT_BLANK}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"in Readings \(this record's row 2\)"):
            check_import(doc)

    def test_a_time_holding_only_a_space_is_left_blank(self):
        # (an XLSX cell): the database would refuse it in its own words
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": " "}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Time Slot is required in Readings \(this record's row 1\)"):
            check_import(doc)

    def test_a_time_an_update_gives_a_row_it_keeps_is_checked_too(self):
        # an export for Update Existing Records, with the rows' IDs: a time
        # corrected to 8.30 would be kept as seconds
        doc = _Doc("QC Frying Line Record", new=False, readings=[{"time_slot": "22:00:00"}, {"time_slot": "8.30"}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Time Slot in Readings \(this record's row 2\) is 8.30"):
            check_import(doc)
        # as the export gives them (a saved time, to the second or less), and to the millionth: taken
        doc = _Doc("QC Frying Line Record", new=False, readings=[{"time_slot": "8:30:00.500000"}, {"time_slot": LEFT_BLANK}])
        with _importing():
            check_import(doc)

    def test_only_in_an_import(self):
        doc = _Doc("QC Frying Line Record", readings=[{"time_slot": LEFT_BLANK}, {"time_slot": "8.30"}])
        with _importing(False):
            check_import(doc)
        # nor when told not to check, as Frappe does
        with _importing():
            check_import(_Doc("QC Frying Line Record", flags={"ignore_validate": 1}, readings=[{"time_slot": LEFT_BLANK}]))

    def test_every_time_on_a_qc_record_is_on_a_row(self):
        # the record types hold no Time of their own: an import fills in none
        for doctype in QC_DOCTYPES.values():
            self.assertEqual(_Meta(doctype).get("fields", {"fieldtype": "Time"}), [], doctype)


class TestScores(unittest.TestCase):
    """Frappe keeps a Rating as the fraction of the stars given: it takes more
    than 1 as full marks, and text as no stars."""

    def test_stars_given_as_a_count_are_refused(self):
        doc = _Doc("QC Tasting Record", scores=[{"appearance_score": 0.8}, {"appearance_score": 0.6, "taste_score": 3}])
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError,
            r"^Taste in Scores \(this record's row 2\) is 3: an import gives a score as a number, the fraction of the 5 stars given \(1 star is 0\.2, 5 stars are 1\)\.$",
        ):
            check_import(doc)
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Shape in Scores \(this record's row 1\) is -0.2"):
            check_import(_Doc("QC Tasting Record", scores=[{"appearance_score": -0.2}]))

    def test_a_score_written_as_text_is_refused(self):
        # as a CSV gives it: Frappe would keep each as no stars; 0,8 as 8
        for score in ("4/5", "80%", "4 stars", "four", "0,8", datetime.datetime(2026, 4, 5)):
            with _importing(), self.assertRaisesRegex(
                frappe.ValidationError, r"Shape in Scores \(this record's row 1\) is .*: an import gives a score as a number"
            ):
                check_import(_Doc("QC Tasting Record", scores=[{"appearance_score": score}]))

    def test_a_fraction_is_taken(self):
        criteria = ("appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score")
        for scores in ((0, 0.2, 0.5, 1, None), ("0.8", " 0.6 ", "1", "0", ""), (Decimal("0.4"), 0.6, 1.0, 0, "  ")):
            with _importing():
                check_import(_Doc("QC Tasting Record", scores=[dict(zip(criteria, scores))]))

    def test_on_the_rows_of_a_record_updated_too(self):
        # an import updating a record gives it the rows of its file
        doc = _Doc("QC Tasting Record", new=False, scores=[{"texture_score": 4}])
        with _importing(), self.assertRaisesRegex(frappe.ValidationError, r"Texture in Scores \(this record's row 1\) is 4"):
            check_import(doc)


class TestTheOverallStars(unittest.TestCase):
    """A tasting row's Overall (stars, before 2026-11), on a record made since:
    the result comes from the five scores."""

    def test_it_is_refused_on_a_record_made_since(self):
        doc = _Doc("QC Tasting Record", scores=[{"appearance_score": 0.8}, {"overall_score": 0.8}])
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError,
            r"Overall \(stars, before 2026-11\) in Scores \(this record's row 2\): not recorded since 2026-11, when the result came to be worked out from the five scores",
        ):
            check_import(doc)

    def test_none_given_or_a_record_kept(self):
        with _importing():
            check_import(_Doc("QC Tasting Record", scores=[{"appearance_score": 0.8, "overall_score": 0}]))
            check_import(_Doc("QC Tasting Record", scores=[{"appearance_score": 0.8, "overall_score": ""}]))
            # a record made before, updated: its rows keep their overall
            check_import(_Doc("QC Tasting Record", new=False, scores=[{"overall_score": 0.6}]))


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
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError, r"Remarks, Tare Weight \(g\) in Samples \(this record's row 2\): not recorded"
        ):
            check_import(doc)
        doc = _Doc("QC Metal Detector Log", corrective_action="Re-tested", tests=[{"test_time": "08:00", "test_remarks": "ok"}])
        with _importing(), self.assertRaisesRegex(
            frappe.ValidationError, r"Corrective Action, .* in Tests \(this record's row 1\): not recorded"
        ):
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
        # a 0, as Frappe saves a blank number, or a stray space (which the
        # record types blank: test_packaging_layout, the weight and metal tests)
        doc = _Doc("QC Packaging Check", film_type=" ", qty_issued=0, qty_used=0, qty_returned=0, remarks="Fine")
        with _importing():
            check_import(doc)


@contextlib.contextmanager
def _receipt(supplier="Supplier A", docstatus=1, item=True, batch=True):
    """The Purchase Receipt MAT-PRE-2026-00900: its supplier and state, whether
    it holds the item, and the batch for it."""
    with patch("frappe.db.get_value", return_value=frappe._dict(supplier=supplier, docstatus=docstatus)) as get_value, patch(
        "frappe.db.exists", return_value=item
    ), patch("frappe.db.sql", return_value=[(1,)] if batch else []):
        yield get_value


class TestADeliveryOfItsReceipt(unittest.TestCase):
    """A QC Receiving Record imported checks a delivery of its Purchase
    Receipt, as the Quality Hub's pickers offer them."""

    def _doc(self, **values):
        return _Doc("QC Receiving Record", supplier="Supplier A", purchase_receipt="MAT-PRE-2026-00900", item_code="RM90001", batch_no="LOT-0001", **values)

    def test_the_receipts_own_are_taken(self):
        with _importing(), _receipt(), patch("frappe.get_all", return_value=[]):
            check_import(self._doc())

    def test_another_supplier_item_or_batch_is_refused(self):
        for receipt, wrong in (
            ({"supplier": "Supplier B"}, r"MAT-PRE-2026-00900.* is Supplier B's, not Supplier A's"),
            ({"docstatus": 0}, r"MAT-PRE-2026-00900.* is not submitted"),
            ({"item": False}, r"RM90001 is not on .*MAT-PRE-2026-00900"),
            ({"batch": False}, r"batch LOT-0001 is not RM90001's on .*MAT-PRE-2026-00900"),
        ):
            with _importing(), _receipt(**receipt), patch("frappe.get_all", return_value=[]), self.assertRaisesRegex(
                frappe.ValidationError, rf"^This delivery is not on its Purchase Receipt: .*{wrong}.*\. Give the receipt's own supplier, item and batch"
            ):
                check_import(self._doc())

    def test_only_a_new_record_in_an_import(self):
        with _importing(), _receipt(supplier="Supplier B") as get_value:
            check_import(self._doc(new=False))
            check_import(self._doc(amended_from="QCA-2026-00900"))
        get_value.assert_not_called()


class TestASecondReceivingRecord(unittest.TestCase):
    """A delivery has one QC Receiving Record: an import run again, or after it
    was recorded by hand, does not record it twice."""

    def _doc(self, **values):
        return _Doc("QC Receiving Record", purchase_receipt="MAT-PRE-2026-00900", item_code="RM90001", **values)

    def setUp(self):
        receipt = _receipt(supplier=None)
        receipt.__enter__()
        self.addCleanup(receipt.__exit__, None, None, None)

    def test_a_delivery_recorded_is_refused(self):
        with _importing(), patch("frappe.get_all", return_value=["QCA-2026-00900"]) as get_all, self.assertRaisesRegex(
            frappe.ValidationError,
            r"QCA-2026-00900.* already records this delivery \(MAT-PRE-2026-00900, RM90001, batch LOT-0001\): an import does not record it again",
        ):
            check_import(self._doc(batch_no="LOT-0001"))
        # (a message translated may read the translations too)
        looked_up = [c for c in get_all.call_args_list if c.args[:1] == ("QC Receiving Record",)]
        self.assertEqual(
            looked_up,
            [
                call(
                    "QC Receiving Record",
                    filters={
                        "purchase_receipt": "MAT-PRE-2026-00900",
                        "item_code": "RM90001",
                        "batch_no": "LOT-0001",
                        "docstatus": ["<", 2],
                        "name": ["!=", "QCX-2026-00009"],
                    },
                    pluck="name",
                    order_by="name asc",
                    limit=1,
                )
            ],
        )

    def test_one_not_recorded_is_taken(self):
        with _importing(), patch("frappe.get_all", return_value=[]) as get_all:
            check_import(self._doc(batch_no="LOT-0001"))
        self.assertEqual(get_all.call_count, 1)

    def test_only_a_new_record_in_an_import(self):
        with patch("frappe.get_all") as get_all:
            with _importing():
                check_import(self._doc(new=False, batch_no="LOT-0001"))
                check_import(self._doc(amended_from="QCA-2026-00900", batch_no="LOT-0001"))
                check_import(_Doc("QC Receiving Record", item_code="RM90001", batch_no="LOT-0001"))  # no receipt
                # no batch: refused for it, as Batch No is mandatory
                check_import(self._doc(batch_no=" "))
            with _importing(False):
                check_import(self._doc(batch_no="LOT-0001"))
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
