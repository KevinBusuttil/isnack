__version__ = "0.0.1"

def override_convert_to_presentation_currency():
    import erpnext.accounts.report.utils as gl_utils
    from isnack.monkey_patches.gl_currency import custom_convert_to_presentation_currency

    gl_utils.convert_to_presentation_currency = custom_convert_to_presentation_currency

override_convert_to_presentation_currency()