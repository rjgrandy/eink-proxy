from __future__ import annotations

from typing import Tuple

from PIL import Image

from ..config import EINK_PALETTE


def palette_image() -> Image.Image:
    palette = Image.new("P", (16, 16))
    flat: Tuple[int, ...] = tuple(channel for rgb in EINK_PALETTE for channel in rgb)
    padded = flat + (0,) * (768 - len(flat))
    palette.putpalette(padded)
    return palette


PAL_IMG = palette_image()


def nearest_palette_index(rgb: Tuple[int, int, int]) -> int:
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
    r, g, b = rgb

    # Neutral colors (very low saturation) look incorrect when they are dithered with
    # saturated inks such as orange. Prefer mixing black and white instead to produce a
    # visually neutral halftone.
    max_channel = max(r, g, b)
    min_channel = min(r, g, b)
    if max_channel - min_channel <= max(12, int(0.1 * max_channel)):
        return 0, 1  # black and white

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
