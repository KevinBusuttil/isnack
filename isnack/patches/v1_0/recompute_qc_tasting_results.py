import frappe

from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import QCTastingRecord


def execute():
    """Recompute the result of every QC Tasting Record on the star scale.

    Frappe keeps a Rating as the fraction of stars given (0..1), and the record
    compared that fraction with a threshold in stars (3.0), so every tasting
    read "Fail". Averages, minimum and result are recomputed from the stored
    scores; drafts and submitted records alike, cancelled ones are left alone.
    """
    if not frappe.db.table_exists("QC Tasting Record"):
        return

    for name in frappe.get_all("QC Tasting Record", filters={"docstatus": ["<", 2]}, pluck="name"):
        doc = frappe.get_doc("QC Tasting Record", name)
        QCTastingRecord.validate(doc)
        doc.db_set(
            {
                "avg_overall": doc.avg_overall,
                "min_score": doc.min_score,
                "overall_status": doc.overall_status,
            },
            update_modified=False,
        )
