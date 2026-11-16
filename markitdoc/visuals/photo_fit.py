import zlib
from pathlib import Path

import numpy
from PIL import Image, ImageFilter, ImageOps

from markitdoc.utils.helpers import lifted


# finds the crop with the most visual detail at the target shape
def interest_box(picture, target):
    small = picture.copy()
    small.thumbnail((160, 160))
    scale = picture.width / small.width
    edges = numpy.asarray(small.convert("L").filter(ImageFilter.FIND_EDGES), dtype=float)
    saturation = numpy.asarray(small.convert("HSV"), dtype=float)[:, :, 1]
    interest = edges + 0.5 * saturation
    rows, columns = interest.shape
    if columns / rows > target:
        window_height, window_width = rows, max(1, int(rows * target))
    else:
        window_width, window_height = columns, max(1, int(columns / target))
    summed = numpy.pad(interest.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best, best_score = (0, 0), -1.0
    for top in range(0, rows - window_height + 1, max(1, (rows - window_height) // 24 or 1)):
        for left in range(0, columns - window_width + 1, max(1, (columns - window_width) // 24 or 1)):
            total = (summed[top + window_height, left + window_width] - summed[top, left + window_width]
                     - summed[top + window_height, left] + summed[top, left])
            centre = abs((left + window_width / 2) / columns - 0.5) + abs((top + window_height / 2) / rows - 0.45)
            score = total * (1 - 0.35 * centre)
            if score > best_score:
                best, best_score = (top, left), score
    top, left = best
    box_width, box_height = window_width * scale, window_height * scale
    return (int(left * scale), int(top * scale), int(min(picture.width, left * scale + box_width)),
            int(min(picture.height, top * scale + box_height)))


# applies the requested photo treatment after adjusting contrast
def treated(picture, treatment, theme):
    picture = ImageOps.autocontrast(picture, cutoff=1)
    if treatment == "mono":
        return ImageOps.grayscale(picture).convert("RGB")
    if treatment == "duotone" and theme is not None:
        return ImageOps.colorize(ImageOps.grayscale(picture), black=theme.rgb("night"), white=lifted(theme.rgb("paper"), 0.2))
    return picture


# crops, treats, fades, and saves an image at the requested size
def fitted_image(path: Path, width, height, work_folder: Path, fades=(), treatment="natural", theme=None):
    picture = Image.open(path).convert("RGB")
    picture = treated(picture.crop(interest_box(picture, width / height)), treatment, theme)
    for top_ratio, bottom_ratio, start, end, rgb in fades:
        mask = Image.new("L", (1, picture.height), 0)
        first, last = int(picture.height * top_ratio), int(picture.height * bottom_ratio)
        for row in range(first, last):
            mask.putpixel((0, row), int(255 * (start + (end - start) * (row - first) / max(1, last - first - 1))))
        picture = Image.composite(Image.new("RGB", picture.size, rgb), picture, mask.resize(picture.size))
    output = work_folder / f"{path.stem}_{int(width)}x{int(height)}_{zlib.crc32(repr(fades).encode()):08x}_{treatment}.jpg"
    picture.save(output, "JPEG", quality=88)
    return str(output)
