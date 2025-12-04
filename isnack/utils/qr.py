import pyqrcode  # ensure this is in your requirements and installed

def get_qr_code(qr_text: str, scale: int = 4) -> str:
    """Return data:image/png;base64,... string for use as <img src>."""
    if not qr_text:
        qr_text = ""
    qr = pyqrcode.create(str(qr_text))
    return "data:image/png;base64," + qr.png_as_base64_str(scale=scale, quiet_zone=1)
