
#!/usr/bin/env python3
"""
E-ink 7-Color Image Converter Proxy — v2.7
Goal: Nicer photo dithering (especially skies/trees).
- Edge-aware smoothing in low-gradient regions to avoid speckle.
- HYBRID dithering for photo track:
    * Low-gradient areas -> ordered 2-color halftone between the 2 closest palette colors (clean texture).
    * Detailed areas -> serpentine Stucki error diffusion to 7-color palette.
Everything else stays simple (no grid detection).

Env:
  PHOTO_MODE=hybrid|fs|stucki|ordered     (default: hybrid)
  SKY_GRAD_THR=14                         gradient threshold for "flat" regions
  SMOOTH_STRENGTH=1                       0=off, 1..2 increasing pre-smoothing in flat regions
  CONTRAST, SATURATION, SHARPNESS_UI, GAMMA, EDGE_THR, MID_* as before
"""

import io, os, time, hashlib, logging, math
from typing import Dict, Tuple, List
import requests
from flask import Flask, send_file, request, jsonify
from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageChops

# ---------------------------- Config ----------------------------
SOURCE_URL = os.getenv('SOURCE_URL', 'http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480')
PORT = int(os.getenv('PORT', '5000'))

CONTRAST = float(os.getenv('CONTRAST', '1.25'))
SATURATION = float(os.getenv('SATURATION', '1.2'))
SHARPNESS_UI = float(os.getenv('SHARPNESS_UI', '2.0'))
GAMMA = float(os.getenv('GAMMA', '0.95'))
EDGE_THR = int(os.getenv('EDGE_THR', '26'))
MID_L_MIN = int(os.getenv('MID_L_MIN', '70'))
MID_L_MAX = int(os.getenv('MID_L_MAX', '200'))
MID_S_MAX = int(os.getenv('MID_S_MAX', '90'))
MASK_BLUR = int(os.getenv('MASK_BLUR', '2'))
TIMEOUT = float(os.getenv('SOURCE_TIMEOUT', '10.0'))
RETRIES = int(os.getenv('SOURCE_RETRIES', '2'))
CACHE_TTL = float(os.getenv("CACHE_TTL", "5"))

PHOTO_MODE = os.getenv("PHOTO_MODE","hybrid").lower()
SKY_GRAD_THR = int(os.getenv("SKY_GRAD_THR","14"))
SMOOTH_STRENGTH = int(os.getenv("SMOOTH_STRENGTH","1"))

EINK_PALETTE = [
    (0, 0, 0), (255,255,255), (255,0,0), (255,255,0), (0,255,0), (0,0,255), (255,165,0)
]

# ---------------------------- Setup -----------------------------
app = Flask(__name__)
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
log = logging.getLogger("eink-proxy-v2.7")

def _palette_img():
    pal = Image.new("P",(16,16))
    flat = []
    for r,g,b in EINK_PALETTE: flat += [r,g,b]
    flat += [0,0,0]*(256-len(EINK_PALETTE))
    pal.putpalette(flat)
    return pal
PAL_IMG = _palette_img()

# ---------------------------- Utility ---------------------------
def _apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    if abs(gamma-1.0) < 1e-3: return img
    inv = 1.0/gamma
    lut = [min(255, max(0, int(((i/255.0)**inv)*255 + 0.5))) for i in range(256)]
    return img.point(lut*3)

def enhance_ui(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    img = ImageEnhance.Color(img).enhance(SATURATION)
    img = _apply_gamma(img, GAMMA)
    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS_UI)
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))

