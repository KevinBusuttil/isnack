import frappe

from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import CHECKS, checks_result


def execute():
    """QC Packaging Check: an Overall Status (2026-11), Pass when Print Quality
    OK, Seal Integrity OK, Packet Label Correct and Artwork Matches are all
    ticked, otherwise Fail. A save works it out; this sets it on the checks
    made since the earlier layout (``earlier_layout`` not set), drafts,
    submitted and cancelled ones alike, which a save cannot reach. A check made
    before keeps its variance result and gets none.

    A plain update: ``modified`` (and so the version history) is left alone.
    """
    if not (
        frappe.db.has_column("QC Packaging Check", "overall_status")
        and frappe.db.has_column("QC Packaging Check", "earlier_layout")
    ):
        return

    checks = frappe.get_all("QC Packaging Check", filters={"earlier_layout": 0}, fields=["name", *CHECKS])
    for result in ("Pass", "Fail"):
        names = [check.name for check in checks if checks_result(check) == result]
        if names:
            frappe.db.sql(
                "update `tabQC Packaging Check` set overall_status = %(result)s where name in %(names)s",
                {"result": result, "names": tuple(names)},
            )
