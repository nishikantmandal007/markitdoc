import html
import io
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from PIL import Image

from markitdoc.utils.constants import CACHE_FOLDER

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 40_000_000
commons_api = "https://commons.wikimedia.org/w/api.php"
allowed_hosts = {"upload.wikimedia.org", "thumb.wikimedia.org"}
allowed_licences = ("public domain", "pd", "cc0", "cc by", "cc-by")
max_image_bytes = 12 * 1024 * 1024
max_query_length = 60
longest_wait_seconds = 10
featured_filter = ' incategory:"Featured_pictures_on_Wikimedia_Commons"'
quality_filter = ' incategory:"Quality_images"'
image_folder = CACHE_FOLDER / "images"
choices_file = image_folder / "choices.json"
client_headers = {"User-Agent": "MarkitDoc/0.1 (https://pypi.org/project/markitdoc/) python-requests"}


@dataclass(frozen=True)
class DocumentImage:
    path: Path
    title: str
    artist: str
    licence: str

    @property
    def caption(self):
        return re.sub(r"\s*\([^)]*\)", "", self.title.rsplit(".", 1)[0]).replace("_", " ").strip()

    @property
    def source(self):
        return "https://commons.wikimedia.org/wiki/File:" + quote(self.title.replace(" ", "_"))

    @property
    def short_credit(self):
        return f"Photo: {self.author}, {self.licence}, Wikimedia Commons"

    @property
    def author(self):
        name = re.sub(r"(?i)^.*?\b(?:taken|photographed|created|uploaded|made)\s+by\s+|^(?:photo|photograph|image)\s*(?:by|:)\s*", "", self.artist)
        name = re.split(r"\.\s|[(\[;|]|\s—\s", name)[0].strip(" ,.")
        return name if 2 <= len(name) <= 40 else name[:40].rsplit(" ", 1)[0] if name else "Unknown"

    @property
    def credit(self):
        name = re.sub(r"\s*\([^)]*\)", "", self.title.rsplit(".", 1)[0]).replace("_", " ").strip()
        return f"{name} — {self.artist}, {self.licence}, via Wikimedia Commons"


def find_images(wanted: dict, ratios: dict) -> dict:
    found, used = {}, set()
    for key, query in wanted.items():
        image = find_image(query, ratios[key], used)
        if image:
            found[key] = image
            used.add(image.title)
    logger.info("Document images: %d of %d found", len(found), len(wanted))
    return found


def find_image(query: str, ratio: float, used=frozenset()) -> DocumentImage | None:
    words = re.sub(r"[^\w\s,.-]", " ", query)[:max_query_length].split()
    if not words:
        return None
    remembered = remembered_choices().get(" ".join(words).lower())
    if remembered and (image_folder / f"{remembered['sha1']}.jpg").exists() and remembered["title"] not in used:
        return DocumentImage(image_folder / f"{remembered['sha1']}.jpg", remembered["title"], remembered["artist"], remembered["licence"])
    image = search_image(words, ratio, used)
    if image:
        remember_choice(" ".join(words).lower(), image)
    return image


def remembered_choices():
    try:
        return json.loads(choices_file.read_text())
    except (OSError, ValueError):
        return {}


def remember_choice(query, image):
    choices = remembered_choices()
    choices[query] = {"sha1": image.path.stem, "title": image.title, "artist": image.artist, "licence": image.licence}
    try:
        choices_file.parent.mkdir(parents=True, exist_ok=True)
        choices_file.write_text(json.dumps(choices, sort_keys=True, indent=1))
    except OSError as error:
        logger.warning("Could not remember image choice: %s", type(error).__name__)


def search_image(words, ratio, used):
    full, shorter = " ".join(words), " ".join(words[-3:])
    name = next((plain(word) for word in words if len(word) > 3), "")
    for text, filter_text, needs_title_match, anchor in ((full, featured_filter, None, ""), (full, "", False, ""),
                                                         (full, quality_filter, False, ""), (shorter, featured_filter, False, name),
                                                         (shorter, quality_filter, False, name), (shorter, "", True, name),
                                                         (" ".join(words[-2:]), "", True, name), (full, "", None, name)):
        pages = search(f"{text} filetype:bitmap{filter_text}")
        title_words = [plain(word) for word in re.findall(r"\w+", text) if len(word) > 3 or word.isdigit() or word.isupper()]
        for _, url, title, artist, licence, sha1 in sorted(candidates(pages, ratio, used, title_words, needs_title_match, anchor))[:4]:
            path = image_folder / f"{sha1}.jpg"
            if path.exists() or save_safe_copy(url, path):
                logger.info("Document image chosen from %s search", filter_text.split(":")[-1] or "plain")
                return DocumentImage(path, title, artist, licence)
    return None


def search(text):
    try:
        response = requests.get(commons_api, headers=client_headers, timeout=15, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 12,
            "gsrsearch": text, "prop": "imageinfo", "iiprop": "url|size|mime|sha1|extmetadata", "iiurlwidth": 1600})
        return list((response.json().get("query") or {}).get("pages", {}).values())
    except (requests.RequestException, ValueError) as error:
        logger.warning("Image search failed: %s", type(error).__name__)
        return []


def plain(text):
    return "".join(letter for letter in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(letter))


def candidates(pages, ratio, used, words, needs_every_word, anchor=""):
    for page in pages:
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        licence = re.sub("<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
        artist = html.unescape(re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", ""))).strip() or "Unknown"
        title = page["title"].removeprefix("File:")
        url = info.get("thumburl") or info["url"]
        if (title in used or info.get("mime") not in ("image/jpeg", "image/png") or info["width"] < 1200
                or not licence.lower().startswith(allowed_licences) or urlparse(url).hostname not in allowed_hosts):
            continue
        if anchor and anchor not in plain(title):
            continue
        title_words = re.findall(r"\w+", plain(title))
        matches = sum(any(word == part or (len(word) > 3 and part.startswith(word)) for part in title_words) for word in words)
        needed = 1 if needs_every_word is None else len(words) if needs_every_word else max(1, len(words) - 1)
        if words and matches >= needed:
            fit = abs(info["width"] / info["height"] - ratio)
            yield (-matches, page.get("index", 99) + (1 if needs_every_word is None else 4) * fit), url, title, artist[:60], licence, info["sha1"]


def save_safe_copy(url, path: Path):
    content = download(url)
    if content is None:
        return False
    try:
        picture = Image.open(io.BytesIO(content))
        picture.load()
        path.parent.mkdir(parents=True, exist_ok=True)
        picture.convert("RGB").save(path, "JPEG", quality=86)
        return True
    except Exception as error:
        logger.warning("Image rejected: not a safe image (%s)", type(error).__name__)
        return False


def download(url):
    for attempt in range(3):
        try:
            response = requests.get(url, headers=client_headers, timeout=30)
        except requests.RequestException as error:
            logger.warning("Image download failed: %s", type(error).__name__)
            return None
        if response.status_code == 200:
            return response.content if len(response.content) <= max_image_bytes else None
        if response.status_code != 429:
            logger.warning("Image download rejected: HTTP %d", response.status_code)
            return None
        wait = int(response.headers.get("Retry-After", "0") or 0) or 2 * (attempt + 1)
        if wait > longest_wait_seconds:
            logger.warning("Wikimedia asks to wait %ds: document continues without this image", wait)
            return None
        time.sleep(wait)
    return None
