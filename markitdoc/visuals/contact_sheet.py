from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from markitdoc.utils.constants import ASSETS_FOLDER

MAX_THUMBNAILS = 6
COLUMNS = 3
THUMB_WIDTH, THUMB_HEIGHT = 270, 320
GAP, LABEL_HEIGHT = 12, 24


# makes a numbered PNG contact sheet from a rendered PDF, prioritising the cover and requested pages
def contact_sheet(pdf_path, output, pages=()):
    output = Path(output)
    if output.resolve() == Path(pdf_path).resolve():
        raise ValueError("The sheet must have a different path from the rendered PDF")
    with pymupdf.open(pdf_path) as pdf:
        if not len(pdf):
            raise ValueError("The PDF has no pages")
        priority = [1, *(page for page in pages if type(page) is int and 1 <= page <= len(pdf))]
        sample = [1 + round(index * (len(pdf) - 1) / (MAX_THUMBNAILS - 1)) for index in range(MAX_THUMBNAILS)]
        selected = sorted(list(dict.fromkeys(priority + sample))[:MAX_THUMBNAILS])
        thumbs = []
        for number in selected:
            page = pdf[number - 1]
            scale = min(THUMB_WIDTH / page.rect.width, THUMB_HEIGHT / page.rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False, annots=False)
            thumbs.append((number, Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)))
    columns = min(COLUMNS, len(thumbs))
    rows = [thumbs[start:start + columns] for start in range(0, len(thumbs), columns)]
    heights = [max(thumb.height for _, thumb in row) + LABEL_HEIGHT + GAP for row in rows]
    sheet = Image.new("RGB", (columns * (THUMB_WIDTH + GAP) + GAP, sum(heights) + GAP), "#e7ebef")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ASSETS_FOLDER / "fonts" / "Inter-Bold.ttf"), 14)
    y = GAP
    for row, height in zip(rows, heights):
        for column, (number, thumb) in enumerate(row):
            x = GAP + column * (THUMB_WIDTH + GAP)
            draw.text((x, y), f"Page {number}", fill="#243044", font=font)
            sheet.paste(thumb, (x + (THUMB_WIDTH - thumb.width) // 2, y + LABEL_HEIGHT))
        y += height
    sheet.save(output, "PNG")
    return output
