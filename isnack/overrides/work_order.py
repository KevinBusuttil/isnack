# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Work Order controller: backport of ERPNext's "Allow Editing of Items and
Quantities in Work Order" onto v15.87.2, without touching ERPNext.

What stock v15.87.2 does
------------------------
``WorkOrder.validate()`` ends with::

    validate_uom_is_integer(self, "stock_uom", ["required_qty"])
    self.set_required_items(reset_only_qty=len(self.get("required_items")))

so every save of an existing draft re-derives ``required_qty`` from the BOM. A
planner who sets RM20003 to 147.910 kg on MFG-WO-2026-00026 gets 155.365 kg back
(193 x 805 / 1000) the moment they hit Save.

What current ERPNext version-15 does
------------------------------------
Upstream gates the *call*, not the method::

    if not len(self.get("required_items")) or not frappe.db.get_single_value(
        "Manufacturing Settings", "allow_editing_of_items_and_quantities_in_work_order"
    ):
        self.set_required_items(reset_only_qty=len(self.get("required_items")))

Why overriding ``set_required_items`` is equivalent (and smaller)
----------------------------------------------------------------
``validate()`` is a 20-line method that differs between v15.87.2 and current
version-15 (``validate_dates``, ``validate_operations``, ``enable_auto_reserve_stock``,
``validate_subcontracting_inward_order`` are all newer). Copying it here would
fork ERPNext logic that iSnack would then have to maintain by hand across every
upgrade. Overriding the callee instead needs no copy at all.

That is only safe if *every* ``reset_only_qty=True`` call in v15.87.2 means "the
periodic BOM re-sync on save". Audited across the whole of erpnext at
v15.87.2 (``292f71bc``) there are exactly three call sites:

    work_order.py:170   validate()                      reset_only_qty=len(required_items)
    work_order.py:1128  get_items_and_operations_from_bom()   (no argument -> False)
    production_plan.py:855  wo.set_required_items()            (no argument -> False)

Only ``validate()`` ever passes a truthy ``reset_only_qty``, and it passes
``len(self.get("required_items"))`` — truthy exactly when rows already exist,
which is the same condition upstream's ``if`` tests. Suppressing that one call
therefore reproduces upstream's semantics exactly, including the fact that
upstream also skips the ``set_available_qty()`` that ``set_required_items``
performs at the end.

The other two call sites keep working untouched: both rebuild the table wholesale
(``reset_only_qty`` false), which is what an explicit "Get Items From BOM", a BOM
change, a ``use_multi_level_bom`` change, a Qty change (the Work Order form's
``qty`` handler re-triggers ``bom_no``) and Production Plan's Work Order creation
all rely on.

This class is registered through ``override_doctype_class`` in hooks.py. That is
orthogonal to ``doc_events``: Frappe still runs every hooked handler for the
doctype, so ``isnack.api.mes_ops.apply_line_warehouses_to_work_order`` continues
to fire on ``before_insert`` and ``validate`` exactly as before.
"""

from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

from isnack.utils.work_order_demand import allow_editing_items


class CustomWorkOrder(WorkOrder):
    def onload(self):
        """Extend ERPNext's onload rather than replace it.

        ``super().onload()`` keeps ``material_consumption``,
        ``backflush_raw_materials_based_on`` and ``overproduction_percentage``
        exactly as v15.87.2 sets them; only the new flag is added, under the
        same ``__onload`` key current upstream uses so the client script is a
        straight port.
        """
        super().onload()
        self.set_onload("allow_editing_items", 1 if allow_editing_items() else 0)

    def set_required_items(self, reset_only_qty=False):
        """Skip only the on-save BOM re-sync, and only while editing is enabled.

        Mirrors upstream's guard in ``validate()``:

        * ``reset_only_qty`` falsy -> a deliberate rebuild (Get Items From BOM,
          BOM/qty change, Production Plan). Always delegate.
        * no rows yet -> nothing to preserve; let ERPNext populate the table.
        * setting off -> stock v15.87.2 behaviour, quantities reset from the BOM.
        """
        if reset_only_qty and self.get("required_items") and allow_editing_items():
            return

        return super().set_required_items(reset_only_qty=reset_only_qty)
