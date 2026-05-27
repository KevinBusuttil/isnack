import frappe
from frappe.utils import cstr


def get_factory_settings():
    try:
        return frappe.get_single("Factory Settings")
    except Exception:
        return frappe._dict()


def _per_user_enabled(fs) -> bool:
    """Resolve the use_per_user_printer_defaults flag defensively.

    Only a real bool ``True`` or a real ``int``/``str`` equal to ``1`` enables
    per-user mode. Anything else — including ``MagicMock`` attribute access in
    unit tests (which would otherwise coerce to ``1`` via ``__int__``),
    missing field, or unparseable values — is treated as off, so the legacy
    single-printer behavior is preserved by default.
    """
    val = getattr(fs, "use_per_user_printer_defaults", 0)
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val == 1
    if isinstance(val, str):
        try:
            return int(val.strip() or 0) == 1
        except ValueError:
            return False
    return False


def _get_user_printer_row(fs):
    user = frappe.session.user
    rows = getattr(fs, "user_printer_defaults", None) or []
    if not isinstance(rows, (list, tuple)):
        return None
    for row in rows:
        if getattr(row, "user", None) == user:
            return row
    return None


def _global_label_printer(fs):
    val = getattr(fs, "default_label_printer", None)
    return cstr(val) if val else None


def _global_a4_printer(fs):
    val = getattr(fs, "default_a4_printer", None)
    return cstr(val) if val else None


def get_label_printer(fs=None) -> str | None:
    """Best label printer for current user.

    When ``use_per_user_printer_defaults`` is enabled on Factory Settings the
    per-user row wins, then the global ``default_label_printer``, then the
    system default in ``Print Settings``. When the flag is off (default) only
    the global ``default_label_printer`` is consulted — matching the
    historical ``getattr(fs, "default_label_printer", None)`` lookup the rest
    of the codebase relied on.
    """
    fs = fs if fs is not None else get_factory_settings()

    if not _per_user_enabled(fs):
        return _global_label_printer(fs)

    row = _get_user_printer_row(fs)
    if row and getattr(row, "label_printer", None):
        return cstr(row.label_printer)

    glob = _global_label_printer(fs)
    if glob:
        return glob

    try:
        return frappe.db.get_single_value("Print Settings", "default_printer")
    except Exception:
        return None


def get_a4_printer(fs=None) -> str | None:
    """Best A4 / normal document printer for current user.

    Mirrors :func:`get_label_printer`: when per-user mode is off, the global
    ``default_a4_printer`` is returned as-is (or ``None``).
    """
    fs = fs if fs is not None else get_factory_settings()

    if not _per_user_enabled(fs):
        return _global_a4_printer(fs)

    row = _get_user_printer_row(fs)
    if row and getattr(row, "a4_printer", None):
        return cstr(row.a4_printer)

    glob = _global_a4_printer(fs)
    if glob:
        return glob

    try:
        return frappe.db.get_single_value("Print Settings", "default_printer")
    except Exception:
        return None
