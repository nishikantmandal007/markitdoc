import pymupdf
import pytest
from docx import Document as WordDocument
from docx.oxml.ns import qn
from PIL import Image

from markitdoc import Options, check_document, render
from markitdoc.themes.themes import theme_for

MM = 72 / 25.4
THEME = theme_for({}, "default")
ACCENT, SURFACE = THEME.rgb("mood"), THEME.rgb("surface")


def unit(rgb):
    return tuple(round(channel / 255, 2) for channel in rgb)


def pdf_pages(markdown, tmp_path, name="out"):
    output = render(markdown, "pdf", tmp_path / f"{name}.pdf", options=Options(style_folders=(tmp_path,)))
    return list(pymupdf.open(output))


def words(page):
    return page.get_text("words")


def word_at(page, text):
    return next(word for word in words(page) if word[4] == text)


def fills(page, rgb):
    return [drawing for drawing in page.get_drawings() if drawing.get("fill") and tuple(round(c, 2) for c in drawing["fill"]) == unit(rgb)]


def picture(tmp_path, name="photo.png", size=(200, 100)):
    Image.new("RGB", size, (200, 30, 30)).save(tmp_path / name)


def test_should_draw_a_box_border_with_the_asked_width_and_colour(tmp_path):
    page = pdf_pages('::: box {border="0.5pt accent"}\nInside the box.\n:::\n', tmp_path)[0]

    strokes = [drawing for drawing in page.get_drawings() if drawing.get("color") and drawing.get("width")]

    assert len(strokes) == 1 and strokes[0]["width"] == pytest.approx(0.5, abs=0.05)
    assert tuple(round(c, 2) for c in strokes[0]["color"]) == unit(ACCENT)


def test_should_inset_the_box_text_by_the_padding(tmp_path):
    small = pdf_pages("::: box {bg=surface padding=s}\nInside the box.\n:::\n", tmp_path, "small")[0]
    large = pdf_pages("::: box {bg=surface padding=l}\nInside the box.\n:::\n", tmp_path, "large")[0]

    inset = lambda page: (word_at(page, "Inside")[0] - fills(page, SURFACE)[0]["rect"].x0,  # noqa: E731
                          word_at(page, "Inside")[1] - fills(page, SURFACE)[0]["rect"].y0)

    assert inset(large)[0] - inset(small)[0] == pytest.approx(4 * MM, abs=1)
    assert inset(large)[1] - inset(small)[1] == pytest.approx(4 * MM, abs=1)


def test_should_fill_the_box_with_the_background_colour(tmp_path):
    page = pdf_pages("::: box {bg=#FDE68A padding=s}\nInside the box.\n:::\n", tmp_path)[0]

    assert fills(page, (0xFD, 0xE6, 0x8A))


def test_should_round_the_corners_only_when_a_radius_is_given(tmp_path):
    rounded = pdf_pages("::: box {border=thin radius=l padding=s}\nInside.\n:::\n", tmp_path, "rounded")[0]
    square = pdf_pages("::: box {border=thin padding=s}\nInside.\n:::\n", tmp_path, "square")[0]

    kinds = lambda page: {item[0] for drawing in page.get_drawings() for item in drawing["items"]}  # noqa: E731

    assert "c" in kinds(rounded) and "c" not in kinds(square)


def test_should_draw_a_frame_on_each_page_a_box_covers(tmp_path):
    lines = "\n\n".join(f"Line number {number} of a long box." for number in range(1, 42))
    pages = pdf_pages("Intro.\n\n::: box {bg=surface border=thin padding=m}\n" + lines + "\n:::\n", tmp_path)

    framed = [page for page in pages if any(drawing["rect"].height > 20 for drawing in fills(page, SURFACE))]
    assert len(framed) == 2
    assert word_at(pages[1], "41")[0] > fills(pages[1], SURFACE)[0]["rect"].x0


def test_should_split_columns_by_the_ratio(tmp_path):
    page = pdf_pages("::: columns {ratio=2:1}\nLeft column text.\n\nRight column text.\n:::\n", tmp_path)[0]

    left, right = word_at(page, "Left")[0], word_at(page, "Right")[0]

    assert (right - left) / MM == pytest.approx((160 - 8) * 2 / 3 + 8, abs=1)


def test_should_wrap_a_box_inside_a_column_to_the_column_width(tmp_path):
    body = "word " * 60
    page = pdf_pages(f"::: columns {{ratio=1:3}}\nNarrow.\n\n::: box {{bg=surface padding=s}}\n{body}\n:::\n:::\n", tmp_path)[0]

    frame = fills(page, SURFACE)[0]["rect"]

    assert frame.width / MM == pytest.approx((160 - 8) * 3 / 4, abs=1)


def test_should_size_an_image_to_half_the_text_width(tmp_path):
    picture(tmp_path)
    page = pdf_pages("![A red block](photo.png){width=1/2}\n", tmp_path)[0]

    bbox = page.get_image_info()[0]["bbox"]

    assert (bbox[2] - bbox[0]) / MM == pytest.approx(80, abs=1)
    assert (bbox[0] + bbox[2]) / 2 == pytest.approx(page.rect.width / 2, abs=2)


