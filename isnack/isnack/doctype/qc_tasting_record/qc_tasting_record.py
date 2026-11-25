# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt

# The scores a taster gives, each a Rating; their Overall % is worked out from them.
CRITERIA = ("appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score")

# The average Overall % a tasting needs to pass: 3 of 5 stars.
PASS_THRESHOLD_PERCENT = 60.0

# A tasting is of a finished good: its Batch No is a batch of an item of this
# group, or of one under it (2026-11). The Quality Hub's Product Item picks the
# same items (isnack/public/js/quality_hub_lines.js, product_query).
FINISHED_GOODS = "Finished Goods"


class QCTastingRecord(Document):
    def validate(self):
        require_finished_good_batch(self)
        # Overall % of each taster; one who gave no score at all is left out of
        # the average, not counted as 0
        scored = []
        for row in self.scores or []:
            row.overall_percent = overall_percent(row)
            if any(flt(row.get(f)) > 0 for f in CRITERIA):
                scored.append(row.overall_percent)
        self.avg_overall = flt(sum(scored) / len(scored), 2) if scored else 0
        self.min_score = min(scored) if scored else 0
        self.overall_status = "Pass" if scored and self.avg_overall >= PASS_THRESHOLD_PERCENT else "Fail"


def require_finished_good_batch(doc):
    """The Batch No is a finished good's batch (2026-11): the batch picker
    offers only those, but a Link takes any batch typed in full, and an
    import or the API any batch at all. A record keeps the batch it has,
    or the record it amends had: one saved before may hold another."""
    batch = cstr(getattr(doc, "batch_no", None)).strip()
    if not batch:
        return  # (mandatory: refused for it, later)
    if doc.is_new():
        kept = doc.amended_from and frappe.db.get_value(doc.doctype, doc.amended_from, "batch_no")
    else:
        kept = frappe.db.get_value(doc.doctype, doc.name, "batch_no")
    if kept and cstr(kept).strip().casefold() == batch.casefold():
        return
    item = frappe.db.get_value("Batch", batch, "item")
    if not item:
        return  # (Frappe's link check refuses a batch there is not)
    if item not in finished_goods():
        frappe.throw(
            _("Batch {0} is of {1} ({2}), not of a finished good: pick the batch of the product tasted.").format(
                frappe.bold(batch), frappe.bold(item), frappe.db.get_value("Item", item, "item_group") or _("no item group")
            ),
            title=_("Batch No"),
        )


def finished_goods() -> list[str]:
    """The items of the Finished Goods item group, or of a group under it."""
    group = frappe.db.get_value("Item Group", FINISHED_GOODS, ["lft", "rgt"], as_dict=True)
    if not group:
        return []
    groups = frappe.get_all("Item Group", filters={"lft": [">=", group.lft], "rgt": ["<=", group.rgt]}, pluck="name")
    return frappe.get_all("Item", filters={"item_group": ["in", groups]}, pluck="name")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def finished_good_batches(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
    """The Batch No's search on a QC Tasting Record (the form and the Quality
    Hub's dialog): the batches of finished goods, not disabled, newest first,
    by batch or item; once a Work Order is picked, only those of the item it
    makes. None for a user who may not record a tasting."""
    if not (frappe.has_permission("QC Tasting Record", "create") or frappe.has_permission("QC Tasting Record", "write")):
        return []
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    items = finished_goods()
    work_order = cstr(filters.get("work_order")).strip()
    if work_order:
        made = frappe.db.get_value("Work Order", work_order, "production_item")
        if made in items:
            items = [made]
    if not items:
        return []
    like = f"%{txt or ''}%"
    return frappe.get_all(
        "Batch",
        filters={"item": ["in", items], "disabled": 0},
        or_filters={"name": ["like", like], "item": ["like", like]},
        fields=["name", "item", "manufacturing_date"],
        order_by="manufacturing_date desc, creation desc",
        limit_start=start,
        limit_page_length=page_len,
        as_list=not as_dict,
    )


def overall_percent(row) -> float:
    """A taster's scores as a percentage of full marks: the stars given on
    Shape, Colour, Smell, Taste and Texture over 5 x 5. A score left blank
    counts as 0.

    Frappe keeps a Rating as the fraction of stars given (4 of 5 stars is 0.8),
    so full marks are a fraction of 1 on each score.
    """
    return flt(sum(min(flt(row.get(f)), 1) for f in CRITERIA) / len(CRITERIA) * 100, 2)


def stars_out_of() -> int:
    """How many stars the tasting score ratings have (the Rating field's options, 5 by default)."""
    field = frappe.get_meta("QC Tasting Score").get_field("appearance_score")
    return cint(field.options if field else 0) or 5
