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
    Photos have high energy density (lots of edges nearby).
    Text has high edge contrast but low energy density (sparse).
    """
    # 1. Find Edges
    edges = gray_src.filter(ImageFilter.FIND_EDGES)
    
    # 2. Spread the energy (Box Blur)
    # If an area is dense with edges (photo), the average remains high.
    # If an area is sparse (text), the average drops significantly.
    energy = edges.filter(ImageFilter.BoxBlur(radius))
    
    return energy


def build_masks(src_rgb: Image.Image, settings: ProxySettings = SETTINGS) -> Tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    gray = src_rgb.convert("L")
    
    # --- 1. Texture/Photo Detection (The "Energy" Algorithm) ---
    # We use a lower threshold here. If local energy > 8 (out of 255), it's likely a photo.
    texture_energy = compute_texture_energy(gray, radius=3)
    
    # Create the Photo Mask
    # We clamp it to remove noise, then expand it slightly (MaxFilter) to cover the whole photo
    photo_mask = threshold_channel(texture_energy, settings.texture_density_threshold) # Default ~10-12
    photo_mask = photo_mask.filter(ImageFilter.MaxFilter(3)) 
    photo_mask = photo_mask.filter(ImageFilter.GaussianBlur(2))

    # --- 2. Edge Detection (UI Lines/Text) ---
    edges = gray.filter(ImageFilter.FIND_EDGES)
    strong_edges = threshold_channel(edges, settings.edge_threshold)
    
    # CRITICAL: Remove Photo regions from the Edge Mask.
    # This ensures the photo is handled by the Dither engine, not the Sharp engine.
    clean_edges = ImageChops.subtract(strong_edges, photo_mask)
    
    # Cleanup: Remove stray "dust" pixels (Despeckle logic)
    clean_edges = clean_edges.filter(ImageFilter.MinFilter(3)) # Erode single pixels
    clean_edges = clean_edges.filter(ImageFilter.MaxFilter(3)) # Dilate back
    
    edge_mask = clean_edges.filter(ImageFilter.GaussianBlur(settings.mask_blur))

    # --- 3. Flat Area / Background Detection ---
    # We want solid blocks of color to be "Flat"
    
    # Find areas with very little gradient
    grad = edges.filter(ImageFilter.GaussianBlur(1))
    flat_raw = grad.point(lambda p: 255 if p < settings.sky_gradient_threshold else 0)
    
    # UNIFORMITY FIX: Dilate (Expand) the flat area.
    # This makes the solid color "grow" into the text edges slightly, 
    # preventing the dither pattern from bleeding in between the text and the background.
    flat = flat_raw.filter(ImageFilter.MaxFilter(5))
    
    # But don't let it overwrite the text itself
    flat = ImageChops.subtract(flat, clean_edges)

    # --- 4. Mid-Tone / Shadow Detection ---
    # (Used for standardizing UI shadows)
    hsv = src_rgb.convert("HSV")
    _, saturation, value = hsv.split()
    
    # Bandpass filter for mid-gray
    mid_l = ImageChops.subtract(
        threshold_channel(value, settings.mid_l_min),
        threshold_channel(value, settings.mid_l_max)
    )
    # Must be low saturation (gray)
    low_sat = threshold_channel(saturation, settings.mid_s_max, invert=True)
    
    mid_gray_mask = ImageChops.multiply(mid_l, low_sat)
    mid_gray_mask = ImageChops.subtract(mid_gray_mask, photo_mask) # Don't flatten grays in photos
    mid_gray_mask = mid_gray_mask.filter(ImageFilter.GaussianBlur(settings.mask_blur))

    return edge_mask, mid_gray_mask, flat, photo_mask
