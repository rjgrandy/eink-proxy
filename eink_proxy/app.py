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
        endpoint_cards = "".join(
            f"""
            <article class=\"endpoint-card\">
              <div class=\"endpoint-icon\">{icon}</div>
              <div class=\"endpoint-content\">
                <h3><a href=\"{href}\" target=\"_blank\" rel=\"noopener\">{name}</a></h3>
                <p>{description}</p>
                <button class=\"copy-btn\" data-endpoint=\"{href}\">Copy URL</button>
              </div>
            </article>
            """
            for name, href, description, icon in (
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
            )
        )

        return f"""
        <!DOCTYPE html>
        <html lang=\"en\">
          <head>
            <meta charset=\"utf-8\" />
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
            <title>E-ink Proxy · v{APP_VERSION}</title>
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
                --accent-strong: #f78c6b;
                font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
              }}

              body {{
                margin: 0;
                min-height: 100vh;
                background: var(--bg-gradient);
                color: var(--text-primary);
                display: flex;
                align-items: stretch;
                justify-content: center;
                padding: 48px 18px 64px;
              }}

              .page {{
                width: min(1100px, 100%);
                display: grid;
                gap: 32px;
              }}

              .hero {{
                position: relative;
                padding: 48px clamp(24px, 5vw, 64px);
                border-radius: 28px;
                background: linear-gradient(135deg, rgba(31, 28, 44, 0.88), rgba(44, 84, 142, 0.72));
                border: 1px solid var(--border-glow);
                box-shadow: 0 30px 50px rgba(12, 12, 26, 0.45);
                overflow: hidden;
              }}

              .hero::after {{
                content: \"\";
                position: absolute;
                inset: -30% 45% auto -40%;
                height: 200%;
                background: conic-gradient(from 120deg, rgba(247, 140, 107, 0.55), rgba(255, 209, 102, 0.6), transparent 60%);
                filter: blur(80px);
                pointer-events: none;
                transform: rotate(-15deg);
              }}

              .version-pill {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 14px;
                border-radius: 999px;
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255, 255, 255, 0.2);
                font-size: 0.85rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
              }}

              h1 {{
                margin: 18px 0 12px;
                font-size: clamp(2.25rem, 5vw, 3.4rem);
                line-height: 1.1;
              }}

              .hero p {{
                margin: 0;
                font-size: 1.05rem;
                color: var(--text-secondary);
              }}

              .cta-row {{
                display: flex;
                flex-wrap: wrap;
                gap: 16px;
                margin-top: 32px;
              }}

              .cta-row a {{
                background: var(--accent);
                color: #1f1c2c;
                padding: 14px 24px;
                border-radius: 999px;
                text-decoration: none;
                font-weight: 600;
                box-shadow: 0 14px 24px rgba(255, 209, 102, 0.35);
                transition: transform 0.2s ease, box-shadow 0.2s ease;
              }}

              .cta-row a:hover {{
                transform: translateY(-2px);
                box-shadow: 0 18px 32px rgba(255, 209, 102, 0.45);
              }}

              .grid {{
                display: grid;
                gap: 20px;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
              }}

              .endpoint-card {{
                backdrop-filter: blur(14px);
                background: var(--card-bg);
                border-radius: 22px;
                padding: 22px;
                border: 1px solid rgba(255, 255, 255, 0.22);
                box-shadow: 0 18px 38px rgba(8, 11, 29, 0.25);
                display: flex;
                gap: 16px;
                align-items: flex-start;
                transition: transform 0.2s ease, border 0.2s ease, box-shadow 0.2s ease;
              }}

              .endpoint-card:hover {{
                transform: translateY(-4px) scale(1.01);
                border-color: rgba(255, 255, 255, 0.45);
                box-shadow: 0 22px 44px rgba(8, 11, 29, 0.35);
              }}

              .endpoint-icon {{
                font-size: 1.9rem;
                filter: drop-shadow(0 8px 16px rgba(31, 28, 44, 0.35));
              }}

              .endpoint-content h3 {{
                margin: 0 0 6px;
              }}

              .endpoint-content a {{
                color: var(--accent);
                text-decoration: none;
              }}

              .endpoint-content a:hover {{
                text-decoration: underline;
              }}

              .endpoint-content p {{
                margin: 0 0 14px;
                color: var(--text-secondary);
              }}

              .copy-btn {{
                background: rgba(31, 28, 44, 0.55);
                color: var(--text-primary);
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 999px;
                padding: 8px 16px;
                font-size: 0.85rem;
                cursor: pointer;
                transition: background 0.2s ease, transform 0.2s ease;
              }}

              .copy-btn:hover {{
                background: rgba(31, 28, 44, 0.75);
                transform: translateY(-1px);
              }}

              .settings-panel {{
                background: rgba(15, 18, 35, 0.8);
                border-radius: 24px;
                border: 1px solid rgba(255, 255, 255, 0.18);
                padding: 24px clamp(18px, 3vw, 32px);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
              }}

              .settings-panel h2 {{
                margin-top: 0;
                font-size: 1.4rem;
              }}

              .settings-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 16px;
                margin-top: 20px;
              }}

              .settings-card {{
                border-radius: 18px;
                padding: 14px 16px;
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.16);
              }}

              .settings-label {{
                font-size: 0.75rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: var(--text-secondary);
                margin-bottom: 6px;
              }}

              .settings-value {{
                font-size: 1.2rem;
                font-weight: 600;
              }}

              @media (max-width: 720px) {{
                body {{
                  padding: 32px 12px 48px;
                }}

                .hero {{
                  padding: 36px 22px;
                }}

                .cta-row {{
                  flex-direction: column;
                }}
              }}
            </style>
          </head>
          <body>
            <main class=\"page\">
              <section class=\"hero\">
                <span class=\"version-pill\">Version v{APP_VERSION}</span>
                <h1>7-Color E-ink Proxy Control Center</h1>
                <p>Monitor, debug, and celebrate your display pipeline. All the knobs, all the modes, right here.</p>
                <div class=\"cta-row\">
                  <a href=\"/eink-image?dither=regional\">View Hybrid Output</a>
                  <a href=\"{SETTINGS.source_url}\" target=\"_blank\" rel=\"noopener\">Open Source Feed</a>
                </div>
              </section>

              <section class=\"grid\" aria-label=\"Primary endpoints\">
                {endpoint_cards}
              </section>

              <section class=\"settings-panel\">
                <h2>Live Configuration</h2>
                <p class=\"settings-lead\">These values are sourced from <code>settings.toml</code> and applied to the processing pipeline.</p>
                <div class=\"settings-grid\">
                  <div class=\"settings-card\">
                    <div class=\"settings-label\">Photo mode</div>
                    <div class=\"settings-value\">{SETTINGS.photo_mode}</div>
                  </div>
                  <div class=\"settings-card\">
                    <div class=\"settings-label\">Sky gradient threshold</div>
                    <div class=\"settings-value\">{SETTINGS.sky_gradient_threshold}</div>
                  </div>
                  <div class=\"settings-card\">
                    <div class=\"settings-label\">Smooth strength</div>
                    <div class=\"settings-value\">{SETTINGS.smooth_strength}</div>
                  </div>
                  <div class=\"settings-card\">
                    <div class=\"settings-label\">Source URL</div>
                    <div class=\"settings-value\">{SETTINGS.source_url}</div>
                  </div>
                </div>
              </section>
            </main>

            <script>
              const toast = document.createElement('div');
              toast.className = 'toast';
              toast.style.position = 'fixed';
              toast.style.bottom = '24px';
              toast.style.right = '24px';
              toast.style.padding = '12px 18px';
              toast.style.borderRadius = '999px';
              toast.style.background = 'rgba(31, 28, 44, 0.85)';
              toast.style.color = 'white';
              toast.style.fontFamily = 'inherit';
              toast.style.fontSize = '0.9rem';
              toast.style.boxShadow = '0 10px 30px rgba(8, 11, 29, 0.35)';
              toast.style.opacity = '0';
              toast.style.transform = 'translateY(16px)';
              toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
              toast.style.pointerEvents = 'none';
              toast.textContent = 'Copied!';
              document.body.appendChild(toast);

              document.querySelectorAll('.copy-btn').forEach(btn => {{
                btn.addEventListener('click', async () => {{
                  const url = new URL(btn.dataset.endpoint, window.location.origin);
                  try {{
                    await navigator.clipboard.writeText(url.href);
                    toast.textContent = `Copied ${url.pathname}!`;
                  }} catch (err) {{
                    toast.textContent = 'Copy failed. Try manual copy instead.';
                  }}

                  toast.style.opacity = '1';
                  toast.style.transform = 'translateY(0)';
                  setTimeout(() => {{
                    toast.style.opacity = '0';
                    toast.style.transform = 'translateY(16px)';
                  }}, 1800);
                }});
              }});
            </script>
          </body>
        </html>
        """
        )

    return app
