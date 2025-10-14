# qrgenerate.py
import qrcode
from io import BytesIO
import base64

def generate_qr(data: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    # base64 string döndür
    return base64.b64encode(buffer.read()).decode("utf-8")
