from dataclasses import dataclass
from pathlib import Path

from markitdoc.errors import ThemeError
from markitdoc.themes.theme_constants import THEMES_FOLDER
from markitdoc.themes.themes import read_theme, theme_folders


@dataclass(frozen=True)
class BrandHooks:
    docx_chrome: object = None
    docx_cover: object = None


brand_hooks_by_theme = {}


# make the theme files in folder available, with optional Word hooks for brand parts a theme file cannot describe
def register_brand(folder, docx_chrome=None, docx_cover=None):
    folder = Path(folder)
    names = [path.stem for path in folder.glob("*.yml")]
    if not names:
        raise ThemeError(f"No theme files in {folder}")
    if folder not in theme_folders:
        theme_folders.insert(0, folder)
    read_theme.cache_clear()
    for name in names:
        brand_hooks_by_theme[name] = BrandHooks(docx_chrome, docx_cover)
    return names


# the Word hooks registered for a theme, empty for the shipped themes
def brand_hooks(name):
    return brand_hooks_by_theme.get(name, BrandHooks())


# the names of the brands an application registered, without the shipped themes
def registered_brands():
    return sorted({path.stem for folder in theme_folders if folder != THEMES_FOLDER for path in folder.glob("*.yml")})


# one line telling a model what a registered brand offers, read from its theme file
def brand_summary(name):
    theme = read_theme(name)
    assets = [part for part in ("logo" if theme.logo else "", f"{len(theme.address)}-line address" if theme.address else "",
                                f"{len(theme.partners)} partner logo{'' if len(theme.partners) == 1 else 's'}" if theme.partners else "") if part]
    summary = f"template: {name} ({theme.brand or name}): {', '.join(assets) or 'colours and fonts only'}"
    if theme.address or theme.partners:
        summary += "; ::: {.cover variant=company} and {.closing variant=company} show the address and partner logos"
    return summary + "."
