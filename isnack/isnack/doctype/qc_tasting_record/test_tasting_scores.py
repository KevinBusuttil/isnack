# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The tasting result on the star scale (no database)."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import QCTastingRecord
from isnack.patches.v1_0 import recompute_qc_tasting_results as patch_module


def _record(overall_scores, pass_threshold=3.0):
	# Frappe stores a Rating as the fraction of stars: 4 of 5 stars is 0.8
	return SimpleNamespace(
		scores=[SimpleNamespace(overall_score=s) for s in overall_scores],
		pass_threshold=pass_threshold,
	)


def _meta(options=None):
	meta = MagicMock()
	meta.get_field.return_value = SimpleNamespace(options=options)
	return meta


@patch("frappe.get_meta", return_value=_meta())
class TestTastingResult(unittest.TestCase):
	def test_four_stars_pass_a_three_star_threshold(self, _meta_):
		rec = _record([0.8, 0.8, 0.6])
		QCTastingRecord.validate(rec)
		self.assertAlmostEqual(rec.avg_overall, 11 / 3)
		self.assertAlmostEqual(rec.min_score, 3.0)
		self.assertEqual(rec.overall_status, "Pass")

	def test_two_stars_fail(self, _meta_):
		rec = _record([0.4, 0.4])
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.overall_status), (2.0, "Fail"))

	def test_a_taster_who_gave_no_rating_is_left_out(self, _meta_):
		rec = _record([0.8, 0, None])
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.min_score, rec.overall_status), (4.0, 4.0, "Pass"))

	def test_no_scores_is_no_pass(self, _meta_):
		rec = _record([])
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.overall_status), (0, "Fail"))

	def test_the_threshold_defaults_to_three_stars(self, _meta_):
		rec = _record([0.6], pass_threshold=None)
		QCTastingRecord.validate(rec)
		self.assertEqual(rec.overall_status, "Pass")

	def test_ratings_out_of_ten(self, get_meta):
		get_meta.return_value = _meta(options="10")
		rec = _record([0.7], pass_threshold=6)
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.overall_status), (7.0, "Pass"))


class TestRecomputePatch(unittest.TestCase):
	@patch("frappe.get_meta", return_value=_meta())
	@patch("frappe.get_doc")
	@patch("frappe.get_all", return_value=["QCF-1"])
	@patch("frappe.db.table_exists", return_value=True)
	def test_stored_results_are_recomputed(self, _exists, get_all, get_doc, _meta_):
		doc = _record([0.8, 0.8])
		doc.overall_status = "Fail"
		doc.db_set = MagicMock()
		get_doc.return_value = doc

		patch_module.execute()

		self.assertEqual(get_all.call_args.kwargs["filters"], {"docstatus": ["<", 2]})
		doc.db_set.assert_called_once_with(
			{"avg_overall": 4.0, "min_score": 4.0, "overall_status": "Pass"}, update_modified=False
		)
