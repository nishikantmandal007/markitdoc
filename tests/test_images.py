import json
from pathlib import Path

import pytest
from PIL import Image

from markitdoc import Options
from markitdoc.options import using_options
from markitdoc.visuals import images
from markitdoc.visuals.images import find_image, find_images

FIXTURES = Path(__file__).parent / "fixtures" / "commons"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeWikimedia:
    def __init__(self, monkeypatch, tmp_path, wikidata="wikidata_wetland.json", answers=None):
        self.calls, self.wikidata, self.answers = [], wikidata, answers or []
        monkeypatch.setattr("markitdoc.visuals.images.requests.get", self.get)
        monkeypatch.setattr(images, "save_safe_copy", self.save)
        self.options = Options(cache_folder=tmp_path)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params", {})))
        name = self.wikidata if "wikidata" in url else self.answers.pop(0) if self.answers else "empty.json"
        return type("Response", (), {"json": lambda response: fixture(name)})()

    def save(self, url, path):
        Image.new("RGB", (4, 4)).save(path, "JPEG")
        return True

    def searches(self):
        return [params["gsrsearch"] for url, params in self.calls if "commons" in url]


def wetland(monkeypatch, tmp_path, **kwargs):
    return FakeWikimedia(monkeypatch, tmp_path, **kwargs)


