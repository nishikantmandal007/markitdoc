import re
import zipfile
from pathlib import Path

import pymupdf
import pytest
from docx import Document as WordDocument

from markitdoc import check_document, render
from markitdoc.options import Options

FIXTURES = Path(__file__).parent / "fixtures" / "editorial"
WORDS = " ".join(f"word{number}" for number in range(1500))
LONG_TEXT = ("Flood days fell sharply after the restoration finished and the river now carries its storm water through marsh "
             "again instead of towns, which is why the valley stays dry in spring.")
HEAD = "---\nmarkitdoc: 2\nlang: en\nrefs: refs.yml\n{extra}---\n\n# Title\n\n## Section\n\n"
CITING = HEAD.replace("{extra}", "") + "Seen in [@dewit2021] and [@brook2019], also [@brook2019; @dewit2021].\n"


def source(body, extra=""):
    return HEAD.replace("{extra}", extra) + body


def render_to(tmp_path, markdown, output_format="pdf", lines=0):
    if lines:
        (tmp_path / "caps.style.yml").write_text(f"set:\n  paragraph.first: {{dropcap: {lines}}}\n", encoding="utf-8")
    (tmp_path / "refs.yml").write_text((FIXTURES / "refs.yml").read_text(encoding="utf-8"), encoding="utf-8")
    return render(markdown, output_format, tmp_path / f"out.{output_format}", options=Options(style_folders=(tmp_path,)))


def pdf_pages(tmp_path, markdown):
    return [page.get_text() for page in pymupdf.open(render_to(tmp_path, markdown))]


def flat(text):
    return " ".join(text.split())


def test_should_number_citations_in_order_of_first_use_and_list_them_under_references(tmp_path):
    text = flat("\n".join(pdf_pages(tmp_path, CITING)))

    assert "Seen in [1] and [2], also [2, 1]." in text
    assert text.index("[1] de Wit, Anna and Jansen, Pieter (2021)") < text.index("[2] Brook, Carla (2019)")
    assert "References" in text and "Never cited" not in text


def test_should_write_author_year_citations_and_sort_the_list_by_author(tmp_path):
    text = flat("\n".join(pdf_pages(tmp_path, CITING.replace("lang: en", "lang: en\nstyle: author-year"))))

    assert "Seen in (de Wit and Jansen, 2021) and (Brook, 2019), also (Brook, 2019; de Wit and Jansen, 2021)." in text
    assert text.index("Brook, Carla (2019)") < text.index("de Wit, Anna and Jansen, Pieter (2021)")


def test_should_put_the_references_where_the_references_block_is(tmp_path):
    markdown = CITING + "\n::: references\n:::\n\n## After\n\nLast words.\n"
    text = flat("\n".join(pdf_pages(tmp_path, markdown)))

    assert text.index("References") < text.index("Last words.")
    assert text.count("References") == 1


def test_should_report_unknown_keys_unused_entries_and_a_missing_refs_file():
    findings = [(item.severity, item.message, item.fix) for item in check_document(CITING.replace("[@brook2019; @dewit2021]", "[@dewitt2021]"), (FIXTURES,))]
    missing = [(item.severity, item.message) for item in check_document(CITING.replace("refs.yml", "absent.yml"), (FIXTURES,))]

    assert ("error", "unknown reference 'dewitt2021'", "did you mean 'dewit2021'?") in findings
    assert ("info", "reference 'unused2000' is never cited", "cite it or remove it from the refs file") in findings
    assert any(severity == "error" and "absent.yml" in message for severity, message in missing)


def test_should_report_a_malformed_refs_file_and_a_key_that_is_also_a_target(tmp_path):
    (tmp_path / "bad.yml").write_text("just a string", encoding="utf-8")
    (tmp_path / "clash.yml").write_text("area:\n  title: T\n  year: 2000\n", encoding="utf-8")
    chart = '```chart {#area caption="Area"}\n{"type": "bar", "labels": ["a"], "values": [1]}\n```\n'

    bad = check_document(CITING.replace("refs.yml", "bad.yml"), (tmp_path,))
    clash = check_document(source(chart + "See [@area].\n").replace("refs.yml", "clash.yml"), (tmp_path,))

    assert any(item.severity == "error" and "must map each key" in item.message for item in bad)
    assert any(item.severity == "error" and "both a target and a reference" in item.message for item in clash)


