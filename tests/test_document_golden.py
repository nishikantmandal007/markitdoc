import json
import os
import re
from pathlib import Path

import pymupdf as fitz
import pytest
from docx import Document as WordDocument
from helpers import generate_document
from pptx import Presentation

GOLDEN = Path(__file__).parent / "document_golden.json"

report = """# Quarterly Privacy Review

## Summary
AI-Safe anonymised every uploaded file this quarter. The review covers detection, replacement and delivery.

- Detection found names, emails and phone numbers.
- Replacement kept the original layout.
- Delivery passed the leak check.

## Results

| Area | Files | Status |
|---|---|---|
| PDF | 120 | Done |
| Word | 45 | Done |

```chart
{"type": "bar", "title": "Files by type", "labels": ["PDF", "Word"], "values": [120, 45]}
```

+++

## Next steps
1. Fix page breaks.
2. Add layouts.

> **Note:** Numbers are sample figures.
"""

brand_report = "---\ntemplate: acme\ntoc: false\n---\n" + report

slides = """---
template: acme
---
# AI-Safe
Private AI for regulated teams

## The problem
- Personal data reaches public models
- Blocking AI costs productivity

## How it works
- Detect personal data
- Replace it with realistic fakes
- Restore real values in the answer

## Results
| Step | Owner |
|---|---|
| Detect | AI-Safe |
| Restore | AI-Safe |
"""

cases = {
    "pdf-default": ("pdf", report, "default"),
    "pdf-brand": ("pdf", brand_report, "acme"),
    "docx-default": ("docx", report, "default"),
    "docx-brand": ("docx", brand_report, "acme"),
    "pptx-default": ("pptx", slides.replace("template: acme", "template: default"), "default"),
    "pptx-brand": ("pptx", slides, "acme"),
}

date_text = re.compile(r"\b(\d{1,2} \w+ \d{4}|\w+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})\b")


def tidy(text):
    return date_text.sub("<date>", " ".join(text.split()))


def describe(path):
    if path.suffix == ".pdf":
        with fitz.open(path) as pdf:
            return {"pages": pdf.page_count, "text": [tidy(page.get_text()) for page in pdf], "images": [len(page.get_images()) for page in pdf]}
    if path.suffix == ".docx":
        document = WordDocument(path)
        return {"paragraphs": [[p.style.name, tidy(p.text)] for p in document.paragraphs if p.text.strip()],
                "tables": [[[tidy(cell.text) for cell in row.cells] for row in table.rows] for table in document.tables],
                "images": len(document.inline_shapes)}
    deck = Presentation(path)
    return {"slides": [[tidy(shape.text_frame.text) for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.strip()]
                       for slide in deck.slides],
            "pictures": [sum(1 for shape in slide.shapes if shape.shape_type == 13) for slide in deck.slides]}


def golden():
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


@pytest.mark.parametrize("name", list(cases))
def test_document_keeps_its_content_and_structure(name, tmp_path):
    output_format, markdown, template = cases[name]
    path = generate_document(markdown, output_format, filename_stem=name, output_dir=str(tmp_path), template=template)
    assert path, f"{name} did not render"
    actual = describe(Path(path))
    if os.getenv("MARKITDOC_GOLDEN_REGEN") == "1":
        recorded = golden()
        recorded[name] = actual
        GOLDEN.write_text(json.dumps(recorded, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        return
    assert actual == golden()[name]
