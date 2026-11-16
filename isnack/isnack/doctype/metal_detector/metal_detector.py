# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MetalDetector(Document):
	"""A metal detector the QC Metal Detector Logs verify. A log picks one by
	its ID and takes its Make/Model and calibration dates (fetch_from), as they
	are when the log is saved: a submitted log keeps them."""

	pass
