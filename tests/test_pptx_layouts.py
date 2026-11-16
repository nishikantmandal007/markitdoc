import re

import pytest
from helpers import generate_document
from pptx import Presentation
from pptx.util import Emu, Inches

import markitdoc.rendering as doc_generator_service
from markitdoc.themes.themes import load_theme

deck_markdown = """---
palette: ocean
date: 2026-10-14
---
::: {.cover}
kicker: Quarterly review
title: Growth held while margins widened
subtitle: Revenue, retention and the decisions we need. Figures are sample data.
:::

::: {.figures}
title: Revenue grew and every region is profitable
$42.8M — Revenue — Up 18% on last year.
650 million — Requests served — A record month for the platform.
94% — Net retention — Held steady through renewals.
:::

## Three things drove the margin improvement

- **Pricing** — The new tier lifted average contract value.
- **Hosting** — Costs fell after the migration.
- **Support** — Tickets per customer dropped by a third.

## Every region beat its target except one

| Region | Plan | Actual |
|---|---:|---:|
| North America | 15.0 | 15.8 |
| Latin America | 3.1 | 2.9 |

```chart
{"type": "bar", "title": "Revenue by region", "labels": ["North America", "Latin America"], "datasets": [{"label": "Q3", "values": [15.8, 2.9]}]}
```

::: {.process}
title: The hub launches in four steps
Approve — Leadership signs off the plan.
Hire — Two engineers join.
Migrate — First customers move.
Launch — Open for everyone.
:::

::: {.closing}
title: Next steps
body: Leadership confirms the decisions by 28 October.
:::
"""


