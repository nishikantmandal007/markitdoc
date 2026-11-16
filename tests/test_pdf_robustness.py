import fitz
from helpers import generate_document

from markitdoc.models.document import parse_document
from markitdoc.visuals.infographics import problems_in_infographic


def page_texts(path):
    with fitz.open(path) as pdf:
        return [" ".join(page.get_text().replace("​", "").split()) for page in pdf]


def render(markdown, tmp_path, name="robust"):
    return generate_document(markdown, "pdf", filename_stem=name, output_dir=str(tmp_path))


class TestRobustRendering:
    def test_should_skip_a_chart_whose_labels_and_values_differ_and_still_write_the_pdf(self, tmp_path):
        markdown = '# Data\n\nBefore.\n\n```chart\n{"type": "bar", "labels": ["A", "B", "C"], "datasets": [{"values": [1, 2]}]}\n```\n\nAfter.\n'

        texts = page_texts(render(markdown, tmp_path))

        assert "Before." in texts[0] and "After." in texts[0]

    def test_should_show_a_table_with_a_cell_taller_than_a_page_as_text(self, tmp_path):
        huge = "word " * 2500
        markdown = f"# Table\n\n| Name | Notes |\n|---|---|\n| First | {huge} |\n| Second | short |\n"

        texts = page_texts(render(markdown, tmp_path))

        assert "Second" in " ".join(texts)

    def test_should_keep_items_written_with_other_separators(self):
        document = parse_document("## page\nlayout: process\ntitle: Steps\n- Plan: agree the scope\n- Build - write the code\nShip – release it\n")

        assert document.blocks[0].items == (("Plan", "agree the scope"), ("Build", "write the code"), ("Ship", "release it"))

    def test_should_join_a_slot_value_that_wraps_onto_the_next_line(self):
        document = parse_document("## page\nlayout: summary\ntitle: Results\nlead: The first half of the lead\ncontinues on this line.\n")

        assert document.blocks[0].slots["lead"] == "The first half of the lead continues on this line."

    def test_should_keep_text_written_before_the_first_page_and_accept_numbered_page_markers(self):
        document = parse_document("# Report\n\nIntro text.\n\n## Page 1\nlayout: cover\ntitle: T\nsubtitle: S\n")

        assert [block.layout for block in document.blocks] == ["flow", "cover"]
        assert "Intro text." in document.blocks[0].body

    def test_should_print_code_like_text_literally(self, tmp_path):
        markdown = "# Notes\n\nCall `__init__` with `**kwargs` and pass --force to the tool.\n"

        text = page_texts(render(markdown, tmp_path))[0]

        assert "__init__" in text and "**kwargs" in text and "--force" in text

    def test_should_keep_hard_line_breaks_in_letters(self, tmp_path):
        markdown = "---\nstyle: plain\n---\n# Letter\n\nTo: Jane Doe  \nFrom: Support team  \nDate: 1 May\n"

        with fitz.open(render(markdown, tmp_path)) as pdf:
            lines = pdf[0].get_text().replace("​", "").splitlines()

        assert "To: Jane Doe" in lines and "From: Support team" in lines

    def test_should_not_add_a_blank_page_for_an_empty_flow_block(self, tmp_path):
        markdown = "## page\nlayout: flow\n# Only page\n\nText.\n\n## page\nlayout: flow\n"

        assert len(page_texts(render(markdown, tmp_path))) == 1

    def test_should_show_an_infographic_as_a_list_when_the_renderer_is_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
        markdown = ("# Flow\n\n```infographic sequence-steps-badge-card\ndata\n  sequences\n    - label Detect\n      desc Find data\n"
                    "    - label Replace\n      desc Swap values\n```\n")

        text = page_texts(render(markdown, tmp_path))[0]

        assert "Detect — Find data" in text and "Replace — Swap values" in text

    def test_should_reject_infographic_values_that_are_not_numbers(self):
        syntax = "infographic chart-column-simple\ndata\n  values\n    - label Speed\n      value 12k TPS"

        assert problems_in_infographic(syntax) == ["every 'value' must be a plain number (put units in the label or desc)"]

    def test_should_write_identical_bytes_for_identical_markdown(self, tmp_path):
        markdown = ("---\npalette: forest\nfonts: serif\ndate: 2026-11-15\nnotes: page\n---\n# Same\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                    "Text with [a marker]{.highlight} and a note.[^1]\n\n$$\nx^2 + y^2\n$$\n\n[^1]: Note.\n")

        first = open(render(markdown, tmp_path, "first"), "rb").read()
        second = open(render(markdown, tmp_path, "second"), "rb").read()

        assert first == second

    def test_should_style_a_single_table_from_its_settings_line(self, tmp_path):
        markdown = "# Data\n\n| A | B |\n|---|---|\n| 1 | 2 |\n{.boxed}\n\nAfter the table.\n"

        text = page_texts(render(markdown, tmp_path))[0]

        assert "After the table." in text and "{.boxed}" not in text
