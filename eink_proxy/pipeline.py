from __future__ import annotations

from PIL import Image, ImageOps

from .dither import ordered_bw_halftone, ordered_two_color, stucki_error_diffusion
from .enhance import enhance_photo, enhance_ui
from .masking import build_masks
from .palette import PAL_IMG
from .config import SETTINGS


def quantize_palette_fs(img: Image.Image) -> Image.Image:
    return img.quantize(palette=PAL_IMG, dither=Image.FLOYDSTEINBERG).convert("RGB")


def quantize_palette_none(img: Image.Image) -> Image.Image:
    return img.quantize(palette=PAL_IMG, dither=Image.NONE).convert("RGB")


def composite_regional(src_rgb: Image.Image) -> Image.Image:
    edge_mask, mid_gray_mask, flat_mask, photo_src = build_masks(src_rgb)

    sharp = quantize_palette_none(enhance_ui(src_rgb))

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
    mix2 = Image.composite(photo, mix1, non_edge)
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