@pytest.fixture
def deck(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    path = generate_document(deck_markdown, "pptx", filename_stem="deck", output_dir=str(tmp_path))
    return path


def all_text(presentation):
    pieces = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                pieces.append(shape.text_frame.text)
            if shape.has_table:
                pieces += [cell.text for row in shape.table.rows for cell in row.cells]
        if slide.has_notes_slide:
            pieces.append(slide.notes_slide.notes_text_frame.text)
    return " ".join(" ".join(pieces).split())


def test_should_keep_every_word_on_a_slide_or_in_the_notes(deck):
    text = all_text(Presentation(deck)).lower()
    source = re.sub(r"```.*?```|^::: ?\{[^}]*\}$|^:::$|^\w+: ", " ", deck_markdown.split("---", 2)[2], flags=re.S | re.M)
    words = {word.strip(".,—$%*|:#-").lower() for word in source.split()}
    missing = sorted(word for word in words if len(word) > 3 and word not in text)
    assert missing == []


def test_should_keep_every_shape_inside_the_slide(deck):
    presentation = Presentation(deck)
    width, height = presentation.slide_width, presentation.slide_height
    for number, slide in enumerate(presentation.slides, 1):
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0, (number, shape.name)
            assert shape.left + shape.width <= width + Emu(9525) and shape.top + shape.height <= height + Emu(9525), (number, shape.name)


def test_should_never_set_slide_text_below_fourteen_points(deck):
    for slide in Presentation(deck).slides:
        for shape in slide.shapes:
            if not shape.has_text_frame or shape.name in ("Footer", "Slide number", "Credit", "Date", "Brand"):
                continue
            sizes = [run.font.size.pt for paragraph in shape.text_frame.paragraphs for run in paragraph.runs if run.font.size]
            assert all(size >= 14 for size in sizes), (shape.name, sizes)


def test_should_turn_short_labelled_bullets_into_cards(deck):
    names = [shape.name for slide in Presentation(deck).slides for shape in slide.shapes]
    assert names.count("Card") == 3


def test_should_place_the_chart_as_a_native_editable_chart(deck):
    charts = [shape.chart for slide in Presentation(deck).slides for shape in slide.shapes if shape.has_chart]
    assert len(charts) == 1 and list(charts[0].plots[0].categories) == ["North America", "Latin America"]


def test_should_write_identical_bytes_for_the_same_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    first = generate_document(deck_markdown, "pptx", filename_stem="first", output_dir=str(tmp_path))
    second = generate_document(deck_markdown, "pptx", filename_stem="second", output_dir=str(tmp_path))
    assert open(first, "rb").read() == open(second, "rb").read()


brand_markdown = deck_markdown.replace("palette: ocean", "template: acme")


@pytest.fixture
def brand_deck(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    return generate_document(brand_markdown, "pptx", filename_stem="brand", output_dir=str(tmp_path))


def test_should_build_the_brand_cover_on_the_brand_master(brand_deck):
    presentation = Presentation(brand_deck)
    cover = presentation.slides[0]
    assert "Title Only" in [layout.name for layout in presentation.slide_layouts]
    assert any(shape.shape_type == 13 for shape in cover.shapes)
    text = all_text(presentation)
    assert "Growth held while margins widened" in text and "Quarterly review" in text.title().replace("Review", "review")
    assert "Aaloka" not in text and "Presented by" not in text and "Unlocking" not in text
    assert presentation.slide_width == Inches(13.333)


def test_should_draw_content_slides_on_the_brand_layout(brand_deck):
    layouts = {slide.slide_layout.name for slide in list(Presentation(brand_deck).slides)[1:]}
    assert layouts == {"Title Only"}


def test_should_put_the_brand_footer_on_every_slide(brand_deck):
    theme = load_theme("acme")
    for number, slide in enumerate(Presentation(brand_deck).slides, 1):
        footers = {shape.name: " ".join(shape.text_frame.text.split()) for shape in slide.shapes if shape.name.startswith("Footer")}
        assert footers["Footer"] == " ".join(theme.footer_text.split()), number
        assert footers["Footer note"] == theme.header_note, number


def test_should_keep_every_word_of_the_brand_deck(brand_deck):
    text = all_text(Presentation(brand_deck)).lower()
    source = re.sub(r"```.*?```|^::: ?\{[^}]*\}$|^:::$|^\w+: ", " ", brand_markdown.split("---", 2)[2], flags=re.S | re.M)
    words = {word.strip(".,—$%*|:#-").lower() for word in source.split()}
    assert sorted(word for word in words if len(word) > 3 and word not in text) == []


def test_should_keep_brand_shapes_inside_the_slide_and_clear_of_the_logo(brand_deck):
    presentation = Presentation(brand_deck)
    for number, slide in enumerate(presentation.slides, 1):
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0, (number, shape.name)
            assert shape.left + shape.width <= presentation.slide_width + Emu(9525), (number, shape.name)
            assert shape.top + shape.height <= presentation.slide_height + Emu(9525), (number, shape.name)
            if slide.slide_layout.name == "Title Only" and shape.name in ("Title", "Lead", "Title rule"):
                assert shape.left + shape.width <= Emu(int(12.2 * 914400)), (number, shape.name)


def test_should_write_identical_brand_bytes_for_the_same_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    first = generate_document(brand_markdown, "pptx", filename_stem="first", output_dir=str(tmp_path))
    second = generate_document(brand_markdown, "pptx", filename_stem="second", output_dir=str(tmp_path))
    assert open(first, "rb").read() == open(second, "rb").read()


def test_should_use_the_brand_deck_for_the_template_argument(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {})
    path = generate_document(deck_markdown, "pptx", filename_stem="arg", output_dir=str(tmp_path), template="acme")
    assert any(shape.shape_type == 13 for shape in Presentation(path).slides[0].shapes)


photo_markdown = """---
images: true
---
::: {.cover image="Palace of Versailles"}
title: The Age of Elegance
subtitle: Proportion and ornament.
:::

::: {.divider image="Wurzburg Residence"}
title: The Baroque gives way
lead: Lighter interiors spread across Europe.
:::

::: {.chapter image="Amalienburg"}
title: Rococo made the interior the masterpiece
body: Scrolls and mirrors dissolved the walls. || Rooms became one work of art.
:::

## Palladian rules returned order

Burlington built Chiswick House on Palladio's ratios.

![Chiswick House](figure)

## The Royal Crescent

![Royal Crescent Bath](figure)

## Three buildings

![Pantheon Paris](figure)

![Monticello](figure)

![Brandenburg Gate](figure)
"""


@pytest.fixture
def photo_deck(tmp_path, monkeypatch):
    from PIL import Image

    from markitdoc.visuals.images import DocumentImage

    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (1600, 1000), (120, 110, 90)).save(photo)
    image = DocumentImage(photo, "File:Sample building.jpg", "Jane Doe", "CC BY 4.0")
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    monkeypatch.setattr(doc_generator_service, "find_images", lambda wanted, ratios: {key: image for key in wanted})
    return Presentation(generate_document(photo_markdown, "pptx", filename_stem="photos", output_dir=str(tmp_path)))


def named(slide, name):
    return [shape for shape in slide.shapes if shape.name == name]


def test_should_fill_section_slides_with_the_photo_edge_to_edge(photo_deck):
    width, height = photo_deck.slide_width, photo_deck.slide_height
    backgrounds = [shape for slide in photo_deck.slides for shape in named(slide, "Background photo")]
    assert len(backgrounds) >= 2
    assert all(shape.left == 0 and shape.top == 0 and shape.width == width and shape.height == height for shape in backgrounds)


def test_should_split_photo_slides_in_half_and_alternate_sides(photo_deck):
    sides = [shape for slide in photo_deck.slides for shape in named(slide, "Side photo")]
    assert len(sides) == 2
    assert all(shape.top == 0 and shape.height == photo_deck.slide_height and abs(shape.width - photo_deck.slide_width / 2) < 20000
               for shape in sides)
    assert sides[0].left != sides[1].left


def test_should_show_a_lone_photo_as_a_full_screen_slide_and_three_as_a_grid(photo_deck):
    slides = list(photo_deck.slides)
    crescent = next(slide for slide in slides if any("Royal Crescent" in shape.text_frame.text for shape in slide.shapes if shape.has_text_frame))
    assert named(crescent, "Background photo")
    grid = next(slide for slide in slides if any("Three buildings" in shape.text_frame.text for shape in slide.shapes if shape.has_text_frame))
    assert sum(shape.shape_type == 13 for shape in grid.shapes) == 3 and len(named(grid, "Caption")) == 3


def test_should_keep_a_four_row_comparison_with_lead_and_takeaway_on_one_slide(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = """::: {.comparison}
title: Rococo sensuality met Neoclassical order
lead: By mid-century, architects divided sharply between the sensual escapism of aristocratic salons and the moral austerity of antique temples.
left: Rococo
right: Neoclassical
takeaway: Neoclassicism replaced ornament for its own sake with civic virtue built in stone.
Curvilinear rocaille and asymmetrical cartouches — Rectilinear pediments, friezes and triglyphs
Gilded stucco, pastel wall washes and tall mirrors — Honed Portland stone, muted distemper and marble
Private boudoirs designed for pleasure and wit — Monumental civic porticos dedicated to public virtue
Organic curves dissolving structural lines — Tectonic clarity celebrating column and beam
:::
"""
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="comparison", output_dir=str(tmp_path)))
    titles = [shape.text_frame.text for slide in deck.slides for shape in slide.shapes if shape.name == "Title"]
    assert not any("(cont.)" in title for title in titles)
    assert "Neoclassicism replaced ornament" in all_text(deck)


