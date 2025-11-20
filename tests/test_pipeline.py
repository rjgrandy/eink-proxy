from PIL import Image, ImageOps

from eink_proxy.processing.dither import ordered_bw_halftone
from eink_proxy.processing.masking import build_masks
from eink_proxy.processing.pipeline import composite_regional


def test_ordered_bw_halftone_returns_invertible_l_mode():
    src = Image.new("L", (4, 4), color=128)

    halftone = ordered_bw_halftone(src)

    assert halftone.mode == "L"
    # Ensure downstream callers relying on ImageOps.invert remain compatible.
    inverted = ImageOps.invert(halftone)
    assert inverted.getbbox() is not None


def test_composite_regional_accepts_rgba_source():
    rgba_source = Image.new("RGBA", (6, 6), color=(120, 140, 200, 180))

    result = composite_regional(rgba_source)

    assert result.mode == "RGB"
    assert result.size == rgba_source.size


def test_composite_regional_accepts_palette_source():
    palette_source = Image.new("P", (4, 4))

    result = composite_regional(palette_source)

    assert result.mode == "RGB"
    assert result.size == palette_source.size


def test_build_masks_return_l_mode_outputs():
    rgb_source = Image.new("RGB", (5, 5), color=(128, 140, 150))

    (
        edge_mask,
        mid_gray_mask,
        flat_mask,
        texture_mask,
        fine_detail_mask,
        photo_src,
    ) = build_masks(rgb_source)

    assert edge_mask.mode == "L"
    assert mid_gray_mask.mode == "L"
    assert flat_mask.mode == "L"
    assert texture_mask.mode == "L"
    assert fine_detail_mask.mode == "L"
    assert photo_src.mode == "RGB"
