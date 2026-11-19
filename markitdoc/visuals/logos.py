import math
import tempfile
import zlib
from pathlib import Path

from PIL import Image, ImageChops

TRIM_TOLERANCE = 12
SMALLEST_LOGO_SCALE = 0.6


# the logo without its transparent or near-white margins, saved once in the temporary folder
def trimmed_logo(path):
    path = Path(path)
    key = f"{path.resolve()}|{path.stat().st_mtime_ns}".encode()
    target = Path(tempfile.gettempdir()) / "markitdoc-logos" / f"{path.stem}-{zlib.crc32(key):08x}.png"
    if target.is_file():
        return target
    with Image.open(path) as picture:
        picture = picture.convert("RGBA")
        solid = picture.getchannel("A").point(lambda alpha: 255 if alpha > TRIM_TOLERANCE else 0)
        ink = ImageChops.difference(picture.convert("RGB"), Image.new("RGB", picture.size, "white")).convert("L")
        box = ImageChops.multiply(solid, ink.point(lambda level: 255 if level > TRIM_TOLERANCE else 0)).getbbox()
        target.parent.mkdir(parents=True, exist_ok=True)
        (picture.crop(box) if box else picture).save(target)
    return target


# the width-to-height ratio of a logo file
def logo_ratio(path):
    with Image.open(path) as picture:
        return picture.width / picture.height


# the drawn size of a logo filling as much of a width by height box as its shape allows
def logo_box(path, width, height):
    ratio = logo_ratio(path)
    drawn = min(width, height * ratio)
    return drawn, drawn / ratio


# places logos of any shape and number in rows across width: equal visual weight, shrunk to fit and wrapped onto more rows
# rather than dropped; returns (x, y, width, height) for each logo, measured from the top left of the area
def logo_row(ratios, width, height, gap):
    for rows in range(1, len(ratios) + 1):
        per_row = math.ceil(len(ratios) / rows)
        row_height = (height - gap * (rows - 1)) / rows
        placed = []
        for row in range(rows):
            chunk = ratios[row * per_row:(row + 1) * per_row]
            sizes = [(ratio * row_height * min(1, 1 / math.sqrt(ratio)), row_height * min(1, 1 / math.sqrt(ratio))) for ratio in chunk]
            total = sum(size[0] for size in sizes) + gap * (len(sizes) - 1)
            scale = min(1.0, width / total) if total else 1.0
            if scale < SMALLEST_LOGO_SCALE and per_row > 1:
                break
            x, top = 0.0, row * (row_height + gap)
            for drawn_width, drawn_height in sizes:
                placed.append((x, top + (row_height - drawn_height * scale) / 2, drawn_width * scale, drawn_height * scale))
                x += drawn_width * scale + gap
        if len(placed) == len(ratios):
            return placed
    return []
