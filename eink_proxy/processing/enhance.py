from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter

from ..config import SETTINGS


def apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    if abs(gamma - 1.0) < 1e-3:
        return img
    inv = 1.0 / gamma
    lut = [
        min(255, max(0, int(((value / 255.0) ** inv) * 255 + 0.5)))
        for value in range(256)
    ]
    return img.point(lut * 3)


def enhance_ui(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(SETTINGS.contrast)
    img = ImageEnhance.Color(img).enhance(SETTINGS.saturation)
    img = apply_gamma(img, SETTINGS.gamma)
    img = ImageEnhance.Sharpness(img).enhance(SETTINGS.sharpness_ui)
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))


def enhance_photo(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(SETTINGS.contrast)
    img = ImageEnhance.Color(img).enhance(SETTINGS.saturation)
    img = apply_gamma(img, SETTINGS.gamma)
    return img
