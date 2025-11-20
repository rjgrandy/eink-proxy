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


def compute_texture_energy(gray_src: Image.Image, radius: int = 5) -> Image.Image:
    """
    Calculates local texture energy to distinguish Photos from Text.
    """
    edges = gray_src.filter(ImageFilter.FIND_EDGES)
    energy = edges.filter(ImageFilter.BoxBlur(radius))
    return energy


def build_masks(src_rgb: Image.Image, settings: ProxySettings = SETTINGS) -> Tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    gray = src_rgb.convert("L")
    
    # 1. Texture/Photo Detection
    texture_energy = compute_texture_energy(gray, radius=3)
    photo_mask = threshold_channel(texture_energy, settings.texture_density_threshold) 
    photo_mask = photo_mask.filter(ImageFilter.MaxFilter(3)) 
    photo_mask = photo_mask.filter(ImageFilter.GaussianBlur(2))

    # 2. Edge Detection
    edges = gray.filter(ImageFilter.FIND_EDGES)
    strong_edges = threshold_channel(edges, settings.edge_threshold)
    clean_edges = ImageChops.subtract(strong_edges, photo_mask)
    clean_edges = clean_edges.filter(ImageFilter.MinFilter(3))
    clean_edges = clean_edges.filter(ImageFilter.MaxFilter(3))
    edge_mask = clean_edges.filter(ImageFilter.GaussianBlur(settings.mask_blur))

    # 3. Flat Area Detection
    grad = edges.filter(ImageFilter.GaussianBlur(1))
    flat_raw = grad.point(lambda p: 255 if p < settings.sky_gradient_threshold else 0)
    flat = flat_raw.filter(ImageFilter.MaxFilter(5))
    flat = ImageChops.subtract(flat, clean_edges)

    # 4. Mid-Tone Detection
    hsv = src_rgb.convert("HSV")
    _, saturation, value = hsv.split()
    mid_l = ImageChops.subtract(
        threshold_channel(value, settings.mid_l_min),
        threshold_channel(value, settings.mid_l_max)
    )
    low_sat = threshold_channel(saturation, settings.mid_s_max, invert=True)
    mid_gray_mask = ImageChops.multiply(mid_l, low_sat)
    mid_gray_mask = ImageChops.subtract(mid_gray_mask, photo_mask)
    mid_gray_mask = mid_gray_mask.filter(ImageFilter.GaussianBlur(settings.mask_blur))

    return edge_mask, mid_gray_mask, flat, photo_mask