def test_should_list_figures_and_tables_with_the_real_page_and_a_link(tmp_path):
    chart = '```chart {#late caption="Late chart"}\n{"type": "bar", "labels": ["a"], "values": [1]}\n```\n'
    markdown = source(f"Intro.\n\n{WORDS}\n\n{chart}\nTable: Late table {{#tab}}\n\n| A |\n|---|\n| 1 |\n", "lists: [figures, tables]\n")
    pages = pdf_pages(tmp_path, markdown)
    real = next(number for number, text in enumerate(pages, 1) if "Figure 1. Late chart" in text and number > 1)
    document = pymupdf.open(tmp_path / "out.pdf")
    first = pages[0].splitlines()
    figure = first.index(next(line for line in first if line.startswith("Figure 1. Late chart")))
    table = first.index(next(line for line in first if line.startswith("Table 1. Late table")))

    assert first[figure + 1] == str(real) and first[table + 1] == str(real)
    assert {link["nameddest"] for link in document[0].get_links()} >= {"late", "tab"}
    assert real > 1


def test_should_put_a_list_of_figures_where_its_block_is(tmp_path):
    chart = '```chart {#one caption="One"}\n{"type": "bar", "labels": ["a"], "values": [1]}\n```\n'
    text = "\n".join(pdf_pages(tmp_path, source(f"Before.\n\n::: list-of-figures\n:::\n\n{chart}")))

    assert text.index("Before.") < text.index("List of figures") < text.index("Figure 1. One")
    assert "List of tables" not in text


def body_spans(tmp_path, markdown, lines=0):
    page = pymupdf.open(render_to(tmp_path, markdown, lines=lines))[0]
    return [(line["bbox"], span) for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]


@pytest.mark.parametrize("lines", [2, 3])
def test_should_set_a_drop_cap_as_high_as_its_lines_with_the_text_beside_it(tmp_path, lines):
    found = body_spans(tmp_path, source(f"{LONG_TEXT} {LONG_TEXT} {LONG_TEXT}\n", "use: [caps]\n"), lines)
    cap = next(item for item in found if item[1]["size"] > 20 and item[1]["text"] == "F")
    rows = sorted([item for item in found if item[1]["size"] == 10 and item[0][1] >= cap[0][1] - 4], key=lambda item: item[0][1])
    pitch = rows[1][1]["origin"][1] - rows[0][1]["origin"][1]
    cap_height = cap[1]["size"] * 0.727

    assert abs(cap_height - ((lines - 1) * pitch + 10 * 0.727)) < 0.12 * lines * pitch
    assert abs(cap[1]["origin"][1] - rows[lines - 1][1]["origin"][1]) < 1.5
    assert all(row[0][0] > cap[0][2] for row in rows[:lines])
    assert rows[lines][0][0] < cap[0][0] + 3
    assert cap[1]["text"] == "F"


def test_should_not_set_a_drop_cap_on_a_paragraph_shorter_than_its_lines(tmp_path):
    markdown = source("Short.\n{dropcap=3}\n")
    found = body_spans(tmp_path, markdown)

    assert not [item for item in found if item[1]["size"] > 24]
    assert not [item for item in found if item[1]["text"] == "S"]
    assert any("shorter than 3 lines" in item.message for item in check_document(markdown, (FIXTURES,)))


