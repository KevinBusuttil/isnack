import frappe
from frappe.utils import flt

from isnack.isnack.doctype.qc_oven_reading.qc_oven_reading import average

# Each average of a QC Frying Line Record: its field, the reading it averages
# and its label.
AVERAGES = (
    ("avg_oil_temperature", "oil_temperature", "Avg Oil Temperature (°C)"),
    ("avg_product_moisture", "product_moisture", "Avg Moisture Content (%)"),
)


def execute():
    """QC Frying Line Record: work the reading averages out again, leaving the
    readings left blank out (2026-11).

    Frappe saves a blank Float as 0, and until 2026-11 the record counted that 0
    in Avg Oil Temperature (°C) and Avg Moisture Content (%) once the blank had
    been saved: a record saved in the desk and then submitted, for one, averaged
    a reading left blank as 0, which pulled the average down. The record now
    leaves it out, as the extruder records do (average(..., zero_is_blank=True)),
    but a submitted record is never worked out again. So the averages of every
    record but the cancelled ones are worked out again from its stored
    readings. Only a record whose averages change is written, leaving its
    modified date alone, with an Info comment saying what changed.
    """
    if not frappe.db.table_exists("QC Frying Line Record"):
        return

    for name in frappe.get_all("QC Frying Line Record", filters={"docstatus": ["<", 2]}, pluck="name"):
        doc = frappe.get_doc("QC Frying Line Record", name)
        readings = doc.readings or []
        after = {field: average(readings, reading, zero_is_blank=True) for field, reading, _label in AVERAGES}
        changed = [
            (label, flt(doc.get(field)), after[field])
            for field, _reading, label in AVERAGES
            if flt(after[field], 6) != flt(doc.get(field), 6)
        ]
        if not changed:
            continue
        doc.db_set(after, update_modified=False)
        # db_set keeps no version: say on the record what changed
        doc.add_comment(
            "Info",
            "Averages worked out again, leaving readings left blank out: "
            + "; ".join(f"{label} {flt(old, 3)} → {flt(new, 3)}" for label, old, new in changed)
            + ".",
        )
