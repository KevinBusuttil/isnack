# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PalletDetail(Document):
	"""Child row describing one physical pallet of a shipment.

	Used as a child table on Delivery Note (``custom_pallets``) and copied onto
	the auto-created Packing Slip. Item rows reference pallets by number via
	their ``custom_pallet_nos`` field (e.g. ``"1-3"`` or ``"4,6"``), so several
	items/batches can share one physical (mixed) pallet.
	"""

	pass
