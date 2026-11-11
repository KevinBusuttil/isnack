# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The extruder records' earlier tables take no new rows; print follows the form (no database)."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from isnack.isnack.doctype.qc_puffs_extruder_record.qc_puffs_extruder_record import QCPuffsExtruderRecord
from isnack.isnack.doctype.qc_rice_extruder_record.qc_rice_extruder_record import QCRiceExtruderRecord


class _Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)

    def set(self, key, value):
        setattr(self, key, value)


def _row(name, idx, doctype="QC Extruder Reading", **values):
    return _Doc(name=name, idx=idx, doctype=doctype, **values)


def _meta(doctype):
    meta = MagicMock()
    meta.fields = [
        frappe._dict(fieldname="time_slot", fieldtype="Time"),
        frappe._dict(fieldname="moisture_content", fieldtype="Float"),
        frappe._dict(fieldname="moisture", fieldtype="Float"),
        frappe._dict(fieldname="reading_remarks", fieldtype="Small Text"),
    ]
    return meta


@patch("frappe.get_meta", side_effect=_meta)
class _NoNewRowsInTheEarlierTables:
    RECORD = None  # the controller class
    DOCTYPE = None
    OVEN_INSTEAD = None  # the label of the table that takes new oven readings
    TABLES = ()  # its own tables

    def _record(self, rows=(), oven_rows=(), new=False, before=None, amended_from=None):
        rec = _Doc(doctype=self.DOCTYPE, readings=list(rows), oven_readings=list(oven_rows), amended_from=amended_from)
        rec.is_new = lambda: new
        rec.get_doc_before_save = lambda: before
        return rec

    def _saved(self, *rows, oven_rows=()):
        return self._record(rows=rows, oven_rows=oven_rows)

    def test_rows_can_be_corrected_or_removed(self, _get_meta):
        before = self._saved(_row("r1", 1, moisture_content=12.0), _row("r2", 2, moisture_content=15.0))
        rec = self._record(rows=[_row("r1", 1, moisture_content=14.0)], before=before)
        self.RECORD.close_earlier_tables(rec)
        self.assertEqual([(r.name, r.moisture_content) for r in rec.readings], [("r1", 14.0)])

    def test_a_blank_row_added_is_dropped(self, _get_meta):
        # Tab out of the last cell, or Ctrl+Up between the rows, adds one
        before = self._saved(_row("r1", 1, moisture_content=12.0), _row("r2", 2, moisture_content=15.0))
        # by the time validate runs, Frappe has saved its blank numbers as 0 and
        # filled its blank Time with the time of the save
        rows = [
            _row("r1", 1, moisture_content=12.0),
            _row("n1", 2, time_slot="22:25:52", moisture_content=0.0),
            _row("r2", 3, moisture_content=15.0),
        ]
        rec = self._record(rows=rows, before=before)
        self.RECORD.close_earlier_tables(rec)
        self.assertEqual([(r.name, r.idx) for r in rec.readings], [("r1", 1), ("r2", 2)])

    def test_a_row_added_with_a_value_is_refused(self, _get_meta):
        before = self._saved(_row("r1", 1, moisture_content=12.0))
        for added in (_row("n1", 2, moisture_content=13.0), _row("n1", 2, time_slot="10:00:00", reading_remarks="late")):
            rec = self._record(rows=[_row("r1", 1, moisture_content=12.0), added], before=before)
            with self.assertRaisesRegex(frappe.ValidationError, r"Readings \(Earlier Layout\) takes no new rows"):
                self.RECORD.close_earlier_tables(rec)

    def test_a_row_swapped_for_a_new_one_is_refused(self, _get_meta):
        before = self._saved(_row("r1", 1, moisture_content=12.0))
        rec = self._record(rows=[_row("n1", 1, moisture_content=13.0)], before=before)
        with self.assertRaises(frappe.ValidationError):
            self.RECORD.close_earlier_tables(rec)

    def test_the_earlier_oven_readings_too(self, _get_meta):
        before = self._saved(oven_rows=[_row("o1", 1, "QC Oven Reading", moisture=3.0)])
        rec = self._record(
            oven_rows=[_row("o1", 1, "QC Oven Reading", moisture=3.0), _row("n1", 2, "QC Oven Reading", moisture=4.0)],
            before=before,
        )
        with self.assertRaises(frappe.ValidationError) as raised:
            self.RECORD.close_earlier_tables(rec)
        self.assertEqual(
            str(raised.exception),
            "Oven Readings (Earlier Layout) takes no new rows: remove the new ones and enter new readings in "
            f"{self.OVEN_INSTEAD}.",
        )

    def test_a_new_record_has_none(self, _get_meta):
        rec = self._record(rows=[_row("n1", 1)], new=True)
        self.RECORD.close_earlier_tables(rec)
        self.assertEqual(rec.readings, [])
        with self.assertRaises(frappe.ValidationError):
            self.RECORD.close_earlier_tables(self._record(rows=[_row("n1", 1, moisture_content=12.0)], new=True))

    @patch("frappe.get_doc")
    def test_an_amendment_keeps_the_rows_of_the_record_it_amends(self, get_doc, _get_meta):
        get_doc.return_value = self._saved(_row("r1", 1, moisture_content=12.0), _row("r2", 2, moisture_content=15.0))
        copies = [_row("a1", 1, moisture_content=12.0), _row("a2", 2, moisture_content=14.0)]
        rec = self._record(rows=copies, new=True, amended_from="QC-2026-00002")
        self.RECORD.close_earlier_tables(rec)
        get_doc.assert_called_once_with(self.DOCTYPE, "QC-2026-00002")
        self.assertEqual(len(rec.readings), 2)

        rec = self._record(rows=copies + [_row("a3", 3, moisture_content=13.0)], new=True, amended_from="QC-2026-00002")
        with self.assertRaises(frappe.ValidationError):
            self.RECORD.close_earlier_tables(rec)

    def test_every_save_applies_it(self, _get_meta):
        rec = self._record(rows=[_row("n1", 1, moisture_content=12.0)], new=True)
        for table in self.TABLES:
            setattr(rec, table, [])
        rec.close_earlier_tables = lambda: self.RECORD.close_earlier_tables(rec)
        rec.average_earlier_readings = lambda: self.RECORD.average_earlier_readings(rec)
        with self.assertRaises(frappe.ValidationError):
            self.RECORD.validate(rec)


