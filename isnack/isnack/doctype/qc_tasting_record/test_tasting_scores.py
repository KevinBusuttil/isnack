# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The tasting result: each taster's Overall %, from their five scores (no database)."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe
from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import CRITERIA, QCTastingRecord, overall_percent
from isnack.patches.v1_0 import qc_tasting_overall_percent as percent_patch
from isnack.patches.v1_0 import recompute_qc_tasting_results as patch_module


def _row(*stars, **other):
	"""A taster's row as Frappe holds it: each Rating the fraction of stars given
	(4 of 5 stars is 0.8), in the order Shape, Colour, Smell, Taste, Texture."""
	row = frappe._dict(zip(CRITERIA, (s / 5 if s is not None else None for s in stars)))
	row.update(other)
	return row


def _record(*rows):
	return SimpleNamespace(scores=list(rows))


def _meta(options=None):
	meta = MagicMock()
	meta.get_field.return_value = SimpleNamespace(options=options)
	return meta


class TestOverallPercent(unittest.TestCase):
	def test_the_stars_given_over_full_marks(self):
		self.assertEqual(overall_percent(_row(5, 5, 5, 5, 5)), 100)
		self.assertEqual(overall_percent(_row(4, 4, 3, 5, 4)), 80)  # 20 of 25 stars
		self.assertEqual(overall_percent(_row(1, 1, 1, 1, 1)), 20)

	def test_a_score_left_blank_counts_as_0(self):
		self.assertEqual(overall_percent(_row(5, 5, 5, 5, None)), 80)
		self.assertEqual(overall_percent(_row()), 0)

	def test_a_rating_beyond_full_marks_counts_as_full(self):
		self.assertEqual(overall_percent(frappe._dict({f: 1.4 for f in CRITERIA})), 100)

	def test_the_tasters_own_overall_rating_no_longer_counts(self):
		self.assertEqual(overall_percent(_row(3, 3, 3, 3, 3, overall_score=1)), 60)


class TestTastingResult(unittest.TestCase):
	def test_each_taster_gets_an_overall_percent(self):
		rec = _record(_row(4, 4, 4, 4, 4), _row(5, 5, 4, 4, 5))
		QCTastingRecord.validate(rec)
		self.assertEqual([r.overall_percent for r in rec.scores], [80, 92])
		self.assertEqual((rec.avg_overall, rec.min_score, rec.overall_status), (86, 80, "Pass"))

	def test_sixty_percent_passes_and_just_under_fails(self):
		# 60 % is 3 of 5 stars, the pass mark before
		rec = _record(_row(3, 3, 3, 3, 3))
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.overall_status), (60, "Pass"))
		rec = _record(_row(3, 3, 3, 3, 2))
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.overall_status), (56, "Fail"))

	def test_a_taster_who_gave_no_score_is_left_out(self):
		rec = _record(_row(4, 4, 4, 4, 4), _row(taster_name="Late"))
		QCTastingRecord.validate(rec)
		self.assertEqual([r.overall_percent for r in rec.scores], [80, 0])
		self.assertEqual((rec.avg_overall, rec.min_score, rec.overall_status), (80, 80, "Pass"))

	def test_no_scores_is_no_pass(self):
		rec = _record()
		QCTastingRecord.validate(rec)
		self.assertEqual((rec.avg_overall, rec.min_score, rec.overall_status), (0, 0, "Fail"))


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


def _db_row(name, parent, overall_score, *criteria, overall_percent=0):
	"""A score row as the database holds it: Ratings as fractions of stars."""
	row = frappe._dict(name=name, parent=parent, overall_percent=overall_percent, overall_score=overall_score)
	row.update(zip(CRITERIA, criteria))
	return row


