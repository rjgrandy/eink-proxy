from PIL import Image, ImageOps

from eink_proxy.processing.dither import ordered_bw_halftone
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
