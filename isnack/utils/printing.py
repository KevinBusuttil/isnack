import frappe
from frappe.utils import cstr

def get_factory_settings():
    try:
        return frappe.get_single("Factory Settings")
    except Exception:
        return frappe._dict()

def _get_user_printer_row(fs=None):
    fs = fs or get_factory_settings()
    user = frappe.session.user
    for row in getattr(fs, "user_printer_defaults", []) or []:
        if row.user == user:
            return row
    return None

def get_label_printer() -> str | None:
    """Best label printer for current user."""
    fs = get_factory_settings()

    # 1) Per-user override in Factory Settings
    row = _get_user_printer_row(fs)
    if row and row.label_printer:
        return row.label_printer

    # 2) Global default label printer (Factory Settings)
    if getattr(fs, "default_label_printer", None):
        return cstr(fs.default_label_printer)

    # 3) System default printer
    return frappe.db.get_single_value("Print Settings", "default_printer")


def get_a4_printer() -> str | None:
    """Best A4 / normal document printer for current user."""
    fs = get_factory_settings()

    # 1) Per-user override in Factory Settings
    row = _get_user_printer_row(fs)
    if row and row.a4_printer:
        return row.a4_printer

    # 2) (optional) You can add a global default_a4_printer field on Factory Settings later
    if getattr(fs, "default_a4_printer", None):
        return cstr(fs.default_a4_printer)

    # 3) System default printer
    return frappe.db.get_single_value("Print Settings", "default_printer")
