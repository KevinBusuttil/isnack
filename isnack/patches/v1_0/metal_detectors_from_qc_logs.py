import frappe
from frappe.utils import cstr

# What a Metal Detector takes from the logs that name it.
LOG_FIELDS = ("detector_make_model", "last_calibration_date", "next_calibration_date", "calibration_certificate")


def execute():
    """QC Metal Detector Log: the Metal Detector ID becomes a link to a Metal
    Detector, which holds the Make/Model and calibration the log takes from it
    (2026-11).

    Make a Metal Detector of each ID the logs name, so their links lead to one
    and a draft can still be saved: with the Make/Model, the calibration dates
    (the two together) and the certificate of the newest log holding each, a
    cancelled log only when no other holds it. An ID differing only in case or
    surrounding spaces is the same detector (as the database compares them); it
    takes the newest log's spelling. The logs are left as they are.

    An ID that cannot name a record is reported and left out: its logs keep
    it, and a draft of them is saved again with a detector picked.
    """
    if not frappe.db.table_exists("Metal Detector"):
        return

    logs = frappe.get_all(
        "QC Metal Detector Log",
        filters={"metal_detector_id": ["is", "set"]},
        fields=["metal_detector_id", "docstatus", *LOG_FIELDS],
        order_by="record_date desc, modified desc",
    )
    detectors = {}
    # newest first, the cancelled after the rest (sorted keeps the date order)
    for log in sorted(logs, key=lambda log: log.docstatus == 2):
        detector_id = cstr(log.metal_detector_id).strip()
        if not detector_id:
            continue
        detector = detectors.setdefault(detector_id.casefold(), {"metal_detector_id": detector_id})
        make_model = cstr(log.detector_make_model).strip()
        if make_model and "make_model" not in detector:
            detector["make_model"] = make_model
        if (log.last_calibration_date or log.next_calibration_date) and "last_calibration_date" not in detector:
            detector["last_calibration_date"] = log.last_calibration_date
            detector["next_calibration_date"] = log.next_calibration_date
        certificate = cstr(log.calibration_certificate).strip()
        if certificate and "calibration_certificate" not in detector:
            detector["calibration_certificate"] = certificate

    for detector in detectors.values():
        if frappe.db.exists("Metal Detector", detector["metal_detector_id"]):
            continue
        frappe.db.savepoint("metal_detector_from_logs")
        try:
            frappe.get_doc({"doctype": "Metal Detector", **detector}).insert(ignore_permissions=True)
        except (frappe.NameError, frappe.ValidationError) as e:
            frappe.db.rollback(save_point="metal_detector_from_logs")
            frappe.clear_last_message()
            print(f"Metal Detector {detector['metal_detector_id']!r} not made from the QC Metal Detector Logs: {e}")
