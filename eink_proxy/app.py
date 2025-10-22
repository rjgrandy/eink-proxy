from __future__ import annotations

import io

from flask import Flask, jsonify, request, send_file

from .cache import last_good_png
from .config import SETTINGS, configure_logging
from .network import FETCHER
from .pipeline import build_debug_overlay, composite_regional, quantize_palette_fs, quantize_palette_none
from .enhance import enhance_photo, enhance_ui
from .responses import send_png


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)

    @app.route("/eink-image")
    def eink_image():
        mode = (request.args.get("dither", "regional") or "regional").lower()
        try:
            src = FETCHER.fetch_source()
            if mode == "regional":
                out = composite_regional(src)
            elif mode == "true":
                out = quantize_palette_fs(enhance_photo(src))
            elif mode == "false":
                out = quantize_palette_none(enhance_ui(src))
            else:
                out = composite_regional(src)
            return send_png(out)
        except Exception as exc:  # pragma: no cover - runtime fallback path
            cached = last_good_png()
            if cached:
                return send_file(io.BytesIO(cached), mimetype="image/png")
            return (f"error: {exc}", 500)

    @app.route("/raw")
    def raw():
        try:
            return send_png(FETCHER.fetch_source())
        except Exception as exc:  # pragma: no cover - runtime fallback path
            return (str(exc), 500)

    @app.route("/debug/masks")
    def debug_masks():
        try:
            src = FETCHER.fetch_source()
            overlay = build_debug_overlay(src)
            return send_png(overlay)
        except Exception as exc:  # pragma: no cover - runtime fallback path
            return (f"error: {exc}", 500)

    @app.route("/health")
    def health():
        return jsonify(
            ok=True,
            photo_mode=SETTINGS.photo_mode,
            sky_grad_thr=SETTINGS.sky_gradient_threshold,
            smooth=SETTINGS.smooth_strength,
        )

    @app.route("/")
    def index():
        return f"""
        <html>
        <head><title>E-ink Proxy v2.7 — hybrid photo dither</title></head>
        <body style=\"font-family:Arial; margin:24px\">
          <h1>E-ink 7-Color Image Proxy v2.7</h1>
          <p>Source: <code>{SETTINGS.source_url}</code></p>
          <ul>
            <li><a href=\"/eink-image?dither=regional\">/eink-image?dither=regional</a></li>
            <li><a href=\"/eink-image?dither=false\">/eink-image?dither=false</a></li>
            <li><a href=\"/eink-image?dither=true\">/eink-image?dither=true</a></li>
            <li><a href=\"/raw\">/raw</a></li>
            <li><a href=\"/debug/masks\">/debug/masks</a> (R=edge, G=midtone, B=low-gradient)</li>
            <li><a href=\"/health\">/health</a></li>
          </ul>
          <p>PHOTO_MODE={SETTINGS.photo_mode} (hybrid|fs|stucki|ordered), SKY_GRAD_THR={SETTINGS.sky_gradient_threshold}, SMOOTH_STRENGTH={SETTINGS.smooth_strength}</p>
        </body>
        </html>
        """

    return app
