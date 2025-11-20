from __future__ import annotations

import dataclasses
import io
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

APP_VERSION = "3.1.1"

def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)

    def get_settings_with_overrides():
        overrides = {}
        for key in ["edge_threshold", "texture_density_threshold", "sky_gradient_threshold"]:
            val = request.args.get(key)
            if val is not None: overrides[key] = int(val)
        for key in ["contrast", "saturation", "gamma", "sharpness_ui"]:
            val = request.args.get(key)
            if val is not None: overrides[key] = float(val)
        if not overrides: return SETTINGS
        return dataclasses.replace(SETTINGS, **overrides)

    @app.route("/eink-image")
    def eink_image():
        mode = (request.args.get("dither", "regional") or "regional").lower()
        debug_crash = request.args.get("debug") == "1"
        settings = get_settings_with_overrides()
        
        try:
            src = FETCHER.fetch_source()
            if mode == "regional":
                out = composite_regional(src, settings=settings)
            elif mode == "true":
                out = quantize_palette_fs(enhance_photo(src, settings=settings))
            elif mode == "false":
                out = quantize_palette_none(enhance_ui(src, settings=settings))
            else:
                out = composite_regional(src, settings=settings)
            return send_png(out)
        except Exception as exc:
            # If debug=1, show the error instead of the cached image
            if debug_crash:
                return (f"CRASH: {exc}", 500)
            
            cached = last_good_png()
            if cached:
                return send_file(io.BytesIO(cached), mimetype="image/png")
            return (f"error: {exc}", 500)

    @app.route("/raw")
    def raw():
        try:
            return send_png(FETCHER.fetch_source())
        except Exception as exc:
            return (str(exc), 500)

    @app.route("/debug/masks")
    def debug_masks():
        settings = get_settings_with_overrides()
        try:
            src = FETCHER.fetch_source()
            overlay = build_debug_overlay(src, settings=settings)
            return send_png(overlay)
        except Exception as exc:
            return (f"error: {exc}", 500)

    @app.route("/health")
    def health():
        return jsonify(ok=True, photo_mode=SETTINGS.photo_mode)

    @app.route("/")
    def index():
        # (Same HTML as previous turn, it is compatible)
        return dedent(f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>E-ink Proxy · Config</title>
                <style>
                  :root {{
                    --bg-gradient: radial-gradient(circle at 5% 10%, #fceabb, transparent 55%),
                                     radial-gradient(circle at 90% 15%, #f8b50055, transparent 45%),
                                     linear-gradient(135deg, #1f1c2c 0%, #928dab 100%);
                    --card-bg: rgba(255, 255, 255, 0.12);
                    --accent: #ffd166;
                    --text: #fff;
                    --border: rgba(255, 255, 255, 0.2);
                  }}
                  body {{ margin: 0; background: var(--bg-gradient); color: var(--text); font-family: system-ui, sans-serif; display: flex; height: 100vh; overflow: hidden; }}
                  .sidebar {{ width: 300px; background: rgba(0,0,0,0.3); backdrop-filter: blur(10px); border-right: 1px solid var(--border); padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 20px; }}
                  .control-group {{ background: rgba(255,255,255,0.05); padding: 15px; border-radius: 12px; }}
                  .control-group h3 {{ margin: 0 0 10px 0; font-size: 0.9rem; text-transform: uppercase; opacity: 0.7; }}
                  label {{ display: block; font-size: 0.85rem; margin-bottom: 4px; display: flex; justify-content: space-between; }}
                  input[type=range] {{ width: 100%; margin-bottom: 12px; }}
                  .main {{ flex: 1; display: flex; flex-direction: column; position: relative; padding: 20px; }}
                  .toolbar {{ display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }}
                  .btn {{ background: rgba(255,255,255,0.1); border: 1px solid var(--border); color: white; padding: 10px 20px; border-radius: 20px; cursor: pointer; transition: all 0.2s; }}
                  .btn:hover {{ background: rgba(255,255,255,0.2); }}
                  .btn.active {{ background: var(--accent); color: black; border-color: var(--accent); }}
                  .viewport {{ flex: 1; display: flex; align-items: center; justify-content: center; gap: 20px; overflow: auto; }}
                  .img-card {{ position: relative; border: 2px solid var(--border); border-radius: 8px; overflow: hidden; background: black; box-shadow: 0 20px 40px rgba(0,0,0,0.3); }}
                  .img-card img {{ display: block; max-width: 100%; max-height: 80vh; image-rendering: pixelated; opacity: 1; transition: opacity 0.2s; }}
                  .img-card.loading img {{ opacity: 0.5; }}
                  .img-card.loading::after {{ content: "Loading..."; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; text-shadow: 0 2px 4px black; }}
                  .img-label {{ position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); padding: 8px; text-align: center; font-size: 0.8rem; backdrop-filter: blur(4px); }}
                  .viewport.grid .img-card {{ flex: 1; min-width: 300px; }}
                </style>
            </head>
            <body>
                <aside class="sidebar">
                    <h2>Config</h2>
                    <div class="control-group">
                        <h3>Processing</h3>
                        <label>Contrast <span id="val-contrast">{SETTINGS.contrast}</span></label>
                        <input type="range" id="contrast" min="0.5" max="2.0" step="0.05" value="{SETTINGS.contrast}">
                        <label>Saturation <span id="val-saturation">{SETTINGS.saturation}</span></label>
                        <input type="range" id="saturation" min="0.0" max="3.0" step="0.1" value="{SETTINGS.saturation}">
                        <label>Gamma <span id="val-gamma">{SETTINGS.gamma}</span></label>
                        <input type="range" id="gamma" min="0.5" max="1.5" step="0.05" value="{SETTINGS.gamma}">
                        <label>Sharpness <span id="val-sharpness">{SETTINGS.sharpness_ui}</span></label>
                        <input type="range" id="sharpness" min="0.0" max="4.0" step="0.1" value="{SETTINGS.sharpness_ui}">
                    </div>
                    <div class="control-group">
                        <h3>Detection</h3>
                        <label>Edge Threshold <span id="val-edge">{SETTINGS.edge_threshold}</span></label>
                        <input type="range" id="edge" min="10" max="100" step="1" value="{SETTINGS.edge_threshold}">
                        <label>Texture Density <span id="val-texture">{SETTINGS.texture_density_threshold}</span></label>
                        <input type="range" id="texture" min="1" max="50" step="1" value="{SETTINGS.texture_density_threshold}">
                    </div>
                    <button class="btn" onclick="resetSettings()">Reset Defaults</button>
                </aside>
                <main class="main">
                    <div class="toolbar">
                        <button class="btn active" id="btn-regional" onclick="setMode('regional')">Hybrid</button>
                        <button class="btn" id="btn-true" onclick="setMode('true')">Photo</button>
                        <button class="btn" id="btn-false" onclick="setMode('false')">UI Only</button>
                        <button class="btn" id="btn-gallery" onclick="toggleGallery()">Show All</button>
                    </div>
                    <div class="viewport" id="viewport"></div>
                </main>
                <script>
                    const state = {{
                        mode: 'regional',
                        gallery: false,
                        params: {{
                            contrast: {SETTINGS.contrast},
                            saturation: {SETTINGS.saturation},
                            gamma: {SETTINGS.gamma},
                            sharpness_ui: {SETTINGS.sharpness_ui},
                            edge_threshold: {SETTINGS.edge_threshold},
                            texture_density_threshold: {SETTINGS.texture_density_threshold}
                        }}
                    }};
                    function getUrl(mode) {{
                        const p = new URLSearchParams(state.params);
                        p.set('dither', mode);
                        p.set('t', Date.now());
                        return `/eink-image?${{p.toString()}}`;
                    }}
                    function createImageCard(mode, label) {{
                        const div = document.createElement('div');
                        div.className = 'img-card loading';
                        const img = document.createElement('img');
                        img.onload = () => div.classList.remove('loading');
                        img.src = getUrl(mode);
                        const lbl = document.createElement('div');
                        lbl.className = 'img-label';
                        lbl.textContent = label;
                        div.appendChild(img);
                        div.appendChild(lbl);
                        return div;
                    }}
                    function render() {{
                        const vp = document.getElementById('viewport');
                        vp.innerHTML = '';
                        if (state.gallery) {{
                            vp.classList.add('grid');
                            vp.appendChild(createImageCard('regional', 'Hybrid'));
                            vp.appendChild(createImageCard('true', 'Photo'));
                            vp.appendChild(createImageCard('false', 'UI Only'));
                        }} else {{
                            vp.classList.remove('grid');
                            vp.appendChild(createImageCard(state.mode, state.mode.toUpperCase()));
                        }}
                        document.querySelectorAll('.toolbar .btn').forEach(b => b.classList.remove('active'));
                        if (state.gallery) {{
                            document.getElementById('btn-gallery').classList.add('active');
                        }} else {{
                            document.getElementById('btn-' + state.mode).classList.add('active');
                        }}
                    }}
                    function setMode(m) {{ state.mode = m; state.gallery = false; render(); }}
                    function toggleGallery() {{ state.gallery = !state.gallery; render(); }}
                    const inputs = {{
                        contrast: document.getElementById('contrast'),
                        saturation: document.getElementById('saturation'),
                        gamma: document.getElementById('gamma'),
                        sharpness_ui: document.getElementById('sharpness'),
                        edge_threshold: document.getElementById('edge'),
                        texture_density_threshold: document.getElementById('texture'),
                    }};
                    function updateParams() {{
                        for (const key in inputs) {{
                            state.params[key] = inputs[key].value;
                            const labelSpan = document.getElementById('val-' + key.replace('_threshold', '').replace('_ui', ''));
                            if(labelSpan) labelSpan.textContent = inputs[key].value;
                        }}
                        render();
                    }}
                    for (const key in inputs) {{ inputs[key].addEventListener('change', updateParams); }}
                    function resetSettings() {{ location.reload(); }}
                    render();
                </script>
            </body>
            </html>
        """)

    return app