class TestPuffsEarlierTables(_NoNewRowsInTheEarlierTables, unittest.TestCase):
    RECORD = QCPuffsExtruderRecord
    DOCTYPE = "QC Puffs Extruder Record"
    OVEN_INSTEAD = "Oven Readings"
    TABLES = ("puffs_readings", "puffs_oven_readings")


class TestRiceEarlierTables(_NoNewRowsInTheEarlierTables, unittest.TestCase):
    RECORD = QCRiceExtruderRecord
    DOCTYPE = "QC Rice Extruder Record"
    OVEN_INSTEAD = "Oven / Slurry Readings"
    TABLES = ("rice_readings", "rice_oven_readings")


class TestPrintFollowsTheForm(unittest.TestCase):
    EARLIER = {
        "avg_moisture": 12.5,
        "avg_density": 0.2,
        "out_of_range_count": 0,
        "avg_oven_zone1_temp": 180.0,
        "avg_oven_zone2_temp": 170.0,
        "avg_oven_moisture": 3.0,
    }
    # each record: its tables, and its summary fields with a value
    RECORDS = {
        QCPuffsExtruderRecord: (
            ("puffs_readings", "puffs_oven_readings"),
            {"avg_moisture_corn_content": 14.0, "avg_oven_temp": 185.0, "avg_puffs_oven_moisture": 4.0},
        ),
        QCRiceExtruderRecord: (
            ("rice_readings", "rice_oven_readings"),
            {"avg_moisture_corn_content": 14.0, "avg_oven_temp": 185.0, "avg_rice_oven_moisture": 4.0},
        ),
    }

    def _print(self, record_type, **tables):
        own_tables, own = self.RECORDS[record_type]
        rec = _Doc(readings=[], oven_readings=[], **{t: [] for t in own_tables}, **own, **self.EARLIER)
        vars(rec).update(tables)
        record_type.before_print(rec)
        return {f: rec.get(f) for f in {**own, **self.EARLIER}}

    def test_a_new_record_leaves_out_the_earlier_summary(self):
        for record_type, (own_tables, own) in self.RECORDS.items():
            printed = self._print(record_type, **{t: [1] for t in own_tables})
            self.assertEqual(printed, dict(own, **{f: None for f in self.EARLIER}), record_type.__name__)

    def test_an_earlier_record_prints_its_out_of_range_count_of_0(self):
        for record_type, (_own_tables, own) in self.RECORDS.items():
            printed = self._print(record_type, readings=[1])
            self.assertEqual(printed["out_of_range_count"], 0, record_type.__name__)
            self.assertEqual((printed["avg_moisture"], printed["avg_density"]), (12.5, 0.2), record_type.__name__)
            for fieldname in [*own, "avg_oven_zone1_temp", "avg_oven_moisture"]:
                self.assertIsNone(printed[fieldname], (record_type.__name__, fieldname))
