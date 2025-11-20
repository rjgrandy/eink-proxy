from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter, ImageOps

from .dither import ordered_bw_halftone, ordered_two_color, stucki_error_diffusion
from .enhance import enhance_photo, enhance_ui
from .masking import build_masks
from .palette import PAL_IMG, mix_ratio, nearest_palette_index, palette_fit_mask
from ..config import EINK_PALETTE, SETTINGS, ProxySettings

# ... (Keep _BAYER_8X8 and _TINTED_HUE_TARGETS from previous files) ...
_BAYER_8X8 = (
    (0, 48, 12, 60, 3, 51, 15, 63),
    (32, 16, 44, 28, 35, 19, 47, 31),
    (8, 56, 4, 52, 11, 59, 7, 55),
    (40, 24, 36, 20, 43, 27, 39, 23),
    (2, 50, 14, 62, 1, 49, 13, 61),
    (34, 18, 46, 30, 33, 17, 45, 29),
    (10, 58, 6, 54, 9, 57, 5, 53),
    (42, 26, 38, 22, 41, 25, 37, 21),
)

_TINTED_HUE_TARGETS = (
    (2, 0.0),   # red ink
    (6, 30.0),  # orange ink
    (3, 60.0),  # yellow ink
    (4, 120.0),  # green ink
    (5, 240.0),  # blue ink
)

def quantize_palette_fs(img: Image.Image) -> Image.Image:
    return img.quantize(palette=PAL_IMG, dither=Image.FLOYDSTEINBERG).convert("RGB")

def quantize_palette_none(img: Image.Image) -> Image.Image:
    src = img.convert("RGB")
    width, height = src.size
    out = Image.new("RGB", (width, height))
    src_pixels = src.load()
    dst_pixels = out.load()
    for y in range(height):
        for x in range(width):
            dst_pixels[x, y] = EINK_PALETTE[nearest_palette_index(src_pixels[x, y])]
    return out

def _tinted_flat_regions(ui_rgb: Image.Image, flat_mask: Image.Image, settings: ProxySettings) -> Image.Image:
    hsv = ui_rgb.convert("HSV")
    _, saturation, value = hsv.split()

    sat_mask = saturation.point(lambda s: 255 if s >= settings.ui_tint_saturation else 0)
    bright_mask = value.point(lambda v: 255 if v >= settings.ui_tint_min_value else 0)
    
    tinted = ImageChops.multiply(sat_mask, bright_mask)
    tinted = ImageChops.multiply(tinted, flat_mask)
    
    # Clean up tint mask to be solid blocks
    tinted = tinted.filter(ImageFilter.MaxFilter(3))
    tinted = tinted.filter(ImageFilter.GaussianBlur(radius=1))
    return tinted.point(lambda p: 255 if p >= 32 else 0)

# ... (Keep _angular_distance and _tinted_palette_mix from previous files) ...
def _angular_distance(h1: float, h2: float) -> float:
    diff = abs(h1 - h2)
    return min(diff, 360.0 - diff)

def _tinted_palette_mix(ui_rgb: Image.Image) -> Image.Image:
    # (Code remains identical to previous version)
    src_rgb = ui_rgb.convert("RGB")
    hsv = ui_rgb.convert("HSV")
    width, height = src_rgb.size
    out = Image.new("RGB", (width, height))
    src_pixels = src_rgb.load()
    hsv_pixels = hsv.load()
    out_pixels = out.load()

    for y in range(height):
        for x in range(width):
            r, g, b = src_pixels[x, y]
            hue_raw, sat, _ = hsv_pixels[x, y]
            if sat <= 1:
                base_index = nearest_palette_index((r, g, b))
                out_pixels[x, y] = EINK_PALETTE[base_index]
                continue
            hue = (hue_raw / 255.0) * 360.0

            base_index = min(
                _TINTED_HUE_TARGETS,
                key=lambda item: _angular_distance(hue, item[1]),
            )[0]

            base_color = EINK_PALETTE[base_index]
            base_error = (base_color[0] - r) ** 2 + (base_color[1] - g) ** 2 + (base_color[2] - b) ** 2

            best_candidate = base_index
            best_alpha = 1.0
            best_error = base_error

            for candidate in range(len(EINK_PALETTE)):
                if candidate == base_index:
                    continue

                alpha = mix_ratio((r, g, b), base_index, candidate)
                candidate_color = EINK_PALETTE[candidate]
                approx = (
                    int(round(alpha * base_color[0] + (1.0 - alpha) * candidate_color[0])),
                    int(round(alpha * base_color[1] + (1.0 - alpha) * candidate_color[1])),
                    int(round(alpha * base_color[2] + (1.0 - alpha) * candidate_color[2])),
                )
                error = (approx[0] - r) ** 2 + (approx[1] - g) ** 2 + (approx[2] - b) ** 2

                if error < best_error:
                    best_error = error
                    best_candidate = candidate
                    best_alpha = alpha

            threshold = (_BAYER_8X8[y & 7][x & 7] + 8) / 72.0
            choose_base = best_alpha >= threshold
            index = base_index if choose_base else best_candidate
            out_pixels[x, y] = EINK_PALETTE[index]

    return out