def test_should_wrap_text_to_the_left_of_an_image_floated_right(tmp_path):
    picture(tmp_path, size=(200, 200))
    body = "Beside the picture " * 12
    page = pdf_pages(f"![A red block](photo.png){{width=1/2 side=right}}\n\n{body}\n", tmp_path)[0]

    bbox = page.get_image_info()[0]["bbox"]
    beside = [word for word in words(page) if word[4] == "Beside"]

    assert bbox[2] == pytest.approx(page.rect.width - 25 * MM, abs=2)
    assert beside and max(word[2] for word in words(page) if word[1] < bbox[3] and word[4] != "") < bbox[0]


def test_should_show_a_placeholder_and_report_an_error_for_a_missing_image(tmp_path):
    markdown = "![Gauge station](images/gauge.jpg){width=1/2}\n"
    page = pdf_pages(markdown, tmp_path)[0]
    findings = check_document(markdown, (tmp_path,))

    assert word_at(page, "Gauge") and not page.get_image_info()
    assert [(finding.severity, "gauge.jpg" in finding.message) for finding in findings if finding.severity == "error"] == [("error", True)]


def test_should_draw_a_rule_for_a_paragraph_border_edge(tmp_path):
    page = pdf_pages("Ruled paragraph.\n{border-top=thick}\n", tmp_path)[0]

    rules = [drawing["rect"] for drawing in page.get_drawings() if drawing.get("fill") and drawing["rect"].width > 100 and drawing["rect"].height < 3]

    assert rules and rules[0].height == pytest.approx(1.5, abs=0.2)
    assert rules[0].y1 < word_at(page, "Ruled")[3]


def test_should_render_a_word_box_as_a_one_cell_table_with_borders_and_shading(tmp_path):
    output = render('::: box {border="1pt accent" bg=#FDE68A padding=m}\nInside.\n:::\n', "docx", tmp_path / "out.docx")
    table = WordDocument(str(output)).tables[0]
    properties = table.cell(0, 0)._tc.tcPr

    assert (len(table.rows), len(table.columns)) == (1, 1)
    assert properties.find(qn("w:shd")).get(qn("w:fill")) == "FDE68A"
    top = properties.find(qn("w:tcBorders")).find(qn("w:top"))
    assert top.get(qn("w:val")) == "single" and top.get(qn("w:sz")) == "8"
    assert top.get(qn("w:color")) == "%02X%02X%02X" % ACCENT


def test_should_use_the_ratio_for_word_column_widths(tmp_path):
    output = render("::: columns {ratio=3:1}\nLeft.\n\nRight.\n:::\n", "docx", tmp_path / "out.docx")
    table = WordDocument(str(output)).tables[0]

    first, second = (column.cells[0].width for column in table.columns)

    assert first / second == pytest.approx(3, abs=0.01)


def test_should_place_a_word_image_inline_at_its_width(tmp_path):
    picture(tmp_path)
    output = render("![A red block](photo.png){width=1/2 side=right}\n", "docx", tmp_path / "out.docx", options=Options(style_folders=(tmp_path,)))
    document = WordDocument(str(output))

    text_width = document.sections[0].page_width.cm - document.sections[0].left_margin.cm - document.sections[0].right_margin.cm

    assert document.inline_shapes[0].width.cm == pytest.approx(text_width / 2, abs=0.05)
    assert [finding.severity for finding in check_document("![A red block](photo.png){side=right}\n", (tmp_path,))] == ["info"]


def test_should_ignore_raw_keys_when_a_style_file_sets_allow_raw_false(tmp_path):
    (tmp_path / "locked.style.yml").write_text("allow: {raw: false}\nstyles:\n  centred: {align: center}\n")
    header = "---\nuse: [locked]\n---\n"
    page = pdf_pages(header + "Raw line.\n{align=center}\n\nNamed line.\n{.centred}\n", tmp_path)[0]

    assert word_at(page, "Raw")[0] == pytest.approx(25 * MM, abs=4)
    assert word_at(page, "Named")[0] > 50 * MM
    assert any("raw keys" in finding.message for finding in check_document(header + "Raw line.\n{align=center}\n", (tmp_path,)))


def test_should_suggest_a_fix_for_bad_box_values():
    findings = check_document("::: box {border=dashed padding=4em}\nText\n:::\n\n::: columns {ratio=5:2}\nText\n:::\n")

    messages = {finding.message.split(":")[1].strip(): finding.fix for finding in findings}

    assert len(findings) == 3 and all(finding.fix for finding in findings)
    assert any("border" in message for message in messages) and any("ratio" in message for message in messages)


def test_should_accept_valid_box_values_without_findings():
    assert check_document('::: box {border="0.5pt accent" padding=m bg=surface radius=s width=1/2}\nText\n:::\n') == []
