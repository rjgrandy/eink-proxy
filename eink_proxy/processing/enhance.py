from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..config import SETTINGS, ProxySettings


def apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    if abs(gamma - 1.0) < 1e-3:
        return img
    inv = 1.0 / gamma
    lut = [
        min(255, max(0, int(((value / 255.0) ** inv) * 255 + 0.5)))
        for value in range(256)
    ]
    return img.point(lut * 3)


def darken_lines(img: Image.Image) -> Image.Image:
    """
    Morphological operation to thicken and darken fine lines.
    This helps graph axes survive the nearest-neighbor quantization.
    """
    # Convert to grayscale, invert so lines are white
    gray = ImageOps.invert(img.convert("L"))
    
    # "Dilate" expands white areas (which are our dark lines)
    # A 3x3 MaxFilter is a slight dilation
    thickened = gray.filter(ImageFilter.MaxFilter(3))
    
    # Invert back. Now lines are thicker/darker.
    thickened = ImageOps.invert(thickened)
    
    # We only want to apply this to things that were already somewhat dark.
    # Blend it back into the original RGB image using the darkened version as the luminance target.
    # Ideally, we just multiply or composite. Simple multiply works well to darken.
    thickened_rgb = thickened.convert("RGB")
    return ImageChops.multiply(img, thickened_rgb)


def enhance_ui(img: Image.Image, settings: ProxySettings = SETTINGS) -> Image.Image:
    # 1. Pre-process: Darken faint lines (Graph fix)
    img = darken_lines(img)

    # 2. Standard Enhance
    img = ImageEnhance.Contrast(img).enhance(settings.contrast)
    img = ImageEnhance.Color(img).enhance(settings.saturation)
    img = apply_gamma(img, settings.gamma)
    
    # 3. Heavy Sharpness for UI
    img = ImageEnhance.Sharpness(img).enhance(settings.sharpness_ui)
    
    # 4. Unsharp Mask to pop edges
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))


def enhance_photo(img: Image.Image, settings: ProxySettings = SETTINGS) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(settings.contrast)
    img = ImageEnhance.Color(img).enhance(settings.saturation)
    img = apply_gamma(img, settings.gamma)
    # Minor sharpening for photos, but less than UI
    img = ImageEnhance.Sharpness(img).enhance(1.2)
    return img
