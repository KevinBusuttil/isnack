import frappe


def execute():
    """QC Packaging Check: Film Type, Film Batch and the material reconciliation
    (Qty Issued, Used and Returned) come off the check (2026-11).

    The checks made before keep them, in an Earlier Layout section, and keep the
    variance result worked out from them: mark them. Their fields and values
    are left as they are.
    """
    if not frappe.db.has_column("QC Packaging Check", "earlier_layout"):
        return
    # every check on the site was made in the earlier layout; a plain update
    # leaves their modified (and so their version history) alone
    frappe.db.sql("update `tabQC Packaging Check` set earlier_layout = 1")
