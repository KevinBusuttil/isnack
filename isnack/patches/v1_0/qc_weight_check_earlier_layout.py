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
    brings it back as it was: one that keeps the earlier layout, or whose
    samples have no Status (a restore could not give them one). The columns
    users chose for the Samples grid before are forgotten, so the grid shows
    the Status and Remarks.
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
    # a restore cannot give a sample the Status it never had
    earlier_layout.mark_deleted_documents(
        "QC Weight Check",
        lambda data: belongs_to_earlier_layout(data, data.get("samples") or ())
        or any(not s.get("status") for s in data.get("samples") or ()),
    )
    # columns a user chose for the samples grid before (Tare, Net Weight, In
    # Range) would keep the Status and Remarks out of it
    earlier_layout.forget_grid_columns("QC Weight Check", "QC Weight Sample")
