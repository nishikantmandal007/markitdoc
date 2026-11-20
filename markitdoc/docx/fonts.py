from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from fontTools.ttLib import TTFont, TTLibError
from lxml import etree

from markitdoc.themes.theme_constants import BUNDLED_FONTS
from markitdoc.utils.constants import ASSETS_FOLDER
from markitdoc.utils.helpers import FONT_FAMILIES, SANS_FONT

FONT_FOLDER = ASSETS_FOLDER / "fonts"
WORD_FONT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
FONT_LICENCE_REL = "https://pypi.org/project/markitdoc/relationships/font-license"
FONT_LICENCES = {"Inter": "Inter", "PT Serif": "PTSerif", "Noto Sans": "Noto",
                 "IBM Plex Sans": "IBMPlexSans", "JetBrains Mono": "JetBrainsMono"}
FONT_VARIANTS = ("Regular", "Bold", "Italic", "BoldItalic")


# reads the font family Office uses, including family names in locally supplied font files
@lru_cache(maxsize=64)
def word_font(path):
    path = Path(path)
    if path.parent == FONT_FOLDER and (family := FONT_FAMILIES.get(path.stem.split("-")[0])):
        return family
    try:
        with TTFont(path, lazy=True) as font:
            return font["name"].getDebugName(1) or SANS_FONT
    except (OSError, KeyError, TTLibError, ValueError):
        return SANS_FONT


# embeds licensed bundled fonts using the OOXML font-table relationships and obfuscation
def embed_fonts(document, used_files):
    families = sorted({word_font(path) for path in used_files if Path(path).parent == FONT_FOLDER} & FONT_LICENCES.keys())
    if not families:
        return
    table = document.part.part_related_by(RT.FONT_TABLE)
    root = parse_xml(table.blob)
    existing = {font.get(qn("w:name")): font for font in root}
    for family in families:
        font = existing.get(family)
        if font is None:
            font = OxmlElement("w:font")
            font.set(qn("w:name"), family)
            root.append(font)
        for variant, filename in zip(FONT_VARIANTS, BUNDLED_FONTS[family.lower()]):
            if not filename.endswith(f"-{variant}.ttf"):
                continue
            guid = uuid5(NAMESPACE_URL, f"markitdoc/fonts/{filename}")
            original = (FONT_FOLDER / filename).read_bytes()
            header = bytes(byte ^ guid.bytes[::-1][index % 16] for index, byte in enumerate(original[:32]))
            part = Part(PackURI(f"/word/fonts/{filename[:-4]}.odttf"), WORD_FONT_TYPE, header + original[32:], table.package)
            embedding = OxmlElement(f"w:embed{variant}")
            embedding.set(qn("r:id"), table.relate_to(part, RT.FONT))
            embedding.set(qn("w:fontKey"), "{" + str(guid).upper() + "}")
            font.append(embedding)
        licence = FONT_FOLDER / f"OFL-{FONT_LICENCES[family]}.txt"
        part = Part(PackURI(f"/word/fonts/{licence.name}"), "text/plain", licence.read_bytes(), table.package)
        table.relate_to(part, FONT_LICENCE_REL)
    table._blob = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
    settings = document.settings.element
    settings.insert_element_before(OxmlElement("w:embedTrueTypeFonts"), "w:saveSubsetFonts", "w:defaultTabStop", "w:compat")
