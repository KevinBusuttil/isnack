def override_convert_to_presentation_currency():
    from erpnext.accounts.report import utils as gl_utils
    from isnack.monkey_patches.gl_currency import custom_convert_to_presentation_currency

    gl_utils.convert_to_presentation_currency = custom_convert_to_presentation_currency

override_convert_to_presentation_currency()
