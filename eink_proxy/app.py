from __future__ import annotations

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
APP_VERSION = "3.0.0"


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
        return dedent(
            f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>E-ink Proxy · Live</title>
                <style>
                  :root {{
                    color-scheme: light dark;
                    --bg-gradient: radial-gradient(circle at 5% 10%, #fceabb, transparent 55%),
                                     radial-gradient(circle at 90% 15%, #f8b50055, transparent 45%),
                                     linear-gradient(135deg, #1f1c2c 0%, #928dab 100%);
                    --card-bg: rgba(255, 255, 255, 0.12);
                    --border-glow: rgba(255, 255, 255, 0.35);
                    --text-primary: #fff;
                    --text-secondary: rgba(255, 255, 255, 0.75);
                    --accent: #ffd166;
                    font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                  }}

                  body {{
                    margin: 0;
                    min-height: 100vh;
                    background: var(--bg-gradient);
                    color: var(--text-primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 48px 18px;
                  }}

                  .page {{
                    width: min(900px, 100%);
                    text-align: center;
                  }}

                  h1 {{
                    font-size: 2.5rem;
                    margin-bottom: 24px;
                    text-shadow: 0 4px 12px rgba(0,0,0,0.3);
                  }}

                  .preview-container {{
                    position: relative;
                    width: 100%;
                    border-radius: 16px;
                    overflow: hidden;
                    box-shadow: 0 30px 60px rgba(0,0,0,0.45);
                    border: 2px solid var(--border-glow);
                    background: #000;
                    margin-bottom: 32px;
                  }}
                  
                  .preview-img {{
                    display: block;
                    width: 100%;
                    height: auto;
                    image-rendering: pixelated;
                  }}

                  .controls {{
                    display: flex;
                    justify-content: center;
                    flex-wrap: wrap;
                    gap: 12px;
                    margin-bottom: 24px;
                  }}

                  .btn {{
                    background: rgba(255, 255, 255, 0.1);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    color: var(--text-primary);
                    padding: 12px 24px;
                    border-radius: 999px;
                    cursor: pointer;
                    font-weight: 600;
                    font-size: 1rem;
                    transition: all 0.2s ease;
                    backdrop-filter: blur(4px);
                  }}
                  
                  .btn:hover {{
                    background: rgba(255, 255, 255, 0.2);
                    transform: translateY(-2px);
                  }}

                  .btn.active {{
                    background: var(--accent);
                    color: #1f1c2c;
                    border-color: var(--accent);
                    box-shadow: 0 0 20px rgba(255, 209, 102, 0.4);
                  }}
                  
                  .status-bar {{
                    color: var(--text-secondary);
                    font-size: 0.9rem;
                    background: rgba(0,0,0,0.3);
                    padding: 8px 16px;
                    border-radius: 999px;
                    display: inline-block;
                    backdrop-filter: blur(4px);
                  }}
                  
                  .links {{
                    margin-top: 32px;
                    display: flex;
                    justify-content: center;
                    gap: 24px;
                  }}
                  
                  .links a {{
                    color: var(--text-secondary);
                    text-decoration: none;
                    font-size: 0.9rem;
                  }}
                  
                  .links a:hover {{
                    color: var(--accent);
                    text-decoration: underline;
                  }}
                </style>
            </head>
            <body>
                <main class="page">
                    <h1>E-ink Proxy Dashboard</h1>
                    
                    <div class="controls">
                        <button class="btn active" onclick="setMode('regional')">Hybrid (Regional)</button>
                        <button class="btn" onclick="setMode('true')">Photo (Dithered)</button>
                        <button class="btn" onclick="setMode('false')">UI (Crisp)</button>
                        <button class="btn" onmousedown="toggleRaw(true)" onmouseup="toggleRaw(false)" onmouseleave="toggleRaw(false)">Hold for Raw</button>
                        <button class="btn" onclick="window.open('/debug/masks', '_blank')">Debug Masks</button>
                    </div>

                    <div class="preview-container">
                        <img id="monitor" src="/eink-image?dither=regional" class="preview-img" alt="Dashboard Preview" />
                    </div>
                    
                    <div class="status-bar">
                        Auto-refreshing (5s) · <span id="timestamp">Waiting for update...</span>
                    </div>
                    
                    <div class="links">
                       <span>v{APP_VERSION}</span>
                       <a href="/health" target="_blank">Health Check</a>
                       <a href="https://github.com/rjgrandy/eink-proxy" target="_blank">GitHub</a>
                    </div>
                </main>

                <script>
                    const img = document.getElementById('monitor');
                    const ts = document.getElementById('timestamp');
                    let currentMode = 'regional';
                    let isRaw = false;
                    let refreshTimer = null;

                    function refreshImage() {{
                        if (isRaw) return;
                        const t = new Date().getTime();
                        const newSrc = `/eink-image?dither=${{currentMode}}&t=${{t}}`;
                        
                        // Preload to prevent flashing
                        const tempImg = new Image();
                        tempImg.onload = () => {{
                           img.src = newSrc;
                           ts.textContent = `Updated: ${{new Date().toLocaleTimeString()}}`;
                        }};
                        tempImg.src = newSrc;
                    }}

                    function setMode(mode) {{
                        currentMode = mode;
                        document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
                        // Note: we can't easily find the exact button without ID, but this is fine for now
                        event.target.classList.add('active');
                        refreshImage();
                    }}

                    function toggleRaw(active) {{
                        isRaw = active;
                        if (isRaw) {{
                            img.src = `/raw?t=${{new Date().getTime()}}`;
                            ts.textContent = 'Showing RAW Source';
                        }} else {{
                            refreshImage();
                        }}
                    }}

                    refreshImage();
                    setInterval(refreshImage, 5000);
                </script>
            </body>
            </html>
            """
        )

    return app