def enhance_photo(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    img = ImageEnhance.Color(img).enhance(SATURATION)
    img = _apply_gamma(img, GAMMA)
    return img

def ordered_bw_halftone(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    BM8 = [
        [0,48,12,60,3,51,15,63],
        [32,16,44,28,35,19,47,31],
        [8,56,4,52,11,59,7,55],
        [40,24,36,20,43,27,39,23],
        [2,50,14,62,1,49,13,61],
        [34,18,46,30,33,17,45,29],
        [10,58,6,54,9,57,5,53],
        [42,26,38,22,41,25,37,21],
    ]
    T = [[int((v+0.5)*4) for v in row] for row in BM8]
    W,H = img.size
    src = img.load()
    out = Image.new("1",(W,H))
    dst = out.load()
    for y in range(H):
        for x in range(W):
            dst[x,y] = 255 if src[x,y] > T[y % 8][x % 8] else 0
    return out

def threshold_channel(channel: Image.Image, thr: int, invert: bool = False) -> Image.Image:
    lut = [255 if i >= thr else 0 for i in range(256)]
    mask = channel.point(lut)
    if invert:
        mask = ImageOps.invert(mask)
    return mask

def bandpass_mask_luma(v: Image.Image, lo: int, hi: int) -> Image.Image:
    low = threshold_channel(v, lo)
    high = threshold_channel(v, hi)
    band = ImageChops.subtract(low, high)
    return band

# ----------------------- Palette helpers ------------------------
def nearest_palette_index(rgb):
    r,g,b = rgb
    bi = 0; bd = 1e9
    for i,(R,G,B) in enumerate(EINK_PALETTE):
        d = (R-r)*(R-r)+(G-g)*(G-g)+(B-b)*(B-b)
        if d < bd: bd=d; bi=i
    return bi

def nearest_two_palette(rgb):
    r,g,b = rgb
    best = [(1e9,-1),(1e9,-1)]
    for i,(R,G,B) in enumerate(EINK_PALETTE):
        d = (R-r)*(R-r)+(G-g)*(G-g)+(B-b)*(B-b)
        if d < best[0][0]:
            best[1] = best[0]; best[0] = (d,i)
        elif d < best[1][0]:
            best[1] = (d,i)
    return best[0][1], best[1][1]

def mix_ratio(rgb, a, b):
    # Least-squares solve alpha for rgb ≈ alpha*Pa + (1-alpha)*Pb, clamp 0..1
    Pa = EINK_PALETTE[a]; Pb = EINK_PALETTE[b]
    num = 0.0; den = 1e-6
    for c in range(3):
        xa = Pa[c]; xb = Pb[c]; y = rgb[c]
        num += (xa - xb) * (y - xb)
        den += (xa - xb) ** 2
    alpha = max(0.0, min(1.0, num/den))
    return alpha

# --------------------- Dither algorithms ------------------------
def stucki_error_diffusion(img: Image.Image) -> Image.Image:
    """Serpentine Stucki error diffusion to EINK_PALETTE."""
    W,H = img.size
    src = img.convert("RGB")
    pixels = src.load()
    out = Image.new("RGB",(W,H))
    outpix = out.load()

    # Stucki kernel (normalized by 42)
    # Row+1: 2 4 8 4 2 ; Row+2: 1 2 4 2 1
    kx = [-2,-1,0,1,2]
    ky = [1,2]
    k1 = [2,4,8,4,2]
    k2 = [1,2,4,2,1]
    def add_err(x,y,err,flip):
        for dx in range(-2,3):
            nx = x+dx if not flip else x-dx
            if nx<0 or nx>=W: continue
            yy = y+1
            if yy<H:
                w = k1[dx+2]/42.0
                r = min(255, max(0, pixels[nx,yy][0] + int(err[0]*w)))
                g = min(255, max(0, pixels[nx,yy][1] + int(err[1]*w)))
                b = min(255, max(0, pixels[nx,yy][2] + int(err[2]*w)))
                pixels[nx,yy] = (r,g,b)
            yy = y+2
            if yy<H:
                w = k2[dx+2]/42.0
                r = min(255, max(0, pixels[nx,yy][0] + int(err[0]*w)))
                g = min(255, max(0, pixels[nx,yy][1] + int(err[1]*w)))
                b = min(255, max(0, pixels[nx,yy][2] + int(err[2]*w)))
                pixels[nx,yy] = (r,g,b)

    for y in range(H):
        flip = (y % 2 == 1)
        xr = range(W-1,-1,-1) if flip else range(W)
        for x in xr:
            old = pixels[x,y]
            idx = nearest_palette_index(old)
            new = EINK_PALETTE[idx]
            outpix[x,y] = new
            err = (old[0]-new[0], old[1]-new[1], old[2]-new[2])
            add_err(x,y,err,flip)

    return out

def ordered_two_color(img: Image.Image, grad_mask: Image.Image) -> Image.Image:
    """Ordered halftone that mixes the two nearest palette colors per-pixel.
    grad_mask: 'L' image 0..255, higher means 'flat area' importance.
    """
    W,H = img.size
    src = img.convert("RGB")
    # 8x8 Bayer threshold normalized 0..64
    B = [
        [0,48,12,60,3,51,15,63],
        [32,16,44,28,35,19,47,31],
        [8,56,4,52,11,59,7,55],
        [40,24,36,20,43,27,39,23],
        [2,50,14,62,1,49,13,61],
        [34,18,46,30,33,17,45,29],
        [10,58,6,54,9,57,5,53],
        [42,26,38,22,41,25,37,21],
    ]
    gm = grad_mask.load()
    out = Image.new("RGB",(W,H))
    op = out.load()
    sp = src.load()
    for y in range(H):
        for x in range(W):
            a,b = nearest_two_palette(sp[x,y])
            alpha = mix_ratio(sp[x,y], a, b)  # 0..1 fraction toward color a
            # use threshold with slight bias using grad mask so flat areas look cleaner
            t = (B[y&7][x&7] + 8) / 72.0  # 0..~1
            choose_a = alpha >= t
            op[x,y] = EINK_PALETTE[a if choose_a else b]
    return out

# ------------------------- Masks & blend ------------------------
def build_masks(src_rgb: Image.Image):
    gray = src_rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mask = edges.point(lambda p: 255 if p >= EDGE_THR else 0).filter(ImageFilter.GaussianBlur(MASK_BLUR))

    hsv = src_rgb.convert("HSV"); h,s,v = hsv.split()
    mid_l = bandpass_mask_luma(v, MID_L_MIN, MID_L_MAX)
    low_sat = threshold_channel(s, MID_S_MAX, invert=True)
    mid_gray_mask = ImageChops.multiply(mid_l, low_sat).filter(ImageFilter.GaussianBlur(MASK_BLUR))

    # Gradient magnitude for photo flatness
    grad = edges.filter(ImageFilter.GaussianBlur(1))
    flat = grad.point(lambda p: 255 if p < SKY_GRAD_THR else 0)  # 255 where flat
    if SMOOTH_STRENGTH>0:
        # light edge-aware smoothing: blur only where flat
        smooth = src_rgb.filter(ImageFilter.MedianFilter(3 if SMOOTH_STRENGTH==1 else 5))
        src_smoothed = Image.composite(smooth, src_rgb, flat)  # replace flat areas with smoothed
    else:
        src_smoothed = src_rgb
    return edge_mask, mid_gray_mask, flat, src_smoothed

def quantize_palette_fs(img: Image.Image) -> Image.Image:
    return img.quantize(palette=PAL_IMG, dither=Image.FLOYDSTEINBERG).convert("RGB")

def quantize_palette_none(img: Image.Image) -> Image.Image:
    return img.quantize(palette=PAL_IMG, dither=Image.NONE).convert("RGB")

def composite_regional(src_rgb: Image.Image) -> Image.Image:
    edge_mask, mid_gray_mask, flat_mask, photo_src = build_masks(src_rgb)

    # UI (no dither)
    sharp = quantize_palette_none(enhance_ui(src_rgb))

    # Halftone for neutral mid-grays (clouds)
    bw = ordered_bw_halftone(src_rgb)
    halftone = Image.new("RGB", bw.size, (255,255,255))
    halftone.paste((0,0,0), mask=ImageOps.invert(bw))

    # Photo track with improved dithering
    photo_base = enhance_photo(photo_src)
    if PHOTO_MODE == "fs":
        photo = quantize_palette_fs(photo_base)
    elif PHOTO_MODE == "stucki":
        photo = stucki_error_diffusion(photo_base)
    elif PHOTO_MODE == "ordered":
        photo = ordered_two_color(photo_base, flat_mask)
    else:  # hybrid
        # blend ordered for flat regions, stucki for the rest
        ord_img = ordered_two_color(photo_base, flat_mask)
        stk_img = stucki_error_diffusion(photo_base)
        # use flat_mask as selector (255=flat->ordered)
        photo = Image.composite(ord_img, stk_img, flat_mask)

    # Compose
    mix1 = Image.composite(halftone, sharp, mid_gray_mask)    # put halftone where neutral
    non_edge = ImageOps.invert(edge_mask)                     # allow photo away from edges
    mix2 = Image.composite(photo, mix1, non_edge)             # photo fills non-edges
    out = Image.composite(sharp, mix2, edge_mask)             # reinforce crisp edges
    return out

# ---------------------------- Fetch/cache -----------------------
_session = requests.Session()
_session.headers.update({"User-Agent": "eink-proxy/2.7"})
_last_good_png: bytes = b""
_cache: Dict[str, Tuple[float, bytes]] = {}

def cache_get(key):
    ent = _cache.get(key)
    if not ent: return None
    ts,data = ent
    if time.time()-ts > CACHE_TTL:
        _cache.pop(key, None); return None
    return data

def cache_put(key, data):
    if len(_cache)>16:
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[0][0]
        _cache.pop(oldest, None)
    _cache[key]=(time.time(), data)

def fetch_source() -> Image.Image:
    last = None
    for i in range(1, RETRIES+2):
        try:
            r = _session.get(SOURCE_URL, timeout=TIMEOUT)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception as e:
            last = e; time.sleep(0.4*i)
    raise RuntimeError(last)

def _send_png(img: Image.Image):
    buf = io.BytesIO(); img.save(buf,"PNG", optimize=True)
    data = buf.getvalue()
    global _last_good_png; _last_good_png = data
    return send_file(io.BytesIO(data), mimetype="image/png")

# ---------------------------- Routes ---------------------------
@app.route("/eink-image")
def eink_image():
    mode = (request.args.get("dither","regional") or "regional").lower()
    try:
        src = fetch_source()
        if mode == "regional":
            out = composite_regional(src)
        elif mode == "true":
            out = quantize_palette_fs(enhance_photo(src))
        elif mode == "false":
            out = quantize_palette_none(enhance_ui(src))
        else:
            out = composite_regional(src)
        return _send_png(out)
    except Exception as e:
        if _last_good_png:
            return send_file(io.BytesIO(_last_good_png), mimetype="image/png")
        return (f"error: {e}", 500)

@app.route("/raw")
def raw():
    try:
        return _send_png(fetch_source())
    except Exception as e:
        return (str(e),500)

@app.route("/debug/masks")
def debug_masks():
    try:
        src = fetch_source()
        edge_mask, mid_gray_mask, flat_mask, _ = build_masks(src)
        base = composite_regional(src)
        R = Image.new("RGB", src.size, (255,0,0))
        G = Image.new("RGB", src.size, (0,255,0))
        B = Image.new("RGB", src.size, (0,0,255))  # blue shows "flat/sky" areas
        overlay = base.copy()
        overlay = Image.composite(R, overlay, edge_mask)
        overlay = Image.composite(G, overlay, mid_gray_mask)
        overlay = Image.composite(B, overlay, flat_mask)
        return _send_png(overlay)
    except Exception as e:
        return (f"error: {e}", 500)

@app.route("/health")
def health():
    return jsonify(ok=True, photo_mode=PHOTO_MODE, sky_grad_thr=SKY_GRAD_THR, smooth=SMOOTH_STRENGTH)

@app.route("/")
def index():
    return f"""
    <html>
    <head><title>E-ink Proxy v2.7 — hybrid photo dither</title></head>
    <body style="font-family:Arial; margin:24px">
      <h1>E-ink 7-Color Image Proxy v2.7</h1>
      <p>Source: <code>{SOURCE_URL}</code></p>
      <ul>
        <li><a href="/eink-image?dither=regional">/eink-image?dither=regional</a></li>
        <li><a href="/eink-image?dither=false">/eink-image?dither=false</a></li>
        <li><a href="/eink-image?dither=true">/eink-image?dither=true</a></li>
        <li><a href="/raw">/raw</a></li>
        <li><a href="/debug/masks">/debug/masks</a> (R=edge, G=midtone, B=low-gradient)</li>
        <li><a href="/health">/health</a></li>
      </ul>
      <p>PHOTO_MODE={PHOTO_MODE} (hybrid|fs|stucki|ordered), SKY_GRAD_THR={SKY_GRAD_THR}, SMOOTH_STRENGTH={SMOOTH_STRENGTH}</p>
    </body>
    </html>
    """

if __name__=="__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
