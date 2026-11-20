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
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
API_HOSTS = {"commons.wikimedia.org", "www.wikidata.org"}
ALLOWED_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}
ALLOWED_LICENCES = ("public domain", "pd", "cc0", "cc by", "cc-by")
CC_LICENCE = re.compile(r"cc[ -]?(by(?:-sa)?)[ -]?(\d\.\d)", re.IGNORECASE)
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_QUERY_LENGTH = 60
LONGEST_WAIT_SECONDS = 10
STARRED_FILTER = ' incategory:"Quality_images|Featured_pictures_on_Wikimedia_Commons"'
MIN_WIDTH = 1600
FULL_BLEED_KILOPIXELS = 2000
SEARCH_RESULTS = 30
ENOUGH_CANDIDATES = 3
REMEMBERED_CHOICES = 8
ABOUT_LENGTH = 600
RELEVANT_SCORE = 3
PHOTO_SUFFIXES = (".jpg", ".jpeg")
STOP_WORDS = {"in", "at", "of", "the", "a", "an", "on", "with", "by", "and", "near", "under", "over"}
NOT_A_SUBJECT = r"name|disambiguation|wikimedia|municipality|film|album|song|band"
OFF_TOPIC = {
    "building", "apartment", "street", "road", "highway", "city", "skyline", "car", "pylon", "power", "construction",
    "factory", "residence", "cityscape", "urban", "skyscraper", "housing", "logo", "map", "diagram", "chart", "poster", "document", "screenshot",
    "sculpture", "statue", "installation", "glass", "painting", "artwork", "illustration", "drawing", "mural", "exhibit",
    "exhibition", "museum", "gallery", "replica", "model", "toy", "figurine", "stamp", "coin", "banknote"}
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

    # the deed of the licence the photo is shared under, so a reader can check its terms
    @property
    def licence_url(self):
        lowered = self.licence.lower()
        if found := CC_LICENCE.search(lowered):
            return f"https://creativecommons.org/licenses/{found.group(1)}/{found.group(2)}/"
        if "cc0" in lowered:
            return "https://creativecommons.org/publicdomain/zero/1.0/"
        return "https://creativecommons.org/publicdomain/mark/1.0/"

    # the attribution a CC licence asks for: title, author, licence with its link, source with its link, and the crop made to fit
    @property
    def full_credit(self):
        return f"“{self.caption}” by {self.author}, [{self.licence}]({self.licence_url}), via [Wikimedia Commons]({self.source}), cropped"

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
    found, used, owner = {}, set(), {}
    for key, query in wanted.items():
        image = find_image(query, ratios[key], used)
        if image:
            if image.title in owner:
                logger.warning("Photo reused on blocks %s and %s: %s; use a more specific image query", owner[image.title], key, image.title)
            found[key] = image
            used.add(image.title)
            owner.setdefault(image.title, key)
    logger.info("Document images: %d of %d found", len(found), len(wanted))
    return found


# picks an unused photo from the remembered or searched pool, reusing the best one only when every photo is used
def find_image(query: str, ratio: float, used=frozenset()) -> DocumentImage | None:
    words = re.sub(r"[^\w\s,.-]", " ", query)[:MAX_QUERY_LENGTH].split()
    if not words:
        return None
    key = " ".join(words).lower()
    pool = remembered_choices().get(key)
    pool = [one for one in [pool] if isinstance(pool, dict)] or pool or []
    pool = [one for one in pool if permitted(one["licence"])]
    if not pool:
        pool = search_pool(words, ratio)
        if pool:
            remember_choice(key, pool)
    pool = sorted((one for one in pool if one["title"].lower().endswith(PHOTO_SUFFIXES) and photo_score(one, words, ratio)[0] >= RELEVANT_SCORE),
                  key=lambda one: photo_score(one, words, ratio), reverse=True)
    if not pool:
        logger.info("No photo relevant enough for %r; the block is drawn without one", query)
    folder = image_folder()
    for pick in [one for one in pool if one["title"] not in used] + [one for one in pool if one["title"] in used]:
        path = folder / f"{pick['sha1']}.jpg"
        if path.exists() or (pick.get("url") and save_safe_copy(pick["url"], path)):
            return DocumentImage(path, pick["title"], pick["artist"], pick["licence"])
    return None


# loads a saved json mapping from the image cache, returning an empty mapping if unavailable
def cached_mapping(name):
    try:
        return json.loads((image_folder() / name).read_text())
    except (OSError, ValueError):
        return {}


# saves one entry in a json mapping in the image cache
def cache_entry(name, key, value):
    mapping = cached_mapping(name)
    mapping[key] = value
    try:
        file = image_folder() / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(mapping, sort_keys=True, indent=1))
    except OSError as error:
        logger.warning("Could not save image cache: %s", type(error).__name__)


# loads saved image choices, returning an empty mapping if unavailable
def remembered_choices():
    return cached_mapping("choices.json")


# saves the best candidates for reuse with the same search
def remember_choice(query, pool):
    cache_entry("choices.json", query, pool[:REMEMBERED_CHOICES])


# resolves a query to a Wikidata item id once, skipping names and disambiguations and remembering misses too
def depicted_item(text):
    known = cached_mapping("depicts.json")
    if text not in known:
        found = api_get(WIKIDATA_API, {"action": "wbsearchentities", "format": "json", "language": "en", "limit": 5, "search": text}).get("search")
        if found is None:
            return ""
        found = [one for one in found if not re.search(NOT_A_SUBJECT, one.get("description", ""), re.I)]
        cache_entry("depicts.json", text, found[0]["id"] if found else "")
        known = cached_mapping("depicts.json")
    return known.get(text, "")


