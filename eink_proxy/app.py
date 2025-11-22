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

APP_VERSION = "3.1.1-fix"


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
                "name": "gamma",
                "label": "Gamma",
                "type": "slider",
                "min": "0.1",
                "max": "2.5",
                "step": "0.01",
                "value": SETTINGS.gamma,
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
                "help": "Edge enhancement strength.",
            },
            # Group: Dither & Photo
            {
                "group": "Dither & Photo",
                "name": "photo_mode",
                "label": "Algorithm",
                "type": "select",
                "value": SETTINGS.photo_mode,
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
                "help": "Softness of transition masks.",
            },
            {
                "group": "Masking Strategy",
                "name": "mid_l_min",
                "label": "Midtone Min",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_min,
                "help": "Luma start for midtone mask.",
            },
            {
                "group": "Masking Strategy",
                "name": "mid_l_max",
                "label": "Midtone Max",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_max,
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
                "help": "Color snap aggressiveness.",
            },
            {
                "group": "Advanced",
                "name": "cache_ttl",
                "label": "Cache TTL",
                "type": "number",
                "step": "0.5",
                "value": SETTINGS.cache_ttl,
                "help": "Output caching duration.",
            },
            {
                "group": "Advanced",
                "name": "port",
                "label": "Port",
                "type": "number",
                "value": SETTINGS.port,
                "help": "Internal container port.",
            },
             {
                "group": "Advanced",
                "name": "log_level",
                "label": "Log Level",
                "type": "select",
                "value": SETTINGS.log_level,
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
            ftype = field.get("type", "text")
            help_text = escape(str(field.get("help", "")))
            
            if ftype == "select":
                # Breakdown option generation to be syntax-safe
                opts_list = []
                for v, l in field.get("options", []):
                    # explicit check to avoid nested f-string complexity
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

            return (
                f'<div class="field">'
                f'<label class="field-label"><span>{label}</span></label>'
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

        # We use dedent with triple-double quotes to be safe
        template = dedent(
            """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>E-ink Proxy Studio</title>
                <style>
                    :root {
                        --bg-body: #0f172a;
                        --bg-panel: #1e293b;
                        --bg-input: #020617;
                        --border: #334155;
                        --primary: #6366f1;
                        --primary-hover: #4f46e5;
                        --text-main: #f8fafc;
                        --text-muted: #94a3b8;
                        --accent: #10b981;
                        --font: 'Inter', system-ui, sans-serif;
                    }
                    body {
                        margin: 0;
                        font-family: var(--font);
                        background: var(--bg-body);
                        color: var(--text-main);
                        display: flex;
                        flex-direction: column;
                        min-height: 100vh;
                    }
                    * { box-sizing: border-box; }
                    
                    /* Header */
                    .header {
                        background: rgba(15, 23, 42, 0.95);
                        border-bottom: 1px solid var(--border);
                        padding: 1rem 1.5rem;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        position: sticky;
                        top: 0;
                        z-index: 100;
                        backdrop-filter: blur(8px);
                    }
                    .brand { font-size: 1.25rem; font-weight: 700; display: flex; align-items: center; gap: 0.5rem; }
                    .badge { font-size: 0.75rem; background: var(--border); padding: 2px 8px; border-radius: 99px; color: var(--text-muted); }
                    .nav-links { display: flex; gap: 1rem; }
                    .nav-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; font-weight: 600; font-size: 0.9rem; padding: 0.5rem; transition: color 0.2s; }
                    .nav-btn:hover, .nav-btn.active { color: var(--primary); }

                    /* Layout */
                    .main-layout {
                        display: grid;
                        grid-template-columns: 320px 1fr;
                        gap: 2rem;
                        max-width: 1600px;
                        margin: 0 auto;
                        width: 100%;
                        padding: 2rem;
                        align-items: start;
                    }
                    
                    /* Sidebar (Settings) */
                    .settings-panel {
                        display: flex;
                        flex-direction: column;
                        gap: 1rem;
                    }
                    .group-box {
                        background: var(--bg-panel);
                        border: 1px solid var(--border);
                        border-radius: 8px;
                        overflow: hidden;
                    }
                    .group-header {
                        padding: 0.75rem 1rem;
                        background: rgba(255,255,255,0.03);
                        font-weight: 600;
                        font-size: 0.9rem;
                        cursor: pointer;
                        user-select: none;
                        display: flex;
                        align-items: center;
                    }
                    .group-header:hover { background: rgba(255,255,255,0.05); }
                    .group-content { padding: 1rem; display: grid; gap: 1rem; }
                    
                    /* Inputs */
                    .field { display: flex; flex-direction: column; gap: 0.4rem; }
                    .field-label { font-size: 0.85rem; font-weight: 500; color: var(--text-muted); display: flex; justify-content: space-between; }
                    .input {
                        background: var(--bg-input);
                        border: 1px solid var(--border);
                        color: var(--text-main);
                        padding: 0.5rem;
                        border-radius: 6px;
                        font-family: inherit;
                        width: 100%;
                        transition: border-color 0.2s;
                    }
                    .input:focus { outline: none; border-color: var(--primary); }
                    .field-help { font-size: 0.75rem; color: #475569; line-height: 1.3; }
                    
                    .slider-group { display: grid; grid-template-columns: 1fr 60px; gap: 0.5rem; align-items: center; }
                    input[type=range] { width: 100%; accent-color: var(--primary); cursor: pointer; }
                    .slider-num { text-align: right; }

                    /* Preview Stage */
                    .stage-container {
                        position: sticky;
                        top: 5.5rem; /* Header height + buffer */
                        display: flex;
                        flex-direction: column;
                        gap: 1.5rem;
                    }
                    .preview-card {
                        background: var(--bg-panel);
                        border: 1px solid var(--border);
                        border-radius: 12px;
                        padding: 1rem;
                        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
                    }
                    .preview-toolbar {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 1rem;
                        padding-bottom: 0.75rem;
                        border-bottom: 1px solid var(--border);
                    }
                    .pill { background: rgba(99, 102, 241, 0.15); color: #818cf8; padding: 4px 10px; border-radius: 99px; font-size: 0.8rem; font-weight: 600; font-family: monospace; }
                    .btn-icon { background: var(--bg-input); border: 1px solid var(--border); color: var(--text-main); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
                    .btn-icon:hover { border-color: var(--text-muted); }
                    
                    .img-wrap {
                        background: #111;
                        border-radius: 8px;
                        overflow: hidden;
                        min-height: 200px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        border: 1px dashed var(--border);
                    }
                    .img-wrap img { width: 100%; height: auto; display: block; opacity: 0; transition: opacity 0.3s; }
                    .img-wrap img.loaded { opacity: 1; }

                    /* Endpoint Grid (Bottom or Modal) */
                    .endpoints-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
                        gap: 1rem;
                    }
                    .ep-card {
                        background: var(--bg-panel);
                        border: 1px solid var(--border);
                        border-radius: 8px;
                        padding: 1rem;
                        text-decoration: none;
                        color: inherit;
                        transition: transform 0.2s, border-color 0.2s;
                        display: grid;
                        grid-template-columns: auto 1fr auto;
                        gap: 0.75rem;
                        align-items: center;
                    }
                    .ep-card:hover { transform: translateY(-2px); border-color: var(--primary); }
                    .ep-icon { font-size: 1.5rem; }
                    .ep-name { font-weight: 600; font-size: 0.9rem; }
                    .ep-desc { font-size: 0.75rem; color: var(--text-muted); margin-top: 2px; }
                    .btn-preview {
                        background: var(--bg-input); border: 1px solid var(--border);
                        color: var(--text-muted); padding: 4px 8px; border-radius: 4px;
                        cursor: pointer; font-size: 0.7rem;
                    }
                    .btn-preview:hover { color: var(--primary); border-color: var(--primary); }

                    /* Toast */
                    .toast {
                        position: fixed; bottom: 2rem; right: 2rem;
                        background: var(--primary); color: white;
                        padding: 0.75rem 1.5rem; border-radius: 99px;
                        font-weight: 500; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
                        transform: translateY(150%); transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                    }
                    .toast.show { transform: translateY(0); }

                    @media (max-width: 900px) {
                        .main-layout { grid-template-columns: 1fr; }
                        .stage-container { position: static; order: -1; }
                    }
                </style>
            </head>
            <body>
                <header class="header">
                    <div class="brand">
                        <span>E-ink Proxy</span>
                        <span class="badge">v{APP_VERSION}</span>
                    </div>
                    <nav class="nav-links">
                        <a href="#" class="nav-btn active" onclick="switchTab('studio')">Studio</a>
                        <a href="#" class="nav-btn" onclick="switchTab('endpoints')">Endpoints</a>
                    </nav>
                </header>

                <main id="tab-studio" class="main-layout">
                    <div class="settings-panel">
                        <div style="margin-bottom:0.5rem; display:flex; justify-content:space-between; align-items:center;">
                            <h3 style="margin:0; font-size:1rem;">Configuration</h3>
                            <div class="badge" style="background:rgba(16, 185, 129, 0.1); color:var(--accent);">Live Auto-save</div>
                        </div>
                        <form id="settings-form">
                            {controls_html}
                        </form>
                    </div>

                    <div class="stage-container">
                        <div class="preview-card">
                            <div class="preview-toolbar">
                                <div>
                                    <div style="font-weight:600; margin-bottom:4px;">Live Preview</div>
                                    <div class="pill" id="active-url">/eink-image?dither=regional</div>
                                </div>
                                <button class="btn-icon" id="refresh-btn">⟳ Refresh</button>
                            </div>
                            <div class="img-wrap">
                                <img id="preview-img" src="" alt="Preview" />
                            </div>
                        </div>
                        
                        <div class="preview-card">
                             <div class="preview-toolbar">
                                <div style="font-weight:600;">Comparison</div>
                                <button class="btn-icon" id="compare-btn">Update</button>
                            </div>
                             <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.5rem; margin-bottom:0.5rem;">
                                <select id="left-sel" class="input">{comparison_options}</select>
                                <select id="right-sel" class="input">{comparison_options}</select>
                             </div>
                             <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.5rem;">
                                <div class="img-wrap" style="min-height:100px;">
                                    <img id="left-img" src="" loading="lazy">
                                </div>
                                <div class="img-wrap" style="min-height:100px;">
                                    <img id="right-img" src="" loading="lazy">
                                </div>
                             </div>
                        </div>
                    </div>
                </main>

                <main id="tab-endpoints" class="main-layout" style="display:none;">
                    <div style="max-width:1000px; margin:0 auto; padding:2rem;">
                        <h2 style="margin-top:0;">Available Endpoints</h2>
                        <div class="endpoints-grid">
                            {endpoint_cards}
                        </div>
                    </div>
                </main>

                <div id="toast" class="toast">Settings Saved</div>

                <script>
                    // State
                    const state = {{
                        currentEndpoint: '/eink-image?dither=regional'
                    }};

                    // DOM
                    const previewImg = document.getElementById('preview-img');
                    const urlLabel = document.getElementById('active-url');
                    const settingsForm = document.getElementById('settings-form');
                    const toast = document.getElementById('toast');

                    // Utils
                    const bust = (u) => `${{u}}${{u.includes('?') ? '&' : '?'}}ts=${{Date.now()}}`;
                    const showToast = (msg) => {{
                        toast.textContent = msg;
                        toast.classList.add('show');
                        setTimeout(() => toast.classList.remove('show'), 2000);
                    }};

                    // Preview Logic
                    const updatePreview = () => {{
                        urlLabel.textContent = state.currentEndpoint;
                        previewImg.classList.remove('loaded');
                        const newSrc = bust(state.currentEndpoint);
                        // Preload to avoid flicker
                        const img = new Image();
                        img.onload = () => {{
                            previewImg.src = newSrc;
                            previewImg.classList.add('loaded');
                        }};
                        img.src = newSrc;
                    }};

                    document.getElementById('refresh-btn').addEventListener('click', updatePreview);

                    // Settings Logic
                    const updateSetting = async (field, value) => {{
                        try {{
                            const res = await fetch('/settings', {{
                                method: 'PATCH',
                                headers: {{ 'Content-Type': 'application/json' }},
                                body: JSON.stringify({{ [field]: value }}),
                            }});
                            if(res.ok) {{
                                showToast(`Saved ${{field}}`);
                                updatePreview(); // Auto refresh on change
                            }}
                        }} catch(e) {{
                            console.error(e);
                        }}
                    }};

                    // Event Delegation for Inputs
                    settingsForm.addEventListener('input', (e) => {{
                        const target = e.target;
                        // Sync slider <-> number
                        if (target.dataset.sync) {{
                            const sibling = settingsForm.querySelector(`[data-field="${{target.dataset.sync}}"].slider-num`);
                            if(sibling) sibling.value = target.value;
                        }}
                        if (target.type === 'range') {{
                             const numberInput = target.parentElement.querySelector('.slider-num');
                             if(numberInput) numberInput.value = target.value;
                        }}
                    }});

                    settingsForm.addEventListener('change', (e) => {{
                         const target = e.target;
                         const field = target.dataset.field || target.dataset.sync;
                         if(!field) return;
                         
                         // If it's a slider group, use the value from the element that changed
                         updateSetting(field, target.value);
                         
                         // If I changed the number input, update the slider
                         if(target.classList.contains('slider-num')) {{
                             const slider = target.parentElement.querySelector('.slider-range');
                             if(slider) slider.value = target.value;
                         }}
                    }});

                    // Tab Switching
                    window.switchTab = (tab) => {{
                        document.getElementById('tab-studio').style.display = tab === 'studio' ? 'grid' : 'none';
                        document.getElementById('tab-endpoints').style.display = tab === 'endpoints' ? 'block' : 'none';
                        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
                        event.target.classList.add('active');
                    }};
                    
                    // Endpoint Buttons
                    document.querySelectorAll('.btn-preview').forEach(btn => {{
                        btn.addEventListener('click', (e) => {{
                            e.preventDefault();
                            e.stopPropagation();
                            state.currentEndpoint = btn.dataset.endpoint;
                            switchTab('studio');
                            updatePreview();
                            document.querySelectorAll('.nav-btn')[0].classList.add('active'); 
                            document.querySelectorAll('.nav-btn')[1].classList.remove('active');
                        }});
                    }});

                    // Comparison
                    const leftSel = document.getElementById('left-sel');
                    const rightSel = document.getElementById('right-sel');
                    const leftImg = document.getElementById('left-img');
                    const rightImg = document.getElementById('right-img');
                    
                    const runCompare = () => {{
                        leftImg.src = bust(leftSel.value);
                        rightImg.src = bust(rightSel.value);
                    }};
                    document.getElementById('compare-btn').addEventListener('click', runCompare);
                    
                    // Init
                    updatePreview();
                    runCompare();

                </script>
            </body>
            </html>
            """
        )
        
        # Safe replacement routine
        replacements = {
            "APP_VERSION": APP_VERSION,
            "controls_html": controls_html,
            "endpoint_cards": endpoint_cards,
            "comparison_options": comparison_options,
        }
        
        # Double escape braces for format() safety
        template = template.replace("{", "{{").replace("}", "}}")
        
        # Expose specific placeholders
        for k in replacements:
            template = template.replace(f"{{{{{k}}}}}", f"{{{k}}}")
            
        return template.format(**replacements)

    return app

# Expose a module-level Flask application for Gunicorn import paths like ``eink_proxy.app:app``
# and provide a conventional ``application`` alias for WSGI servers that default to that name.
app = create_app()
application = app
