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
                "Hybrid Regional Dither",
                "/eink-image?dither=regional",
                "Optimized hybrid flow for photo + UI composites.",
                "🎯",
            ),
            (
                "UI-Only Enhance",
                "/eink-image?dither=false",
                "Punchy UI colors using selective palette quantization.",
                "🧭",
            ),
            (
                "Full Photographic",
                "/eink-image?dither=true",
                "Fine detail Floyd–Steinberg palette rendering.",
                "🌌",
            ),
            (
                "Raw Source",
                "/raw",
                "Bypass the processing pipeline and view the original PNG.",
                "🖼️",
            ),
            (
                "Mask Debugger",
                "/debug/masks",
                "Visualize segmentation (R=edge, G=midtone, B=low-gradient).",
                "🧪",
            ),
            (
                "Health Endpoint",
                "/health",
                "Operational heartbeat and current tuning values.",
                "💓",
            ),
        ]
    
        endpoint_cards = "".join(
            f"""
            <article class="endpoint-card" data-endpoint="{href}">              <div class="endpoint-icon">{icon}</div>              <div class="endpoint-content">                <div class="endpoint-title">                  <h3>{escape(name)}</h3>                  <span class="endpoint-pill">Live</span>                </div>                <p>{escape(description)}</p>                <div class="endpoint-actions">                  <button class="btn primary preview-btn" data-endpoint="{href}">Preview here</button>                  <a class="btn ghost" href="{href}" target="_blank" rel="noopener">Open tab</a>                  <button class="btn ghost copy-btn" data-endpoint="{href}">Copy URL</button>                </div>              </div>            </article>            """
            for name, href, description, icon in endpoints
        )
    
        comparison_options = "".join(
            f'<option value="{href}">{escape(name)}</option>' for name, href, *_ in endpoints
        )
    
        control_fields = [
            {
                "name": "source_url",
                "label": "Source URL",
                "type": "url",
                "value": SETTINGS.source_url,
                "help": "Upstream feed used for rendering.",
            },
            {
                "name": "port",
                "label": "Port",
                "type": "number",
                "value": SETTINGS.port,
                "step": "1",
                "help": "Listening port (requires restart to move listeners).",
            },
            {
                "name": "photo_mode",
                "label": "Photo mode",
                "type": "select",
                "value": SETTINGS.photo_mode,
                "options": [
                    ("hybrid", "Hybrid regional"),
                    ("fs", "Floyd–Steinberg"),
                    ("stucki", "Stucki"),
                    ("ordered", "Ordered"),
                ],
                "help": "Dither profile for photographic content.",
            },
            {
                "name": "contrast",
                "label": "Contrast",
                "type": "number",
                "step": "0.05",
                "value": SETTINGS.contrast,
                "help": "Global contrast applied before palette quantization.",
            },
            {
                "name": "saturation",
                "label": "Saturation",
                "type": "number",
                "step": "0.05",
                "value": SETTINGS.saturation,
                "help": "Overall saturation boost for both modes.",
            },
            {
                "name": "sharpness_ui",
                "label": "Sharpness (UI)",
                "type": "number",
                "step": "0.1",
                "value": SETTINGS.sharpness_ui,
                "help": "Sharpen filter for UI imagery.",
            },
            {
                "name": "gamma",
                "label": "Gamma",
                "type": "number",
                "step": "0.01",
                "value": SETTINGS.gamma,
                "help": "Gamma curve tweak pre-quantization.",
            },
            {
                "name": "edge_threshold",
                "label": "Edge threshold",
                "type": "number",
                "step": "1",
                "value": SETTINGS.edge_threshold,
                "help": "Edge detection cutoff for mask creation.",
            },
            {
                "name": "mid_l_min",
                "label": "Mid L min",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_min,
                "help": "Lower lightness bound for mid-tone mask.",
            },
            {
                "name": "mid_l_max",
                "label": "Mid L max",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_l_max,
                "help": "Upper lightness bound for mid-tone mask.",
            },
            {
                "name": "mid_s_max",
                "label": "Mid S max",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mid_s_max,
                "help": "Saturation threshold for mid-tone filtering.",
            },
            {
                "name": "mask_blur",
                "label": "Mask blur",
                "type": "number",
                "step": "1",
                "value": SETTINGS.mask_blur,
                "help": "Gaussian blur radius for segmentation masks.",
            },
            {
                "name": "timeout",
                "label": "Source timeout",
                "type": "number",
                "step": "0.1",
                "value": SETTINGS.timeout,
                "help": "HTTP timeout when fetching upstream imagery.",
            },
            {
                "name": "retries",
                "label": "Retries",
                "type": "number",
                "step": "1",
                "value": SETTINGS.retries,
                "help": "Retry attempts for source fetches.",
            },
            {
                "name": "cache_ttl",
                "label": "Cache TTL",
                "type": "number",
                "step": "0.5",
                "value": SETTINGS.cache_ttl,
                "help": "Seconds to keep last good PNG for fallback.",
            },
            {
                "name": "sky_gradient_threshold",
                "label": "Sky gradient threshold",
                "type": "number",
                "step": "1",
                "value": SETTINGS.sky_gradient_threshold,
                "help": "Gradient cutoff for sky smoothing.",
            },
            {
                "name": "smooth_strength",
                "label": "Smooth strength",
                "type": "number",
                "step": "1",
                "value": SETTINGS.smooth_strength,
                "help": "Mask smoothing strength (0 disables).",
            },
            {
                "name": "log_level",
                "label": "Log level",
                "type": "select",
                "value": SETTINGS.log_level,
                "options": [
                    ("DEBUG", "Debug"),
                    ("INFO", "Info"),
                    ("WARNING", "Warning"),
                    ("ERROR", "Error"),
                ],
                "help": "Logging verbosity for the proxy service.",
            },
            {
                "name": "ui_palette_threshold",
                "label": "UI palette threshold",
                "type": "number",
                "step": "10",
                "value": SETTINGS.ui_palette_threshold,
                "help": "Distance cutoff when mapping UI colors to the palette.",
            },
            {
                "name": "ui_tint_saturation",
                "label": "UI tint saturation",
                "type": "number",
                "step": "1",
                "value": SETTINGS.ui_tint_saturation,
                "help": "Saturation threshold for UI tinting mask.",
            },
            {
                "name": "ui_tint_min_value",
                "label": "UI tint min value",
                "type": "number",
                "step": "1",
                "value": SETTINGS.ui_tint_min_value,
                "help": "Minimum value for highlights used in tinting.",
            },
        ]
    
        def render_field(field: dict[str, object]) -> str:
            help_text = escape(str(field.get("help", "")))
            label = escape(str(field.get("label", field["name"])))
            name = escape(str(field["name"]))
            value = escape(str(field.get("value", "")))
            step = field.get("step")
            if field.get("type") == "select":
                options = "".join(
                    f'<option value="{escape(str(v))}"'
                    f"{' selected' if str(v) == str(field.get('value')) else ''}>"
                    f"{escape(str(label))}</option>"
                    for v, label in field.get("options", [])
                )
                control = f"<select name=\"{name}\" data-field=\"{name}\" class=\"control-input\">{options}</select>"
            else:
                step_attr = f' step="{step}"' if step else ""
                control = (
                    f'<input type="{field.get("type", "text")}" name="{name}" '
                    f'value="{value}" class="control-input" data-field="{name}"{step_attr} />'
                )
    
            return (
                "<label class=\"control-field\">"
                f"<div class=\"control-top\"><span>{label}</span><span class=\"chip\">Live</span></div>"
                f"{control}"
                f"<small>{help_text}</small>"
                "</label>"
            )
    
        controls_html = "".join(render_field(field) for field in control_fields)
    
        class SafeDict(dict):
            def __missing__(self, key):  # pragma: no cover - passthrough
                return "{" + key + "}"

        template = dedent(
            """
        <!DOCTYPE html>
        <html lang="en">          <head>            <meta charset="utf-8" />            <meta name="viewport" content="width=device-width, initial-scale=1" />            <title>E-ink Proxy · v{APP_VERSION}</title>            <style>              :root {{                color-scheme: light dark;                --bg: radial-gradient(circle at 12% 20%, #23364d, transparent 35%),                         radial-gradient(circle at 90% 10%, #3c2d4e, transparent 30%),                         linear-gradient(140deg, #0b1022 0%, #111a2f 52%, #1f2e4d 100%);                --panel: rgba(255, 255, 255, 0.08);                --panel-strong: rgba(255, 255, 255, 0.12);                --border: rgba(255, 255, 255, 0.16);                --text: #f4f6fb;                --muted: #9fb0d1;                --accent: #8be9c7;                --accent-2: #7aa2f7;                --shadow: 0 25px 55px rgba(5, 12, 32, 0.55);                font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;              }}
              body {{                margin: 0;                min-height: 100vh;                background: var(--bg);                color: var(--text);                display: flex;                justify-content: center;                padding: 42px 16px 64px;              }}
              .page {{                width: min(1280px, 100%);                display: grid;                gap: 28px;              }}
              .shell {{                background: rgba(255, 255, 255, 0.03);                border: 1px solid var(--border);                border-radius: 24px;                padding: clamp(20px, 3vw, 32px);                box-shadow: var(--shadow);              }}
              .hero {{                display: grid;                grid-template-columns: 1.2fr 1fr;                gap: 24px;                align-items: center;              }}
              .hero h1 {{                margin: 10px 0 12px;                font-size: clamp(2.1rem, 5vw, 3.2rem);                letter-spacing: -0.02em;              }}
              .version-pill {{                display: inline-flex;                align-items: center;                gap: 8px;                padding: 8px 14px;                border-radius: 999px;                background: rgba(255, 255, 255, 0.08);                border: 1px solid var(--border);                color: var(--muted);                text-transform: uppercase;                font-size: 0.78rem;                letter-spacing: 0.08em;              }}
              .lede {{                color: var(--muted);                margin: 0;                line-height: 1.55;              }}
              .cta-row {{                display: flex;                gap: 12px;                flex-wrap: wrap;                margin-top: 18px;              }}
              .btn {{                border-radius: 12px;                border: 1px solid var(--border);                padding: 10px 16px;                font-weight: 600;                background: transparent;                color: var(--text);                cursor: pointer;                text-decoration: none;                display: inline-flex;                align-items: center;                gap: 6px;                transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;              }}
              .btn.primary {{                background: linear-gradient(120deg, var(--accent) 0%, var(--accent-2) 100%);                color: #04101f;                border-color: rgba(255, 255, 255, 0.18);                box-shadow: 0 10px 28px rgba(122, 162, 247, 0.35);              }}
              .btn.ghost {{                background: rgba(255, 255, 255, 0.05);              }}
              .btn:hover {{                transform: translateY(-2px);                border-color: rgba(255, 255, 255, 0.35);              }}
              .source-card {{                background: rgba(255, 255, 255, 0.04);                border-radius: 18px;                padding: 14px 16px;                border: 1px solid var(--border);              }}
              .chip {{                display: inline-flex;                align-items: center;                gap: 6px;                padding: 6px 10px;                border-radius: 999px;                background: rgba(255, 255, 255, 0.06);                color: var(--muted);                font-size: 0.82rem;              }}
              .grid {{                display: grid;                gap: 18px;                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));              }}
              .endpoint-card {{                display: flex;                gap: 16px;                padding: 16px;                border-radius: 18px;                border: 1px solid var(--border);                background: var(--panel);                box-shadow: 0 14px 32px rgba(0, 0, 0, 0.32);                transition: transform 0.15s ease, border 0.15s ease;              }}
              .endpoint-card:hover {{                transform: translateY(-3px);                border-color: rgba(139, 233, 199, 0.6);              }}
              .endpoint-icon {                font-size: 1.8rem;              }
    
              .endpoint-title {                display: flex;                align-items: center;                gap: 10px;                margin-bottom: 4px;              }
    
              .endpoint-title h3 {                margin: 0;
              }
    
              .endpoint-pill {                padding: 4px 8px;                border-radius: 10px;                background: rgba(122, 162, 247, 0.18);                color: #a7c5ff;                font-size: 0.75rem;                text-transform: uppercase;                letter-spacing: 0.04em;              }
    
              .endpoint-content p {{                margin: 4px 0 12px;                color: var(--muted);              }}
              .endpoint-actions {                display: flex;                flex-wrap: wrap;                gap: 8px;
              }
    
              .controls-grid {                display: grid;                gap: 14px;                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));              }
    
              .control-field {                display: flex;                flex-direction: column;                gap: 8px;                padding: 12px 14px;                border-radius: 12px;                background: rgba(255, 255, 255, 0.05);                border: 1px solid var(--border);              }
    
              .control-top {                display: flex;                align-items: center;                justify-content: space-between;                font-weight: 600;              }
    
              .control-input {                width: 100%;                padding: 10px 12px;                border-radius: 10px;                border: 1px solid var(--border);                background: rgba(0, 0, 0, 0.25);                color: var(--text);                font-size: 1rem;              }
    
              .control-input:focus {                outline: 2px solid rgba(139, 233, 199, 0.5);                border-color: rgba(139, 233, 199, 0.4);              }
    
              .control-field small {                color: var(--muted);              }
    
              .preview-grid {                display: grid;                gap: 16px;                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));              }
    
              .preview-card {                background: var(--panel);                border: 1px solid var(--border);                border-radius: 16px;                padding: 12px;                box-shadow: var(--shadow);              }
    
              .preview-stage {                background: rgba(0, 0, 0, 0.18);                border-radius: 12px;                padding: 8px;                border: 1px dashed rgba(255, 255, 255, 0.1);                min-height: 220px;              }
    
              .preview-stage img {                width: 100%;                display: block;                border-radius: 8px;              }
    
              .preview-header {                display: flex;                justify-content: space-between;                align-items: center;                margin-bottom: 8px;              }
    
              .pill {                padding: 4px 10px;                border-radius: 999px;                background: rgba(255, 255, 255, 0.08);                color: var(--muted);                font-size: 0.8rem;              }
    
              .compare-grid {                display: grid;                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));                gap: 12px;                align-items: start;              }
    
              figure {                margin: 0;              }
    
              figcaption {                margin-top: 6px;                color: var(--muted);                font-size: 0.9rem;              }
    
              @media (max-width: 860px) {                .hero {                  grid-template-columns: 1fr;                }
              }
            </style>          </head>          <body>            <main class="page">              <section class="shell" aria-label="Hero">                <div class="hero">                  <div>                    <span class="version-pill">Version v{APP_VERSION}</span>                    <h1>7-Color E-ink Control Room</h1>                    <p class="lede">Refined controls, live previews, and comparison views for every endpoint in your proxy.</p>                    <div class="cta-row">                      <a class="btn primary" href="/eink-image?dither=regional">View hybrid output</a>                      <a class="btn ghost" href="/raw">Download raw PNG</a>                      <span class="chip">Source: <code id="source-url">{source_url}</code></span>                    </div>                  </div>                  <div class="source-card">                    <div class="control-top">                      <span>Live knobs</span>                      <span class="pill">Instant apply</span>                    </div>                    <p class="lede" style="margin-top:8px;">Adjust any setting and the pipeline will consume it immediately—no reload required.</p>                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:10px;">                      <div class="chip">Mode: <strong id="summary-photo-mode">{SETTINGS.photo_mode}</strong></div>                      <div class="chip">Sky thr: <strong id="summary-sky">{SETTINGS.sky_gradient_threshold}</strong></div>                      <div class="chip">Smooth: <strong id="summary-smooth">{SETTINGS.smooth_strength}</strong></div>                      <div class="chip">Cache TTL: <strong id="summary-cache">{SETTINGS.cache_ttl}</strong>s</div>                    </div>                  </div>                </div>              </section>
              <section class="shell" aria-label="Endpoints">                <div class="control-top" style="margin-bottom:12px;">                  <div>                    <h2 style="margin:0;">Endpoint explorer</h2>                    <p class="lede">Click preview to render inline, or open the raw responses in a new tab.</p>                  </div>                  <span class="pill">Clickable &amp; copyable</span>                </div>                <div class="grid">                  {endpoint_cards}                </div>              </section>
              <section class="shell" aria-label="Comparison">                <div class="control-top" style="margin-bottom:12px;">                  <div>                    <h2 style="margin:0;">Comparison lab</h2>                    <p class="lede">Pick two endpoints and refresh to review them side-by-side.</p>                  </div>                  <div class="cta-row">                    <button class="btn ghost" id="swap-btn">Swap</button>                    <button class="btn primary" id="refresh-btn">Refresh comparison</button>                  </div>                </div>                <div class="compare-grid">                  <label class="control-field">                    <div class="control-top"><span>Left endpoint</span></div>                    <select class="control-input" id="left-select">{comparison_options}</select>                  </label>                  <label class="control-field">                    <div class="control-top"><span>Right endpoint</span></div>                    <select class="control-input" id="right-select">{comparison_options}</select>                  </label>                </div>                <div class="compare-grid" style="margin-top:12px;">                  <figure class="preview-card">                    <div class="preview-header"><span class="pill" id="left-label"></span></div>                    <div class="preview-stage"><img id="left-image" alt="Left endpoint preview" loading="lazy" /></div>                  </figure>                  <figure class="preview-card">                    <div class="preview-header"><span class="pill" id="right-label"></span></div>                    <div class="preview-stage"><img id="right-image" alt="Right endpoint preview" loading="lazy" /></div>                  </figure>                </div>              </section>
              <section class="shell" aria-label="Preview &amp; controls">                <div class="preview-grid">                  <div class="preview-card">                    <div class="preview-header">                      <h3 style="margin:0;">Inline endpoint preview</h3>                      <button class="btn ghost" id="refresh-preview">Refresh</button>                    </div>                    <div class="control-top" style="margin-bottom:8px;">                      <span class="pill" id="active-endpoint">/eink-image?dither=regional</span>                    </div>                    <div class="preview-stage">                      <img id="endpoint-preview" src="/eink-image?dither=regional" alt="Endpoint preview" loading="lazy" />                    </div>                  </div>                  <div class="preview-card">                    <div class="preview-header">                      <h3 style="margin:0;">Live configuration</h3>                      <span class="pill">Auto-save</span>                    </div>                    <form id="settings-form" class="controls-grid" autocomplete="off">                      {controls_html}                    </form>                  </div>                </div>              </section>            </main>
            <script>              const toast = document.createElement('div');              toast.className = 'toast';              toast.style.position = 'fixed';              toast.style.bottom = '24px';              toast.style.right = '24px';              toast.style.padding = '12px 18px';              toast.style.borderRadius = '999px';              toast.style.background = 'rgba(13, 19, 36, 0.9)';              toast.style.color = 'white';              toast.style.fontFamily = 'inherit';              toast.style.fontSize = '0.9rem';              toast.style.boxShadow = '0 10px 30px rgba(8, 11, 29, 0.35)';              toast.style.opacity = '0';              toast.style.transform = 'translateY(16px)';              toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';              toast.style.pointerEvents = 'none';              toast.textContent = 'Copied!';              document.body.appendChild(toast);
              const setToast = (msg) => {                toast.textContent = msg;                toast.style.opacity = '1';                toast.style.transform = 'translateY(0)';                setTimeout(() => {                  toast.style.opacity = '0';                  toast.style.transform = 'translateY(12px)';                }, 2000);              };
              const bust = (url) => {                const separator = url.includes('?') ? '&' : '?';                return `${url}${separator}ts=${Date.now()}`;              };
              document.querySelectorAll('.copy-btn').forEach(btn => {                btn.addEventListener('click', async (e) => {                  e.stopPropagation();                  const url = new URL(btn.dataset.endpoint, window.location.origin);                  try {                    await navigator.clipboard.writeText(url.href);                    setToast(`Copied ${url.pathname}`);                  } catch (err) {                    setToast('Copy failed.');                  }                });              });
              const previewImg = document.getElementById('endpoint-preview');              const previewLabel = document.getElementById('active-endpoint');              const refreshPreview = () => {                previewImg.src = bust(previewLabel.textContent);              };
              document.getElementById('refresh-preview').addEventListener('click', refreshPreview);
              document.querySelectorAll('.preview-btn').forEach((btn) => {                btn.addEventListener('click', (event) => {                  event.preventDefault();                  const endpoint = btn.dataset.endpoint;                  previewLabel.textContent = endpoint;                  previewImg.src = bust(endpoint);                  setToast(`Previewing ${endpoint}`);                });              });
              const settingsForm = document.getElementById('settings-form');              const summary = {                photo_mode: document.getElementById('summary-photo-mode'),                sky_gradient_threshold: document.getElementById('summary-sky'),                smooth_strength: document.getElementById('summary-smooth'),                cache_ttl: document.getElementById('summary-cache'),                source_url: document.getElementById('source-url'),              };
              const patchSetting = async (field, value) => {                try {                  const res = await fetch('/settings', {                    method: 'PATCH',                    headers: { 'Content-Type': 'application/json' },                    body: JSON.stringify({ [field]: value }),                  });
                  const data = await res.json();                  if (!res.ok) {                    const err = data.errors?.[field] || 'Unable to apply change';                    setToast(err);                    return;                  }
                  Object.entries(data.settings || {}).forEach(([key, val]) => {                    if (summary[key]) {                      summary[key].textContent = val;                    }                    const control = settingsForm.querySelector(`[data-field="${key}"]`);                    if (control && document.activeElement !== control) {                      control.value = val;                    }                  });
                  setToast(`Updated ${field}`);                } catch (error) {                  setToast('Network error while saving.');                }              };
              settingsForm.addEventListener('change', (event) => {                const target = event.target;                if (!target.dataset.field) return;                patchSetting(target.dataset.field, target.value);              });
              const leftSelect = document.getElementById('left-select');              const rightSelect = document.getElementById('right-select');              const leftImage = document.getElementById('left-image');              const rightImage = document.getElementById('right-image');              const leftLabel = document.getElementById('left-label');              const rightLabel = document.getElementById('right-label');
              const refreshComparison = () => {                const leftEndpoint = leftSelect.value;                const rightEndpoint = rightSelect.value;                leftLabel.textContent = leftEndpoint;                rightLabel.textContent = rightEndpoint;                leftImage.src = bust(leftEndpoint);                rightImage.src = bust(rightEndpoint);              };
              document.getElementById('refresh-btn').addEventListener('click', refreshComparison);              document.getElementById('swap-btn').addEventListener('click', () => {                const left = leftSelect.value;                leftSelect.value = rightSelect.value;                rightSelect.value = left;                refreshComparison();              });
                refreshComparison();            </script>          </body>        </html>            """
        )

        placeholders = [
            "APP_VERSION",
            "endpoint_cards",
            "controls_html",
            "comparison_options",
            "SETTINGS.photo_mode",
            "SETTINGS.sky_gradient_threshold",
            "SETTINGS.smooth_strength",
            "SETTINGS.cache_ttl",
            "source_url",
        ]

        for name in placeholders:
            template = template.replace(f"{{{name}}}", f"__PLACEHOLDER_{name}__")

        template = template.replace("{", "{{").replace("}", "}}")

        for name in placeholders:
            template = template.replace(f"__PLACEHOLDER_{name}__", f"{{{name}}}")

        return template.format_map(
            SafeDict(
                APP_VERSION=APP_VERSION,
                SETTINGS=SETTINGS,
                endpoint_cards=endpoint_cards,
                controls_html=controls_html,
                comparison_options=comparison_options,
                source_url=escape(SETTINGS.source_url),
            )
        )

        return app
