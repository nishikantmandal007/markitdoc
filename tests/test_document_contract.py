import markitdoc
from markitdoc.guide.contract import EXAMPLE_DOCUMENT
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.document import parse_document
from markitdoc.pdf.checks import page_problems
from markitdoc.themes.theme_constants import FONT_PAIRS, PALETTES, PAPERS
from markitdoc.themes.themes import theme_for


def test_should_describe_every_layout_palette_and_paper_without_character_counts():
    contract = markitdoc.guide("pdf")

    assert all(f"- {name}:" in contract for name in LAYOUTS)
    assert all(f"- {name}:" in contract for name in PALETTES) and all(paper in contract for paper in PAPERS)
    assert all(f"- {name}:" in contract for name in FONT_PAIRS)
    assert "chars" not in contract and "≤" not in contract and "+++" not in markitdoc.guide("pdf", "writing")


def test_should_render_the_guide_example_without_problems_in_every_font_pair():
    document = parse_document(EXAMPLE_DOCUMENT)

    assert [block.layout for block in document.blocks] == ["cover", "flow", "figures", "closing"]
    for pair in FONT_PAIRS:
        assert page_problems(document, theme_for({**document.meta, "fonts": pair}, "default")) == []


def test_should_teach_every_markdown_setting_the_renderer_understands():
    from markitdoc.markup.elements import CALLOUT_KINDS, CHART_SIZES, PARAGRAPH_ALIGNMENTS, TABLE_STYLES

    contract = markitdoc.guide("pdf")

    assert all("{." + name + "}" in contract for name in [*PARAGRAPH_ALIGNMENTS, *TABLE_STYLES, "indent", "lead", "underline"])
    assert all(size in contract for size in CHART_SIZES) and all(f"**{kind}:**" in contract for kind in CALLOUT_KINDS)
    assert "[^1]" in contract and "- [ ]" in contract and "{{" not in contract and "}}" not in contract


def test_should_teach_spans_list_styles_containers_and_fields():
    from markitdoc.markup.elements import LIST_SCHEMES, SPAN_COLORS
    from markitdoc.models.model_constants import FLOW_CONTAINERS

    contract = markitdoc.guide("pdf")

    assert all("{." + name + "}" in contract for name in [*SPAN_COLORS, *LIST_SCHEMES, *FLOW_CONTAINERS])
    assert all(field in contract for field in ("{page}", "{pages}", "{title}", "{date}", "numbering: decimal", "Table:", "{#risks}"))


def test_should_teach_maths_notes_and_language():
    contract = markitdoc.guide("pdf")

    assert "$$" in contract and "\\frac" in contract and "notes: section | page" in contract and "lang:" in contract


def test_should_teach_every_diagram_type_and_no_icons():
    from markitdoc.visuals.diagrams import DIAGRAM_TYPES

    contract = markitdoc.guide("pdf")

    assert "```mermaid" in contract and "Never draw diagrams with text characters" in contract
    assert all(kind in contract for kind in DIAGRAM_TYPES) and ":shield-check:" not in contract and "Icons:" not in contract


def test_should_give_slides_their_own_guide_with_every_slide_type():
    from markitdoc.pptx.render import DRAWERS

    guide = markitdoc.guide("pptx")

    assert markitdoc.guide("pptx", "writing").startswith("SLIDE WRITING GUIDE") and "action title" in guide and all(f"- {name}:" in guide for name in DRAWERS)


def test_should_serve_each_format_its_own_guide_from_the_package():
    import pytest

    assert "SLIDE WRITING GUIDE" in markitdoc.guide("pptx") and "SLIDE WRITING GUIDE" not in markitdoc.guide("pdf")
    with pytest.raises(markitdoc.UnsupportedFormatError):
        markitdoc.guide("odt")


def test_should_render_from_the_package_and_reject_bad_input(tmp_path):
    import pytest

    assert markitdoc.render("# Hello\n\nWorld.", "pdf", tmp_path / "hello.pdf").stat().st_size > 0
    with pytest.raises(markitdoc.EmptyDocumentError):
        markitdoc.render("  ", "pdf", tmp_path / "empty.pdf")
    with pytest.raises(markitdoc.UnsupportedFormatError):
        markitdoc.render("# Hi", "odt", tmp_path / "hi.odt")
