import frappe

from isnack.isnack.doctype.qc_weight_check.qc_weight_check import belongs_to_earlier_layout
from isnack.utils import earlier_layout


def execute():
    """QC Weight Check: the TU1 and TU2 limits, the tare, the Overall Status and
    the record's Remarks come off the check (2026-11); each sample gets a
    Status and Remarks of its own.

    The checks made before that keep them (submitted or cancelled, or a draft
    holding any) keep them in an Earlier Layout section, with the Overall
    Status they were given: mark them. A draft holding none is finished the new
    way. Fields and values are left as they are; so is ``modified`` (and so the
    version history), a plain update.

    A check deleted before is marked in its Deleted Document too, so a restore
    brings it back as it was.
    """
    if not frappe.db.has_column("QC Weight Check", "earlier_layout"):
        return

    with_tare = {}
    for sample in frappe.get_all(
        "QC Weight Sample",
        filters={"parenttype": "QC Weight Check", "tare_weight": ["!=", 0]},
        fields=["parent", "tare_weight"],
    ):
        with_tare.setdefault(sample.parent, []).append(sample)
    checks = frappe.get_all(
        "QC Weight Check", fields=["name", "docstatus", "tu1_limit", "tu2_limit", "overall_status", "remarks"]
    )
    earlier_layout.mark_records(
        "QC Weight Check", [c.name for c in checks if belongs_to_earlier_layout(c, with_tare.get(c.name, ()))]
    )
    earlier_layout.mark_deleted_documents(
        "QC Weight Check", lambda data: belongs_to_earlier_layout(data, data.get("samples") or ())
    )
