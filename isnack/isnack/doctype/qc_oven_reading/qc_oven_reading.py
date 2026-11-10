# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QCOvenReading(Document):
	pass


def average(readings, fieldname, zero_is_blank=False):
	"""Average ``fieldname`` over the readings that have it, 0 when none has.

	Frappe saves a blank Float as 0, so a reading left blank is None only until
	the record is first saved, and 0 from then on. ``zero_is_blank`` leaves the
	zeros out too, for a measure that is never 0, so that saving again or
	submitting gives the same average."""
	values = [getattr(r, fieldname) for r in readings if getattr(r, fieldname) is not None]
	if zero_is_blank:
		values = [v for v in values if v]
	return sum(values) / len(values) if values else 0


def oven_averages(readings):
	"""Average zone 1 temperature, zone 2 temperature and moisture of oven
	readings, each 0 when no reading has it."""
	return average(readings, "zone_1_temp"), average(readings, "zone_2_temp"), average(readings, "moisture")
