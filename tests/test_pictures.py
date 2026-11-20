import fitz
import pytest
from docx import Document as WordDocument
from PIL import Image

import markitdoc
from markitdoc.markup.elements import cropped_picture, fitted_size, image_size, picture_ratio


@pytest.mark.parametrize("width, height, expected", [
    (None, None, (40, 20)), (60, None, (60, 30)), (None, 10, (20, 10)), (60, 10, (20, 10)), (20, 30, (20, 10)), (500, None, (100, 50)),
    (None, 500, (100, 50)),
])
def test_should_keep_the_proportions_and_shrink_to_the_room(width, height, expected):
    assert fitted_size((40, 20), width, height, 100, 80) == pytest.approx(expected)


def test_should_read_ratios_and_reject_anything_else():
    assert picture_ratio("16:9") == pytest.approx(16 / 9) and picture_ratio("1:1") == 1
    assert [picture_ratio(text) for text in ("wide", "16/9", "0:1", "", None)] == [None] * 5


def test_should_crop_to_the_ratio_and_leave_an_image_without_one_alone(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGB", (900, 300), "white").save(source)

    cropped = cropped_picture(source, 1.0)

    assert cropped_picture(source, None) == source
    assert image_size(cropped)[0] == pytest.approx(image_size(cropped)[1], rel=0.02)


def picture_document(tmp_path, attributes):
    if not (tmp_path / "tall.png").is_file():
        Image.new("RGB", (300, 3000), "navy").save(tmp_path / "tall.png")
    (tmp_path / "doc.md").write_text(f"# Pictures\n\n![tall](tall.png){{{attributes}}}\n")
    return (tmp_path / "doc.md").read_text()


def test_should_fit_a_tall_image_on_the_pdf_page(tmp_path):
    output = markitdoc.render(picture_document(tmp_path, "caption=\"Tall\""), "pdf", tmp_path / "doc.pdf",
                              options=markitdoc.Options(style_folders=(tmp_path,)))

    with fitz.open(output) as pdf:
        bottoms = [(rect.y1, page.rect.height) for page in pdf for info in page.get_images() for rect in page.get_image_rects(info[0])]
        assert bottoms and all(bottom <= height - 15 for bottom, height in bottoms)
        assert pdf[0].get_images(), "a page with room left takes the image instead of leaving it empty"


def test_should_size_a_word_picture_by_height(tmp_path):
    output = markitdoc.render(picture_document(tmp_path, "height=50mm"), "docx", tmp_path / "doc.docx",
                              options=markitdoc.Options(style_folders=(tmp_path,)))

    shape = WordDocument(output).inline_shapes[0]
    assert shape.height.mm == pytest.approx(50, abs=0.5) and shape.width.mm == pytest.approx(5, abs=0.5)


def test_should_crop_and_render_in_every_format(tmp_path):
    for output_format in markitdoc.FORMATS:
        output = markitdoc.render(picture_document(tmp_path, "ratio=16:9 width=1/2"), output_format, tmp_path / f"doc.{output_format}",
                                  options=markitdoc.Options(style_folders=(tmp_path,), cache_folder=tmp_path / "cache"))
        assert output.stat().st_size > 0
    assert len(list((tmp_path / "cache" / "markitdoc-crops").glob("*.png"))) == 1


def test_should_report_a_ratio_that_is_not_a_shape():
    findings = markitdoc.check_document("# Pictures\n\n![logo](logo.png){ratio=wide}\n")

    assert [(finding.line, finding.message) for finding in findings if finding.severity == "error"] == [(3, "image ratio 'wide' is not a shape")]


def test_photo_focus_selects_an_edge_and_has_its_own_cached_crop(tmp_path):
    from markitdoc.markup.elements import cropped_picture
    from markitdoc.visuals.photo_fit import interest_box

    source = tmp_path / "focus.png"
    picture = Image.new("RGB", (300, 100), "red")
    picture.paste("blue", (200, 0, 300, 100))
    picture.save(source)
    left = cropped_picture(source, 1, "left")
    right = cropped_picture(source, 1, "right")
    assert Image.open(left).getpixel((50, 50)) == (255, 0, 0)
    assert Image.open(right).getpixel((50, 50)) == (0, 0, 255)
    assert interest_box(picture, 1, "center") == (100, 0, 200, 100)
    assert interest_box(picture, 6, "bottom") == (0, 50, 300, 100)
    assert any(finding.severity == "error" and "invalid photo focus" in finding.message for finding in
               markitdoc.check_document('::: {.cover focus=diagonal}\ntitle: Test\n:::'))
