# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCOvenReading(Document):
	pass


def oven_averages(readings):
	"""Average zone 1 temperature, zone 2 temperature and moisture of oven
	readings, each 0 when no reading has it."""

	def average(fieldname):
		values = [getattr(r, fieldname) for r in readings if getattr(r, fieldname) is not None]
		return sum(values) / len(values) if values else 0

	return average("zone_1_temp"), average("zone_2_temp"), average("moisture")
