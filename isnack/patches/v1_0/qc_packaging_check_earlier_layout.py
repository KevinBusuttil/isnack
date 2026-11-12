import frappe

from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import RETIRED_FIELDS, belongs_to_earlier_layout
from isnack.utils import earlier_layout


def execute():
    """QC Packaging Check: Film Type, Film Batch and the material reconciliation
    (Qty Issued, Used and Returned) come off the check (2026-11).

    The checks made before that keep them (submitted or cancelled, or a draft
    holding any) keep them in an Earlier Layout section, with the variance
    result worked out from them: mark them. A draft holding none is finished
    the new way. Fields and values are left as they are; so is ``modified``
    (and so the version history), a plain update.

    A check deleted before is marked in its Deleted Document too, so a restore
    brings it back as it was.
    """
    if not frappe.db.has_column("QC Packaging Check", "earlier_layout"):
        return

    checks = frappe.get_all("QC Packaging Check", fields=["name", "docstatus", *RETIRED_FIELDS])
    earlier_layout.mark_records("QC Packaging Check", [c.name for c in checks if belongs_to_earlier_layout(c)])
    earlier_layout.mark_deleted_documents("QC Packaging Check", belongs_to_earlier_layout)
