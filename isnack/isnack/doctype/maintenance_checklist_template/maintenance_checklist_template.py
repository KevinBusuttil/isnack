import frappe
from frappe.model.document import Document


class MaintenanceChecklistTemplate(Document):
    def validate(self):
        # Normalise sequence ordering for predictable rendering.
        for idx, row in enumerate(
            sorted(self.items, key=lambda r: (r.sequence or 0, r.idx)), start=1
        ):
            if not row.sequence:
                row.sequence = idx * 10


def find_matching_template(asset_category=None, item_code=None, maintenance_type=None,
                           maintenance_task=None, company=None):
    """Return the most specific enabled template matching the given criteria.

    Specificity is scored: item_code > asset_category, plus maintenance_task and
    maintenance_type matches. Returns the template name or ``None``.
    """
    templates = frappe.get_all(
        "Maintenance Checklist Template",
        filters={"enabled": 1},
        fields=[
            "name", "asset_category", "item_code", "maintenance_type",
            "maintenance_task", "company",
        ],
    )

    best, best_score = None, -1
    for t in templates:
        # Disqualify on any mismatching non-empty criterion.
        if t.company and company and t.company != company:
            continue
        if t.item_code and item_code and t.item_code != item_code:
            continue
        if t.asset_category and asset_category and t.asset_category != asset_category:
            continue
        if t.maintenance_type and maintenance_type and t.maintenance_type != maintenance_type:
            continue
        if t.maintenance_task and maintenance_task and t.maintenance_task != maintenance_task:
            continue

        score = 0
        if t.item_code and t.item_code == item_code:
            score += 8
        if t.asset_category and t.asset_category == asset_category:
            score += 4
        if t.maintenance_task and t.maintenance_task == maintenance_task:
            score += 2
        if t.maintenance_type and t.maintenance_type == maintenance_type:
            score += 1
        if score > best_score:
            best, best_score = t.name, score

    return best
