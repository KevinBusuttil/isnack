# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The tasting result on the star scale (no database)."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
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


RATINGS = ("appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score", "overall_score")


def _score_meta():
	meta = _meta()
	meta.fields = [frappe._dict(fieldname="taster_name", fieldtype="Data")]
	meta.fields += [frappe._dict(fieldname=f, fieldtype="Rating") for f in RATINGS]
	return meta


def _stored(rows, avg_overall=0.0, min_score=0.0, overall_status="Fail"):
	"""A tasting as the database holds it: every Rating a fraction of stars."""
	doc = MagicMock()
	doc.scores = [frappe._dict(row) for row in rows]
	doc.pass_threshold = 3.0
	doc.avg_overall, doc.min_score, doc.overall_status = avg_overall, min_score, overall_status
	return doc


@patch("frappe.get_meta", return_value=_score_meta())
@patch("frappe.get_doc")
@patch("frappe.get_all", return_value=["QCF-1"])
@patch("frappe.db.table_exists", return_value=True)
class TestRecomputePatch(unittest.TestCase):
	def test_stored_results_are_recomputed(self, _exists, get_all, get_doc, _meta_):
		doc = get_doc.return_value = _stored(
			[{"overall_score": 0.8, "taste_score": 0.6}, {"overall_score": 0.8}], avg_overall=0.8
		)

		patch_module.execute()

		self.assertEqual(get_all.call_args.kwargs["filters"], {"docstatus": ["<", 2]})
		doc.db_set.assert_called_once_with(
			{"avg_overall": 4.0, "min_score": 4.0, "overall_status": "Pass"}, update_modified=False
		)
		# db_set keeps no version: the record says what changed
		self.assertIn("Fail → Pass", doc.add_comment.call_args.args[1])

	@patch("builtins.print")
	def test_ratings_that_may_have_been_clamped_are_left_alone(self, printed, _exists, _all, get_doc, _meta_):
		# the old dialog sent stars: 1, 2 or 5 of them were all stored as 1.0
		doc = get_doc.return_value = _stored(
			[{"overall_score": 1, "taste_score": 1}, {"overall_score": 1, "aroma_score": 0}], avg_overall=1.0
		)

		patch_module.execute()

		doc.db_set.assert_not_called()
		self.assertEqual((doc.avg_overall, doc.overall_status), (1.0, "Fail"))
		self.assertIn("Check the scores", doc.add_comment.call_args.args[1])
		self.assertIn("QCF-1", printed.call_args.args[0])

	@patch("builtins.print")
	def test_a_dialog_row_among_desk_rows_is_left_alone(self, _printed, _exists, _all, get_doc, _meta_):
		# a dialog draft finished in the desk form: the first taster gave 1 star
		doc = get_doc.return_value = _stored(
			[{"overall_score": 1, "taste_score": 1}, {"overall_score": 0.8, "taste_score": 0.6}], avg_overall=0.9
		)

		patch_module.execute()

		doc.db_set.assert_not_called()
		self.assertIn("Check the scores", doc.add_comment.call_args.args[1])

	def test_a_row_with_a_fraction_was_scored_in_the_desk_form(self, _exists, _all, get_doc, _meta_):
		doc = get_doc.return_value = _stored([{"overall_score": 1, "appearance_score": 0.8}], avg_overall=1.0)

		patch_module.execute()

		doc.db_set.assert_called_once_with(
			{"avg_overall": 5.0, "min_score": 5.0, "overall_status": "Pass"}, update_modified=False
		)

	def test_a_result_already_right_is_not_rewritten(self, _exists, _all, get_doc, _meta_):
		doc = get_doc.return_value = _stored(
			[{"overall_score": 0.4}], avg_overall=2.0, min_score=2.0, overall_status="Fail"
		)

		patch_module.execute()

		doc.db_set.assert_not_called()
		doc.add_comment.assert_not_called()