def composite_regional(src_rgb: Image.Image, settings: ProxySettings = SETTINGS) -> Image.Image:
    src_rgb = src_rgb.convert("RGB")
    
    # 1. Generate Masks
    # photo_mask here is the result of the new Texture Energy algorithm
    edge_mask, mid_gray_mask, flat_mask, photo_mask = build_masks(src_rgb, settings=settings)

    # 2. Generate Sharp UI Layer
    ui_enhanced = enhance_ui(src_rgb, settings=settings)
    sharp_base = quantize_palette_none(ui_enhanced)
    
    # 3. Detect "Bad Colors" (High Error Mask)
    # This fixes the purple background issue.
    # If the Sharp version is too different from Source, it means we don't have that ink.
    # Force Dither in these spots.
    diff = ImageChops.difference(src_rgb, sharp_base)
    diff_gray = diff.convert("L")
    # Threshold 45 is strict enough to allow Black/White matching but loose enough to catch Purple/Dark Blue
    high_error_mask = diff_gray.point(lambda p: 255 if p > 45 else 0) 
    high_error_mask = high_error_mask.filter(ImageFilter.MedianFilter(3))
    high_error_mask = high_error_mask.filter(ImageFilter.GaussianBlur(3))

    # 4. Apply Tinting to UI
    # (Keeps light pastel backgrounds looking solid instead of noisy)
    palette_mask = palette_fit_mask(ui_enhanced, sharp_base, settings=settings)
    tinted_ui = _tinted_flat_regions(ui_enhanced, flat_mask, settings=settings)
    tinted_ui = ImageChops.subtract(tinted_ui, edge_mask)
    
    # Mix the specialized tinted dithering into the sharp layer
    tinted_mix = _tinted_palette_mix(ui_enhanced)
    sharp_composite = Image.composite(tinted_mix, sharp_base, tinted_ui)

    # 5. Generate Photo/Dither Layer
    photo_base = enhance_photo(src_rgb, settings=settings) # Note: use src_rgb, not photo_src (deprecated)
    
    if settings.photo_mode == "fs":
        dithered_layer = quantize_palette_fs(photo_base)
    elif settings.photo_mode == "stucki":
        dithered_layer = stucki_error_diffusion(photo_base)
    elif settings.photo_mode == "ordered":
        dithered_layer = ordered_two_color(photo_base, flat_mask)
    else:
        # Default hybrid photo processing
        ordered = ordered_two_color(photo_base, flat_mask)
        stucki = stucki_error_diffusion(photo_base)
        dithered_layer = Image.composite(ordered, stucki, flat_mask)

    # 6. Final Composite Logic
    # Start with Dithered Layer (Photos/Backgrounds)
    final_out = dithered_layer.copy()
    
    # Decide where to put the Sharp UI
    # Logic: Show Sharp UI IF:
    #   1. It is an Edge (Text/Lines) ... AND NOT in a Photo (handled by clean_edges in masking.py)
    #   2. OR It matches the palette well (White background, solid Red blocks) ... AND NOT High Error (Purple)
    
    # "Safe to be sharp" mask:
    safe_palette_match = ImageChops.subtract(palette_mask, high_error_mask)
    
    # Combine Edges + Safe Solid Colors
    ui_region_mask = ImageChops.lighter(edge_mask, safe_palette_match)
    
    # Paste Sharp UI on top of Dithered Background
    final_out.paste(sharp_composite, mask=ui_region_mask)
    
    # 7. Final Safety: Force Photo Mask regions to be Dithered
    # (Just in case the edge mask bled into the photo)
    final_out.paste(dithered_layer, mask=photo_mask)

    return final_out
