from __future__ import annotations

import io
from pathlib import Path
from string import Template
from dataclasses import asdict, fields
from html import escape

from flask import Flask, jsonify, request, send_file

# Import ProxySettings class so we can regenerate defaults from env vars
from .config import SETTINGS, ProxySettings, configure_logging
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

APP_VERSION = "3.2.1-env-defaults"


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
            return (f"Source Error: {exc}", 500)

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

        # Load fresh defaults from environment variables (Docker config)
        # This ensures the Reset buttons revert to the container's initial state
        defaults = ProxySettings.from_env()

        control_fields = [
            # Group: Network & Source
            {
                "group": "Network & Source",
                "name": "source_url",
                "label": "Source URL",
                "type": "url",
                "value": SETTINGS.source_url,
                "default": defaults.source_url,
                "help": "Upstream feed URL.",
            },
            {
                "group": "Network & Source",
                "name": "timeout",
                "label": "Timeout (s)",
                "type": "number",
                "step": "0.1",
                "value": SETTINGS.timeout,
                "default": defaults.timeout,
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
                "default": defaults.contrast,
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
                "default": defaults.saturation,
                "help": "Color intensity multiplier.",
            },
            {
                "group": "Image Enhancement",
                "name": "gamma",
                "label": "Gamma",
                "type": "slider",
                "min": "0.1",
                "max": "2.5",
                "step": "0.01",
                "value": SETTINGS.gamma,
                "default": defaults.gamma,
                "help": "Non-linear brightness adj.",
            },
            {
                "group": "Image Enhancement",
                "name": "sharpness_ui",
                "label": "Sharpness",
                "type": "slider",
                "min": "0.0",
                "max": "4.0",
                "step": "0.1",
                "value": SETTINGS.sharpness_ui,
                "default": defaults.sharpness_ui,
                "help": "Edge enhancement strength.",
            },
            # Group: Dither & Photo
            {
                "group": "Dither & Photo",
                "name": "photo_mode",
                "label": "Algorithm",
                "type": "select",
                "value": SETTINGS.photo_mode,
                "default": defaults.photo_mode,
                "options": [
                    ("hybrid", "Hybrid Regional"),
                    ("fs", "Floyd–Steinberg"),
                    ("stucki", "Stucki"),
                    ("ordered", "Ordered"),
                ],
                "help": "Dither strategy for photos.",
            },
            {
                "group": "Dither & Photo",
                "name": "sky_gradient_threshold",
                "label": "Sky Threshold",
                "type": "slider",
                "min": "0",
                "max": "60",
                "step": "1",
                "value": SETTINGS.sky_gradient_threshold,
                "default": defaults.sky_gradient_threshold,
                "help": "Skip dither on smooth gradients.",
            },
            {
                "group": "Dither & Photo",
                "name": "smooth_strength",
                "label": "Smoothing",
                "type": "slider",
                "min": "0",
                "max": "5",
                "step": "1",
                "value": SETTINGS.smooth_strength,
                "default": defaults.smooth_strength,
                "help": "Blur strength for skies.",
            },
            # Group: Masking
            {
                "group": "Masking Strategy",
                "name": "edge_threshold",
                "label": "Edge Detect",
                "type": "slider",
                "min": "0",
                "max": "100",
                "step": "1",
                "value": SETTINGS.edge_threshold,
                "default": defaults.edge_threshold,
                "help": "Sensitivity for UI edges.",
            },
            {
                "group": "Masking Strategy",
                "name": "mask_blur",
                "label": "Mask Blur",
                "type": "slider",
                "min": "0",
                "max": "10",
                "step": "1",
                "value": SETTINGS.mask_blur,
                "default": defaults.mask_blur,
                "help": "Softness of transition masks.",
            },
            {
                "group": "Masking Strategy",
                "name": "mid_l_min",
                "label": "Midtone Min",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_min,
                "default": defaults.mid_l_min,
                "help": "Luma start for midtone mask.",
            },
            {
                "group": "Masking Strategy",
                "name": "mid_l_max",
                "label": "Midtone Max",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_max,
                "default": defaults.mid_l_max,
                "help": "Luma end for midtone mask.",
            },
            # Group: Advanced
            {
                "group": "Advanced",
                "name": "ui_palette_threshold",
                "label": "Palette Dist",
                "type": "number",
                "step": "10",
                "value": SETTINGS.ui_palette_threshold,
                "default": defaults.ui_palette_threshold,
                "help": "Color snap aggressiveness.",
            },
            {
                "group": "Advanced",
                "name": "cache_ttl",
                "label": "Cache TTL",
                "type": "number",
                "step": "0.5",
                "value": SETTINGS.cache_ttl,
                "default": defaults.cache_ttl,
                "help": "Output caching duration.",
            },
            {
                "group": "Advanced",
                "name": "port",
                "label": "Port",
                "type": "number",
                "value": SETTINGS.port,
                "default": defaults.port,
                "help": "Internal container port.",
            },
             {
                "group": "Advanced",
                "name": "log_level",
                "label": "Log Level",
                "type": "select",
                "value": SETTINGS.log_level,
                "default": defaults.log_level,
                "options": [
                    ("DEBUG", "Debug"),
                    ("INFO", "Info"),
                    ("WARNING", "Warning"),
                    ("ERROR", "Error"),
                ],
                "help": "Service verbosity.",
            },
        ]

        # Group fields by category
        grouped_fields = {}
        for f in control_fields:
            g = f.pop("group", "Other")
            if g not in grouped_fields:
                grouped_fields[g] = []
            grouped_fields[g].append(f)

        def render_field(field: dict) -> str:
            # Helper to render individual inputs
            label = escape(str(field.get("label", field["name"])))
            name = escape(str(field["name"]))
            val = escape(str(field.get("value", "")))
            default_val = escape(str(field.get("default", "")))
            ftype = field.get("type", "text")
            help_text = escape(str(field.get("help", "")))
            
            if ftype == "select":
                opts_list = []
                for v, l in field.get("options", []):
                    is_sel = 'selected' if str(v) == str(field["value"]) else ''
                    safe_v = escape(str(v))
                    safe_l = escape(l)
                    opts_list.append(f'<option value="{safe_v}" {is_sel}>{safe_l}</option>')
                
                opts = "".join(opts_list)
                input_html = f'<select name="{name}" data-field="{name}" class="input">{opts}</select>'
            
            elif ftype == "slider":
                min_v = field.get("min", 0)
                max_v = field.get("max", 100)
                step_v = field.get("step", 1)
                
                input_html = (
                    f'<div class="slider-group">'
                    f'<input type="range" min="{min_v}" max="{max_v}" step="{step_v}" value="{val}" '
                    f'class="slider-range" data-sync="{name}">'
                    f'<input type="number" name="{name}" data-field="{name}" value="{val}" '
                    f'min="{min_v}" max="{max_v}" step="{step_v}" class="input slider-num">'
                    f'</div>'
                )
            else:
                step_attr = f'step="{field["step"]}"' if "step" in field else ""
                input_html = f'<input type="{ftype}" name="{name}" data-field="{name}" value="{val}" {step_attr} class="input">'

            reset_btn = (
                f'<button type="button" class="reset-btn" data-field="{name}" data-default="{default_val}" '
                f'title="Reset to {default_val}">'
                f'↺'
                f'</button>'
            )

            return (
                f'<div class="field">'
                f'<div class="field-header">'
                f'<label class="field-label">{label}</label>'
                f'{reset_btn}'
                f'</div>'
                f'{input_html}'
                f'<div class="field-help">{help_text}</div>'
                f'</div>'
            )

        controls_parts = []
        for group, fields_list in grouped_fields.items():
            fields_html = "".join(render_field(f) for f in fields_list)
            # Open the first two groups by default
            is_open = "open" if group in ["Image Enhancement", "Network & Source"] else ""
            
            section = (
                f'<details class="group-box" {is_open}>'
                f'<summary class="group-header">{group}</summary>'
                f'<div class="group-content">{fields_html}</div>'
                f'</details>'
            )
            controls_parts.append(section)

        controls_html = "".join(controls_parts)

        endpoint_cards = "".join(
            f"""
            <a href="{href}" target="_blank" class="ep-card">
                <div class="ep-icon">{icon}</div>
                <div class="ep-info">
                    <div class="ep-name">{escape(name)}</div>
                    <div class="ep-desc">{escape(desc)}</div>
                </div>
                <button class="btn-preview" data-endpoint="{href}" title="Preview in Studio">Use</button>
            </a>
            """
            for name, href, desc, icon in endpoints
        )

        comparison_options = "".join(
            f'<option value="{href}">{escape(name)}</option>' for name, href, *_ in endpoints
        )

        # Load the template file
        template_path = Path(__file__).parent / "templates" / "index.html"
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                tmpl_str = f.read()
        except Exception as e:
            return f"Error loading template: {e}", 500

        # Substitute using string.Template (safe for HTML/CSS braces)
        return Template(tmpl_str).substitute(
            APP_VERSION=APP_VERSION,
            controls_html=controls_html,
            endpoint_cards=endpoint_cards,
            comparison_options=comparison_options,
        )

    return app


# Expose a module-level Flask application for Gunicorn import paths like ``eink_proxy.app:app``
# and provide a conventional ``application`` alias for WSGI servers that default to that name.
app = create_app()
application = app
