import json

import pymupdf
import pytest
from docx import Document as WordDocument

import markitdoc
from markitdoc import Options, check_document, render
from markitdoc.cli import main
from markitdoc.guide.language import core_card
from markitdoc.guide.support import SUPPORT, SUPPORT_FORMATS, support_table
from markitdoc.themes.theme_constants import STYLE_FILE_KEYS

BOX_DOCUMENT = "## A\n\n::: columns\nx\n\ny\n:::\n\n::: box {border=thin}\nin\n:::\n"


def test_should_keep_the_core_card_short_and_name_every_top_level_key():
    card = core_card("pdf")

    assert len(card) < 4000 and all(key in card for key in STYLE_FILE_KEYS)


def test_should_put_the_core_card_before_the_catalogue_and_let_the_level_pick_it_alone():
    assert markitdoc.guide("pptx").startswith("MARKITDOC LANGUAGE") and "SLIDE DESIGN GUIDE" in markitdoc.guide("pptx")
    assert markitdoc.guide("pdf", level="core") == core_card("pdf") and "LAYOUTS" not in markitdoc.guide("pdf", level="core")
    assert all("markitdoc " not in markitdoc.guide(name) and "generate_document" not in markitdoc.guide(name) for name in markitdoc.FORMATS)
    with pytest.raises(markitdoc.UnsupportedFormatError):
        markitdoc.guide("pdf", level="tiny")


def test_should_leave_out_of_the_slide_card_what_slides_ignore():
    card = core_card("pptx")

    assert "page / pages" not in card and "dropcap" not in card and "page / pages" in core_card("pdf")


def test_should_list_every_feature_with_a_status_for_each_format():
    assert all(len(row) == 6 and row[1:4] and set(row[1:4]) <= {"full", "approximate", "ignored"} for row in SUPPORT.values())
    assert all(f"{name} " in support_table() for name in SUPPORT_FORMATS)


def test_should_note_each_approximate_or_ignored_feature_once_for_the_requested_format():
    findings = check_document(BOX_DOCUMENT + "\n::: box\nagain\n:::\n", output_format="pptx")
    notes = [finding for finding in findings if finding.severity == "info"]

    assert [note.message.split(":")[0] for note in notes] == ["columns", "boxes with borders, fill and padding"]
    assert not [finding for finding in check_document(BOX_DOCUMENT) if finding.severity == "info"]


def test_should_note_ignored_page_features_for_slides_only():
    markdown = "---\npage: {paper: a4}\n---\n## A\n\nText.\n"

    assert any("ignored in pptx" in finding.message for finding in check_document(markdown, output_format="pptx"))
    assert not any("ignored" in finding.message for finding in check_document(markdown, output_format="docx"))


def test_should_pass_the_format_option_to_check(tmp_path, capsys):
    source = tmp_path / "doc.md"
    source.write_text(BOX_DOCUMENT)

    assert main(["check", str(source), "--json", "--format", "pptx"]) == 0
    assert any(item["severity"] == "info" and "pptx" in item["message"] for item in json.loads(capsys.readouterr().out))


def test_should_write_a_skill_with_its_reference_files(tmp_path, capsys):
    assert main(["skill", "-o", str(tmp_path / "skill")]) == 0

    folder = tmp_path / "skill"
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: markitdoc\ndescription:") and "markitdoc check file.md --json" in text
    assert all(key in text for key in STYLE_FILE_KEYS)
    assert all((folder / "references" / name).stat().st_size > 200 for name in ("layouts.md", "styles.md", "charts.md"))
    assert len(capsys.readouterr().out.splitlines()) == 4


def references_document(extra=""):
    return ("---\nnumbering: decimal\nrefs: refs.yml\nlists: [figures]\n---\n# Title\n\n## Methods\n\nSee [@dewit2021] and [@fig1].\n\n"
            + extra + '```chart {#fig1 caption="Levels"}\n{"type": "bar", "labels": ["a", "b"], "datasets": [{"values": [1, 2]}]}\n```\n')


@pytest.fixture
def refs_folder(tmp_path):
    (tmp_path / "refs.yml").write_text("dewit2021: {author: [Marie de Wit], title: Floodplains, year: 2021, url: 'https://example.org/f'}\n", encoding="utf-8")
    return tmp_path


def test_should_not_number_the_generated_headings_in_pdf_and_put_them_in_the_contents(refs_folder):
    output = render(references_document().replace("---\n# Title", "toc: true\n---\n# Title", 1), "pdf", refs_folder / "out.pdf",
                    options=Options(style_folders=(refs_folder,)))
    contents = pymupdf.open(output)[0].get_text()
    text = "\n".join(page.get_text() for page in pymupdf.open(output))

    assert "1  Methods" in text and "2  References" not in text and "2  List of figures" not in text
    assert "References" in contents and "List of figures" in contents and "{.unnumbered}" not in text


def test_should_not_number_the_generated_headings_in_word(refs_folder):
    output = render(references_document(), "docx", refs_folder / "out.docx", options=Options(style_folders=(refs_folder,)))
    headings = [paragraph.text for paragraph in WordDocument(str(output)).paragraphs if paragraph.style.name.startswith("Heading")]

    assert any(heading.strip().endswith("Methods") and heading[:1].isdigit() for heading in headings)
    assert "References" in headings and "List of figures" in headings


def test_should_set_the_list_entries_in_the_body_font(refs_folder):
    markdown = references_document().replace("lists: [figures]", "lists: [figures]\ntext: {font: serif}\nfonts:\n  serif: PT Serif", 1)
    output = render(markdown, "pdf", refs_folder / "out.pdf", options=Options(style_folders=(refs_folder,)))
    page = list(pymupdf.open(output))[0]
    fonts = {span["text"]: span["font"] for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]}
    entry = next(font for text, font in fonts.items() if "Levels" in text)
    body = next(font for text, font in fonts.items() if "See" in text)

    assert entry == body and "Serif" in body


def test_should_link_a_citation_to_its_references_entry_in_pdf_and_word(refs_folder):
    options = Options(style_folders=(refs_folder,))
    pdf = pymupdf.open(render(references_document(), "pdf", refs_folder / "out.pdf", options=options))
    cited = [link["nameddest"] for page in pdf for link in page.get_links() if link.get("nameddest")]
    docx = render(references_document(), "docx", refs_folder / "out.docx", options=options)
    xml = WordDocument(str(docx)).element.xml

    assert "ref-dewit2021" in cited
    assert 'w:anchor="ref_dewit2021"' in xml and 'w:name="ref_dewit2021"' in xml


def test_should_split_the_guide_into_parts_a_model_loads_on_demand():
    for name in markitdoc.FORMATS:
        writing = markitdoc.guide(name, level="writing")
        assert len(writing) < len(markitdoc.guide(name)) * 0.6
        assert "LAYOUTS (word counts" not in writing and "read the layouts part" in writing
        assert "- cover:" in markitdoc.guide(name, level="layouts")
        assert "## Palettes" in markitdoc.guide(name, level="styles")
        assert "```mermaid" in markitdoc.guide(name, level="charts")
