from pathlib import Path

import pymupdf
import pytest
from docx import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from markitdoc import Options, check_document, render
from markitdoc.cli import main
from markitdoc.themes.stylesheet import load_stylesheet
from markitdoc.themes.themes import load_theme

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = (FIXTURES / "styled_report.md").read_text()
OPTIONS = Options(style_folders=(FIXTURES / "styles",))
TEAL, WARM, BLUE, MUTED, INK = 0x0F766E, 0xB45309, 0x1D4ED8, 0x6B7280, 0x111827
BOLD, ITALIC = 16, 2


def pdf_spans(markdown, tmp_path, options=OPTIONS):
    output = render(markdown, "pdf", tmp_path / "out.pdf", options=options)
    return [span for page in pymupdf.open(output) for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
            for span in line["spans"]]


def span_with(spans, start):
    return next(span for span in spans if span["text"].startswith(start))


@pytest.fixture(scope="module")
def spans(tmp_path_factory):
    return pdf_spans(REPORT, tmp_path_factory.mktemp("styled"))


@pytest.fixture(scope="module")
def word(tmp_path_factory):
    return WordDocument(str(render(REPORT, "docx", tmp_path_factory.mktemp("styled") / "out.docx", options=OPTIONS)))


def word_run(word, paragraph_start, run_start=""):
    paragraph = next(item for item in word.paragraphs if item.text.startswith(paragraph_start))
    return paragraph, next(run for run in paragraph.runs if run.text.startswith(run_start))


def test_should_apply_a_set_rule_for_h2_in_the_pdf(spans):
    heading = span_with(spans, "Evidence")

    assert heading["font"] == "PTSerifBold" and heading["size"] == pytest.approx(16.8, abs=0.05)
    assert heading["color"] == TEAL and heading["flags"] & BOLD


def test_should_apply_a_named_inline_style_with_small_caps_in_the_pdf(spans):
    term = span_with(spans, "RIPARIAN BUFFER")

    assert term["size"] == pytest.approx(10.5 * 0.8, abs=0.05) and term["color"] == WARM
    assert span_with(spans, "The ")["size"] == pytest.approx(10.5, abs=0.05)


def test_should_apply_raw_inline_keys_in_the_pdf(spans):
    words = span_with(spans, "display words")
    quiet = span_with(spans, "grey words")

    assert words["font"] == "PTSerifBold" and words["size"] == pytest.approx(14, abs=0.05) and words["color"] == TEAL
    assert quiet["color"] == MUTED and quiet["flags"] & ITALIC
    assert span_with(spans, "LOUD WORDS")["flags"] & BOLD


def test_should_follow_based_on_and_centre_a_named_block_style_in_the_pdf(spans):
    deep = span_with(spans, "Chained from pull")

    assert deep["size"] == pytest.approx(10.5 * 1.25, abs=0.05) and deep["flags"] & ITALIC and deep["color"] == WARM
    assert (deep["bbox"][0] + deep["bbox"][2]) / 2 == pytest.approx(595.3 / 2, abs=2)


def test_should_let_front_matter_beat_the_style_file_and_inline_beat_the_block_style(spans):
    assert span_with(spans, "Minor heading")["color"] == BLUE
    assert span_with(spans, "The river")["color"] == TEAL
    assert span_with(spans, "Inline beats")["color"] == WARM


def test_should_justify_a_paragraph_with_the_align_key_in_the_pdf(spans):
    first = span_with(spans, "Plain paragraph")

    assert first["bbox"][2] == pytest.approx(595.3 - 25 / 25.4 * 72, abs=4)


def test_should_space_letters_for_tracking_in_the_pdf(tmp_path):
    text = "# T\n\nA [abcdefghij]{tracking=wide} B [abcdefghij]{tracking=tight} C [abcdefghij]{tracking=normal} D.\n"
    output = render(text, "pdf", tmp_path / "t.pdf")
    words = [word for word in pymupdf.open(output)[0].get_text("words") if word[4].startswith("abcdefghij")]
    wide, tight, normal = (word[2] - word[0] for word in words)

    assert wide > normal + 4 and tight < normal - 1


