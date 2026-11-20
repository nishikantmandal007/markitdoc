import shutil
from pathlib import Path

import fitz
import pytest
from docx import Document as WordDocument
from PIL import Image
from pptx import Presentation

import markitdoc
from markitdoc.themes.themes import read_theme, theme_folders
from markitdoc.visuals.logos import logo_row, trimmed_logo

FIXTURES = Path(__file__).parent / "fixtures" / "brand"
COMPANY_COVER = "::: {.cover variant=company}\nkicker: Annual review\ntitle: Globex in 2026\nsubtitle: What changed.\n:::\n\n## Results\n\nRevenue grew.\n"


@pytest.mark.parametrize("count", [0, 1, 7, 15])
def test_should_place_every_logo_inside_the_area(count):
    ratios = [(4.0, 1.0, 2.5)[index % 3] for index in range(count)]

    places = logo_row(ratios, 170, 12, 6)

    assert len(places) == count
    assert all(x >= 0 and top >= -1e-9 and x + width <= 170 + 1e-9 and top + height <= 12 + 1e-9 for x, top, width, height in places)


def test_should_give_wide_and_square_logos_the_same_visual_weight():
    (_, _, wide_width, wide_height), (_, _, square_width, square_height) = logo_row([4.0, 1.0], 170, 12, 6)

    assert wide_width * wide_height == pytest.approx(square_width * square_height) and wide_height < square_height


def test_should_trim_white_and_transparent_margins(tmp_path):
    picture = Image.new("RGBA", (400, 200), (255, 255, 255, 0))
    picture.paste((255, 255, 255, 255), (20, 20, 380, 180))
    picture.paste((200, 30, 30, 255), (100, 60, 300, 140))
    picture.save(tmp_path / "logo.png")

    with Image.open(trimmed_logo(tmp_path / "logo.png")) as trimmed:
        assert trimmed.size == (200, 80)


@pytest.fixture(scope="module")
def globex(tmp_path_factory):
    folder = tmp_path_factory.mktemp("globex")
    shutil.copy(FIXTURES / "logo.png", folder / "logo.png")
    partners = []
    for index in range(15):
        Image.new("RGB", ((400, 100, 250)[index % 3], 100), (30 * (index % 8), 90, 160)).save(folder / f"partner{index}.png")
        partners.append(f"  - partner{index}.png")
    theme = [line for line in (FIXTURES / "acme.yml").read_text().splitlines()
             if not line.startswith(("name:", "master:", "content_layout:", "master_sample_text", "  - Unlocking", "  - Presented"))]
    text = "\n".join(theme).split("partners:")[0] + "partners:\n" + "\n".join(partners) + "\n"
    (folder / "globex.yml").write_text("name: globex\n" + text.replace("- {file: logo.png, height: 8}\n", ""))
    markitdoc.register_brand(folder)
    yield folder
    theme_folders.remove(folder)
    read_theme.cache_clear()


def test_should_show_every_partner_logo_and_the_address_on_a_company_cover(globex, tmp_path):
    pdf = markitdoc.render(COMPANY_COVER, "pdf", tmp_path / "cover.pdf", template="globex")
    word = markitdoc.render(COMPANY_COVER, "docx", tmp_path / "cover.docx", template="globex")
    deck = markitdoc.render(COMPANY_COVER, "pptx", tmp_path / "cover.pptx", template="globex")

    with fitz.open(pdf) as document:
        assert len(document[0].get_images()) == 16 and "1 Example Street" in document[0].get_text()
    assert len(WordDocument(word).inline_shapes) == 16
    cover = Presentation(deck).slides[0]
    assert len([shape for shape in cover.shapes if shape.name == "Partner logo"]) == 15 and any(shape.name == "Logo" for shape in cover.shapes)


def test_should_show_a_branded_deck_title_once(tmp_path):
    deck = Presentation(markitdoc.render("# Quarterly review\n\n## Results\n\nRevenue grew.\n", "pptx", tmp_path / "deck.pptx", template="acme"))

    titled = [slide for slide in deck.slides if any(shape.has_text_frame and "Quarterly review" in shape.text_frame.text for shape in slide.shapes)]
    assert len(titled) == 1


def test_should_tell_a_model_what_each_registered_brand_offers():
    summary = markitdoc.brand_summary("acme")

    assert summary == ("template: acme (Acme Tools): logo, 3-line address, 1 partner logo; ::: {.cover variant=company} and "
                       "{.closing variant=company} show the address and partner logos.")
    assert "acme" in markitdoc.registered_brands() and "professional" not in markitdoc.registered_brands()
    assert summary in markitdoc.guide("pdf", "writing") and summary in markitdoc.guide("pptx", "writing")


def test_should_match_master_text_whatever_its_punctuation():
    from markitdoc.pptx.brand_cover import letters_of

    assert letters_of("Compliant Data, Boundless Potential") == letters_of("Compliant  Data Boundless Potential")


def test_should_give_a_brand_deck_without_a_master_its_logo_footer_and_colours(globex, tmp_path):
    deck = Presentation(markitdoc.render(COMPANY_COVER, "pptx", tmp_path / "deck.pptx", template="globex"))
    content = deck.slides[1]
    names = [shape.name for shape in content.shapes]

    assert "Logo" in names and names.count("Accent bar") == 2
    assert any(shape.name == "Footer" and "acme.example" in shape.text_frame.text for shape in content.shapes)
    title = next(shape for shape in content.shapes if shape.has_text_frame and shape.text_frame.text == "Results")
    assert str(title.text_frame.paragraphs[0].runs[0].font.color.rgb) == "0F766E"
    assert any(shape.name == "Tagline" for shape in deck.slides[0].shapes)
