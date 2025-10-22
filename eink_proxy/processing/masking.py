from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..config import SETTINGS


def threshold_channel(channel: Image.Image, threshold: int, invert: bool = False) -> Image.Image:
    lut = [255 if value >= threshold else 0 for value in range(256)]
    mask = channel.point(lut)
    if invert:
        mask = ImageOps.invert(mask)
    return mask


def bandpass_mask_luma(luma: Image.Image, lo: int, hi: int) -> Image.Image:
    low = threshold_channel(luma, lo)
    high = threshold_channel(luma, hi)
    return ImageChops.subtract(low, high)


def build_masks(src_rgb: Image.Image) -> Tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    gray = src_rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mask = edges.point(lambda p: 255 if p >= SETTINGS.edge_threshold else 0).filter(
        ImageFilter.GaussianBlur(SETTINGS.mask_blur)
    )

    hsv = src_rgb.convert("HSV")
    _, saturation, value = hsv.split()
    mid_l = bandpass_mask_luma(value, SETTINGS.mid_l_min, SETTINGS.mid_l_max)
    low_sat = threshold_channel(saturation, SETTINGS.mid_s_max, invert=True)
    mid_gray_mask = ImageChops.multiply(mid_l, low_sat).filter(
        ImageFilter.GaussianBlur(SETTINGS.mask_blur)
    )

    grad = edges.filter(ImageFilter.GaussianBlur(1))
    flat = grad.point(lambda p: 255 if p < SETTINGS.sky_gradient_threshold else 0)
    if SETTINGS.smooth_strength > 0:
        kernel = 3 if SETTINGS.smooth_strength == 1 else 5
        smooth = src_rgb.filter(ImageFilter.MedianFilter(kernel))
        src_smoothed = Image.composite(smooth, src_rgb, flat)
    else:
        src_smoothed = src_rgb

    return edge_mask, mid_gray_mask, flat, src_smoothed