def test_should_let_a_locked_brand_win_over_the_document(tmp_path):
    (tmp_path / "brand.style.yml").write_text('locked: true\ncolors: {brand: "#112233"}\nset: {h2: {color: brand}}\n')
    text = ('---\nuse: [brand]\ncolors: {brand: "#EE4455"}\nset: {h2: {color: "#EE4455"}}\n---\n\n# T\n\n## Locked\n\n'
            "[words]{color=brand}\n")
    found = pdf_spans(text, tmp_path, Options(style_folders=(tmp_path,)))

    assert span_with(found, "Locked")["color"] == 0x112233 and span_with(found, "words")["color"] == 0x112233


def test_should_apply_the_same_properties_in_word(word):
    _, heading = word_run(word, "Evidence")
    _, term = word_run(word, "The riparian", "riparian")
    _, words = word_run(word, "The riparian", "display words")
    _, loud = word_run(word, "Quiet", "LOUD")
    _, grey = word_run(word, "Quiet", "grey")

    assert heading.font.name == "PT Serif" and heading.font.size.pt == pytest.approx(16.8, abs=0.5) and heading.bold
    assert str(heading.font.color.rgb) == "0F766E"
    assert term.font.small_caps and str(term.font.color.rgb) == "B45309" and term.font.name == "Inter"
    assert term._r.rPr.find(qn("w:spacing")).get(qn("w:val")) == "12"
    assert words.font.size.pt == 14 and words.bold and str(words.font.color.rgb) == "0F766E"
    assert loud.font.all_caps and loud.bold
    assert grey.italic and str(grey.font.color.rgb) == "6B7280"


def test_should_apply_block_styles_alignment_and_cascade_in_word(word):
    deep, run = word_run(word, "Chained")
    justified, _ = word_run(word, "Plain paragraph")
    _, minor = word_run(word, "Minor heading")
    _, inline = word_run(word, "Inline beats")

    assert deep.alignment == WD_ALIGN_PARAGRAPH.CENTER and run.font.size.pt == 13 and run.italic and str(run.font.color.rgb) == "B45309"
    assert justified.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert str(minor.font.color.rgb) == "1D4ED8" and minor.bold is False
    assert str(inline.font.color.rgb) == "B45309"


def test_should_resolve_the_cascade_with_the_source_of_each_property(tmp_path):
    (tmp_path / "base.style.yml").write_text("styles:\n  a: {size: l}\n  b: {based-on: a, color: accent}\n  c: {based-on: b}\n"
                                             "  d: {based-on: c}\n  e: {based-on: d, weight: bold}\n")
    sheet = load_stylesheet({"use": ["base"], "text": {"size": "12pt"}}, load_theme(None), (tmp_path,))

    assert sheet.resolve(None, ("c",))["size"] == ("l", "base.style.yml:styles.a")
    assert sheet.look(None, ("c",)).size == 15
    assert sheet.resolve(None, ("c",))["color"][1] == "base.style.yml:styles.b"
    assert sheet.resolve(None, ("e",))["color"][1] == "base.style.yml:styles.b" and sheet.resolve(None, ("e",))["size"][1] == "front matter:text"
    assert sheet.resolve("paragraph")["size"] == ("12pt", "front matter:text")


def test_should_explain_where_each_property_on_a_line_came_from(capsys):
    assert main(["explain", f"{FIXTURES / 'styled_report.md'}:20"]) == 0
    printed = capsys.readouterr().out

    assert "line 20: paragraph .deep" in printed
    assert "house.style.yml:styles.deep" in printed and "house.style.yml:styles.pull" in printed and "house.style.yml:set.quote" in printed
    assert main(["explain", f"{FIXTURES / 'styled_report.md'}:12"]) == 0
    assert "span .term" in capsys.readouterr().out


def test_should_warn_about_an_unknown_style_name():
    findings = check_document("Text [x]{.trem}\n\n{.pul}\n", (FIXTURES / "styles",))

    assert [f.message for f in findings] == ["unknown style '.trem'", "unknown style '.pul'"]


