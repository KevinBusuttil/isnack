import frappe
from frappe.utils import flt


def _get_customer_discount_rule(customer, item_code):
    """
    Return a single Customer Discount Rules row (if any) for this
    customer + item.

    Uses the 'Customer Discount Rules' doctype you defined:

      - customer
      - item
      - discount_tier_1
      - discount_tier_2
      - pricing_rule_tier_1
      - pricing_rule_tier_2
    """
    if not customer or not item_code:
        return None

    rows = frappe.get_all(
        "Customer Discount Rules",
        filters={"customer": customer, "item": item_code},
        fields=[
            "name",
            "discount_tier_1",
            "discount_tier_2",
            "pricing_rule_tier_1",
            "pricing_rule_tier_2",
        ],
        limit=1,
    )
    return rows[0] if rows else None


def _get_applicable_pricing_rules(doc, row):
    """
    Fallback: infer applicable rules for this row from Sales Invoice.Pricing Rules
    (doc.pricing_rules), when no Customer Discount Rules entry exists.

    - Item-specific rules: prd.item_code == row.item_code
    - Global rules: prd.item_code is empty
    """
    rules = []
    for prd in getattr(doc, "pricing_rules", []) or []:
        if not getattr(prd, "pricing_rule", None):
            continue

        # Item-specific rule
        if getattr(prd, "item_code", None):
            if prd.item_code != row.item_code:
                continue
            rules.append(prd.pricing_rule)
        else:
            # Global rule (no item_code)
            rules.append(prd.pricing_rule)

    return rules


def _pricing_rule_discount_percent(rule_name, base_rate):
    """
    Given a Pricing Rule name and a base_rate (price_list_rate),
    return an effective discount % for that rule.

    Handles:
    - discount_percentage
    - discount_amount -> converted to %
    - rate_or_discount == "Rate" -> convert rate difference to %
    """
    if not rule_name:
        return 0.0

    try:
        pr = frappe.get_cached_doc("Pricing Rule", rule_name)
    except Exception:
        return 0.0

    base_rate = flt(base_rate)
    pct = 0.0

    # Case 1: explicit discount percentage
    if getattr(pr, "discount_percentage", None):
        pct = flt(pr.discount_percentage)

    # Case 2: explicit discount amount (flat) -> convert to %
    elif getattr(pr, "discount_amount", None) and base_rate:
        pct = flt(pr.discount_amount) / base_rate * 100.0

    # Case 3: rule sets a specific rate
    elif (
        getattr(pr, "rate_or_discount", None) == "Rate"
        and getattr(pr, "rate", None)
        and base_rate
    ):
        pct = (base_rate - flt(pr.rate)) / base_rate * 100.0

    return pct


def get_item_discounts(doc, row):
    """
    Compute discount figures for a Sales Invoice Item row.

    Priority for tier order:

    1) If a 'Customer Discount Rules' record exists for (doc.customer, row.item_code),
       use:
         - pricing_rule_tier_1 / pricing_rule_tier_2
         - discount_tier_1 / discount_tier_2 (if set)
       to determine Tier 1 and Tier 2 percentages.

    2) Otherwise, fall back to the first two applicable rules in doc.pricing_rules.

    Returns frappe._dict with:
      base_rate       : rate before discounts (prefer price_list_rate)
      base_amount     : qty * base_rate
      disc1_percent   : Tier 1 discount %
      disc2_percent   : Tier 2 discount %
      disc1_amount    : Tier 1 discount amount
      disc2_amount    : Tier 2 discount amount
      total           : line total after both tiers
    """
    base_rate = flt(getattr(row, "price_list_rate", 0) or getattr(row, "rate", 0) or 0)
    qty = flt(getattr(row, "qty", 0) or 0)
    base_amount = base_rate * qty

    customer = getattr(doc, "customer", None)
    item_code = getattr(row, "item_code", None)

    disc1_percent = 0.0
    disc2_percent = 0.0

    # --- 1) Try Customer Discount Rules for explicit tier order ---
    cdr = _get_customer_discount_rule(customer, item_code)
    if cdr:
        # If discount_tier_X is set, that is the primary source of truth.
        if cdr.get("discount_tier_1") is not None:
            disc1_percent = flt(cdr.get("discount_tier_1"))
        elif cdr.get("pricing_rule_tier_1"):
            disc1_percent = _pricing_rule_discount_percent(
                cdr.get("pricing_rule_tier_1"), base_rate
            )

        if cdr.get("discount_tier_2") is not None:
            disc2_percent = flt(cdr.get("discount_tier_2"))
        elif cdr.get("pricing_rule_tier_2"):
            disc2_percent = _pricing_rule_discount_percent(
                cdr.get("pricing_rule_tier_2"), base_rate
            )

    # --- 2) Fallback to applied rules on the Sales Invoice itself ---
    if not cdr:
        applicable_rules = _get_applicable_pricing_rules(doc, row)

        if len(applicable_rules) > 0:
            disc1_percent = _pricing_rule_discount_percent(
                applicable_rules[0], base_rate
            )
        if len(applicable_rules) > 1:
            disc2_percent = _pricing_rule_discount_percent(
                applicable_rules[1], base_rate
            )

    # --- Amounts and final total ---
    disc1_amount = base_amount * disc1_percent / 100.0
    disc2_amount = (base_amount - disc1_amount) * disc2_percent / 100.0
    total = base_amount - disc1_amount - disc2_amount

    return frappe._dict(
        base_rate=base_rate,
        base_amount=base_amount,
        disc1_percent=disc1_percent,
        disc2_percent=disc2_percent,
        disc1_amount=disc1_amount,
        disc2_amount=disc2_amount,
        total=total,
    )
