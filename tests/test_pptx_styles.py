import time

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Pt

from markitdoc import Options, check_document, render
from markitdoc.themes.themes import theme_for

THEME = theme_for({}, "default")
FRONT = """---
colors:
  brand: "#0F766E"
fonts:
  display: PT Serif
text: {size: 20pt}
set:
  paragraph: {size: 18pt, color: brand, weight: bold}
  h2: {font: display, color: brand, size: 30pt}
styles:
  term: {kind: inline, caps: small, tracking: wide, color: "#B45309", size: 22pt}
  pull: {kind: block, size: 26pt, align: center, italic: true}
  card: {kind: box, border: "2pt #B45309", bg: "#EEF2F7", padding: 8mm, radius: m}
---
"""


def deck_of(markdown, tmp_path, name="out"):
    output = render(markdown, "pptx", tmp_path / f"{name}.pptx", options=Options(style_folders=(tmp_path,)))
    return Presentation(str(output))


def runs_of(deck):
    return [run for slide in deck.slides for shape in slide.shapes if shape.has_text_frame for paragraph in shape.text_frame.paragraphs
            for run in paragraph.runs]


def run_with(deck, text):
    return next(run for run in runs_of(deck) if text in run.text)


def test_should_apply_a_set_rule_to_slide_body_runs(tmp_path):
    run = run_with(deck_of(FRONT + "## Findings\n\nWater levels rose steadily.\n", tmp_path), "Water levels")

    assert run.font.size == Pt(18) and run.font.bold is True
    assert str(run.font.color.rgb) == "0F766E"


def test_should_apply_a_set_rule_to_the_slide_title(tmp_path):
    run = run_with(deck_of(FRONT + "## Findings\n\nWater levels rose steadily.\n", tmp_path), "Findings")

    assert run.font.size == Pt(30) and run.font.name == "PT Serif" and str(run.font.color.rgb) == "0F766E"


def test_should_apply_a_named_inline_style_to_a_span(tmp_path):
    run = run_with(deck_of(FRONT + "## Findings\n\nThe [riparian buffer]{.term} tripled.\n", tmp_path), "riparian")

    assert run.font.size == Pt(22) and str(run.font.color.rgb) == "B45309"
    assert run._r.rPr.get("cap") == "small" and run._r.rPr.get("spc") == "60"


def test_should_apply_a_named_block_style_to_a_paragraph(tmp_path):
    deck = deck_of(FRONT + "## Findings\n\nA short pulled line.\n{.pull}\n", tmp_path)
    run = run_with(deck, "pulled")

    assert run.font.size == Pt(26) and run.font.italic is True
    assert run._r.getparent().pPr.get("algn") == "ctr"


def test_should_draw_a_box_as_a_rounded_shape_with_fill_border_and_margins(tmp_path):
    deck = deck_of(FRONT + "## Facts\n\n::: box {.card}\nInside the box.\n:::\n", tmp_path)
    shape = next(shape for slide in deck.slides for shape in slide.shapes if shape.name == "Box")

    assert shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and "Inside the box." in shape.text_frame.text
    assert str(shape.fill.fore_color.rgb) == "EEF2F7" and str(shape.line.color.rgb) == "B45309"
    assert shape.line.width == Pt(2)
    assert shape.text_frame.margin_left == pytest.approx(8 / 25.4 * 914400, abs=2)
    assert shape._element.spPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom").get("prst") == "roundRect"


def test_should_put_text_in_the_box_with_inherited_box_text_props(tmp_path):
    front = FRONT.replace("radius: m}", "radius: m, color: brand}")
    run = run_with(deck_of(front + "## Facts\n\n::: box {.card}\nInside the box.\n:::\n", tmp_path), "Inside")

    assert str(run.font.color.rgb) == "0F766E"


def test_should_set_two_to_one_columns_as_frames_in_ratio(tmp_path):
    deck = deck_of(FRONT + "## Two\n\n::: columns {ratio=2:1}\nLeft text here.\n\nRight text here.\n:::\n", tmp_path)
    frames = [shape for slide in deck.slides for shape in slide.shapes if shape.name == "Column"]

    assert len(frames) == 2 and frames[0].width / frames[1].width == pytest.approx(2, rel=0.02)
    assert frames[0].top == frames[1].top and frames[1].left > frames[0].left + frames[0].width


def test_should_place_an_image_file_at_the_asked_width(tmp_path):
    Image.new("RGB", (400, 200), (200, 30, 30)).save(tmp_path / "photo.png")
    deck = deck_of(FRONT + '## Picture\n\n![Gauge](photo.png){width=1/2 caption="Alder, 2024"}\n', tmp_path)
    slide = next(slide for slide in deck.slides if any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in slide.shapes))
    picture = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)

    assert picture.width / 914400 == pytest.approx(12.133 / 2, rel=0.02)
    assert any("Alder, 2024" in shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)


def test_should_show_a_resolved_reference_and_citation_as_text(tmp_path):
    (tmp_path / "refs.yml").write_text("dewit2021: {author: [Marie de Wit], title: Floodplains, year: 2021}\n", encoding="utf-8")
    markdown = ("---\nrefs: refs.yml\n---\n"
                + "## Evidence\n\nSee [@dewit2021] and [@chart1].\n\n```chart {#chart1 caption=\"Levels\"}\n"
                '{"type": "bar", "labels": ["a", "b"], "datasets": [{"values": [1, 2]}]}\n```\n')
    text = " ".join(run.text for run in runs_of(deck_of(markdown, tmp_path)))

    assert "[1]" in text and "Figure 1" in text


def test_should_show_a_field_in_slide_text(tmp_path):
    front = "---\nfields:\n  client: Nordwind\n---\n"

    assert "Nordwind" in " ".join(run.text for run in runs_of(deck_of(front + "## Intro\n\nPrepared for {client}.\n", tmp_path)))


def test_should_render_a_very_long_paragraph_quickly(tmp_path):
    words = " ".join(["alder", "buffer", "stream", "bank"] * 375)
    started = time.perf_counter()
    deck_of(f"## Long\n\n{words}\n", tmp_path)

    assert time.perf_counter() - started < 10


def test_should_note_what_a_slide_ignores_in_check(tmp_path):
    findings = check_document(FRONT + "## A\n\n::: columns\nx\n\ny\n:::\n", output_format="pptx")

    assert any("columns" in finding.message and finding.severity == "info" for finding in findings)


def test_should_scale_a_print_sized_title_rule_to_the_slide_and_clamp_it_to_the_title_range(tmp_path):
    front = "---\ntext: {size: 10pt}\nset:\n  h2: {size: 14.5pt}\n---\n"
    run = run_with(deck_of(front + "## Findings\n\nWater levels rose steadily.\n", tmp_path), "Findings")

    assert run.font.size == Pt(29)
    huge = front.replace("14.5pt", "40pt")

    assert run_with(deck_of(huge + "## Findings\n\nWater.\n", tmp_path, "huge"), "Findings").font.size == Pt(30)


def test_should_size_a_scale_word_span_relative_to_the_slide_body(tmp_path):
    front = "---\ntext: {size: 10pt}\n---\n"
    run = run_with(deck_of(front + "## Findings\n\nA [big]{size=l} word.\n", tmp_path), "big")

    assert run.font.size == Pt(25)
