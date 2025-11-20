from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter, ImageOps

from .dither import ordered_bw_halftone, ordered_two_color, stucki_error_diffusion
from .enhance import enhance_photo, enhance_ui
from .masking import build_masks
from .palette import PAL_IMG, mix_ratio, nearest_palette_index, palette_fit_mask
from ..config import EINK_PALETTE, SETTINGS


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
    (2, 0.0),  # red ink
    (5, 60.0),  # yellow ink
    (3, 120.0),  # green ink
    (4, 240.0),  # blue ink
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


def _tinted_flat_regions(ui_rgb: Image.Image, flat_mask: Image.Image) -> Image.Image:
    hsv = ui_rgb.convert("HSV")
    _, saturation, value = hsv.split()

    sat_mask = saturation.point(
        lambda s: 255 if s >= SETTINGS.ui_tint_saturation else 0
    )
    bright_mask = value.point(lambda v: 255 if v >= SETTINGS.ui_tint_min_value else 0)
    tinted = ImageChops.multiply(sat_mask, bright_mask)
    tinted = ImageChops.multiply(tinted, flat_mask)
    tinted = tinted.filter(ImageFilter.MaxFilter(3))
    tinted = tinted.filter(ImageFilter.GaussianBlur(radius=1))
    return tinted.point(lambda p: 255 if p >= 32 else 0)


def composite_regional(src_rgb: Image.Image) -> Image.Image:
    edge_mask, mid_gray_mask, flat_mask, texture_mask, photo_src = build_masks(src_rgb)

    ui_enhanced = enhance_ui(src_rgb)
    sharp = quantize_palette_none(ui_enhanced)
    palette_mask = palette_fit_mask(ui_enhanced, sharp)
    tinted_ui = _tinted_flat_regions(ui_enhanced, flat_mask)
    tinted_ui = ImageChops.subtract(tinted_ui, edge_mask)
    palette_mask = ImageChops.lighter(palette_mask, tinted_ui)

    tinted_mix = _tinted_palette_mix(ui_enhanced)
    sharp = Image.composite(tinted_mix, sharp, tinted_ui)

    bw = ordered_bw_halftone(src_rgb)
    halftone = Image.new("RGB", bw.size, (255, 255, 255))
    halftone.paste((0, 0, 0), mask=ImageOps.invert(bw))

    photo_base = enhance_photo(photo_src)
    if SETTINGS.photo_mode == "fs":
        photo = quantize_palette_fs(photo_base)
    elif SETTINGS.photo_mode == "stucki":
        photo = stucki_error_diffusion(photo_base)
    elif SETTINGS.photo_mode == "ordered":
        photo = ordered_two_color(photo_base, flat_mask)
    else:
        ordered_img = ordered_two_color(photo_base, flat_mask)
        stucki_img = stucki_error_diffusion(photo_base)
        photo = Image.composite(ordered_img, stucki_img, flat_mask)

    mix1 = Image.composite(halftone, sharp, mid_gray_mask)
    non_edge = ImageOps.invert(edge_mask)
    photo_mask = ImageChops.multiply(non_edge, ImageOps.invert(palette_mask))
    texture_photo_mask = ImageChops.multiply(non_edge, texture_mask)
    photo_mask = ImageChops.lighter(photo_mask, texture_photo_mask)
    mix2 = Image.composite(photo, mix1, photo_mask)
    return Image.composite(sharp, mix2, edge_mask)


def build_debug_overlay(src: Image.Image) -> Image.Image:
    edge_mask, mid_gray_mask, flat_mask, texture_mask, _ = build_masks(src)
    base = composite_regional(src)
    red = Image.new("RGB", src.size, (255, 0, 0))
    green = Image.new("RGB", src.size, (0, 255, 0))
    blue = Image.new("RGB", src.size, (0, 0, 255))
    magenta = Image.new("RGB", src.size, (255, 0, 255))
    overlay = base.copy()
    overlay = Image.composite(red, overlay, edge_mask)
    overlay = Image.composite(green, overlay, mid_gray_mask)
    overlay = Image.composite(blue, overlay, flat_mask)
    overlay = Image.composite(magenta, overlay, texture_mask)
    return overlay


def _angular_distance(h1: float, h2: float) -> float:
    """Return the circular distance between two hue angles in degrees."""

    diff = abs(h1 - h2)
    return min(diff, 360.0 - diff)


def _tinted_palette_mix(ui_rgb: Image.Image) -> Image.Image:
    """Generate a two-color ordered dither that preserves tint hues."""

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
                # Extremely low saturation can yield unstable hues; fall back to direct mapping.
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

