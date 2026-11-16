
import fitz
from helpers import generate_document

from markitdoc.models.document import parse_document
from markitdoc.pdf.checks import problems_in

story = ("The programme grew from a single speech into the work of four hundred thousand people across the country. "
         "Engineers tested every part again and again, and each flight taught the next one something new. ") * 4

report = f"""---
template: editorial
mood: analytical
---
## page
layout: cover
kicker: A short history
title: The Road to the Moon
subtitle: How a decade of engineering carried people to another world.

## page
layout: chapter
number: 01
title: A decade of daring
lead: In May 1961 a president set a goal that seemed impossible.
body: The first paragraph tells the start. {story} || The second paragraph tells what followed. {story}
quote: We choose to go to the Moon. — John F. Kennedy

## page
layout: timeline
title: Key moments
lead: Eight years from promise to landing.
- May 1961 — Kennedy sets the goal — A speech to Congress commits the United States.
- Dec 1968 — Apollo 8 orbits the Moon — The first crew to leave Earth orbit.
- Jul 1969 — Apollo 11 lands — Armstrong and Aldrin walk on the Moon.
- Jul 1969 — Safe return — The crew splashes down in the Pacific.

## page
layout: feature
title: Touchdown
body: The landing story. {story} || What happened next.
- 21.5 hours — on the lunar surface
- 650 million — people watching live

## page
layout: closing
quote: That's one small step for man, one giant leap for mankind.
quote_by: Neil Armstrong
title: A promise kept
body: The mission ended safely. {story} || It changed how people saw Earth.
"""


def page_texts(path):
    with fitz.open(path) as pdf:
        return [" ".join(page.get_text().split()) for page in pdf]


class TestLaidOutPdf:
    def test_should_print_sparse_designed_pages_as_text_without_losing_anything(self, tmp_path):
        path = generate_document(report, "pdf", filename_stem="report", output_dir=str(tmp_path))

        texts = page_texts(path)
        text = " ".join(texts)
        assert len(texts) < 5
        assert "The Road to the Moon" in texts[0]
        assert "A decade of daring" in texts[1] and "We choose to go to the Moon." in texts[1]
        assert text.index("Apollo 8 orbits the Moon") < text.index("21.5 hours") < text.index("A promise kept")
        assert text.index("one giant leap") < text.index("A promise kept")

    def test_should_find_no_problems_in_a_valid_document(self):
        assert problems_in(parse_document(report)) == []

    def test_should_measure_the_title_and_accept_text_that_really_fits(self):
        fits = report.replace("title: The Road to the Moon", "title: " + "Moon " * 8)

        assert problems_in(parse_document(fits)) == []

    def test_should_report_a_title_that_needs_more_lines_than_the_layout_allows(self):
        too_long = report.replace("title: The Road to the Moon", "title: " + "Moon landing " * 12)

        problems = problems_in(parse_document(too_long))

        assert len(problems) == 1 and problems[0].startswith("page 1 (cover): title needs ") and "fits 3" in problems[0]

    def test_should_report_an_unknown_layout(self):
        problems = problems_in(parse_document(report.replace("layout: feature", "layout: poster")))

        assert problems[0].startswith("page 4: unknown layout 'poster'")

    def test_should_report_a_missing_required_slot_and_a_wrong_item_count(self):
        broken = report.replace("title: A promise kept\n", "").replace("- Jul 1969 — Safe return — The crew splashes down in the Pacific.\n", "")
        broken = broken.replace("- Dec 1968 — Apollo 8 orbits the Moon — The first crew to leave Earth orbit.\n", "")

        problems = problems_in(parse_document(broken))

        assert "page 3 (timeline): needs 3 to 8 items, has 2" in problems
        assert "page 5 (closing): title is missing" in problems

    def test_should_render_a_page_that_breaks_its_layout_as_plain_text(self, tmp_path):
        broken = report.replace("layout: feature", "layout: poster")

        texts = page_texts(generate_document(broken, "pdf", filename_stem="broken", output_dir=str(tmp_path)))

        assert any("Touchdown" in text and "21.5 hours" in text for text in texts)
        assert "A promise kept" in " ".join(texts[-2:])

    def test_should_report_a_chart_without_values(self):
        markdown = '## page\nlayout: flow\n# Data\n\n```chart\n{"type": "bar", "labels": ["A", "B"]}\n```\n'

        assert problems_in(parse_document(markdown)) == ["page 1 (flow): chart 1 has no labels or values"]

    def test_should_keep_the_flow_footer_off_designed_pages(self, tmp_path):
        markdown = report.replace("## page\nlayout: closing", "## page\nlayout: flow\n# Notes\n\nSome notes.\n\n## page\nlayout: closing")

        texts = page_texts(generate_document(markdown, "pdf", filename_stem="mixed", output_dir=str(tmp_path)))

        assert [text.count(f" / {len(texts)}") for text in texts[1:]] == [1] * (len(texts) - 1)

    def test_should_accept_an_infographic_list_written_without_its_data_key(self):
        from markitdoc.visuals.infographics import problems_in_infographic

        syntax = "infographic sequence-steps-badge-card\ndata\n  title Missions\n  - label Apollo 11\n    desc First landing"

        assert problems_in_infographic(syntax) == []

    def test_should_read_an_infographic_template_written_on_the_fence_line(self):
        from markitdoc.pdf.checks import fences

        body = "Intro\n\n```infographic compare-swot\ndata\n  compares\n    - label Strengths\n```\n"

        assert fences(body, "infographic") == ["infographic compare-swot\ndata\n  compares\n    - label Strengths\n"]
