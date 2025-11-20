from __future__ import annotations

from PIL import Image

from .palette import EINK_PALETTE, mix_ratio, nearest_palette_index, nearest_two_palette


def ordered_bw_halftone(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    bm8 = [
        [0, 48, 12, 60, 3, 51, 15, 63],
        [32, 16, 44, 28, 35, 19, 47, 31],
        [8, 56, 4, 52, 11, 59, 7, 55],
        [40, 24, 36, 20, 43, 27, 39, 23],
        [2, 50, 14, 62, 1, 49, 13, 61],
        [34, 18, 46, 30, 33, 17, 45, 29],
        [10, 58, 6, 54, 9, 57, 5, 53],
        [42, 26, 38, 22, 41, 25, 37, 21],
    ]
    threshold_table = [[int((value + 0.5) * 4) for value in row] for row in bm8]
    width, height = img.size
    src = img.load()
    out = Image.new("L", (width, height))
    dst = out.load()
    for y in range(height):
        for x in range(width):
            dst[x, y] = 255 if src[x, y] > threshold_table[y % 8][x % 8] else 0

    # ``ImageOps.invert`` only accepts "L"/"RGB" modes. Returning an "L" image keeps
    # the downstream compositing flow compatible while preserving the binary mask
    # semantics of the halftone output.
    return out


def stucki_error_diffusion(img: Image.Image) -> Image.Image:
    width, height = img.size
    src = img.convert("RGB")
    pixels = src.load()
    out = Image.new("RGB", (width, height))
    out_pixels = out.load()

    kernel1 = [2, 4, 8, 4, 2]
    kernel2 = [1, 2, 4, 2, 1]

    def add_error(x: int, y: int, error, flip: bool) -> None:
        for dx in range(-2, 3):
            nx = x + dx if not flip else x - dx
            if nx < 0 or nx >= width:
                continue
            for offset, kernel, weight in ((1, kernel1, 42.0), (2, kernel2, 42.0)):
                ny = y + offset
                if ny >= height:
                    continue
                factor = kernel[dx + 2] / weight
                r = min(255, max(0, pixels[nx, ny][0] + int(error[0] * factor)))
                g = min(255, max(0, pixels[nx, ny][1] + int(error[1] * factor)))
                b = min(255, max(0, pixels[nx, ny][2] + int(error[2] * factor)))
                pixels[nx, ny] = (r, g, b)

    for y in range(height):
        flip = y % 2 == 1
        x_range = range(width - 1, -1, -1) if flip else range(width)
        for x in x_range:
            old = pixels[x, y]
            index = nearest_palette_index(old)
            new = EINK_PALETTE[index]
            out_pixels[x, y] = new
            error = (old[0] - new[0], old[1] - new[1], old[2] - new[2])
            add_error(x, y, error, flip)

    return out


def ordered_two_color(img: Image.Image, grad_mask: Image.Image) -> Image.Image:
    width, height = img.size
    src = img.convert("RGB")
    bayer = [
        [0, 48, 12, 60, 3, 51, 15, 63],
        [32, 16, 44, 28, 35, 19, 47, 31],
        [8, 56, 4, 52, 11, 59, 7, 55],
        [40, 24, 36, 20, 43, 27, 39, 23],
        [2, 50, 14, 62, 1, 49, 13, 61],
        [34, 18, 46, 30, 33, 17, 45, 29],
        [10, 58, 6, 54, 9, 57, 5, 53],
        [42, 26, 38, 22, 41, 25, 37, 21],
    ]
    out = Image.new("RGB", (width, height))
    out_pixels = out.load()
    src_pixels = src.load()
    for y in range(height):
        for x in range(width):
            color_a, color_b = nearest_two_palette(src_pixels[x, y])
            alpha = mix_ratio(src_pixels[x, y], color_a, color_b)
            threshold = (bayer[y & 7][x & 7] + 8) / 72.0
            choose_a = alpha >= threshold
            out_pixels[x, y] = EINK_PALETTE[color_a if choose_a else color_b]
    return out
