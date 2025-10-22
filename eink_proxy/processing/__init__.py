"""Image processing pipeline components for the E-ink proxy."""

from .dither import ordered_bw_halftone, ordered_two_color, stucki_error_diffusion
from .enhance import enhance_photo, enhance_ui
from .masking import build_masks
from .palette import PAL_IMG, mix_ratio, nearest_palette_index, nearest_two_palette
from .pipeline import (
    build_debug_overlay,
    composite_regional,
    quantize_palette_fs,
    quantize_palette_none,
)

__all__ = [
    "ordered_bw_halftone",
    "ordered_two_color",
    "stucki_error_diffusion",
    "enhance_photo",
    "enhance_ui",
    "build_masks",
    "PAL_IMG",
    "mix_ratio",
    "nearest_palette_index",
    "nearest_two_palette",
    "build_debug_overlay",
    "composite_regional",
    "quantize_palette_fs",
    "quantize_palette_none",
]
