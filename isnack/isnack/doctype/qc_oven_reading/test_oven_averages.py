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


class TestRiceExtruderRecord(unittest.TestCase):
	def _record(self, oven_readings):
		return SimpleNamespace(
			readings=[SimpleNamespace(moisture_content=15.0, product_density=0.2)], oven_readings=oven_readings
		)

	def test_averages_its_oven_readings(self):
		rec = self._record([_oven(180, 170, 3.0), _oven(200, 190, 5.0)])
		QCRiceExtruderRecord.validate(rec)
		self.assertEqual((rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (190, 180, 4.0))
		# the extruder's own readings are summed apart from the oven's
		self.assertEqual((rec.avg_moisture, rec.out_of_range_count), (15.0, 1))

	def test_without_oven_readings(self):
		rec = self._record(None)
		QCRiceExtruderRecord.validate(rec)
		self.assertEqual((rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (0, 0, 0))


def _puffs(moisture_corn_content=None):
	return SimpleNamespace(moisture_corn_content=moisture_corn_content)


def _puffs_oven(oven_temp=None, moisture=None):
	return SimpleNamespace(oven_temp=oven_temp, moisture=moisture)


class TestPuffsExtruderRecord(unittest.TestCase):
	"""Puffs has its own readings since 2026-11; the earlier ones are kept."""

	def _record(self, **tables):
		rec = SimpleNamespace(puffs_readings=None, puffs_oven_readings=None, readings=None, oven_readings=None)
		rec.average_earlier_readings = lambda: QCPuffsExtruderRecord.average_earlier_readings(rec)
		rec.close_earlier_tables = lambda: None  # test_earlier_readings
		vars(rec).update(tables)
		return rec

	def test_averages_its_readings_and_oven_readings(self):
		rec = self._record(
			puffs_readings=[_puffs(13.0), _puffs(15.0), _puffs(None)],
			puffs_oven_readings=[_puffs_oven(180, 3.0), _puffs_oven(200, None), _puffs_oven(None, 5.0)],
		)
		QCPuffsExtruderRecord.validate(rec)
		self.assertEqual(rec.avg_moisture_corn_content, 14.0)
		self.assertEqual((rec.avg_oven_temp, rec.avg_puffs_oven_moisture), (190, 4.0))
		# nothing in the earlier layout
		self.assertEqual(
			(rec.avg_moisture, rec.avg_density, rec.out_of_range_count, rec.avg_oven_zone1_temp, rec.avg_oven_moisture),
			(0, 0, 0, 0, 0),
		)

	def test_earlier_readings_average_as_before(self):
		rec = self._record(
			readings=[SimpleNamespace(moisture_content=15.0, product_density=0.2)],
			oven_readings=[_oven(180, 170, 3.0), _oven(200, 190, 5.0)],
		)
		QCPuffsExtruderRecord.validate(rec)
		self.assertEqual((rec.avg_moisture, rec.avg_density, rec.out_of_range_count), (15.0, 0.2, 1))
		self.assertEqual((rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (190, 180, 4.0))
		self.assertEqual((rec.avg_moisture_corn_content, rec.avg_oven_temp, rec.avg_puffs_oven_moisture), (0, 0, 0))

	def test_no_readings(self):
		rec = self._record()
		QCPuffsExtruderRecord.validate(rec)
		self.assertEqual((rec.avg_moisture_corn_content, rec.avg_oven_temp, rec.avg_puffs_oven_moisture), (0, 0, 0))

	def test_a_blank_reading_is_left_out_once_saved_as_0(self):
		# blank in the dialog: None on the first save, 0.0 when saved again or submitted
		for blank in (None, 0.0):
			rec = self._record(
				puffs_readings=[_puffs(13.0), _puffs(15.0), _puffs(blank)],
				puffs_oven_readings=[_puffs_oven(180, blank), _puffs_oven(blank, 4.0)],
			)
			QCPuffsExtruderRecord.validate(rec)
			self.assertEqual(
				(rec.avg_moisture_corn_content, rec.avg_oven_temp, rec.avg_puffs_oven_moisture), (14.0, 180, 4.0), blank
			)


class TestOvenRecord(unittest.TestCase):
	def test_an_old_oven_record_averages_as_before(self):
		rec = SimpleNamespace(readings=[_oven(180, 170, 3.0), _oven(190, 180, None)])
		QCOvenRecord.validate(rec)
		self.assertEqual((rec.avg_zone1_temp, rec.avg_zone2_temp, rec.avg_moisture, rec.out_of_range_count), (185, 175, 3.0, 0))
