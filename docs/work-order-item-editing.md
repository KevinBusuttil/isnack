# Allow Editing of Items and Quantities in Work Order

Backport of ERPNext `version-15`'s Work Order editing feature onto the
production checkout (ERPNext `v15.87.2`, commit `292f71bc`), implemented
entirely inside the iSnack app.

## Why

ERPNext v15.87.2 re-derives `Work Order.required_items` from the BOM on every
save:

```python
# erpnext/manufacturing/doctype/work_order/work_order.py (v15.87.2, line 170)
self.set_required_items(reset_only_qty=len(self.get("required_items")))
```

So on MFG-WO-2026-00026 (qty 193, BOM-FG10005-001, RM20003 at 805 kg / 1000
units) a planner who types 147.910 kg gets 155.365 kg back the moment they save.

Current ERPNext `version-15` added a Manufacturing Settings switch (upstream
commit `b5e6c3e`, refined by `62d5870` and `3c327d5`) that skips that reset. This
backport reproduces its semantics without modifying `apps/erpnext` or
`apps/frappe`.

## The setting

| | |
|---|---|
| Doctype | Manufacturing Settings (BOM section) |
| Label | Allow Editing of Items and Quantities in Work Order |
| iSnack fieldname | `custom_allow_editing_of_items_and_quantities_in_work_order` |
| Upstream fieldname | `allow_editing_of_items_and_quantities_in_work_order` |
| Type / default | Check / **0 (off)** |

Shipped as a Custom Field in `isnack/isnack/custom/manufacturing_settings.json`
(`sync_on_migrate`), the same mechanism the app already uses for its Work Order,
BOM and Stock Entry customisations. It is deliberately **not** duplicated into
`isnack/fixtures/custom_field.json`.

The `custom_` prefix means the field can never collide with the real upstream
column when ERPNext is upgraded past v15.87.2.
`isnack.utils.work_order_demand.allow_editing_items()` reads the upstream field
first and falls back to the iSnack one, so after an upgrade the real setting
drives the feature — and a site that had already switched the iSnack field on
does not silently lose the behaviour. Retiring the iSnack field afterwards is a
one-line patch.

Installing or migrating changes nothing until somebody ticks the box.

## What changes when it is ON

### Work Order

`isnack.overrides.work_order.CustomWorkOrder` (registered in
`override_doctype_class`) overrides `set_required_items()` and suppresses only
the on-save re-sync. Every other path still rebuilds the table from the BOM:
"Get Items From BOM", a BOM change, a `use_multi_level_bom` change, a Qty change
(the form re-triggers `bom_no`), and Production Plan's Work Order creation. An
empty `required_items` table is always repopulated.

`onload()` additionally exposes `__onload.allow_editing_items`;
`isnack/public/js/work_order.js` uses it to unlock `cannot_add_rows`,
`cannot_delete_rows` and the `item_code` / `required_qty` columns — and to lock
them when the setting is off, matching current upstream. Read-only columns
(`transferred_qty`, `consumed_qty`, `returned_qty`, rates, availability) stay
read-only in both states, and docstatus/permission handling is left to Frappe.

The controller class is orthogonal to the Work Order `doc_events`; the Factory
Section / warehouse hook `isnack.api.mes_ops.apply_line_warehouses_to_work_order`
still runs on `before_insert` and `validate` exactly as before.

### Material demand across iSnack

Preserving the row is not enough: the Storekeeper Hub and Operator Hub derived
demand from the BOM, so an edited Work Order would still be staged and consumed
against 155.365 kg. `isnack/utils/work_order_demand.py` is the single place that
reconciles the two, and it is a no-op while the setting is off.

The rule is: **BOM decides membership, Work Order decides quantity.**

| Item | Behaviour |
|---|---|
| On the BOM **and** on the Work Order | Work Order `required_qty` wins |
| On the BOM, deleted from the Work Order | demand removed (planning paths) |
| On the Work Order, unknown to the BOM ("manual") | demand added |
| On the BOM but outside the Work Order table's scope — e.g. an exploded sub-assembly raw material on a single-level Work Order | untouched, BOM quantity kept |

"Unknown to the BOM" means absent from both `BOM Item` and `BOM Explosion Item`.
That is what keeps the parent / semi-finished separation intact: an SFG's raw
material is BOM-known, so it can never be promoted into a parent finished-good
Work Order's leaf demand, and `_validate_item_in_bom` still refuses to consume it
against the parent.

