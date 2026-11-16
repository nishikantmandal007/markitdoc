from markitdoc.guide.contract import example_document, pdf_contract
from markitdoc.models.document import parse_document
from markitdoc.models.catalogue import layouts
from markitdoc.pdf.checks import page_problems
from markitdoc.themes.themes import theme_for
from markitdoc.themes.theme_constants import FONT_PAIRS, PALETTES, PAPERS


def test_should_describe_every_layout_palette_and_paper_without_character_counts():
    contract = pdf_contract()

    assert all(f"- {name}:" in contract for name in layouts)
    assert all(f"- {name}:" in contract for name in PALETTES) and all(paper in contract for paper in PAPERS)
    assert all(f"- {name}:" in contract for name in FONT_PAIRS)
    assert "chars" not in contract and "≤" not in contract and "+++" not in contract


def test_should_render_the_guide_example_without_problems_in_every_font_pair():
    document = parse_document(example_document)

    assert [block.layout for block in document.blocks] == ["cover", "flow", "figures", "closing"]
    for pair in FONT_PAIRS:
        assert page_problems(document, theme_for({**document.meta, "fonts": pair}, "default")) == []


def test_should_teach_every_markdown_setting_the_renderer_understands():
    from markitdoc.markup.elements import callout_kinds, chart_sizes, paragraph_alignments, table_styles

    contract = pdf_contract()

    assert all("{." + name + "}" in contract for name in [*paragraph_alignments, *table_styles, "indent", "lead", "underline"])
    assert all(size in contract for size in chart_sizes) and all(f"**{kind}:**" in contract for kind in callout_kinds)
    assert "[^1]" in contract and "- [ ]" in contract and "{{" not in contract and "}}" not in contract


def test_should_teach_spans_list_styles_containers_and_fields():
    from markitdoc.models.model_constants import FLOW_CONTAINERS
    from markitdoc.markup.elements import list_schemes, span_colors

    contract = pdf_contract()

    assert all("{." + name + "}" in contract for name in [*span_colors, *list_schemes, *FLOW_CONTAINERS])
    assert all(field in contract for field in ("{page}", "{pages}", "{title}", "{date}", "numbering: decimal", "Table:", "{#risks}"))


def test_should_teach_maths_notes_and_language():
    contract = pdf_contract()

    assert "$$" in contract and "\\frac" in contract and "notes: section | page" in contract and "lang:" in contract


def test_should_teach_every_diagram_type_and_no_icons():
    from markitdoc.visuals.diagrams import diagram_types

    contract = pdf_contract()

    assert "```mermaid" in contract and "instead of drawing with text characters" in contract
    assert all(kind in contract for kind in diagram_types) and ":shield-check:" not in contract and "Icons:" not in contract


def test_should_give_slides_their_own_guide_with_every_slide_type():
    from markitdoc.guide.contract import slides_contract
    from markitdoc.pptx.layouts import drawers

    guide = slides_contract()

    assert guide.startswith("SLIDE DESIGN GUIDE") and "action title" in guide and all(f"- {name}:" in guide for name in drawers)