def test_should_brand_the_table_header_and_colour_changes_and_ticks(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = "## Results by region\n\n| Region | Change | Supported |\n|---|---:|:---:|\n| Europe | +12.0% | Yes |\n| Africa | -12.5% | No |\n"
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="table", output_dir=str(tmp_path)))
    table = next(shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table)
    header_fill = table.cell(0, 0).fill.fore_color.rgb
    colours = [table.cell(row, 1).text_frame.paragraphs[0].runs[0].font.color.rgb for row in (1, 2)]
    assert header_fill is not None and colours[0] != colours[1]
    assert [table.cell(row, 2).text_frame.text for row in (1, 2)] == ["✓", "✕"]


def test_should_draw_a_straight_flowchart_as_steps(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = "## How a request flows\n\n```mermaid\nflowchart LR\n  A[Client] --> B[Gateway]\n  B --> C[Vault]\n  C --> D[Model]\n  D --> E[Answer]\n```\n"
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="steps", output_dir=str(tmp_path)))
    names = [shape.name for slide in deck.slides for shape in slide.shapes]
    assert names.count("Step") == 5 and "Gateway" in all_text(deck)


@pytest.mark.parametrize("kind", ["bar", "horizontal_bar", "stacked_bar", "line", "pie", "donut"])
def test_should_draw_every_chart_type_natively(tmp_path, monkeypatch, kind):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    datasets = '[{"label": "A", "values": [3, 5, 4]}]' if kind in ("pie", "donut") else '[{"label": "A", "values": [3, 5, 4]}, {"label": "B", "values": [2, 6, 1]}]'
    markdown = f'## Load fell after the change\n\n```chart\n{{"type": "{kind}", "labels": ["Jan", "Feb", "Mar"], "datasets": {datasets}}}\n```\n'
    deck = Presentation(generate_document(markdown, "pptx", filename_stem=kind, output_dir=str(tmp_path)))
    assert [shape for slide in deck.slides for shape in slide.shapes if shape.has_chart]


