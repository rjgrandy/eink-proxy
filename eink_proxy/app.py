from __future__ import annotations

import io
from dataclasses import asdict, fields
from html import escape
from textwrap import dedent

from flask import Flask, jsonify, request, send_file

from .config import SETTINGS, configure_logging
from .infrastructure.cache import last_good_png
from .infrastructure.network import FETCHER
from .infrastructure.responses import send_png
from .processing.enhance import enhance_photo, enhance_ui
from .processing.pipeline import (
    build_debug_overlay,
    composite_regional,
    quantize_palette_fs,
    quantize_palette_none,
)

APP_VERSION = "3.1.0-modern"


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

    @app.route("/settings", methods=["GET", "PATCH"])
    def settings_view():
        if request.method == "GET":
            return jsonify(asdict(SETTINGS))

        payload = request.get_json(silent=True) or {}
        errors: dict[str, str] = {}
        applied: dict[str, object] = {}

        for field in fields(SETTINGS):
            if field.name not in payload:
                continue

            raw_value = payload[field.name]
            try:
                if field.type is int:
                    coerced = int(raw_value)
                elif field.type is float:
                    coerced = float(raw_value)
                else:
                    coerced = str(raw_value)
            except (TypeError, ValueError):
                errors[field.name] = f"Expected {field.type.__name__}"
                continue

            if field.name == "photo_mode":
                coerced = str(coerced).lower()

            setattr(SETTINGS, field.name, coerced)
            applied[field.name] = coerced

        status = 400 if errors else 200
        return (
            jsonify(updated=applied, errors=errors, settings=asdict(SETTINGS)),
            status,
        )

    @app.route("/")
    def index():
        endpoints = [
            (
                "Hybrid Regional",
                "/eink-image?dither=regional",
                "Best for mixed content",
                "✨",
            ),
            (
                "UI-Only Crisp",
                "/eink-image?dither=false",
                "No dither, high contrast",
                "🔷",
            ),
            (
                "Full Photo",
                "/eink-image?dither=true",
                "Floyd–Steinberg dither",
                "📸",
            ),
            (
                "Raw Source",
                "/raw",
                "Original upstream image",
                "💾",
            ),
            (
                "Mask Debug",
                "/debug/masks",
                "Visualize segmentation",
                "🧪",
            ),
        ]

        # Define controls with range limits for slider generation
        control_fields = [
            # Group: Network & Source
            {
                "group": "Network & Source",
                "name": "source_url",
                "label": "Source URL",
                "type": "url",
                "value": SETTINGS.source_url,
                "help": "Upstream feed URL.",
            },
            {
                "group": "Network & Source",
                "name": "timeout",
                "label": "Timeout (s)",
                "type": "number",
                "step": "0.1",
                "value": SETTINGS.timeout,
                "help": "Max wait time for source.",
            },
            # Group: Image Enhancement
            {
                "group": "Image Enhancement",
                "name": "contrast",
                "label": "Contrast",
                "type": "slider",
                "min": "0.5",
                "max": "2.0",
                "step": "0.05",
                "value": SETTINGS.contrast,
                "help": "Global contrast boost.",
            },
            {
                "group": "Image Enhancement",
                "name": "saturation",
                "label": "Saturation",
                "type": "slider",
                "min": "0.0",
                "max": "3.0",
                "step": "0.05",
                "value": SETTINGS.saturation,
                "help": "Color intensity multiplier.",
            },
            {
                "group": "Image Enhancement",
                "