def test_should_hyphenate_a_span_with_its_own_language_and_not_print_the_attribute(tmp_path, monkeypatch):
    import markitdoc.pdf.flow.text as text

    seen = []
    original = text.hyphenated
    monkeypatch.setattr(text, "hyphenated", lambda value, lang: seen.append((value.strip(), lang)) or original(value, lang))
    markdown = source("The *Donaudampfschifffahrtsgesellschaft*{lang=de} sails and [Verkehrsinfrastruktur]{lang=de} stays.\n{align=justify}\n")
    page = flat(pdf_pages(tmp_path, markdown)[0])

    assert ("Donaudampfschifffahrtsgesellschaft", "de") in seen and ("Verkehrsinfrastruktur", "de") in seen
    assert ("The", "en") in seen
    assert "lang=de" not in page and "{" not in page
    assert original("Donaudampfschifffahrtsgesellschaft", "de") != original("Donaudampfschifffahrtsgesellschaft", "en")


LATEX_CASES = [
    (r"\textbf{loud}", "loud", "**text**"), (r"\textit{soft}", "soft", "*text*"), (r"\emph{stress}", "stress", "*text*"),
    (r"\underline{marked}", "marked", "[text]{.underline}"), (r"\texttt{code}", "code", "`text`"),
    (r"\LaTeX", "LaTeX", "write LaTeX as plain text"), (r"100\% of R\&D costs \$5", "100% of R&D costs $5", "write % without the backslash"),
]


@pytest.mark.parametrize(("command", "shown", "advice"), LATEX_CASES)
def test_should_render_a_latex_text_command_and_warn_with_the_markdown_form(tmp_path, command, shown, advice):
    markdown = source(f"Before {command} after.\n")
    text = flat(pdf_pages(tmp_path, markdown)[0])

    assert f"Before {shown} after." in text
    assert any(item.severity == "warning" and advice in item.fix and "LaTeX" in item.message
               for item in check_document(markdown, (FIXTURES,)))


def test_should_render_latex_newpage_footnote_and_centering(tmp_path):
    markdown = source("One\\footnote{the note} word \\centering stays.\n\nFirst page text \\newpage second text.\n")
    text = flat("\n".join(pdf_pages(tmp_path, markdown)))
    messages = [item.message for item in check_document(markdown, (FIXTURES,))]

    assert "the note" in text and "\\centering" not in text and "\\footnote" not in text
    assert sum("LaTeX command" in message for message in messages) == 3


def test_should_leave_latex_in_code_and_maths_alone(tmp_path):
    markdown = source("Write `\\textbf{x}` and $\\textbf{y}$.\n\n```\n\\textit{z}\n```\n")

    assert not [item for item in check_document(markdown, (FIXTURES,)) if "LaTeX" in item.message]
    assert "\\textbf{x}" in flat(pdf_pages(tmp_path, markdown)[0])


def test_should_write_citations_a_drop_cap_and_a_language_into_word(tmp_path):
    path = render_to(tmp_path, source(f"{LONG_TEXT} See [@dewit2021]; *Wasser*{{lang=de}} here.\n", "use: [caps]\nlists: [figures]\n"), "docx", 2)
    xml = zipfile.ZipFile(path).read("word/document.xml").decode()
    text = " ".join(paragraph.text for paragraph in WordDocument(str(path)).paragraphs)

    assert "See [1];" in text and "[1] de Wit, Anna and Jansen, Pieter (2021)" in text
    assert re.search(r'<w:framePr w:dropCap="drop" w:lines="2"', xml)
    assert '<w:lang w:val="de-DE"/>' in xml


def test_should_list_figures_in_word_with_a_dotted_tab_and_a_page_field(tmp_path):
    chart = '```chart {#one caption="One"}\n{"type": "bar", "labels": ["a"], "values": [1]}\n```\n'
    path = render_to(tmp_path, source(f"{chart}", "lists: [figures]\n"), "docx")
    xml = zipfile.ZipFile(path).read("word/document.xml").decode()

    assert "Figure 1. One" in " ".join(paragraph.text for paragraph in WordDocument(str(path)).paragraphs)
    assert 'w:leader="dot"' in xml and "PAGEREF one" in xml


def test_should_keep_a_version_one_document_unchanged(tmp_path):
    markdown = "# Title\n\nSee [@dewit2021] and \\textbf{x} and *a*{lang=de}.\n"
    text = flat(pdf_pages(tmp_path, markdown)[0])

    assert "[@dewit2021]" in text and "\\textbf{x}" in text
