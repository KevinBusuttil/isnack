import frappe
from frappe.utils import flt

from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import PASS_THRESHOLD_PERCENT
from isnack.patches.v1_0.recompute_qc_tasting_results import _may_be_clamped


def execute():
    """Tasting scores: an Overall % worked out from the five scores replaces the
    taster's own Overall rating (2026-11).

    Tastings recorded before were judged on that rating, in stars; it stays,
    hidden, as overall_score. They keep their result: each taster's Overall %
    is their Overall rating as a percentage (4 of 5 stars is 80 %), and the
    record's average and lowest are worked out from those (3.4 stars is 68 %).
    The result read in % is the result read in stars (3 stars is 60 %), except
    on a tasting never judged in stars (one cancelled before 2026-10, still
    "Fail" on the old scale), which gets the result its scores give. A draft
    works its Overall % out from the five scores when it is saved again.

    A tasting whose ratings could not be read (entered through the Quality Hub
    dialog before 2026-10, every rating stored as full stars) was left as it
    was by recompute_qc_tasting_results, with a comment to check its scores:
    it gets no Overall % from them.
    """
    if not frappe.db.has_column("QC Tasting Score", "overall_percent"):
        return

    rating_fields = [df.fieldname for df in frappe.get_meta("QC Tasting Score").fields if df.fieldtype == "Rating"]
    columns = ", ".join(f"`{f}`" for f in rating_fields)
    rows = frappe.db.sql(
        f"""
        select name, parent, overall_percent, {columns}
        from `tabQC Tasting Score`
        where parenttype = 'QC Tasting Record'
        order by parent, idx
        """,
        as_dict=True,
    )
    by_record = {}
    for row in rows:
        by_record.setdefault(row.parent, []).append(row)

    for record, scores in by_record.items():
        to_convert = [r for r in scores if not flt(r.overall_percent) and flt(r.overall_score) > 0]
        if not to_convert:
            continue
        avg_overall, status = frappe.db.get_value("QC Tasting Record", record, ["avg_overall", "overall_status"])
        doc = frappe.get_doc("QC Tasting Record", record)

        # never read on the star scale (avg still a fraction) and a row the
        # October patch could not trust: no Overall % from those scores
        if flt(avg_overall) <= 1 and any(_may_be_clamped(r, rating_fields) for r in scores):
            frappe.db.set_value(
                "QC Tasting Record", record, {"avg_overall": 0, "min_score": 0}, update_modified=False
            )
            doc.add_comment(
                "Info",
                "Scores now read as an Overall %, worked out from Shape, Colour, Smell, Taste and Texture. "
                "This tasting's ratings could not be read (see the earlier comment), so it shows no Overall %: "
                "check its scores and enter them again.",
            )
            continue

        for row in to_convert:
            # a Rating is the fraction of stars given, 1 at most
            row.overall_percent = flt(min(flt(row.overall_score), 1) * 100, 2)
            frappe.db.set_value(
                "QC Tasting Score", row.name, "overall_percent", row.overall_percent, update_modified=False
            )
        scored = [flt(r.overall_percent) for r in scores if flt(r.overall_percent) > 0]
        new_status = "Pass" if scored and flt(sum(scored) / len(scored), 2) >= PASS_THRESHOLD_PERCENT else "Fail"
        frappe.db.set_value(
            "QC Tasting Record",
            record,
            {
                "avg_overall": flt(sum(scored) / len(scored), 2) if scored else 0,
                "min_score": min(scored) if scored else 0,
                "overall_status": new_status,
            },
            update_modified=False,
        )
        # set_value keeps no version: say on the record what changed
        result = (
            "the result stands"
            if new_status == status
            else f"its result reads on its scores: {status or 'no result'} → {new_status}"
        )
        doc.add_comment(
            "Info",
            "Scores now read as an Overall %, worked out from Shape, Colour, Smell, Taste and Texture. "
            "This tasting was scored before, on each taster's own Overall rating: that rating is shown as "
            f"the Overall % (4 of 5 stars is 80 %), and {result}. Saving a draft again works the Overall % "
            "out from the five scores.",
        )
