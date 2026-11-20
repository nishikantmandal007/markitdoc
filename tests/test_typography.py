from collections import Counter

import pymupdf as fitz
from docx import Document as WordDocument
from helpers import generate_document

PARAGRAPH = "Plain body text that wraps across the line and keeps going for a while so the measure is realistic. " * 2
TABLE = "| Item | Files | Share |\n|---|---|---|\n" + "\n".join(f"| Row {n} | {n * 11} | {n}% |" for n in range(1, 6))
CODE = "```python\n" + "\n".join(f"line_{n} = {n}" for n in range(10)) + "\n```"
FILLER = "\n\n".join(PARAGRAPH for _ in range(4))
SECTIONS = "\n\n".join(f"## Section {n}\n\n{PARAGRAPH}\n\n### Detail {n}\n\n{PARAGRAPH}\n\n#### Point {n}\n\n{PARAGRAPH}" for n in range(1, 4))
DOCUMENT = f"---\ntoc: true\n---\n# Typography Title\n\n{PARAGRAPH}\n\n{SECTIONS}\n\n{TABLE}\n"


def render(markdown, tmp_path, name, output_format="pdf"):
    return generate_document(markdown, output_format, filename_stem=name, output_dir=str(tmp_path))


def spans(path):
    with fitz.open(path) as pdf:
        return [(page.number, span, line["bbox"]) for page in pdf for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", []) for span in line["spans"] if span["text"].strip()]


def size_of(path, text):
    return next(round(span["size"], 1) for _, span, _ in spans(path) if span["text"].strip() == text)


def test_should_set_body_and_heading_sizes(tmp_path):
    path = render(DOCUMENT, tmp_path, "sizes")

    body = Counter(round(span["size"], 1) for _, span, _ in spans(path) if span["text"].startswith("Plain body"))
    assert body.most_common(1)[0][0] == 10
    assert size_of(path, "Typography Title") == 28
    assert size_of(path, "Section 1") == 17
    assert size_of(path, "Detail 1") == 13
    assert size_of(path, "Point 1") == 11


def test_should_not_draw_an_accent_rule_under_h2(tmp_path):
    path = render(f"# Title\n\n{PARAGRAPH}\n\n## Heading\n\n{PARAGRAPH}\n", tmp_path, "rule")

    with fitz.open(path) as pdf:
        page = pdf[0]
        heading = next(bbox for _, span, bbox in spans(path) if span["text"].strip() == "Heading")
        bottom = heading[3]
        mm = 72 / 25.4
        near = [d for d in page.get_drawings() if bottom <= d["rect"].y0 <= bottom + 6 * mm and d["rect"].width > 2 * mm and d["rect"].height < 2 * mm
                and d["rect"].width < page.rect.width - 20 * mm]
    assert near == []


def test_should_keep_table_body_rows_at_most_six_millimetres(tmp_path):
    path = render(f"# Title\n\n{TABLE}\n", tmp_path, "rows")

    rows = sorted({round(bbox[1], 1) for _, span, bbox in spans(path) if span["text"].startswith("Row ")})
    pitch = [(second - first) / (72 / 25.4) for first, second in zip(rows, rows[1:])]
    assert len(rows) == 5 and max(pitch) <= 6


def test_should_move_a_short_code_block_to_the_next_page_instead_of_splitting_it(tmp_path):
    path = None
    for paragraphs in range(1, 12):
        filler = "\n\n".join(PARAGRAPH for _ in range(paragraphs))
        candidate = render(f"# Title\n\n{filler}\n\n{CODE}\n", tmp_path, f"code{paragraphs}")
        with fitz.open(candidate) as pdf:
            if len(pdf) == 2 and "line_0" in pdf[1].get_text():
                path = candidate
                break
    assert path
    with fitz.open(path) as pdf:
        assert "line_0" not in pdf[0].get_text()
        assert all(f"line_{n} " in pdf[1].get_text() for n in range(10))


def test_should_not_list_the_document_title_in_the_contents(tmp_path):
    path = render(DOCUMENT, tmp_path, "contents")

    with fitz.open(path) as pdf:
        contents = pdf[0].get_text()
    assert "Contents" in contents and "Section 1" in contents
    assert "Typography Title" not in contents


def test_should_use_the_same_sizes_in_word(tmp_path):
    path = render(DOCUMENT, tmp_path, "sizes", "docx")

    styles = WordDocument(path).styles
    assert styles["Normal"].font.size.pt == 10
    assert styles["Heading 2"].font.size.pt == 17


def test_should_collapse_paragraph_and_heading_spacing(tmp_path):
    path = render(f"# Title\n\n{PARAGRAPH}\n\n## Heading\n\n{PARAGRAPH}\n", tmp_path, "gap")

    found = spans(path)
    last = max(bbox[3] for _, span, bbox in found if span["text"].startswith("Plain body"))
    heading = next(bbox for _, span, bbox in found if span["text"].strip() == "Heading")
    assert (heading[1] - last) / (72 / 25.4) < 9


def test_should_not_fill_default_table_rows(tmp_path):
    path = render(f"# Title\n\n```\ncode\n```\n\n{TABLE}\n", tmp_path, "nofill")

    with fitz.open(path) as pdf:
        fills = [d for d in pdf[0].get_drawings() if d.get("fill") and d["fill"] != (1, 1, 1) and d["rect"].width > 10 and d["rect"].height < 8 * 72 / 25.4]
    assert fills == []


def test_should_keep_a_lead_in_with_the_block_it_introduces(tmp_path):
    for paragraphs in range(1, 12):
        filler = "\n\n".join(PARAGRAPH for _ in range(paragraphs))
        path = render(f"# Title\n\n{filler}\n\nExample file:\n\n{CODE}\n", tmp_path, f"lead{paragraphs}")
        with fitz.open(path) as pdf:
            if len(pdf) == 2 and "line_0" in pdf[1].get_text():
                assert "Example file:" in pdf[1].get_text()
                assert "Example file:" not in pdf[0].get_text()
                return
    raise AssertionError("no filler length pushed the code block to page 2")


def test_should_not_fill_default_word_table_rows(tmp_path):
    path = render(f"# Title\n\n{TABLE}\n", tmp_path, "wordtable", "docx")

    assert 'w:fill="' not in WordDocument(path).tables[0]._tbl.xml.replace('w:fill="auto"', "")


def test_word_embeds_the_actual_licensed_font_faces(tmp_path):
    from uuid import UUID
    from zipfile import ZipFile

    from docx.oxml.ns import qn
    from lxml import etree

    import markitdoc
    from markitdoc.utils.constants import ASSETS_FOLDER

    markdown = "---\nfonts: serif-heads\n---\n# Headline\n\nBody."
    path = markitdoc.render(markdown, "docx", tmp_path / "fonts.docx")
    word = WordDocument(path)
    assert word.styles["Heading 2"].font.name == "PT Serif"
    assert word.styles["Normal"].font.name == "Inter"
    with ZipFile(path) as package:
        fonts = etree.fromstring(package.read("word/fontTable.xml"))
        embedded = next(font for font in fonts if font.get(qn("w:name")) == "PT Serif").find(qn("w:embedRegular"))
        key = UUID(embedded.get(qn("w:fontKey"))).bytes[::-1]
        data = package.read("word/fonts/PTSerif-Regular.odttf")
        assert bytes(byte ^ key[index % 16] for index, byte in enumerate(data[:32])) + data[32:] == (
            ASSETS_FOLDER / "fonts/PTSerif-Regular.ttf").read_bytes()
        assert "SIL OPEN FONT LICENSE" in package.read("word/fonts/OFL-PTSerif.txt").decode()


def test_powerpoint_uses_deliberate_office_font_equivalents(tmp_path):
    from pptx import Presentation

    import markitdoc

    markdown = "---\nfonts: plex\n---\n# Headline\n\n## Evidence\n\nBody text."
    deck = Presentation(markitdoc.render(markdown, "pptx", tmp_path / "fonts.pptx"))
    assert {run.font.name for slide in deck.slides for shape in slide.shapes if shape.has_text_frame
            for paragraph in shape.text_frame.paragraphs for run in paragraph.runs} == {"Trebuchet MS"}