# resolves the whole query to a Wikidata item, else its longest content-word sequence that resolves
def depicted_phrase(words):
    content = [word for word in words if word.lower() not in STOP_WORDS]
    phrases = [" ".join(words).lower()] + [" ".join(content[start:start + size]).lower()
                                           for size in range(len(content), 0, -1) for start in range(len(content) - size + 1)]
    return next((item for item in map(depicted_item, dict.fromkeys(phrases)) if item), "")


# searches Wikimedia for permitted images, stopping at the first ladder step that gives enough candidates
def search_pool(words, ratio):
    full, shorter = " ".join(words), " ".join(words[-min(2, max(1, len(words) - 1)):])
    item = depicted_phrase(words)
    filters = f" filetype:bitmap filew:>{MIN_WIDTH}" + (f" fileres:>{FULL_BLEED_KILOPIXELS}" if ratio < 1 else "")
    steps = [(f"haswbstatement:P180={item}{STARRED_FILTER}", True, False), (f"haswbstatement:P180={item}", False, False)] if item else []
    steps += [(full + STARRED_FILTER, True, False), (full, False, False)] + ([(shorter, False, True)] if shorter != full else [])
    pool = []
    for text, starred, strict in steps:
        title_words = [plain(word) for word in re.findall(r"\w+", text.split(" incategory")[0]) if len(word) > 3 or word.isdigit() or word.isupper()]
        found = candidates(search(text + filters), ratio, title_words, starred, strict, text.startswith("haswbstatement"))
        pool += [one for one in found if one["title"] not in {have["title"] for have in pool}]
        if sum(photo_score(one, words, ratio)[0] >= RELEVANT_SCORE for one in pool) >= ENOUGH_CANDIDATES:
            break
    return sorted(pool, key=lambda one: photo_score(one, words, ratio), reverse=True)[:REMEMBERED_CHOICES]


# queries Wikimedia Commons for matching image files
def search(text):
    pages = api_get(COMMONS_API, {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": SEARCH_RESULTS,
        "gsrsearch": text, "prop": "imageinfo|categories", "clshow": "!hidden", "cllimit": "max", "iiprop": "url|size|mime|sha1|extmetadata", "iiurlwidth": 1600})
    return list((pages.get("query") or {}).get("pages", {}).values())


# gets json from an allowed Wikimedia API host, returning an empty mapping on failure
def api_get(url, params):
    if urlparse(url).hostname not in API_HOSTS:
        return {}
    try:
        return requests.get(url, headers=client_headers(), timeout=15, params=params).json()
    except (requests.RequestException, ValueError) as error:
        logger.warning("Image search failed: %s", type(error).__name__)
        return {}


# removes accents and lowercases text for image-title matching
def plain(text):
    return "".join(letter for letter in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(letter))


# accepts public domain, CC0, CC BY and CC BY-SA, rejecting non-commercial and no-derivatives licences
def permitted(licence):
    lowered = licence.lower()
    return lowered.startswith(ALLOWED_LICENCES) and not re.search(r"\b(?:nc|nd)\b", lowered)


# lists the distinct word stems of a text for photo matching
def stems(text):
    return {part[:-1] if len(part) > 3 and part.endswith("s") and not part.endswith("ss") else part for part in re.findall(r"\w+", plain(text))}


# scores how well a photo suits the query: relevance first (depicts, words in title and description, off-topic penalty), then shape, quality and resolution as tie-breakers
def photo_score(pick, words, ratio):
    subject = [stem for stem in stems(" ".join(word for word in words if len(word) > 3 or word.isdigit() or word.isupper()))]
    wanted = stems(" ".join(words))
    title, about = stems(pick["title"].rsplit(".", 1)[0]), stems(pick.get("about", ""))
    hit = lambda found: sum(any(word == part or part.startswith(word) for part in found) for word in subject) / max(len(subject), 1)
    off = len((title | about) & (OFF_TOPIC - wanted))
    relevance = 4 * bool(pick.get("depicts")) + 3 * hit(title) + 2 * hit(about) - 5 * min(off, 2)
    width, height = pick.get("size", (0, 0))
    fit = abs(width / height - ratio) if height else 0
    shape = min(fit, 2) * -1 + 0.5 * (width >= height)
    return relevance, 2 * bool(pick.get("starred")) + shape + min(width * height / 4e6, 1)


# filters image search results by licence, size and content, keeping what ranking needs
def candidates(pages, ratio, words, starred=False, strict=False, depicts=False):
    found = []
    for page in pages:
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        text = lambda name: html.unescape(re.sub("<[^>]+>", " ", meta.get(name, {}).get("value", ""))).strip()
        licence = re.sub("<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
        artist = text("Artist") or "Unknown"
        title = page["title"].removeprefix("File:")
        url = info.get("thumburl") or info["url"]
        if (info.get("mime") != "image/jpeg" or info["width"] < 1200
                or not permitted(licence) or urlparse(url).hostname not in ALLOWED_HOSTS):
            continue
        title_words = re.findall(r"\w+", plain(title))
        matches = sum(any(word == part or (len(word) > 3 and part.startswith(word)) for part in title_words) for word in words)
        if strict and words and not matches:
            continue
        categories = " ".join(one["title"].removeprefix("Category:") for one in page.get("categories", []))
        about = " ".join(re.sub(r"\s+", " ", f"{text('ObjectName')} {text('ImageDescription')} {categories}").split())[:ABOUT_LENGTH]
        found.append({"title": title, "url": url, "artist": artist[:60], "licence": licence, "sha1": info["sha1"],
                      "about": about, "depicts": depicts, "starred": starred, "size": [info["width"], info["height"]]})
    return found


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
