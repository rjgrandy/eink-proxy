from __future__ import annotations

from typing import Tuple

from PIL import Image

from ..config import EINK_PALETTE, SETTINGS


def palette_image() -> Image.Image:
    palette = Image.new("P", (16, 16))
    flat: Tuple[int, ...] = tuple(channel for rgb in EINK_PALETTE for channel in rgb)
    padded = flat + (0,) * (768 - len(flat))
    palette.putpalette(padded)
    return palette


PAL_IMG = palette_image()


def _is_neutral(rgb: Tuple[int, int, int]) -> bool:
    r, g, b = rgb
    max_channel = max(r, g, b)
    min_channel = min(r, g, b)
    return max_channel - min_channel <= max(12, int(0.1 * max_channel))


def _nearest_bw(rgb: Tuple[int, int, int]) -> int:
    r, g, b = rgb
    # Choose the ink that keeps neutral UI elements visible. Thin gridlines and
    # separators are typically drawn as medium grays; map those to black so they
    # remain legible, while still allowing very light grays to stay white.
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 0 if luminance <= 200 else 1
    black_distance = rgb[0] ** 2 + rgb[1] ** 2 + rgb[2] ** 2
    white_distance = (255 - rgb[0]) ** 2 + (255 - rgb[1]) ** 2 + (255 - rgb[2]) ** 2
    return 0 if black_distance < white_distance else 1


def nearest_palette_index(rgb: Tuple[int, int, int]) -> int:
    if _is_neutral(rgb):
        return _nearest_bw(rgb)

    best_index = 0
    best_distance = float("inf")
    r, g, b = rgb
    for index, (R, G, B) in enumerate(EINK_PALETTE):
        distance = (R - r) ** 2 + (G - g) ** 2 + (B - b) ** 2
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def nearest_two_palette(rgb: Tuple[int, int, int]) -> Tuple[int, int]:
    if _is_neutral(rgb):
        return 0, 1  # black and white

    r, g, b = rgb
    best = [(float("inf"), -1), (float("inf"), -1)]
    for index, (R, G, B) in enumerate(EINK_PALETTE):
        distance = (R - r) ** 2 + (G - g) ** 2 + (B - b) ** 2
        if distance < best[0][0]:
            best[1] = best[0]
            best[0] = (distance, index)
        elif distance < best[1][0]:
            best[1] = (distance, index)
    return best[0][1], best[1][1]


def mix_ratio(rgb: Tuple[int, int, int], color_a_index: int, color_b_index: int) -> float:
    color_a = EINK_PALETTE[color_a_index]
    color_b = EINK_PALETTE[color_b_index]
    numerator = 0.0
    denominator = 1e-6
    for channel in range(3):
        xa = color_a[channel]
        xb = color_b[channel]
        y = rgb[channel]
        numerator += (xa - xb) * (y - xb)
        denominator += (xa - xb) ** 2
    alpha = max(0.0, min(1.0, numerator / denominator))
    return alpha


def palette_fit_mask(src: Image.Image, quantized: Image.Image, threshold: int | None = None) -> Image.Image:
    """Return a mask highlighting pixels that closely match their quantized color.

    Pixels whose squared Euclidean distance between the source and quantized
    colors is below ``threshold`` are marked as 255 in the returned ``L`` mode
    mask. These regions represent areas where the source already aligns well
    with the hardware palette and therefore benefit from direct color mapping.
    """

    distance_threshold = SETTINGS.ui_palette_threshold if threshold is None else threshold
    src_rgb = src.convert("RGB")
    quant_rgb = quantized.convert("RGB")
    width, height = src_rgb.size
    mask = Image.new("L", src_rgb.size, 0)
    src_pixels = src_rgb.load()
    quant_pixels = quant_rgb.load()
    mask_pixels = mask.load()

    for y in range(height):
        for x in range(width):
            r1, g1, b1 = src_pixels[x, y]
            r2, g2, b2 = quant_pixels[x, y]
            distance = (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2
            if distance <= distance_threshold:
                mask_pixels[x, y] = 255

    return mask
