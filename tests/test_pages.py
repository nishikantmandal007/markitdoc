from pathlib import Path

import pymupdf
import pytest
from docx import Document as WordDocument
from docx.oxml.ns import qn

from markitdoc import check_document, render
from markitdoc.models.document import parse_document

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = (FIXTURES / "pages_report.md").read_text()
WORDS = " ".join(f"word{number}" for number in range(2000))


def pdf_pages(markdown, tmp_path):
    return list(pymupdf.open(render(markdown, "pdf", tmp_path / f"out{len(list(tmp_path.iterdir()))}.pdf")))


def paper(setting, body="Plain text."):
    return f"---\npage: {{{setting}}}\n---\n\n# T\n\n{body}\n"


def lines_of(page):
    return [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return pdf_pages(REPORT, tmp_path_factory.mktemp("pages"))


@pytest.mark.parametrize(("paper_name", "size"), [("a5", (419.5, 595.3)), ("a3", (841.9, 1190.6)), ("letter", (612, 792)), ("legal", (612, 1008))])
def test_should_size_the_pdf_page_from_the_paper(tmp_path, paper_name, size):
    page = pdf_pages(paper(f"paper: {paper_name}"), tmp_path)[0]

    assert (page.rect.width, page.rect.height) == pytest.approx(size, abs=0.5)


def test_should_swap_the_page_box_for_landscape(tmp_path):
    page = pdf_pages(paper("paper: a4, orientation: landscape"), tmp_path)[0]

    assert (page.rect.width, page.rect.height) == pytest.approx((841.9, 595.3), abs=0.5)


def test_should_switch_to_a_landscape_master_from_that_page(report):
    sizes = [(round(page.rect.width), round(page.rect.height)) for page in report]

    assert sizes[:-1] == [(420, 595)] * (len(sizes) - 1) and sizes[-1] == (595, 420)


def test_should_number_roman_on_the_front_master_then_restart_in_arabic(report):
    assert [page.get_label() for page in report] == ["1", "ii", "1", "2"]
    assert "ii" in [span["text"].strip() for span in lines_of(report[1])]
    assert "1" in [span["text"].strip() for span in lines_of(report[2])]


def test_should_draw_header_slots_left_centre_and_right_with_the_current_section(report):
    page = report[2]
    spans = {span["text"].strip(): span for span in lines_of(page) if span["origin"][1] < 40}

    assert {"Evidence", "Valley Report", "Nordwind AG"} <= set(spans)
    left, centre, right = spans["Evidence"], spans["Valley Report"], spans["Nordwind AG"]
    assert left["bbox"][0] == pytest.approx(14 * 72 / 25.4 + 2, abs=3)
    assert centre["bbox"][0] + centre["bbox"][2] == pytest.approx(page.rect.width, abs=3)
    assert right["bbox"][2] == pytest.approx(page.rect.width - 14 * 72 / 25.4 - 2, abs=3)


def test_should_hide_the_header_on_a_master_that_says_none(report):
    assert "Valley Report" not in [span["text"].strip() for span in lines_of(report[1]) if span["origin"][1] < 40]


def test_should_replace_fields_in_text_heading_cover_slot_and_footer_but_not_code(report):
    cover, summary = report[0].get_text(), report[1].get_text()

    assert "FOR NORDWIND AG" in cover and "Nordwind AG on 4 March 2025." in cover
    assert "Front matter text for Nordwind AG" in summary and "{client}" in summary and "4 March 2025" in summary


def test_should_replace_a_field_in_a_heading(tmp_path):
    page = pdf_pages("---\nfields: {client: Nordwind AG}\n---\n\n## Report for {client}\n\nText.\n", tmp_path)[0]

    assert "Report for Nordwind AG" in page.get_text()


def test_should_fit_more_words_on_a_larger_paper_at_the_same_body_size(tmp_path):
    a4 = pdf_pages(paper("paper: a4", WORDS), tmp_path)
    a3 = pdf_pages(paper("paper: a3", WORDS), tmp_path)
    size = lambda pages: {round(span["size"], 1) for span in lines_of(pages[0]) if span["text"].startswith("word")}  # noqa: E731

    assert size(a4) == size(a3)
    assert len(a3[0].get_text().split()) > len(a4[0].get_text().split())


def test_should_centre_a_designed_page_on_a_larger_paper(tmp_path):
    markdown = "---\npage: {paper: a3}\n---\n\n::: {.cover variant=light}\ntitle: Valley\nsubtitle: Short.\n:::\n"
    page = pdf_pages(markdown, tmp_path)[0]
    span = next(span for span in lines_of(page) if span["text"].startswith("Valley"))

    assert page.rect.width == pytest.approx(841.9, abs=0.5) and span["bbox"][0] > (297 - 210) / 2 * 72 / 25.4


@pytest.fixture(scope="module")
def word(tmp_path_factory):
    return WordDocument(str(render(REPORT, "docx", tmp_path_factory.mktemp("pages") / "out.docx")))


def test_should_make_a_word_section_for_each_master_switch(word):
    assert len(word.sections) == 4
    assert [section.orientation for section in word.sections][-1] == 1 and word.sections[0].orientation == 0
    assert word.sections[0].page_width.cm == pytest.approx(14.8, abs=0.05)


def test_should_set_the_word_page_number_format_and_restart(word):
    numbering = [section._sectPr.find(qn("w:pgNumType")) for section in word.sections]

    assert [item.get(qn("w:fmt")) for item in numbering] == ["decimal", "lowerRoman", "decimal", "decimal"]
    assert [item.get(qn("w:start")) for item in numbering] == [None, None, "1", None]


def test_should_write_the_word_header_slots_with_fields_replaced(word):
    header = word.sections[2].header
    footer = word.sections[2].footer

    assert header.paragraphs[0].text.startswith("\tValley Report\tNordwind AG") and not header.is_linked_to_previous
    assert "4 March 2025" in footer.paragraphs[0].text
    assert word.sections[1].header.paragraphs[0].text == ""


def test_should_warn_about_an_unknown_master_with_a_suggestion():
    findings = check_document(REPORT.replace("{page=front}", "{page=fron}"), ())

    assert any("unknown page master 'fron'" in finding.message and "'front'" in finding.fix for finding in findings)


def test_should_warn_about_an_unknown_field_but_not_a_defined_one_or_one_in_code():
    findings = check_document(REPORT + "\nHello {nobody} and {client} and `{nope}`.\n")

    assert [finding.message for finding in findings if "field" in finding.message] == ["unknown field '{nobody}'"]


def test_should_not_flag_the_page_keys_of_a_report():
    assert not [finding for finding in check_document(REPORT) if "numbers" in finding.message or "page" in finding.message]


BOX_STYLE = "---\nstyles:\n  note: {kind: box, bg: surface, padding: m}\n---\n\n# T\n\n::: {.note}\nInside the note.\n:::\n"


def test_should_treat_a_top_level_named_box_as_flow():
    assert {block.layout for block in parse_document(BOX_STYLE).blocks} == {"flow"}


def test_should_draw_a_top_level_named_box_as_a_filled_rectangle_in_the_flow(tmp_path):
    page = pdf_pages(BOX_STYLE, tmp_path)[0]
    text = page.get_text()

    assert "Inside the note." in text and "# T" not in text
    assert any(drawing.get("fill") and drawing["rect"].width > 100 for drawing in page.get_drawings())


def test_should_shrink_a_designed_page_to_fit_smaller_paper(tmp_path):
    markdown = "---\npage: {paper: a5}\n---\n\n::: {.cover variant=light}\ntitle: Valley\nsubtitle: Short.\n:::\n"
    page = pdf_pages(markdown, tmp_path)[0]
    span = next(span for span in lines_of(page) if span["text"].startswith("Valley"))

    assert span["size"] < 40 and 0 <= span["bbox"][0] and span["bbox"][2] <= page.rect.width
