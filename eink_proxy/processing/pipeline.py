from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter, ImageOps

from .dither import ordered_bw_halftone, ordered_two_color, stucki_error_diffusion
from .enhance import enhance_photo, enhance_ui
from .masking import build_masks
from .palette import PAL_IMG, nearest_palette_index, palette_fit_mask
from ..config import EINK_PALETTE, SETTINGS


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
    edge_mask, mid_gray_mask, flat_mask, photo_src = build_masks(src_rgb)

    ui_enhanced = enhance_ui(src_rgb)
    sharp = quantize_palette_none(ui_enhanced)
    palette_mask = palette_fit_mask(ui_enhanced, sharp)
    tinted_ui = _tinted_flat_regions(ui_enhanced, flat_mask)
    tinted_ui = ImageChops.subtract(tinted_ui, edge_mask)
    palette_mask = ImageChops.lighter(palette_mask, tinted_ui)

    tinted_mix = ordered_two_color(ui_enhanced, flat_mask)
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
    mix2 = Image.composite(photo, mix1, photo_mask)
    return Image.composite(sharp, mix2, edge_mask)


def build_debug_overlay(src: Image.Image) -> Image.Image:
    edge_mask, mid_gray_mask, flat_mask, _ = build_masks(src)
    base = composite_regional(src)
    red = Image.new("RGB", src.size, (255, 0, 0))
    green = Image.new("RGB", src.size, (0, 255, 0))
    blue = Image.new("RGB", src.size, (0, 0, 255))
    overlay = base.copy()
    overlay = Image.composite(red, overlay, edge_mask)
    overlay = Image.composite(green, overlay, mid_gray_mask)
    overlay = Image.composite(blue, overlay, flat_mask)
    return overlay