class TestPhotoSearch:
    def test_should_add_server_side_filters_and_ask_for_thirty_results(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"] * 5)
        with using_options(fake.options):
            find_image("wetland", 1.5)

        commons = [params for url, params in fake.calls if "commons" in url]
        assert all(params["gsrlimit"] == 30 for params in commons)
        assert all("filemime:image/jpeg filew:>1600" in params["gsrsearch"] for params in commons)

    def test_should_ask_for_resolution_only_on_full_bleed_slots(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"] * 5)
        with using_options(fake.options):
            find_image("wetland", 0.7)
            find_image("marsh", 1.9)

        full, band = fake.searches()[0], fake.searches()[-1]
        assert "fileres:>" in full and "fileres:>" not in band

    def test_should_fall_back_down_the_ladder_in_order(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, wikidata="wikidata_none.json")
        with using_options(fake.options):
            assert find_image("reed wetland", 1.5) is None

        steps = [text.split(" filemime")[0] for text in fake.searches()]
        assert steps == ['reed wetland incategory:"Quality_images|Featured_pictures_on_Wikimedia_Commons"', "reed wetland", "wetland"]

    def test_should_stop_at_the_first_step_with_enough_candidates(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_starred.json"])
        with using_options(fake.options):
            assert find_image("wetland", 1.5)

        assert len(fake.searches()) == 1

    def test_should_reject_unlicensed_and_small_images(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"])
        with using_options(fake.options):
            find_image("wetland", 1.5)
            titles = {pick["title"] for pick in json.loads((tmp_path / "images" / "choices.json").read_text())["wetland"]}

        assert titles == {"Wetland at dawn.jpg", "Wetland birds.jpg", "Wetland marsh.jpg"}

    def test_should_remember_at_most_eight_candidates(self, monkeypatch, tmp_path):
        pages = []
        for number in range(12):
            template = json.loads(json.dumps(fixture("wetland_starred.json")["query"]["pages"]["0"]))
            template["title"], template["imageinfo"][0]["sha1"] = f"File:Wetland {number}.jpg", f"sha{number}"
            pages.append(template)
        fake = wetland(monkeypatch, tmp_path)
        fixture_pages = {"query": {"pages": {str(i): page for i, page in enumerate(pages)}}}
        monkeypatch.setattr("markitdoc.visuals.images.requests.get", lambda url, **kwargs: type("Response", (), {
            "json": lambda response: {"search": []} if "wikidata" in url else fixture_pages})())
        with using_options(fake.options):
            find_image("wetland", 1.5)
            saved = json.loads((tmp_path / "images" / "choices.json").read_text())["wetland"]

        assert len(saved) == 8


class TestDistinctPhotos:
    def test_should_give_three_slots_three_different_photos(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"])
        with using_options(fake.options):
            found = find_images({1: "wetland", 2: "wetland", 3: "wetland"}, {1: 1.5, 2: 1.5, 3: 1.5})

        assert len({image.title for image in found.values()}) == 3

    def test_should_reuse_the_best_photo_only_when_the_pool_is_exhausted_and_say_so(self, monkeypatch, tmp_path, caplog):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_one.json"] * 4)
        with using_options(fake.options), caplog.at_level("WARNING"):
            found = find_images({1: "wetland", 2: "wetland"}, {1: 1.5, 2: 1.5})

        assert len(found) == 2 and found[1].title == found[2].title
        assert "reused on blocks 1 and 2" in caplog.text and "more specific image query" in caplog.text

    def test_should_never_leave_a_slot_empty_when_a_usable_photo_exists(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_one.json"] * 8)
        with using_options(fake.options):
            found = find_images({n: "wetland" for n in range(4)}, {n: 1.5 for n in range(4)})

        assert set(found) == {0, 1, 2, 3}


@pytest.mark.parametrize("licence", ["All rights reserved", "GFDL", "CC BY-NC 4.0", "CC BY-ND 2.0", "CC BY-NC-SA 3.0", "cc by-nc 2.0"])
def test_should_reject_non_permitted_licences(licence):
    page = json.loads(json.dumps(fixture("wetland_one.json")["query"]["pages"]["0"]))
    page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = licence

    assert images.candidates([page], 1.5, []) == []


@pytest.mark.parametrize("licence", ["CC BY 4.0", "CC BY-SA 3.0", "CC0", "Public domain"])
def test_should_accept_open_licences(licence):
    page = json.loads(json.dumps(fixture("wetland_one.json")["query"]["pages"]["0"]))
    page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = licence

    assert len(images.candidates([page], 1.5, [])) == 1


def test_should_skip_a_remembered_non_commercial_candidate(monkeypatch, tmp_path):
    fake = wetland(monkeypatch, tmp_path, answers=["wetland_one.json"])
    (tmp_path / "images").mkdir()
    old = {"sha1": "oldsha", "title": "Old.jpg", "artist": "X", "licence": "CC BY-NC 4.0", "url": "https://upload.wikimedia.org/o.jpg"}
    (tmp_path / "images" / "choices.json").write_text(json.dumps({"wetland": [old]}))
    with using_options(fake.options):
        image = find_image("wetland", 1.5)

    assert image.title == "Wetland at dawn.jpg"


class TestPhotoRelevance:
    def titles(self, monkeypatch, tmp_path, query, answer, ratio=1.5, wikidata="wikidata_none.json"):
        fake = wetland(monkeypatch, tmp_path, wikidata=wikidata, answers=[answer] * 3)
        with using_options(fake.options):
            find_image(query, ratio)
            return [pick["title"] for pick in json.loads((tmp_path / "images" / "choices.json").read_text())[query]]

    def test_should_rank_a_wetland_with_buildings_below_a_plain_reed_marsh(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "wetland marsh", "wetland_mixed.json")

        assert titles.index("Reed marsh at sunrise.jpg") < titles.index("Wetland marsh near town.jpg")

    def test_should_not_penalise_city_photos_when_the_query_says_city(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "city street", "city_mixed.json")

        assert titles[0] == "City street at night.jpg"

    def test_should_never_let_a_map_or_diagram_win_a_cover_slot(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "river delta", "map_only_and_photo.json", ratio=0.7)

        assert titles[0] == "Delta at dusk.jpg"

    def test_should_rerank_remembered_candidates_with_the_same_score(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path)
        pool = images.candidates(fixture("wetland_mixed.json")["query"]["pages"].values(), 1.5, ["wetland", "marsh"])
        (tmp_path / "images").mkdir()
        (tmp_path / "images" / "choices.json").write_text(json.dumps({"wetland marsh": pool}))
        with using_options(fake.options):
            image = find_image("wetland marsh", 1.5)

        assert image.title == "Reed marsh at sunrise.jpg"

    def test_should_rank_a_real_heron_above_a_sculpture_of_herons(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "heron in reeds", "heron_art.json")

        assert titles == ["Grey heron in reeds.jpg", "Heron sculpture in reeds.jpg"]

    def test_should_not_penalise_sculptures_when_the_query_says_glass_sculpture(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "glass sculpture", "heron_art.json")

        assert titles[0] == "Heron sculpture in reeds.jpg"

    def test_should_rank_a_photo_whose_only_art_signal_is_a_category_below_a_real_heron(self, monkeypatch, tmp_path):
        titles = self.titles(monkeypatch, tmp_path, "heron in reeds", "heron_category_art.json")

        assert titles == ["Grey heron in reeds.jpg", "Yellow Herons and Reeds.jpg"]


def test_should_use_only_relevant_photos_never_graphics(tmp_path, monkeypatch):
    from markitdoc.visuals import images

    pool = [{"title": "Smart city traffic diagram.png", "about": "smart city traffic", "sha1": "a", "licence": "CC BY 4.0", "artist": "A",
             "depicts": True, "starred": False, "size": [2000, 1000]},
            {"title": "Sunlit walkway with leafy trees.jpg", "about": "walkway trees", "sha1": "b", "licence": "CC BY 4.0", "artist": "B",
             "depicts": False, "starred": False, "size": [2000, 1000]},
            {"title": "Smart city traffic at night.jpg", "about": "smart city traffic night", "sha1": "c", "licence": "CC BY 4.0", "artist": "C",
             "depicts": False, "starred": False, "size": [2000, 1000]}]
    monkeypatch.setattr(images, "image_folder", lambda: tmp_path)
    for one in pool:
        (tmp_path / f"{one['sha1']}.jpg").write_bytes(b"x")

    monkeypatch.setattr(images, "remembered_choices", lambda: {"smart city traffic night": pool})
    assert images.find_image("smart city traffic night", 16 / 9).title == "Smart city traffic at night.jpg"
    monkeypatch.setattr(images, "remembered_choices", lambda: {"smart city traffic night": pool[:2]})
    assert images.find_image("smart city traffic night", 16 / 9) is None


@pytest.mark.parametrize("licence, url", [
    ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"), ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/"),
    ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/"), ("Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
])
def test_should_link_each_photo_licence_to_its_deed(licence, url):
    from markitdoc.visuals.images import DocumentImage

    image = DocumentImage(Path("x.jpg"), "Tram 28 in Alfama (2016).jpg", "Photo by Ana Silva", licence)

    assert image.licence_url == url
    assert image.full_credit.startswith("“Tram 28 in Alfama” by Ana Silva, [" + licence + "](" + url + ")") and image.full_credit.endswith(", cropped")


def test_should_credit_every_photo_in_every_format(tmp_path, monkeypatch):
    import fitz
    from docx import Document as WordDocument
    from PIL import Image as Picture
    from pptx import Presentation

    import markitdoc
    from markitdoc import rendering
    from markitdoc.visuals.images import DocumentImage

    Picture.new("RGB", (1600, 900), (90, 120, 160)).save(tmp_path / "tram.jpg")
    photo = DocumentImage(tmp_path / "tram.jpg", "Tram 28 in Alfama.jpg", "Ana Silva", "CC BY-SA 4.0")
    monkeypatch.setattr(rendering, "find_images", lambda wanted, ratios: {key: photo for key in wanted})
    markdown = "---\nimages: true\n---\n# Lisbon\n\n## Trams\n\nThe trams climb the hills.\n\n![Lisbon tram 28](figure)\n"

    with fitz.open(markitdoc.render(markdown, "pdf", tmp_path / "doc.pdf")) as pdf:
        assert "Photo credits" in "".join(page.get_text() for page in pdf)
    assert any("Photo credits" in paragraph.text for paragraph in WordDocument(markitdoc.render(markdown, "docx", tmp_path / "doc.docx")).paragraphs)
    deck = Presentation(markitdoc.render(markdown, "pptx", tmp_path / "doc.pptx"))
    assert any(shape.has_text_frame and "Photo credits" in shape.text_frame.text for slide in deck.slides for shape in slide.shapes)


def test_should_offer_candidates_with_thumbnails_for_a_writer_to_choose(monkeypatch, tmp_path):
    fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"])
    monkeypatch.setattr(images, "shrunk", lambda path: True)
    with using_options(fake.options):
        found = images.photo_candidates("wetland")

    assert 1 <= len(found) <= 5 and all(one["title"].startswith("File:") and one["thumbnail"].is_file() for one in found)
    assert fake.searches() == ["wetland filemime:image/jpeg filew:>1600"]


def test_should_fetch_exactly_the_file_a_writer_chose(monkeypatch, tmp_path):
    title = next(iter(fixture("wetland_one.json")["query"]["pages"].values()))["title"]
    fake = wetland(monkeypatch, tmp_path, answers=["wetland_one.json"])
    with using_options(fake.options):
        image = find_image(title, 1.5)

    assert image.title == title.removeprefix("File:") and not any("gsrsearch" in params for url, params in fake.calls)
    assert [params["titles"] for url, params in fake.calls] == [title]


def test_should_place_a_named_photo_written_as_a_figure(tmp_path, monkeypatch):
    import markitdoc
    from markitdoc import rendering
    from markitdoc.visuals.images import DocumentImage

    Image.new("RGB", (1600, 900), (90, 120, 160)).save(tmp_path / "tram.jpg")
    asked = []
    monkeypatch.setattr(rendering, "find_images", lambda wanted, ratios: asked.extend(wanted.values()) or
                        {key: DocumentImage(tmp_path / "tram.jpg", "Tram 28 Lisbon.jpg", "Ana", "CC BY 2.0") for key in wanted})
    import fitz
    for photo in ("![File:Tram 28 Lisbon.jpg](figure)", "![Tram 28 climbing in Alfama](File:Tram 28 Lisbon.jpg){width=70%}"):
        asked.clear()
        markdown = f"---\nimages: true\n---\n# Lisbon\n\n## Trams\n\nText.\n\n{photo}\n"
        with fitz.open(markitdoc.render(markdown, "pdf", tmp_path / "doc.pdf")) as pdf:
            assert asked == ["File:Tram 28 Lisbon.jpg"] and any(page.get_images() for page in pdf)
