import frappe
from frappe.utils import flt


def execute():
    """Tasting scores: an Overall % worked out from the five scores replaces the
    taster's own Overall rating (2026-11).

    Tastings recorded before were judged on that rating, in stars; it stays,
    hidden, as overall_score. They keep their result: each taster's Overall %
    is their Overall rating as a percentage (4 of 5 stars is 80 %), and the
    record's average and lowest are worked out from those, as they were in
    stars (3.4 stars is 68 %). A draft works its Overall % out from the five
    scores when it is saved again.
    """
    if not frappe.db.has_column("QC Tasting Score", "overall_percent"):
        return

    rows = frappe.db.sql(
        """
        select name, parent, overall_score
        from `tabQC Tasting Score`
        where parenttype = 'QC Tasting Record'
            and ifnull(overall_percent, 0) = 0
            and ifnull(overall_score, 0) > 0
        """,
        as_dict=True,
    )
    by_record = {}
    for row in rows:
        by_record.setdefault(row.parent, []).append(row)

    for record, converted in by_record.items():
        for row in converted:
            # a Rating is the fraction of stars given, 1 at most
            percent = flt(min(flt(row.overall_score), 1) * 100, 2)
            frappe.db.set_value("QC Tasting Score", row.name, "overall_percent", percent, update_modified=False)
        scored = [
            flt(p)
            for p in frappe.get_all(
                "QC Tasting Score",
                filters={"parent": record, "parenttype": "QC Tasting Record", "overall_percent": [">", 0]},
                pluck="overall_percent",
            )
        ]
        frappe.db.set_value(
            "QC Tasting Record",
            record,
            {"avg_overall": flt(sum(scored) / len(scored), 2), "min_score": min(scored)},
            update_modified=False,
        )
        # set_value keeps no version: say on the record what changed
        frappe.get_doc("QC Tasting Record", record).add_comment(
            "Info",
            "Scores now read as an Overall %, worked out from Shape, Colour, Smell, Taste and Texture. "
            "This tasting was scored before, on each taster's own Overall rating: that rating is shown as "
            "the Overall % (4 of 5 stars is 80 %), and the result stands. Saving a draft again works the "
            "Overall % out from the five scores.",
        )
