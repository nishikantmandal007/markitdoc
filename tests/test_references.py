import pymupdf
from docx import Document as WordDocument
from pptx import Presentation

from markitdoc import check_document, render
from markitdoc.models.document import parse_document
from markitdoc.models.references import number_document

WORDS = " ".join(f"word{number}" for number in range(1500))
SOURCE = f"""---
markitdoc: 2
---

# Report

Read [@cha], [@costs], [@eq], [@later], and [@cha; @costs] or [@cha; @fig2].

## Setup {{#setup}}

```chart {{#cha caption="Area, hectares"}}
{{"type": "bar", "labels": ["a", "b"], "values": [1, 2]}}
```

Table: Cost per hectare {{#costs}}

| A | B |
|---|---|
| 1 | 2 |

$$ x = y + 1 $$ {{#eq}}

```chart {{#fig2}}
{{"type": "bar", "labels": ["a", "b"], "values": [1, 2]}}
```

{WORDS}

## Later {{#later}}

It is on page [@later page]. Missing: [@nowhere].
"""


def render_to(tmp_path, markdown, output_format):
    return render(markdown, output_format, tmp_path / f"out.{output_format}")


def pdf_text(tmp_path, markdown=SOURCE):
    return "\n".join(page.get_text() for page in pymupdf.open(render_to(tmp_path, markdown, "pdf")))


def test_should_number_every_kind_in_document_order():
    _, numbering = number_document(parse_document(SOURCE))

    found = {ident: (target.kind, target.number) for ident, target in numbering.targets.items()}

    assert found == {"setup": ("section", ""), "cha": ("figure", "1"), "costs": ("table", "1"), "eq": ("equation", "1"),
                     "fig2": ("figure", "2"), "later": ("section", "")}


def test_should_resolve_the_same_reference_text_in_pdf_word_and_powerpoint(tmp_path):
    expected = ["Figure 1", "Table 1", "Equation 1", "Figures 1 and 2"]
    pdf = " ".join(pdf_text(tmp_path).split())
    word = " ".join(paragraph.text for paragraph in WordDocument(str(render_to(tmp_path, SOURCE, "docx"))).paragraphs)
    slides = " ".join(shape.text_frame.text for slide in Presentation(str(render_to(tmp_path, SOURCE.replace(WORDS, "filler"), "pptx"))).slides
                      for shape in slide.shapes if shape.has_text_frame)

    for text in (pdf, word, slides):
        assert all(item in text for item in expected)
        assert "Read Figure 1, Table 1, Equation 1, Later" in text.replace(" ,", ",")


def test_should_put_the_page_of_the_target_in_a_page_reference(tmp_path):
    pages = list(pymupdf.open(render_to(tmp_path, SOURCE, "pdf")))
    real = next(number for number, page in enumerate(pages, 1) if "\nLater\n" in page.get_text())
    shown = next(line for page in pages for line in page.get_text().splitlines() if line.startswith("It is on page"))

    assert shown.startswith(f"It is on page {real}.")


def test_should_link_a_reference_to_the_page_of_its_target(tmp_path):
    pages = pymupdf.open(render_to(tmp_path, SOURCE, "pdf"))
    first = pages[0] if pages[0].get_links() else pages[1]
    targets = pages.resolve_names()
    named = [link for link in first.get_links() if link.get("nameddest")]

    assert named and all(targets[link["nameddest"]]["page"] >= 0 for link in named)
    cha = next(link for link in named if link["nameddest"] == "cha")
    assert "Area" in pages[targets["cha"]["page"]].get_text()
    assert cha["kind"] == pymupdf.LINK_NAMED


def test_should_leave_unknown_ids_as_literal_text_and_report_them(tmp_path):
    findings = [(item.severity, item.message, item.fix) for item in check_document(SOURCE)]

    assert "[?nowhere]" in pdf_text(tmp_path)
    assert ("error", "unknown reference 'nowhere'", "label the target with {#nowhere}") in findings


def test_should_suggest_the_closest_id_for_a_misspelt_reference():
    findings = check_document(SOURCE.replace("[@later page]", "[@latter page]"))

    assert any(item.severity == "error" and item.fix == "did you mean 'later'?" for item in findings)


def test_should_report_a_duplicate_id_as_an_error():
    findings = check_document(SOURCE.replace("{#fig2}", "{#cha}"))

    assert any(item.severity == "error" and "already used" in item.message for item in findings)


def test_should_caption_a_chart_as_figure_one_and_an_equation_as_one_in_brackets(tmp_path):
    text = pdf_text(tmp_path)

    assert "Figure 1. Area, hectares" in text
    assert "(1)" in text.split()


def test_should_leave_a_literal_reference_in_a_version_one_document(tmp_path):
    text = pdf_text(tmp_path, "# Title\n\nSee [@cha] here.\n")

    assert "[@cha]" in text


def test_should_count_pages_of_the_current_numbering_run_in_the_footer(tmp_path):
    markdown = ("---\nmarkitdoc: 2\npages:\n  default:\n    footer: ' | {page} of {pages} | '\n---\n\n# T\n\nFirst.\n\n"
                f"+++ {{numbers=restart}}\n\n{WORDS}\n\n{WORDS}\n")
    pages = list(pymupdf.open(render_to(tmp_path, markdown, "pdf")))
    footers = [next(line for line in page.get_text().splitlines() if " of " in line) for page in pages]

    assert footers[0] == "1 of 1"
    assert footers[1] == f"1 of {len(pages) - 1}"


def test_should_use_section_pages_in_word_when_a_run_is_one_section(tmp_path):
    markdown = "---\nmarkitdoc: 2\npages:\n  default:\n    footer: ' | {page} of {pages} | '\n---\n\n# T\n\nFirst.\n\n+++ {numbers=restart}\n\nSecond.\n"
    document = WordDocument(str(render_to(tmp_path, markdown, "docx")))
    codes = [element.text for section in document.sections for element in section.footer._element.iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instrText")]

    assert any("SECTIONPAGES" in code for code in codes)