def test_should_warn_about_an_undeclared_font_and_a_missing_style_file():
    findings = check_document("---\nuse: [nothing]\n---\n\nText [x]{font=display}\n")

    assert [(f.line, f.message) for f in findings] == [(2, "style file 'nothing' not found"), (5, "font 'display' is not declared under fonts:")]


def test_should_ask_to_name_a_style_used_three_times():
    text = "[a]{size=14pt color=ink}\n\n[b]{size=14pt color=ink}\n\n[c]{color=ink size=14pt}\n"
    findings = check_document(text)

    assert len(findings) == 1 and findings[0].line == 1 and "name this style" in findings[0].message
    assert check_document(text.rsplit("\n\n", 1)[0] + "\n") == []


def test_should_warn_about_low_contrast_hex_colors():
    findings = check_document("[a]{color=#BBBBBB} [b]{color=#222222}\n")

    assert [f.line for f in findings] == [1] and "contrast" in findings[0].message


def test_should_accept_the_style_keys_on_a_box():
    assert check_document("::: box color=ink\n:::\n") == []


def test_should_drop_an_unavailable_font_so_the_next_layer_font_remains(tmp_path):
    (tmp_path / "x.style.yml").write_text('fonts: {display: "Playfair Display", serif: PT Serif}\ntext: {font: serif}\n'
                                          "set: {h2: {font: display}}\nstyles: {fancy: {font: display, size: l}}\n")
    sheet = load_stylesheet({"use": ["x"]}, load_theme(None), (tmp_path,))
    heading = sheet.look("h2")
    paragraph = sheet.look("paragraph")
    span = sheet.span_look((("class", "fancy"),), paragraph)

    assert heading.font == "heading" and paragraph.font == "serif"
    assert span.font == "serif" and span.size == 12.5
    assert ("x.style.yml:styles.fancy", "display") in sheet.dropped


def test_should_render_an_unavailable_font_in_the_inherited_font_and_explain_it(tmp_path, capsys):
    (tmp_path / "x.style.yml").write_text('fonts: {display: "Playfair Display", serif: PT Serif}\ntext: {font: serif}\n')
    text = "---\nuse: [x]\n---\n\n# T\n\nWords [here]{font=display} now.\n"
    found = pdf_spans(text, tmp_path, Options(style_folders=(tmp_path,)))
    (tmp_path / "d.md").write_text(text)

    assert span_with(found, "Words")["font"] == "PTSerif"
    assert "not available; using the inherited font" in check_document(text, (tmp_path,))[0].message
    assert main(["explain", f"{tmp_path / 'd.md'}:7"]) == 0
    assert "'display' dropped" in capsys.readouterr().out


@pytest.mark.parametrize(("preset", "heading", "lead", "metric", "margin"), [
    ("board-brief", 20, 15, 17.6, 28), ("editorial-report", 18, 13.5, 13.125, 28), ("manual", 16, 12, 10.5, 20),
])
def test_should_apply_preset_styles_in_a_pdf(preset, heading, lead, metric, margin, tmp_path):
    markdown = (f"---\npreset: {preset}\n---\n## Headline\n\n"
                "The opening statement.\n{.lead}\n\nA share of [42%]{.metric} of the work.")
    found = pdf_spans(markdown, tmp_path)
    assert span_with(found, "Headline")["size"] == pytest.approx(heading)
    assert span_with(found, "The opening")["size"] == pytest.approx(lead)
    assert span_with(found, "42%")["size"] == pytest.approx(metric, abs=0.02)
    assert span_with(found, "Headline")["bbox"][0] == pytest.approx((margin + 1) * 72 / 25.4, abs=0.1)


def test_should_let_explicit_rules_override_a_preset_and_check_its_name():
    sheet = load_stylesheet({"preset": "board-brief", "set": {"h2": {"size": "22pt"}}}, load_theme(None))
    assert sheet.look("h2").size == 22
    assert sheet.look("h3").size == 14
    assert any(finding.severity == "error" and "unknown preset" in finding.message
               for finding in check_document("---\npreset: briefing\n---\n# Headline"))
