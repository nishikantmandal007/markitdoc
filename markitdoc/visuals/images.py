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

from markitdoc.options import options_in_use
from markitdoc.utils.constants import CACHE_FOLDER

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 40_000_000
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}
ALLOWED_LICENCES = ("public domain", "pd", "cc0", "cc by", "cc-by")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_QUERY_LENGTH = 60
LONGEST_WAIT_SECONDS = 10
FEATURED_FILTER = ' incategory:"Featured_pictures_on_Wikimedia_Commons"'
QUALITY_FILTER = ' incategory:"Quality_images"'
IMAGE_FOLDER = CACHE_FOLDER / "images"
CLIENT_HEADERS = {"User-Agent": "MarkitDoc/0.1 (https://pypi.org/project/markitdoc/) python-requests"}


@dataclass(frozen=True)
class DocumentImage:
    path: Path
    title: str
    artist: str
    licence: str

    # adds a numbered figure caption with its optional credit and source
    @property
    def caption(self):
        return re.sub(r"\s*\([^)]*\)", "", self.title.rsplit(".", 1)[0]).replace("_", " ").strip()

    # returns the Wikimedia Commons page for the image
    @property
    def source(self):
        return "https://commons.wikimedia.org/wiki/File:" + quote(self.title.replace(" ", "_"))

    # formats a compact image credit for display
    @property
    def short_credit(self):
        return f"Photo: {self.author}, {self.licence}, Wikimedia Commons"

    # extracts a short author name from image attribution text
    @property
    def author(self):
        name = re.sub(r"(?i)^.*?\b(?:taken|photographed|created|uploaded|made)\s+by\s+|^(?:photo|photograph|image)\s*(?:by|:)\s*", "", self.artist)
        name = re.split(r"\.\s|[(\[;|]|\s—\s", name)[0].strip(" ,.")
        return name if 2 <= len(name) <= 40 else name[:40].rsplit(" ", 1)[0] if name else "Unknown"

    # formats the full image credit and source attribution
    @property
    def credit(self):
        name = re.sub(r"\s*\([^)]*\)", "", self.title.rsplit(".", 1)[0]).replace("_", " ").strip()
        return f"{name} — {self.artist}, {self.licence}, via Wikimedia Commons"


# returns the image cache folder in use
def image_folder():
    return options_in_use().cache_folder / "images" if options_in_use().cache_folder else IMAGE_FOLDER


# returns request headers with the user agent in use
def client_headers():
    user_agent = options_in_use().user_agent
    return {**CLIENT_HEADERS, "User-Agent": user_agent} if user_agent is not None else CLIENT_HEADERS


# finds distinct images for the requested document sections
def find_images(wanted: dict, ratios: dict) -> dict:
    found, used = {}, set()
    for key, query in wanted.items():
        image = find_image(query, ratios[key], used)
        if image:
            found[key] = image
            used.add(image.title)
    logger.info("Document images: %d of %d found", len(found), len(wanted))
    return found


# reuses a remembered image or searches for a suitable match
def find_image(query: str, ratio: float, used=frozenset()) -> DocumentImage | None:
    words = re.sub(r"[^\w\s,.-]", " ", query)[:MAX_QUERY_LENGTH].split()
    if not words:
        return None
    remembered = remembered_choices().get(" ".join(words).lower())
    folder = image_folder()
    if remembered and (folder / f"{remembered['sha1']}.jpg").exists() and remembered["title"] not in used:
        return DocumentImage(folder / f"{remembered['sha1']}.jpg", remembered["title"], remembered["artist"], remembered["licence"])
    image = search_image(words, ratio, used)
    if image:
        remember_choice(" ".join(words).lower(), image)
    return image


# loads saved image choices, returning an empty mapping if unavailable
def remembered_choices():
    try:
        choices_file = image_folder() / "choices.json"
        return json.loads(choices_file.read_text())
    except (OSError, ValueError):
        return {}


