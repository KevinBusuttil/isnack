# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Oven readings on the extruder records (no database)."""

import unittest
from types import SimpleNamespace

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import oven_averages
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


class TestExtruderRecords(unittest.TestCase):
	def _record(self, oven_readings):
		return SimpleNamespace(
			readings=[SimpleNamespace(moisture_content=15.0, product_density=0.2)], oven_readings=oven_readings
		)

	def test_both_extruders_average_their_oven_readings(self):
		for record_type in (QCPuffsExtruderRecord, QCRiceExtruderRecord):
			rec = self._record([_oven(180, 170, 3.0), _oven(200, 190, 5.0)])
			record_type.validate(rec)
			self.assertEqual(
				(rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (190, 180, 4.0)
			)
			# the extruder's own readings are summed apart from the oven's
			self.assertEqual((rec.avg_moisture, rec.out_of_range_count), (15.0, 1), record_type.__name__)

	def test_without_oven_readings(self):
		rec = self._record(None)
		QCPuffsExtruderRecord.validate(rec)
		self.assertEqual((rec.avg_oven_zone1_temp, rec.avg_oven_zone2_temp, rec.avg_oven_moisture), (0, 0, 0))

	def test_an_old_oven_record_averages_as_before(self):
		rec = SimpleNamespace(readings=[_oven(180, 170, 3.0), _oven(190, 180, None)])
		QCOvenRecord.validate(rec)
		self.assertEqual((rec.avg_zone1_temp, rec.avg_zone2_temp, rec.avg_moisture, rec.out_of_range_count), (185, 175, 3.0, 0))