Call sites that now respect the saved quantities:

* `storekeeper_hub._required_leaf_map_for_wo` / `_required_map_for_wo` — and
  therefore `_remaining_leaf_map_for_wo`, `_stage_status`,
  `get_consolidated_remaining*` and `create_consolidated_transfers`
* `mes_ops._planned_items_for_wo` — used by `get_requestable_items_for_wo`,
  `_end_wo_consumption_summary`, `complete_work_order` and `_close_single_wo`
  (rescaled by `production qty / Work Order qty`)
* `mes_ops.get_materials_snapshot`, `get_manual_load_item_context`
* the over-consumption ceiling in `scan_material` and
  `_post_material_consumption_for_wo`
* `get_staging_items_for_wo` — the Manual Load picker also offers hand-added rows

Call sites that stay BOM-based on purpose:

* `_validate_item_in_bom`'s DIRECT `BOM Item` membership test (plus hand-added
  rows only)
* `get_sfg_components_for_wo` — semi-finished detection is structural
* `get_packaging_bom_items_for_ended_wos` — packaging item universe
* `_get_bom_items_for_quantity` itself, which remains a pure BOM read

## What happens when it is OFF

Everything behaves exactly as ERPNext v15.87.2 and iSnack do today. The Work
Order resets `required_qty` from the BOM on save; the overlay short-circuits
before issuing a single extra query, so Storekeeper Hub maps, staged status,
consolidated allocation, Operator Hub snapshots, End WO tolerances, Close
Production consumption and over-consumption ceilings are unchanged. The grid also
locks `item_code` / `required_qty`, matching current upstream.

## Interaction with "Validate Components and Quantities Per BOM"

That is a **separate, independent** Manufacturing Settings switch
(`validate_components_quantities_per_bom`). This backport does not read it, does
not change it and does not weaken it.

When it is enabled, `StockEntry.validate()` runs
`validate_component_and_quantities()` (erpnext v15.87.2,
`stock/doctype/stock_entry/stock_entry.py:769`) for purposes **Manufacture** and
**Material Transfer for Manufacture** with a non-zero `fg_completed_qty`. It
compares each row against `get_bom_raw_materials(fg_completed_qty)` — a pure BOM
read — and throws:

* *Incorrect Component Quantity* when a row differs from the BOM figure
* *Missing Item* when a BOM item has no row at all

So with both settings on, an edited Work Order will be rejected at posting time:
the iSnack entries in scope are `transfer_staged_to_wip` (Material Transfer for
Manufacture), `complete_work_order` and `_close_single_wo` (Manufacture). The
LOAD / scan path posts *Material Consumption for Manufacture*, which is outside
that validation's purpose list and is unaffected.

Note this is not new tension introduced by the backport: iSnack already posts
*remainders* on those entries (whatever the operator did not consume via LOAD),
which the same validation would already reject. In practice the setting is off on
this site, and it must stay off for Work Order editing to be usable. Turning it
back on is a deliberate business decision that re-imposes "the BOM is the only
truth" — it is not something this feature should quietly override.

## Known limitations

* **A hand-added item that happens to be a sub-assembly's raw material** is
  treated as BOM-known, so it does not join the parent's leaf staging demand and
  cannot be loaded against the parent. That is the conservative choice: the
  alternative would let a parent Work Order claim material belonging to a
  separate SFG Work Order. Add such material to the SFG's own Work Order.
* **A deleted row does not zero the over-consumption ceiling.** Planning paths
  honour the deletion, but `scan_material` / Manual Load fall back to the BOM
  ceiling rather than blocking the operator mid-shift over a planning edit. The
  same fallback drives the Manual Load dialog's Required / Remaining display.
* **Changing Qty To Manufacture rebuilds the table from the BOM** and discards
  manual quantities, because the Work Order form re-triggers
  `get_items_and_operations_from_bom`. This is upstream behaviour, not a
  backport artefact: re-apply the manual quantities after changing the Qty.
* **Editing is only meaningful before material movement.** Nothing recalculates
  already-transferred or already-consumed quantities; reducing a requirement
  below what is already staged simply leaves that stock in staging (visible as
  surplus at the next consolidated transfer).