# saves the selected image for reuse with the same search
def remember_choice(query, image):
    choices = remembered_choices()
    choices[query] = {"sha1": image.path.stem, "title": image.title, "artist": image.artist, "licence": image.licence}
    try:
        choices_file = image_folder() / "choices.json"
        choices_file.parent.mkdir(parents=True, exist_ok=True)
        choices_file.write_text(json.dumps(choices, sort_keys=True, indent=1))
    except OSError as error:
        logger.warning("Could not remember image choice: %s", type(error).__name__)


# searches Wikimedia for a permitted image matching the query
def search_image(words, ratio, used):
    folder = image_folder()
    full, shorter = " ".join(words), " ".join(words[-3:])
    name = next((plain(word) for word in words if len(word) > 3), "")
    for text, filter_text, needs_title_match, anchor in ((full, FEATURED_FILTER, None, ""), (full, "", False, ""),
                                                         (full, QUALITY_FILTER, False, ""), (shorter, FEATURED_FILTER, False, name),
                                                         (shorter, QUALITY_FILTER, False, name), (shorter, "", True, name),
                                                         (" ".join(words[-2:]), "", True, name), (full, "", None, name)):
        pages = search(f"{text} filetype:bitmap{filter_text}")
        title_words = [plain(word) for word in re.findall(r"\w+", text) if len(word) > 3 or word.isdigit() or word.isupper()]
        for _, url, title, artist, licence, sha1 in sorted(candidates(pages, ratio, used, title_words, needs_title_match, anchor))[:4]:
            path = folder / f"{sha1}.jpg"
            if path.exists() or save_safe_copy(url, path):
                logger.info("Document image chosen from %s search", filter_text.split(":")[-1] or "plain")
                return DocumentImage(path, title, artist, licence)
    return None


# queries Wikimedia Commons for matching image files
def search(text):
    try:
        response = requests.get(COMMONS_API, headers=client_headers(), timeout=15, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 12,
            "gsrsearch": text, "prop": "imageinfo", "iiprop": "url|size|mime|sha1|extmetadata", "iiurlwidth": 1600})
        return list((response.json().get("query") or {}).get("pages", {}).values())
    except (requests.RequestException, ValueError) as error:
        logger.warning("Image search failed: %s", type(error).__name__)
        return []


# removes accents and lowercases text for image-title matching
def plain(text):
    return "".join(letter for letter in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(letter))


# filters and ranks image search results by license, content, and shape
def candidates(pages, ratio, used, words, needs_every_word, anchor=""):
    for page in pages:
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        licence = re.sub("<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
        artist = html.unescape(re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", ""))).strip() or "Unknown"
        title = page["title"].removeprefix("File:")
        url = info.get("thumburl") or info["url"]
        if (title in used or info.get("mime") not in ("image/jpeg", "image/png") or info["width"] < 1200
                or not licence.lower().startswith(ALLOWED_LICENCES) or urlparse(url).hostname not in ALLOWED_HOSTS):
            continue
        if anchor and anchor not in plain(title):
            continue
        title_words = re.findall(r"\w+", plain(title))
        matches = sum(any(word == part or (len(word) > 3 and part.startswith(word)) for part in title_words) for word in words)
        needed = 1 if needs_every_word is None else len(words) if needs_every_word else max(1, len(words) - 1)
        if words and matches >= needed:
            fit = abs(info["width"] / info["height"] - ratio)
            yield (-matches, page.get("index", 99) + (1 if needs_every_word is None else 4) * fit), url, title, artist[:60], licence, info["sha1"]


# validates a downloaded image and saves a JPEG copy
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


# downloads an image with bounded retries for rate limiting
def download(url):
    for attempt in range(3):
        try:
            response = requests.get(url, headers=client_headers(), timeout=30)
        except requests.RequestException as error:
            logger.warning("Image download failed: %s", type(error).__name__)
            return None
        if response.status_code == 200:
            return response.content if len(response.content) <= MAX_IMAGE_BYTES else None
        if response.status_code != 429:
            logger.warning("Image download rejected: HTTP %d", response.status_code)
            return None
        wait = int(response.headers.get("Retry-After", "0") or 0) or 2 * (attempt + 1)
        if wait > LONGEST_WAIT_SECONDS:
            logger.warning("Wikimedia asks to wait %ds: document continues without this image", wait)
            return None
        time.sleep(wait)
    return None
