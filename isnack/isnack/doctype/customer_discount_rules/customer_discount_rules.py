# Copyright (c) 2025, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

class CustomerDiscountRules(Document):
    def after_insert(self):
        self.sync_pricing_rules()

    def on_update(self):
        self.sync_pricing_rules()

    def on_trash(self):
        self.delete_pricing_rules()

    def sync_pricing_rules(self):
        tier_1_name = self._upsert_pricing_rule(
            tier="T1",
            discount=self.discount_tier_1,
            priority=20,
            allow_multiple=1,
        )
        tier_2_name = None
        if self.discount_tier_2:
            tier_2_name = self._upsert_pricing_rule(
                tier="T2",
                discount=self.discount_tier_2,
                priority=10,
                allow_multiple=1,
            )
        else:
            self._delete_pricing_rule(tier="T2", link_field="pricing_rule_tier_2", priority=10)

        if tier_1_name:
            self.db_set("pricing_rule_tier_1", tier_1_name, update_modified=False)
        if tier_2_name:
            self.db_set("pricing_rule_tier_2", tier_2_name, update_modified=False)
        elif self.pricing_rule_tier_2:
            self.db_set("pricing_rule_tier_2", None, update_modified=False)

    def delete_pricing_rules(self):
        self._delete_pricing_rule(tier="T1", link_field="pricing_rule_tier_1", priority=20)
        self._delete_pricing_rule(tier="T2", link_field="pricing_rule_tier_2", priority=10)

    def _upsert_pricing_rule(self, tier: str, discount: float, priority: int, allow_multiple: int) -> str | None:
        if discount is None:
            return None

        link_field = "pricing_rule_tier_1" if tier == "T1" else "pricing_rule_tier_2"
        doc = self._find_existing_pricing_rule(link_field=link_field, priority=priority)

        if not doc:
            doc = frappe.new_doc("Pricing Rule")

        company = frappe.defaults.get_user_default("company")
        doc.update(
            {
                "title": f"{self.customer} {self.item} {tier}",
                "apply_on": "Item Code",
                "items": [{"item_code": self.item}],
                "applicable_for": "Customer",
                "customer": self.customer,
                "selling": 1,
                "price_or_product_discount": "Price",
                "rate_or_discount": "Discount Percentage",
                "discount_percentage": discount,
                "priority": priority,
                "apply_multiple_pricing_rules": allow_multiple,
                "apply_discount_on_rate": 1,
                "company": company,
                "disable": 0,
            }
        )

        doc.flags.ignore_permissions = True
        doc.save(ignore_version=True)

        return doc.name

    def _find_existing_pricing_rule(self, link_field: str, priority: int):
        link_name = getattr(self, link_field)
        if link_name and frappe.db.exists("Pricing Rule", link_name):
            return frappe.get_doc("Pricing Rule", link_name)

        filters = {
            "applicable_for": "Customer",
            "customer": self.customer,
            "selling": 1,
            "apply_on": "Item Code",
            "price_or_product_discount": "Price",
            "priority": priority,
            "items.item_code": self.item,  
        }

        query = frappe.qb.get_query(
            "Pricing Rule",
            fields=["name"],
            filters=filters,
            distinct=True,
            limit=1,
        )
        names = query.run(pluck=True)

        if names:
            return frappe.get_doc("Pricing Rule", names[0])

        return None

    def _delete_pricing_rule(self, tier: str, link_field: str, priority: int):
        link_name = getattr(self, link_field)
        if link_name and frappe.db.exists("Pricing Rule", link_name):
            frappe.delete_doc("Pricing Rule", link_name, force=1, ignore_permissions=True)
            self.db_set(link_field, None, update_modified=False)

        filters = {
            "applicable_for": "Customer",
            "customer": self.customer,
            "selling": 1,
            "apply_on": "Item Code",
            "price_or_product_discount": "Price",
            "priority": priority,
            "title": f"{self.customer} {self.item} {tier}",
            "items.item_code": self.item,   
        }

        query = frappe.qb.get_query(
            "Pricing Rule",
            fields=["name"],
            filters=filters,
            distinct=True,
        )
        duplicates = query.run(pluck=True)

        for name in duplicates:
            if name != link_name:
                frappe.delete_doc("Pricing Rule", name, force=1, ignore_permissions=True)

@frappe.whitelist()
def bulk_adjust_discounts(
    names: list[str] | str,
    tier1_action: str | None = None,
    tier1_value: float | int | str | None = None,
    tier2_action: str | None = None,
    tier2_value: float | int | str | None = None,
):
    """Adjust tier discounts for multiple Customer Discount Rules records.

    Actions:
    - Tier 1: add / deduct
    - Tier 2: add / deduct / clear
    """

    docnames = _parse_names(names)
    if not docnames:
        frappe.throw("No Customer Discount Rules selected")

    tier1_action = _normalize_action(tier1_action, {"add", "deduct"})
    tier2_action = _normalize_action(tier2_action, {"add", "deduct", "clear"})

    tier1_delta = _coerce_delta(tier1_value, tier1_action)
    tier2_delta = _coerce_delta(tier2_value, tier2_action)

    updated = 0
    for name in docnames:
        doc: CustomerDiscountRules = frappe.get_doc("Customer Discount Rules", name)

        if tier1_action:
            doc.discount_tier_1 = _apply_delta(doc.discount_tier_1, tier1_delta, tier1_action)

        if tier2_action:
            if tier2_action == "clear":
                doc.discount_tier_2 = None
            else:
                doc.discount_tier_2 = _apply_delta(doc.discount_tier_2, tier2_delta, tier2_action)

        if tier1_action or tier2_action:
            doc.save()
            updated += 1

    return {"updated": updated}


def _parse_names(names: list[str] | str | None) -> list[str]:
    if names is None:
        return []
    if isinstance(names, str):
        try:
            names = frappe.parse_json(names)
        except Exception:
            names = [names]
    return [name for name in names if name]


def _normalize_action(action: str | None, allowed: set[str]) -> str | None:
    if not action:
        return None
    action = action.lower()
    if action not in allowed:
        frappe.throw(f"Invalid action: {action}")
    return action


def _coerce_delta(value: float | int | str | None, action: str | None) -> float:
    if not action:
        return 0.0
    if action == "clear":
        return 0.0
    if value is None or value == "":
        frappe.throw("Please provide a discount change value for the selected action")
    return flt(value)


def _apply_delta(current: float | None, delta: float, action: str) -> float:
    base = flt(current)
    if action == "add":
        return base + delta
    if action == "deduct":
        return base - delta
    return base                