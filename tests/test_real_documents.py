import re
from pathlib import Path

import fitz
import pytest

import markitdoc.render as service
from helpers import generate_document

fixtures = sorted((Path(__file__).parent / "fixtures").glob("*.md"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(service, "find_images", lambda wanted, ratios: {})
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)


def render(source, tmp_path):
    template = "company" if "security" in source.stem else "default"
    return generate_document(source.read_text(), "pdf", filename_stem=source.stem, output_dir=str(tmp_path), template=template)


def hidden_text(page):
    texts = [(span["seqno"], fitz.Rect(span["bbox"])) for span in page.get_texttrace() if span["chars"]]
    covers = [(drawing["seqno"], drawing["rect"]) for drawing in page.get_drawings()
              if drawing.get("fill") and (drawing.get("fill_opacity") or 1) >= 0.99]
    return [(text_rect, cover_rect) for text_order, text_rect in texts for cover_order, cover_rect in covers
            if cover_order > text_order and (text_rect & cover_rect).get_area() > text_rect.get_area() * 0.5]


@pytest.mark.parametrize("source", fixtures, ids=[path.stem for path in fixtures])
class TestRealDocuments:
    def test_should_never_paint_over_text(self, source, tmp_path):
        with fitz.open(render(source, tmp_path)) as pdf:
            assert [(page.number + 1, len(hidden_text(page))) for page in pdf if hidden_text(page)] == []

    def test_should_draw_every_display_equation(self, source, tmp_path):
        markdown = source.read_text()
        equations = len(re.findall(r"\$\$(.+?)\$\$", markdown, re.S))

        data = open(render(source, tmp_path), "rb").read()

        assert data.count(b"/Alt") >= equations

    def test_should_keep_the_words_of_coloured_spans(self, source, tmp_path):
        spans = re.findall(r"\[([^\]\n]{3,60})\]\{\.(?:accent|second|muted|danger|success|highlight)\}", source.read_text())

        with fitz.open(render(source, tmp_path)) as pdf:
            text = " ".join(" ".join(page.get_text().split()) for page in pdf)

        missing = [span for span in spans if re.sub(r"[*_`\\\\]", "", span).split()[0] not in text]
        assert missing == []


def test_should_tag_a_devanagari_document_as_hindi(tmp_path):
    source = next(path for path in fixtures if path.stem.endswith("_hi"))

    data = open(render(source, tmp_path), "rb").read()

    assert b"/Lang (hi)" in data
