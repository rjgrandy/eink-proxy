from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..config import SETTINGS, ProxySettings


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


def build_masks(src_rgb: Image.Image, settings: ProxySettings = SETTINGS) -> Tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    gray = src_rgb.convert("L")
    
    # 1. Edge Detection
    edges = gray.filter(ImageFilter.FIND_EDGES)
    
    # 2. Texture Density (Fix for embedded photos)
    edge_density = edges.filter(ImageFilter.BoxBlur(3))
    texture_thr = max(5, settings.texture_density_threshold - 2)
    texture_mask = edge_density.point(lambda p: 255 if p > texture_thr else 0)
    texture_mask = texture_mask.filter(ImageFilter.MaxFilter(3))

    # 3. Refine Edge Mask
    strong_edges = edges.point(lambda p: 255 if p >= settings.edge_threshold else 0)
    clean_edges = ImageChops.subtract(strong_edges, texture_mask)
    edge_mask = clean_edges.filter(
        ImageFilter.GaussianBlur(settings.mask_blur)
    )

    hsv = src_rgb.convert("HSV")
    _, saturation, value = hsv.split()
    mid_l = bandpass_mask_luma(value, settings.mid_l_min, settings.mid_l_max)
    low_sat = threshold_channel(saturation, settings.mid_s_max, invert=True)
    
    mid_gray_mask_base = ImageChops.multiply(mid_l, low_sat)
    mid_gray_mask = ImageChops.subtract(mid_gray_mask_base, texture_mask).filter(
        ImageFilter.GaussianBlur(settings.mask_blur)
    )

    grad = edges.filter(ImageFilter.GaussianBlur(1))
    flat = grad.point(lambda p: 255 if p < settings.sky_gradient_threshold else 0)
    
    if settings.smooth_strength > 0:
        kernel = 3 if settings.smooth_strength == 1 else 5
        smooth = src_rgb.filter(ImageFilter.MedianFilter(kernel))
        src_smoothed = Image.composite(smooth, src_rgb, flat)
    else:
        src_smoothed = src_rgb

    return edge_mask, mid_gray_mask, flat, src_smoothed
