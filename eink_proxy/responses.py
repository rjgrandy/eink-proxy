from __future__ import annotations

import io

from flask import send_file
from PIL import Image

from .cache import remember_last_good


def send_png(img: Image.Image):
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True)
    data = buffer.getvalue()
    remember_last_good(data)
    return send_file(io.BytesIO(data), mimetype="image/png")
