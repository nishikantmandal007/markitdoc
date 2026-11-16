import time

import fitz
from helpers import generate_document

paragraph = ("AI-Safe detects personal data, replaces it with realistic fakes and restores the real values in the answer. "
             "Every step is logged with counts and timings, never with the values themselves. ") * 3


def section(number):
    rows = "\n".join(f"| Item {number}.{row} | {row * 125} | {row * 3.5:.1f}% | Approved by the review board |" for row in range(1, 9))
    return (f"## Section {number}: Findings\n\n{paragraph}\n\n- First point for section {number}\n- Second point\n\n"
            f"| Item | Files | Share | Status |\n|---|---|---|---|\n{rows}\n\n> **Note:** Section {number} uses sample figures.\n\n"
            f"### Detail {number}\n\n{paragraph}\n\n{paragraph}\n")


def render(markdown, tmp_path, name):
    return generate_document(markdown, "pdf", filename_stem=name, output_dir=str(tmp_path))


def page_texts(path):
    with fitz.open(path) as pdf:
        return [" ".join(page.get_text().split()) for page in pdf]


class TestFlowPdf:
    def test_should_render_a_hundred_page_report_quickly_and_completely(self, tmp_path):
        markdown = "---\nstyle: report\ntoc: true\n---\n# Annual Privacy Report\n\n" + "\n".join(section(n) for n in range(1, 121))

        started = time.perf_counter()
        path = render(markdown, tmp_path, "hundred")
        seconds = time.perf_counter() - started

        texts = page_texts(path)
        assert len(texts) >= 100
        assert seconds < 60
        assert all(f"Section {n}: Findings" in " ".join(texts) for n in (1, 60, 120))
        assert "Contents" in texts[0] and "Section 1: Findings" in texts[0]

    def test_should_add_a_bookmark_for_every_section(self, tmp_path):
        markdown = "---\nstyle: report\n---\n# Report\n\n" + "\n".join(section(n) for n in range(1, 4))

        with fitz.open(render(markdown, tmp_path, "bookmarks")) as pdf:
            titles = [entry[1] for entry in pdf.get_toc()]

        assert ["Section 1: Findings", "Section 2: Findings", "Section 3: Findings"] == [t for t in titles if t.startswith("Section")]

    def test_should_repeat_the_table_header_on_every_page_it_spans(self, tmp_path):
        rows = "\n".join(f"| Row {row} | Value {row} |" for row in range(1, 160))
        path = render(f"---\nstyle: report\n---\n# Long table\n\n| Name | Value |\n|---|---|\n{rows}\n", tmp_path, "long_table")

        texts = page_texts(path)
        assert len(texts) >= 3
        assert all(text.count("Name Value") >= 1 for text in texts)

    def test_should_put_a_too_wide_table_on_a_landscape_page(self, tmp_path):
        header = "| " + " | ".join(f"Quarterly measure {column}" for column in range(1, 11)) + " |"
        divider = "|" + "---|" * 10
        row = "| " + " | ".join(f"Considerably long value {column}" for column in range(1, 11)) + " |"
        path = render(f"---\nstyle: report\n---\n# Wide\n\nBefore the table.\n\n{header}\n{divider}\n{row}\n\nAfter.\n", tmp_path, "wide")

        with fitz.open(path) as pdf:
            shapes = [(page.rect.width > page.rect.height, " ".join(page.get_text().split())) for page in pdf]

        assert any(landscape and "Quarterly measure 10" in text for landscape, text in shapes)
        assert not shapes[0][0]

    def test_should_render_plain_documents_without_running_headers(self, tmp_path):
        markdown = "---\nstyle: plain\n---\n# Meeting notes\n\n" + "\n\n".join([paragraph] * 30)

        texts = page_texts(render(markdown, tmp_path, "plain"))

        assert len(texts) >= 2
        assert "MEETING NOTES" not in texts[1]
        assert "Meeting notes" in texts[0]
