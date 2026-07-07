# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PalletDetail(Document):
	"""One allocation line of the pallet manifest: an exact quantity of an
	item (optionally batch-specific) stacked on one physical pallet.

	Used as the ``custom_pallets`` child table on Delivery Note and copied
	onto the auto-created Packing Slip. Several rows sharing a Pallet No
	describe one mixed pallet; one item split over several pallets simply has
	several rows. The pallet's type lives on every row of that pallet and
	must be consistent (validated on the Delivery Note).
	"""

	pass
