import pymupdf
import pytest
from PIL import Image

from markitdoc import contact_sheet
from markitdoc.visuals.contact_sheet import GAP, LABEL_HEIGHT, THUMB_WIDTH


def test_contact_sheet_includes_cover_and_requested_page_within_its_page_cap(tmp_path):
    pdf_path = tmp_path / "pages.pdf"
    with pymupdf.open() as pdf:
        for number in range(1, 11):
            page = pdf.new_page(width=320, height=320)
            page.draw_rect(page.rect, fill=((1, 0, 0) if number == 3 else (0, 0, 1) if number == 1 else (1, 1, 1)))
        pdf.save(pdf_path)

    path = contact_sheet(pdf_path, tmp_path / "sheet.png", pages=[3, 3, 80, 0])
    with Image.open(path) as sheet:
        assert sheet.size == (3 * (THUMB_WIDTH + GAP) + GAP, 2 * (THUMB_WIDTH + LABEL_HEIGHT + GAP) + GAP)
        assert sheet.getpixel((GAP + 50, GAP + LABEL_HEIGHT + 50)) == (0, 0, 255)
        assert sheet.getpixel((2 * GAP + THUMB_WIDTH + 50, GAP + LABEL_HEIGHT + 50)) == (255, 0, 0)
        label = sheet.crop((GAP, GAP, GAP + 80, GAP + LABEL_HEIGHT))
        assert len(label.getcolors()) > 1

    with pytest.raises(ValueError, match="different path"):
        contact_sheet(pdf_path, pdf_path)
