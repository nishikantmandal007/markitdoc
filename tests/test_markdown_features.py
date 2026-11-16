import fitz
from helpers import generate_document


def render(markdown, tmp_path, name="features"):
    return generate_document(markdown, "pdf", filename_stem=name, output_dir=str(tmp_path))


def spans(path):
    with fitz.open(path) as pdf:
        return [(span["text"].replace("​", "").strip(), span["bbox"][0], span["bbox"][2], span["flags"])
                for page in pdf for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
                for span in line["spans"] if span["text"].strip()]


def sized_spans(path):
    with fitz.open(path) as pdf:
        return [(span["text"].strip(), span["size"]) for page in pdf for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", []) for span in line["spans"] if span["text"].strip()]


def text_of(path):
    with fitz.open(path) as pdf:
        return " ".join(" ".join(page.get_text().replace("​", "").split()) for page in pdf)


class TestMarkdownFeatures:
    def test_should_print_a_footnote_marker_and_collect_the_note(self, tmp_path):
        text = text_of(render("# Notes\n\nA claim.[^1]\n\n[^1]: The source of the claim.\n", tmp_path))

        assert "A claim.¹" in text and "¹ The source of the claim." in text and "[^1]" not in text

    def test_should_draw_checkboxes_for_task_lists(self, tmp_path):
        text = text_of(render("# Tasks\n\n- [ ] Book the venue\n- [x] Send the invitations\n", tmp_path))

        assert "☐" in text and "☑" in text and "Book the venue" in text and "[ ]" not in text

    def test_should_align_paragraphs_from_their_settings_line_without_printing_it(self, tmp_path):
        markdown = "# Align\n\nLeft text.\n\nCentred text.\n{.center}\n\nRight text.\n{.right}\n"

        found = {text: (left, right) for text, left, right, _ in spans(render(markdown, tmp_path))}

        assert found["Left text."][0] < found["Centred text."][0] < found["Right text."][0]
        assert "{.center}" not in text_of(render(markdown, tmp_path, "again"))

    def test_should_use_a_different_bullet_per_depth_and_letters_for_nested_numbers(self, tmp_path):
        text = text_of(render("# Lists\n\n- One\n  - Two\n    - Three\n\n1. First\n   1. Inner\n", tmp_path))

        assert "• One" in text and "– Two" in text and "◦ Three" in text and "a. Inner" in text

    def test_should_honour_table_column_alignment(self, tmp_path):
        markdown = "# Table\n\n| Name | Mid | Amount |\n|:---|:---:|---:|\n| alpha | beta | gamma |\n"

        found = {text: (left, right) for text, left, right, _ in spans(render(markdown, tmp_path))}

        assert found["alpha"][0] < found["beta"][0] < found["gamma"][0]

    def test_should_make_links_clickable_and_underline_only_the_span(self, tmp_path):
        path = render("# Links\n\nSee [the site](https://example.com) and [this]{.underline} only, then plain.\n", tmp_path)

        with fitz.open(path) as pdf:
            links = [link.get("uri") for link in pdf[0].get_links()]
        assert links == ["https://example.com"] and "plain." in text_of(path)

    def test_should_print_raw_html_as_text_and_render_definition_lists(self, tmp_path):
        text = text_of(render("# Terms\n\n<b>bold?</b>\n\nRetention\n: How long a record is kept.\n", tmp_path))

        assert "<b>bold?</b>" in text and "Retention How long a record is kept." in text

    def test_should_link_to_a_heading_anchor_and_leave_unknown_anchors_as_text(self, tmp_path):
        markdown = "# Report\n\nSee [the risks](#risks) and [nowhere](#missing).\n\n+++\n\n## Risks {#risks}\n\nDetails.\n"

        path = render(markdown, tmp_path)

        with fitz.open(path) as pdf:
            links = [link for page in pdf for link in page.get_links()]
            text = " ".join(page.get_text() for page in pdf)
            heading_page = next(page.number for page in pdf if "Risks" in page.get_text())
        assert len(links) == 1 and links[0]["page"] == heading_page and "{#risks}" not in text

    def test_should_number_headings_when_asked(self, tmp_path):
        text = text_of(render("---\nnumbering: decimal\n---\n# Doc\n\n## Scope\n\n### Data\n\n### Users\n\n## Risks\n", tmp_path))

        assert "1 Scope" in text and "1.1 Data" in text and "1.2 Users" in text and "2 Risks" in text

    def test_should_fill_header_and_footer_fields(self, tmp_path):
        markdown = "---\nfooter: '{title} — page {page} of {pages}'\n---\n# Field test\n\n" + "Text paragraph. " * 400

        text = text_of(render(markdown, tmp_path))

        assert "Field test — page 1 of 2" in text and "Field test — page 2 of 2" in text

    def test_should_caption_tables_and_use_list_number_styles_and_scripts(self, tmp_path):
        markdown = ("# Data\n\nTable: Revenue by region\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n{.roman}\n\n1. First\n2. Second\n\n"
                    "Water is H~2~O and area is m^2^.\n")

        text = text_of(render(markdown, tmp_path))

        assert "Table 1. Revenue by region" in text and "i. First" in text and "ii. Second" in text
        sizes = {text: size for text, size in sized_spans(render(markdown, tmp_path, "scripts"))}
        assert "H2O" in text.replace(" ", "") and sizes["2"] < sizes["Water is H"]

    def test_should_not_leave_a_single_line_at_the_bottom_of_a_page(self, tmp_path):
        filler = "\n\n".join(["Short line of text."] * 52)
        markdown = f"# Widows\n\n{filler}\n\n" + "A long closing paragraph that wraps onto several lines. " * 6 + "\n"

        with fitz.open(render(markdown, tmp_path)) as pdf:
            last_on_first = pdf[0].get_text().strip().splitlines()[-2]
        assert "A long closing paragraph" not in last_on_first

    def test_should_colour_spans_with_palette_roles_and_keep_the_rest_body_coloured(self, tmp_path):
        path = render("---\npalette: crimson\n---\n# Spans\n\nCosts were [critical]{.danger} but sales were steady.\n", tmp_path)

        with fitz.open(path) as pdf:
            colours = {span["text"].strip(): span["color"] for block in pdf[0].get_text("dict")["blocks"]
                       for line in block.get("lines", []) for span in line["spans"] if span["text"].strip()}
        assert colours["critical"] != colours["Costs were"] and colours["but sales were steady."] == colours["Costs were"]

    def test_should_draw_boxes_and_two_balanced_columns(self, tmp_path):
        markdown = ("# Review\n\n::: {.box title=\"Key facts\"}\n- First fact\n- Second fact\n:::\n\n::: {.columns}\n### Left topic\n"
                    "Left column text.\n\n### Right topic\nRight column text.\n:::\n\nAfter columns.\n")

        found = {text: left for text, left, _, _ in spans(render(markdown, tmp_path))}

        assert "Key facts" in found and "First fact" in found and "{.box" not in " ".join(found)
        assert found["Right topic"] > found["Left topic"] + 50 and "After columns." in found

    def test_should_fill_landscape_pages_and_not_add_a_blank_page_after_a_wide_table(self, tmp_path):
        header = "| " + " | ".join(f"Quarterly measure {column}" for column in range(1, 11)) + " |"
        row = "| " + " | ".join(f"Considerably long value {column}" for column in range(1, 11)) + " |"
        markdown = f"---\npaper: warm\n---\n# Wide\n\nBefore.\n\n{header}\n|{'---|' * 10}\n{row}\n"

        with fitz.open(render(markdown, tmp_path)) as pdf:
            pages = [(page.rect.width > page.rect.height, page.get_pixmap(dpi=10).pixel(int(page.rect.width / 72 * 10) - 2, 5)) for page in pdf]
        assert len(pages) == 2 and pages[1][0] and pages[1][1] != (255, 255, 255)

    def test_should_keep_every_chapter_paragraph_and_number_list_items_once(self, tmp_path):
        chapter = "::: {.chapter}\ntitle: Story\nbody: First part. || Second part. || Third part kept.\n:::\n"
        listing = "1. Item one\n\n   Its second paragraph.\n\n2. Item two\n"

        text = text_of(render(chapter + "\n" + listing, tmp_path))

        assert "Third part kept." in text and "2. Item two" in text and "3." not in text

    def test_should_survive_malformed_chart_data(self, tmp_path):
        markdown = '# Data\n\n```chart\n{"type": "bar", "labels": ["A"], "datasets": [1]}\n```\n\nStill here.\n'

        assert "Still here." in text_of(render(markdown, tmp_path))

    def test_should_paint_a_marker_behind_highlighted_words(self, tmp_path):
        path = render("---\npalette: ochre\n---\n# Marker\n\nKeep [cash above six months]{.highlight} of costs.\n", tmp_path)

        with fitz.open(path) as pdf:
            page = pdf[0]
            words = [word for word in page.get_text("words") if word[4] in ("cash", "months")]
            fills = [drawing["rect"] for drawing in page.get_drawings() if drawing.get("fill") and drawing["rect"].height < 25]
        assert words and any(fill.x0 <= words[0][0] + 1 and fill.x1 >= words[-1][2] - 1 for fill in fills)

    def test_should_hyphenate_justified_text(self, tmp_path):
        paragraph = "Internationalisation and harmonisation of interoperability requirements remain contentious. " * 6
        markdown = f"# Text\n\n::: {{.sidebar}}\n{paragraph}\n:::\n"

        with fitz.open(render(markdown, tmp_path)) as pdf:
            lines = pdf[0].get_text().splitlines()
        assert any(line.rstrip().endswith("-") for line in lines)

    def test_should_draw_display_maths_as_vector_with_alt_text_and_inline_maths_as_text(self, tmp_path):
        markdown = "# Maths\n\nThe rate is $r = C/\\tau$ per second.\n\n$$\n\\sum_{i=1}^{n} x_i^2\n$$\n"

        path = render(markdown, tmp_path)

        with fitz.open(path) as pdf:
            assert "r = C/τ" in pdf[0].get_text() and len(pdf[0].get_drawings()) > 3
            assert b"/Alt" in open(path, "rb").read()

    def test_should_put_page_notes_at_the_bottom_of_the_page(self, tmp_path):
        markdown = "---\nnotes: page\n---\n# Notes\n\nA claim with a source.[^1]\n\n[^1]: The source text.\n"

        with fitz.open(render(markdown, tmp_path)) as pdf:
            note = [block for block in pdf[0].get_text("blocks") if "The source text." in block[4]][0]
            height = pdf[0].rect.height
        assert note[1] > height * 0.8

    def test_should_mark_language_and_show_the_document_title(self, tmp_path):
        data = open(render("---\nlang: de\n---\n# Bericht\n\nText.\n", tmp_path), "rb").read()

        assert b"/Lang" in data and b"(de)" in data and b"/DisplayDocTitle true" in data

    def test_should_turn_common_latex_into_readable_inline_text(self):
        from markitdoc.markup.inline import inline_maths

        assert inline_maths(r"R_{\oplus} = 6{,}378.14 \text{ km}") == "R⊕ = 6,378.14 km"
        assert inline_maths(r"\varepsilon = \frac{v^2}{2} - \frac{\mu}{r}") == "ε = v²/2 - μ/r"
        assert inline_maths(r"\frac{a+b}{c}") == "(a+b)/c" and inline_maths(r"\Delta v \approx 3.9\ \mathrm{km/s}") == "Δ v ≈ 3.9 km/s"

    def test_should_ignore_a_page_break_marker_on_a_mostly_empty_page_but_honour_it_near_the_bottom(self, tmp_path):
        short = text_of(render("# Doc\n\nOne short paragraph.\n\n+++\n\n## Next section\n\nMore text.\n", tmp_path, "short"))
        long_markdown = "# Doc\n\n" + "\n\n".join(["A paragraph of filler text for the page."] * 45) + "\n\n+++\n\n## Next section\n\nMore.\n"

        with fitz.open(render(long_markdown, tmp_path, "long")) as pdf:
            next_section_page = next(page.number for page in pdf if "Next section" in page.get_text())

        assert "1 / 1" in short and next_section_page == 1

    def test_should_keep_paragraph_geometry_when_words_are_coloured(self, tmp_path):
        sentence = "The quarterly results show steady growth across every region we operate in today. " * 4
        plain = f"# Geometry\n\n{sentence}\n\nAfter."
        coloured = plain.replace("steady growth", "[steady growth]{.success}")

        def after_position(name, markdown):
            with fitz.open(render(markdown, tmp_path, name)) as pdf:
                return next(word[1] for word in pdf[0].get_text("words") if word[4] == "After.")

        assert abs(after_position("plain", plain) - after_position("coloured", coloured)) < 1.0


def test_should_keep_a_heading_on_the_same_page_as_its_table(tmp_path):
    filler = "\n\n".join(["Filler sentence for the page. " * 12] * 7)
    rows = "\n".join(f"| Row {number} | " + "long wrapped cell text " * 6 + " |" for number in range(12))
    markdown = f"# Report\n\n{filler}\n\n### Schedule heading\n\nTable: Schedule caption\n\n| Time | Activity |\n|---|---|\n{rows}\n"

    path = generate_document(markdown, "pdf", filename_stem="kept", output_dir=str(tmp_path))

    with fitz.open(path) as pdf:
        pages = {word: next(page.number for page in pdf if word in page.get_text()) for word in ("Schedule heading", "Schedule caption", "Row 0")}
    assert len(set(pages.values())) == 1


def test_should_draw_box_character_art_unwrapped_on_its_own_lines(tmp_path):
    art = "┌──────┐\n│ Base │──┐\n└──────┘  │\n          └── Top " + "─" * 120
    markdown = f"# Notes\n\nIntro.\n\n```\n{art}\n```\n\n```python\nprint('kept')\n```\n"

    with fitz.open(generate_document(markdown, "pdf", filename_stem="art", output_dir=str(tmp_path))) as pdf:
        lines = [line for page in pdf for line in page.get_text().splitlines()]
    assert "│ Base │──┐" in lines and any(line.strip().startswith("└── Top ──") for line in lines) and "print('kept')" in lines


def test_should_keep_a_table_caption_on_the_landscape_page_of_its_wide_table(tmp_path):
    header = "| " + " | ".join(f"Column heading {n}" for n in range(9)) + " |"
    rows = "\n".join("| " + " | ".join(f"value {r}.{n} long" for n in range(9)) + " |" for r in range(4))
    markdown = f"# Wide\n\nIntro.\n\nTable: Every quarter by region\n\n{header}\n|{'---|' * 9}\n{rows}\n"

    with fitz.open(generate_document(markdown, "pdf", filename_stem="wide", output_dir=str(tmp_path))) as pdf:
        page = next(page for page in pdf if "Every quarter by region" in page.get_text())
        assert page.rect.width > page.rect.height and "value 0.0" in page.get_text()


def test_should_print_section_header_classification_watermark_and_author(tmp_path):
    markdown = ("---\nheader: \"{section}\"\nclassification: Confidential\nwatermark: Draft\nauthor: Jane Doe\n---\n# Report\n\n"
                "## Findings\n\n" + "Sentence about findings. " * 300 + "\n\n## Totals\n\n| Item | Cost |\n|---|---:|\n| A | 1 |\n| B | 2 |\n"
                "| Total | 3 |\n")

    with fitz.open(generate_document(markdown, "pdf", filename_stem="marks", output_dir=str(tmp_path))) as pdf:
        assert pdf.metadata["author"] == "Jane Doe"
        second = pdf[1].get_text()
        assert "Findings" in second.splitlines()[:6] and "CONFIDENTIAL" in second and "DRAFT" in second
        bold = [span["text"] for page in pdf for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
                for span in line["spans"] if span["flags"] & 16]
        assert "Total" in bold


def test_should_not_end_a_quote_with_a_dash_when_nobody_is_credited(tmp_path):
    markdown = "::: {.closing}\ntitle: The end\nquote: Short words stay.\nbody: Thanks for reading.\n:::\n"

    with fitz.open(generate_document(markdown, "pdf", filename_stem="quote", output_dir=str(tmp_path))) as pdf:
        text = " ".join(page.get_text() for page in pdf)
    assert "Short words stay." in text and "stay. —" not in text and "stay.—" not in text
