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
    
    # 1. Edge Detection
    edges = gray.filter(ImageFilter.FIND_EDGES)

    # 2. Texture Density Calculation
    # Calculate local edge density to identify complex textures (photos/images)
    edge_density = edges.filter(ImageFilter.BoxBlur(4))
    texture_mask = edge_density.point(lambda p: 255 if p > SETTINGS.texture_density_threshold else 0)
    texture_mask = texture_mask.filter(ImageFilter.MaxFilter(3))  # Expand slightly to cover edges

    # 3. Refine Edge Mask (UI Lines)
    strong_edges = edges.point(lambda p: 255 if p >= SETTINGS.edge_threshold else 0)
    # Subtract texture regions from the edge mask so they fall through to the dither path
    clean_edges = ImageChops.subtract(strong_edges, texture_mask)
    
    edge_mask = clean_edges.filter(
        ImageFilter.GaussianBlur(SETTINGS.mask_blur)
    )

    hsv = src_rgb.convert("HSV")
    _, saturation, value = hsv.split()
    mid_l = bandpass_mask_luma(value, SETTINGS.mid_l_min, SETTINGS.mid_l_max)
    low_sat = threshold_channel(saturation, SETTINGS.mid_s_max, invert=True)
    
    # 4. Refine Mid-tone Mask
    mid_gray_mask_base = ImageChops.multiply(mid_l, low_sat)
    # Ensure mid-tones inside photos don't get flattened
    mid_gray_mask = ImageChops.subtract(mid_gray_mask_base, texture_mask).filter(
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
