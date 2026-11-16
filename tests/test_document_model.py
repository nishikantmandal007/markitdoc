from markitdoc.models import parse_document
from markitdoc.models.model_constants import FLOW_LAYOUT

laid_out = """---
template: company
---
## slide
layout: cover
title: AI-Safe: private AI for EU teams
subtitle: Personal data never reaches the model

## slide
layout: process
headline: How it works
- Detect — Finds personal data in text and files
- Restore — Puts real values back in the answer

## page
layout: chapter
title: The pledge
body: First paragraph || Second paragraph
```infographic
infographic list-row-simple-horizontal-arrow
data
  title: not a slot
```
"""


class TestParseDocument:
    def test_should_read_front_matter_and_one_block_per_slide_or_page(self):
        document = parse_document(laid_out)

        assert document.meta == {"template": "company"}
        assert [block.layout for block in document.blocks] == ["cover", "process", "chapter"]
        assert document.is_laid_out

    def test_should_read_slots_without_the_layout_line(self):
        cover = parse_document(laid_out).blocks[0]

        assert cover.slots == {"title": "AI-Safe: private AI for EU teams", "subtitle": "Personal data never reaches the model"}

    def test_should_split_list_items_on_the_em_dash(self):
        process = parse_document(laid_out).blocks[1]

        assert process.items == (("Detect", "Finds personal data in text and files"),
                                 ("Restore", "Puts real values back in the answer"))

    def test_should_keep_fenced_visuals_in_the_body_and_never_read_them_as_slots(self):
        chapter = parse_document(laid_out).blocks[2]

        assert chapter.slots == {"title": "The pledge", "body": "First paragraph || Second paragraph"}
        assert chapter.body.startswith("```infographic")
        assert "title: not a slot" in chapter.body

    def test_should_treat_free_markdown_as_one_flow_block(self):
        document = parse_document("# Report\n\n## Summary\nText with a colon: here.")

        assert [block.layout for block in document.blocks] == [FLOW_LAYOUT]
        assert document.blocks[0].body == "# Report\n\n## Summary\nText with a colon: here."
        assert not document.is_laid_out

    def test_should_return_an_empty_flow_block_for_empty_markdown(self):
        document = parse_document("")

        assert document.blocks[0].layout == FLOW_LAYOUT
        assert document.blocks[0].body == ""


def test_should_read_bare_item_lines_on_designed_pages_and_keep_dashed_bullets_in_flow_text():
    document = parse_document("## page\nlayout: process\ntitle: Steps\nPlan — Agree the scope\n- Build — Write the code\n\n"
                              "## page\nlayout: flow\n## Tools\n\n- **Git** — version control\n")

    assert document.blocks[0].items == (("Plan", "Agree the scope"), ("Build", "Write the code"))
    assert document.blocks[1].items == () and "**Git** — version control" in document.blocks[1].body


def test_should_read_fenced_div_pages_with_settings_and_flow_text_between_them():
    document = parse_document('::: {.cover variant=photo image="Saturn V launch"}\ntitle: Moonshot\nsubtitle: Sub\n:::\n\n'
                              "## Intro\n\nFree text.\n\n::: figures\ntitle: Numbers\n42% — Share — Note\n:::\n")

    assert [block.layout for block in document.blocks] == ["cover", "flow", "figures"]
    assert document.blocks[0].slots == {"variant": "photo", "image": "Saturn V launch", "title": "Moonshot", "subtitle": "Sub"}
    assert "Free text." in document.blocks[1].body and document.blocks[2].items == (("42%", "Share", "Note"),)


def test_should_not_treat_colons_inside_code_fences_as_page_markers():
    document = parse_document("::: flow\n```text\n:::\n```\nAfter.\n:::\n")

    assert len(document.blocks) == 1 and "After." in document.blocks[0].body


def test_should_keep_the_case_of_free_text_settings_and_lowercase_choices():
    document = parse_document('---\npalette: Forest\nheader: "St. Jude Health System"\nfooter: Page {page} of {pages}\n---\n# Doc\n')

    assert document.meta["palette"] == "forest"
    assert document.meta["header"] == "St. Jude Health System" and document.meta["footer"] == "Page {page} of {pages}"


def test_should_nest_any_opener_inside_a_flow_container_and_close_the_innermost():
    from markitdoc.models.document import split_blocks

    body = "::: cover\ntitle: T\n:::\n::: columns {ratio=2:1}\nA\n\n::: {.aside title=\"M\"}\nB\n:::\nC\n:::\nafter"

    chunks = split_blocks(body)
    assert len(chunks) == 2 and chunks[1][1:] == [
        ":::: columns {ratio=2:1}", "A", "", "::: {.aside title=\"M\"}", "B", ":::", "C", "::::", "after"]
    deeper = split_blocks("::: box\n::: foo\n::: bar\nx\n:::\n:::\n:::\nz\n::: cover\n:::")
    assert len(deeper) == 2 and deeper[0][1:6] == ["::::: box", ":::: foo", "::: bar", "x", ":::"] and deeper[0][-1] == "z"


def test_should_still_start_a_designed_block_at_top_level():
    from markitdoc.models.document import split_blocks

    assert len(split_blocks("intro\n\n::: cover\ntitle: T\n:::\n")) == 2
