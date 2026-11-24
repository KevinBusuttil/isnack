# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCMetalDetectorTest(Document):
	def __setup__(self):
		# On saving, Frappe gives a new test a Test Time it was not sent (the time
		# of saving) and a Select its first option: a test sent without them (from a
		# page loaded before 2026-11, or through the API) is refused rather than
		# given them (QCMetalDetectorLog.require_detector_and_tests), and the tests
		# of a log made before keep a missing time as it was when it is amended or
		# restored. A Data Import gives a blank Test Time the time of import as it
		# makes the row, which isnack.utils.qc_import refuses.
		self.dont_update_if_missing = ["test_time", "test_piece_type"]
