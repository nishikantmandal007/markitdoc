import pytest
from docx import Document as WordDocument

import markitdoc.render as doc_generator_service
from helpers import generate_document

report = """---
palette: ocean
date: 2026-10-14
toc: true
---
::: {.cover}
kicker: Quarterly review
title: Growth held while margins widened
subtitle: Revenue, retention and decisions. Figures are sample data.
:::

::: {.figures}
title: Revenue grew
$42.8M — Revenue — Up 18%.
94% — Net retention — Held steady.
112 — New customers — A record.
:::

## Three things drove margin

1. Pricing lifted contract value.
2. Hosting costs fell.

- Support tickets dropped.
- Partners closed faster.

> **Risk:** Two renewals fall in the same month.

Table: Revenue by region, $M

| Region | Plan | Actual | Change |
|---|---:|---:|---:|
| Europe | 10.0 | 11.2 | +12.0% |
| Africa | 0.8 | 0.7 | -12.5% |
| Total | 10.8 | 11.9 | +10.2% |

## We lead on controls

| Capability | Us | Them |
|---|:---:|:---:|
| Residency | Full | Partial |
| Masking | High | None |

```chart
{"type": "waterfall", "labels": ["2025", "Customers", "Hosting"], "values": [12, 6.5, -3.4], "total": "2026"}
```

::: {.timeline}
title: Roadmap
Q1 2026 – Q2 2026 — Hub — Lease.
Q2 2026 – Q4 2026 — Partners — Certified.
Q3 2026 – Q1 2027 — Cloud — Frankfurt.
:::

A claim with a source.[^1]

[^1]: Annual report, page 4.
"""


@pytest.fixture
def word(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    return generate_document(report, "docx", filename_stem="report", output_dir=str(tmp_path))


def all_text(document):
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts += [cell.text for cell in row.cells]
    return " ".join(" ".join(parts).split())


def test_should_use_real_word_styles_for_title_and_headings(word):
    document = WordDocument(word)
    styles = {paragraph.style.name for paragraph in document.paragraphs}
    assert {"Title", "Heading 2", "Subtitle"} <= styles
    assert any(paragraph.style.name == "Heading 2" and paragraph.text == "Three things drove margin" for paragraph in document.paragraphs)


def test_should_keep_every_word(word):
    text = all_text(WordDocument(word))
    for phrase in ("Growth held while margins widened", "$42.8M", "Pricing lifted contract value.", "Two renewals fall in the same month",
                   "Revenue by region", "Residency", "Annual report, page 4.", "Partners"):
        assert phrase in text, phrase
    assert ":::" not in text and "title:" not in text


def test_should_number_ordered_lists_with_real_word_numbering(word):
    document = WordDocument(word)
    numbered = [paragraph for paragraph in document.paragraphs if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None]
    assert len(numbered) == 4


def test_should_repeat_table_headers_and_draw_harvey_balls_as_pictures(word):
    document = WordDocument(word)
    region = next(table for table in document.tables if table.cell(0, 0).text == "Region")
    assert region.rows[0]._tr.trPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader") is not None
    controls = next(table for table in document.tables if table.cell(0, 0).text == "Capability")
    assert controls.cell(1, 1).text == "" and controls.cell(1, 1)._tc.xpath(".//w:drawing")


def test_should_write_identical_bytes_for_the_same_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    first = generate_document(report, "docx", filename_stem="first", output_dir=str(tmp_path))
    second = generate_document(report, "docx", filename_stem="second", output_dir=str(tmp_path))
    assert open(first, "rb").read() == open(second, "rb").read()


def test_should_hand_the_word_chrome_and_cover_to_the_brand_hooks(tmp_path, monkeypatch):
    from markitdoc.themes import BrandHooks, brands

    calls = []
    hooks = BrandHooks(docx_chrome=lambda document, border: calls.append("chrome"),
                       docx_cover=lambda document, title, border: calls.append(("cover", title)) or document.add_paragraph(title))
    monkeypatch.setitem(brands.brand_hooks_by_theme, "acme", hooks)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    path = generate_document("# Brand report\n\nBody text.", "docx", filename_stem="brand", output_dir=str(tmp_path), template="acme")
    assert calls == ["chrome", ("cover", "Brand report")]
    assert "Body text." in "\n".join(paragraph.text for paragraph in WordDocument(path).paragraphs)
