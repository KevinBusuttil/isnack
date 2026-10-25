import frappe
from frappe.utils import flt

from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import QCTastingRecord, stars_out_of


def execute():
    """Recompute the result of every QC Tasting Record on the star scale.

    Frappe keeps a Rating as the fraction of stars given (0..1), and the record
    compared that fraction with a threshold in stars (3.0), so every tasting
    read "Fail". Averages, minimum and result are recomputed from the stored
    scores; drafts and submitted records alike, cancelled ones are left alone.

    The Quality Hub dialog sent stars (1..5) rather than the fraction, which
    Frappe clamped to 1.0: from its rows 1 star and 5 stars read the same. A
    row whose every rating is 1.0 may be one of those (a dialog draft may have
    had rows added in the desk form since), so a record holding one is left
    as it was, rather than turned into a pass on 5-star scores, and flagged
    for QC.
    """
    if not frappe.db.table_exists("QC Tasting Record"):
        return

    rating_fields = [
        df.fieldname for df in frappe.get_meta("QC Tasting Score").fields if df.fieldtype == "Rating"
    ]
    top = stars_out_of()
    unclear = []
    for name in frappe.get_all("QC Tasting Record", filters={"docstatus": ["<", 2]}, pluck="name"):
        doc = frappe.get_doc("QC Tasting Record", name)
        if any(_may_be_clamped(row, rating_fields) for row in doc.scores or []):
            unclear.append(name)
            doc.add_comment(
                "Info",
                f"A taster's ratings on this tasting all read {top} stars. Ratings entered through the "
                f"Quality Hub dialog before this update were all stored as {top} stars, whatever the "
                "taster gave, so the result was left as it was. Check the scores and enter them again "
                "if needed.",
            )
            continue

        before = (flt(doc.avg_overall, 6), flt(doc.min_score, 6), doc.overall_status)
        QCTastingRecord.validate(doc)
        if (flt(doc.avg_overall, 6), flt(doc.min_score, 6), doc.overall_status) == before:
            continue
        doc.db_set(
            {
                "avg_overall": doc.avg_overall,
                "min_score": doc.min_score,
                "overall_status": doc.overall_status,
            },
            update_modified=False,
        )
        # db_set keeps no version: say on the record what changed
        doc.add_comment(
            "Info",
            f"Result recomputed on the star scale: {before[2] or 'no result'} → {doc.overall_status}, "
            f"average {flt(doc.avg_overall, 2)} stars.",
        )

    if unclear:
        print(f"QC Tasting Records left as they were, a taster's ratings all {top} stars (check them): {', '.join(unclear)}")


def _may_be_clamped(row, rating_fields):
    """Every rating the taster gave reads the top of the scale (1.0)."""
    ratings = [flt(row.get(f)) for f in rating_fields if flt(row.get(f)) > 0]
    return bool(ratings) and all(r >= 1 for r in ratings)