def test_should_turn_numeric_bullets_into_figures_and_six_bullets_into_a_grid(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = """## The market is large and growing

- **$32.4B Global TAM** — Recoverable battery minerals by 2032.
- **$9.8B SAM** — North American and European scrap.
- **$1.4B SOM** — Our first three plants.

Regulation drives the growth.

## Six reasons customers choose us

- **Speed** — Live in a week.
- **Price** — Half the cost.
- **Support** — Around the clock.
- **Security** — Certified.
- **Scale** — Any volume.
- **Reach** — Every region.
"""
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="grid", output_dir=str(tmp_path)))
    names = [shape.name for slide in deck.slides for shape in slide.shapes]
    assert names.count("Figure card") == 3 and names.count("Card") == 6 and len(deck.slides) == 2
    assert "Regulation drives the growth." in all_text(deck)


def test_should_draw_a_branching_flowchart_as_native_shapes_with_whole_words(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = """## Requests are checked first

```mermaid
flowchart LR
  A[User request] --> B[Gateway]
  B --> C{Contains personal data?}
  C -->|Yes| D[Replace with tokens]
  C -->|No| E[Send as is]
  D --> F[Model]
  E --> F
```
"""
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="flow", output_dir=str(tmp_path)))
    shapes = [shape for slide in deck.slides for shape in slide.shapes]
    nodes = [shape for shape in shapes if shape.name == "Flow node"]
    assert len(nodes) == 6 and sum(shape.name == "Flow connector" for shape in shapes) == 6
    assert {"Yes", "No"} <= {shape.text_frame.text for shape in shapes if shape.name == "Flow label"}
    assert not any(shape.shape_type == 13 for shape in shapes)


def test_should_draw_waterfall_harvey_balls_gantt_and_progress_rings(tmp_path, monkeypatch):
    monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
    markdown = """::: {.figures}
title: Retention rose
82% — Gross retention — Up from 74%.
64% — Weekly active — All accounts.
$4.1M — Net new ARR — Ahead of plan.
:::

## Profit grew despite higher costs

```chart
{"type": "waterfall", "labels": ["2025", "Customers", "Hosting"], "values": [12, 6.5, -3.4], "total": "2026"}
```

## We lead on controls

| Capability | Us | Them |
|---|:---:|:---:|
| Residency | Full | Partial |
| Masking | High | None |

::: {.timeline}
title: Roadmap
Q1 2026 – Q2 2026 — Hub — Lease.
Q2 2026 – Q4 2026 — Partners — Certified.
Q3 2026 – Q1 2027 — Cloud — Frankfurt.
:::
"""
    deck = Presentation(generate_document(markdown, "pptx", filename_stem="visuals", output_dir=str(tmp_path)))
    names = [shape.name for slide in deck.slides for shape in slide.shapes]
    assert names.count("Progress") == 2 and names.count("Harvey ball") == 4 and names.count("Gantt bar") == 3
    chart = next(shape.chart for slide in deck.slides for shape in slide.shapes if shape.has_chart)
    assert list(chart.plots[0].categories) == ["2025", "Customers", "Hosting", "2026"]
    assert "Residency" in all_text(deck) and "Full" not in all_text(deck)