@patch("frappe.get_doc")
@patch("frappe.db.get_value")
@patch("frappe.db.set_value")
@patch("frappe.db.sql")
@patch("frappe.get_meta", return_value=_score_meta())
@patch("frappe.db.has_column", return_value=True)
class TestOverallPercentPatch(unittest.TestCase):
	"""Tastings scored on the taster's own Overall rating keep their result, in %."""

	def _records(self, get_value, stored):
		get_value.side_effect = lambda doctype, name, fields: stored[name]

	def test_the_overall_rating_becomes_the_overall_percent(self, _has, _meta, sql, set_value, get_value, get_doc):
		sql.return_value = [
			_db_row("r1", "QCF-1", 0.8, 0.8, 0.6),
			_db_row("r2", "QCF-1", 0.6, 0.6),
			_db_row("r3", "QCF-2", 1.0, 0.8, 1.0),
		]
		# judged in stars: 3.5 and 5 on average
		self._records(get_value, {"QCF-1": (3.5, "Pass"), "QCF-2": (5.0, "Pass")})

		percent_patch.execute()

		self.assertEqual(
			set_value.call_args_list,
			[
				call("QC Tasting Score", "r1", "overall_percent", 80, update_modified=False),
				call("QC Tasting Score", "r2", "overall_percent", 60, update_modified=False),
				call("QC Tasting Record", "QCF-1", {"avg_overall": 70, "min_score": 60, "overall_status": "Pass"}, update_modified=False),
				call("QC Tasting Score", "r3", "overall_percent", 100, update_modified=False),
				call("QC Tasting Record", "QCF-2", {"avg_overall": 100, "min_score": 100, "overall_status": "Pass"}, update_modified=False),
			],
		)
		# set_value keeps no version: each record says what changed
		self.assertEqual(get_doc.return_value.add_comment.call_count, 2)
		self.assertIn("and the result stands.", get_doc.return_value.add_comment.call_args.args[1])

	def test_rows_already_converted_are_left_alone(self, _has, _meta, sql, set_value, _get_value, get_doc):
		sql.return_value = [_db_row("r1", "QCF-1", 0.8, 0.8, overall_percent=76)]
		percent_patch.execute()
		set_value.assert_not_called()
		get_doc.return_value.add_comment.assert_not_called()

	def test_a_tasting_never_judged_in_stars_gets_the_result_its_scores_give(self, _has, _meta, sql, set_value, get_value, get_doc):
		# cancelled before the October patch: its average still a fraction, "Fail" whatever the scores
		sql.return_value = [_db_row("r1", "QCF-1", 0.8, 0.8), _db_row("r2", "QCF-1", 0.6, 0.6)]
		self._records(get_value, {"QCF-1": (0.7, "Fail")})

		percent_patch.execute()

		self.assertEqual(
			set_value.call_args_list[-1],
			call("QC Tasting Record", "QCF-1", {"avg_overall": 70, "min_score": 60, "overall_status": "Pass"}, update_modified=False),
		)
		self.assertIn("Fail → Pass", get_doc.return_value.add_comment.call_args.args[1])

	def test_ratings_that_could_not_be_read_get_no_overall_percent(self, _has, _meta, sql, set_value, get_value, get_doc):
		# entered through the old dialog: every rating stored as full stars, left as it was in October
		sql.return_value = [_db_row("r1", "QCF-1", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0), _db_row("r2", "QCF-1", 0.8, 0.8)]
		self._records(get_value, {"QCF-1": (0.9, "Fail")})

		percent_patch.execute()

		set_value.assert_called_once_with("QC Tasting Record", "QCF-1", {"avg_overall": 0, "min_score": 0}, update_modified=False)
		self.assertIn("check its scores", get_doc.return_value.add_comment.call_args.args[1])

	def test_full_marks_judged_in_stars_are_read(self, _has, _meta, sql, set_value, get_value, get_doc):
		# all 5 stars, entered in the desk form and judged in stars since: not one to doubt
		sql.return_value = [_db_row("r1", "QCF-1", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)]
		self._records(get_value, {"QCF-1": (5.0, "Pass")})

		percent_patch.execute()

		self.assertEqual(
			set_value.call_args_list[-1],
			call("QC Tasting Record", "QCF-1", {"avg_overall": 100, "min_score": 100, "overall_status": "Pass"}, update_modified=False),
		)

	def test_before_the_column_exists(self, has_column, _meta, sql, set_value, _get_value, _get_doc):
		has_column.return_value = False
		percent_patch.execute()
		sql.assert_not_called()
		set_value.assert_not_called()
