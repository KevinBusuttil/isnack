# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Reading averages of the extruder records and the old oven records (no database)."""

import unittest
from types import SimpleNamespace

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average, oven_averages
from isnack.isnack.doctype.qc_oven_record.qc_oven_record import QCOvenRecord
from isnack.isnack.doctype.qc_puffs_extruder_record.qc_puffs_extruder_record import QCPuffsExtruderRecord
from isnack.isnack.doctype.qc_rice_extruder_record.qc_rice_extruder_record import QCRiceExtruderRecord


def _oven(zone_1_temp=None, zone_2_temp=None, moisture=None):
	return SimpleNamespace(zone_1_temp=zone_1_temp, zone_2_temp=zone_2_temp, moisture=moisture)


class TestOvenAverages(unittest.TestCase):
	def test_each_average_over_the_readings_that_have_it(self):
		readings = [_oven(180, 170, 3.0), _oven(190, None, 4.0), _oven(None, 160, None)]
		self.assertEqual(oven_averages(readings), (185, 165, 3.5))

	def test_no_readings(self):
		self.assertEqual(oven_averages([]), (0, 0, 0))

	def test_a_zero_counts_unless_it_stands_for_blank(self):
		readings = [_oven(moisture=4.0), _oven(moisture=0.0), _oven(moisture=None)]
		self.assertEqual(average(readings, "moisture"), 2.0)
		self.assertEqual(average(readings, "moisture", zero_is_blank=True), 4.0)
		self.assertEqual(average([_oven(moisture=0.0)], "moisture", zero_is_blank=True), 0)


def _reading(moisture_corn_content=None):
	return SimpleNamespace(moisture_corn_content=moisture_corn_content)


def _oven_now(oven_temp=None, moisture=None):
	return SimpleNamespace(oven_temp=oven_temp, moisture=moisture)


# Each extruder's own tables since 2026-11, and its oven moisture average
EXTRUDERS = {
	QCPuffsExtruderRecord: ("puffs_readings", "puffs_oven_readings", "avg_puffs_oven_moisture"),
	QCRiceExtruderRecord: ("rice_readings", "rice_oven_readings", "avg_rice_oven_moisture"),
}


class TestExtruderRecords(unittest.TestCase):
	"""Puffs and Rice have their own readings since 2026-11; the earlier ones are kept."""

	def _record(self, record_type, readings=None, oven_readings=None, **earlier):
		table, oven_table, _moisture = EXTRUDERS[record_type]
		rec = SimpleNamespace(readings=None, oven_readings=None, **{table: readings, oven_table: oven_readings})
		rec.average_earlier_readings = lambda: record_type.average_earlier_readings(rec)
		rec.close_earlier_tables = lambda: None  # isnack/utils/test_earlier_readings.py
		vars(rec).update(earlier)
		return rec

	def _new_averages(self, record_type, rec):
		return (rec.avg_moisture_corn_content, rec.avg_oven_temp, getattr(rec, EXTRUDERS[record_type][2]))

	def test_averages_its_readings_and_oven_readings(self):
		for record_type in EXTRUDERS:
			rec = self._record(
				record_type,
				readings=[_reading(13.0), _reading(15.0), _reading(None)],
				oven_readings=[_oven_now(180, 3.0), _oven_now(200, None), _oven_now(None, 5.0)],
			)
			record_type.validate(rec)
			self.assertEqual(self._new_averages(record_type, rec), (14.0, 190, 4.0), record_type.__name__)
			# nothing in the earlier layout
			self.assertEqual(
				(rec.avg_moisture, rec.avg_density, rec.out_of_range_count, rec.avg_oven_zone1_temp, rec.avg_oven_moisture),
				(0, 0, 0, 0, 0),
				record_type.__name__,
			)

	def test_earlier_readings_average_as_before(self):
		for record_type in EXTRUDERS:
			rec = self._record(
				record_type,
				readings=[SimpleNamespace(moisture_content=15.0, product_density=0.2)],
				oven_readings=[_oven(180, 170, 3.0), _oven(200, 190, 5.0)],
			)
			# the earlier tables are readings / oven_readings; the new ones stay empty
			table, oven_table, _moisture = EXTRUDERS[record_type]
			rec.readings, rec.oven_readings = getattr(rec, table), getattr(rec, oven_table)
			setattr(rec, table, None)
			setattr(rec, oven_table, None)
			record_type.validate(rec)
			self.assertEqual((rec.avg_moisture, rec.avg_density, rec.out_of_range_count), (15.0, 0.2, 1), record_type.__name__)
			self.assertEqual(
				(rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (190, 180, 4.0), record_type.__name__
			)
			self.assertEqual(self._new_averages(record_type, rec), (0, 0, 0), record_type.__name__)

	def test_no_readings(self):
		for record_type in EXTRUDERS:
			rec = self._record(record_type)
			record_type.validate(rec)
			self.assertEqual(self._new_averages(record_type, rec), (0, 0, 0), record_type.__name__)

	def test_a_blank_reading_is_left_out_once_saved_as_0(self):
		# blank in the dialog: None on the first save, 0.0 when saved again or submitted
		for record_type in EXTRUDERS:
			for blank in (None, 0.0):
				rec = self._record(
					record_type,
					readings=[_reading(13.0), _reading(15.0), _reading(blank)],
					oven_readings=[_oven_now(180, blank), _oven_now(blank, 4.0)],
				)
				record_type.validate(rec)
				self.assertEqual(self._new_averages(record_type, rec), (14.0, 180, 4.0), (record_type.__name__, blank))


class TestOvenRecord(unittest.TestCase):
	def test_an_old_oven_record_averages_as_before(self):
		rec = SimpleNamespace(readings=[_oven(180, 170, 3.0), _oven(190, 180, None)])
		QCOvenRecord.validate(rec)
		self.assertEqual((rec.avg_zone1_temp, rec.avg_zone2_temp, rec.avg_moisture, rec.out_of_range_count), (185, 175, 3.0, 0))
