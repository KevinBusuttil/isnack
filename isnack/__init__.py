# flit (pyproject.toml's build backend) reads this literal without importing the
# package. Keep it a plain string: without one, flit imports this module to find
# the version, and installing the app fails on the imports below.
__version__ = "0.0.1"

def override_convert_to_presentation_currency():
    from erpnext.accounts.report import utils as gl_utils
    from isnack.monkey_patches.gl_currency import custom_convert_to_presentation_currency

    gl_utils.convert_to_presentation_currency = custom_convert_to_presentation_currency

override_convert_to_presentation_currency()
