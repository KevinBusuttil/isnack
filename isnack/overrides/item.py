from frappe.utils import flt


def sync_weight_per_unit(doc, method=None):
    """
    Keep Item.weight_per_unit in sync with:
      - custom_net_weight_per_unit
      - custom_tare_weight_per_unit
    """
    if not _should_sync_weight_per_unit(doc):
        return

    doc.weight_per_unit = flt(doc.get("custom_net_weight_per_unit")) + flt(
        doc.get("custom_tare_weight_per_unit")
    )


def _should_sync_weight_per_unit(doc):
    net_weight = doc.get("custom_net_weight_per_unit")
    tare_weight = doc.get("custom_tare_weight_per_unit")

    if doc.is_new():
        return net_weight not in (None, "") or tare_weight not in (None, "")

    previous_doc = doc.get_doc_before_save()
    if not previous_doc:
        return False

    return (net_weight != previous_doc.get("custom_net_weight_per_unit")) or (
        tare_weight != previous_doc.get("custom_tare_weight_per_unit")
    )
