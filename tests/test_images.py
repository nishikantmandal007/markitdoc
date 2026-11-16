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
        assert all("filetype:bitmap filew:>1600" in params["gsrsearch"] for params in commons)

    def test_should_ask_for_resolution_only_on_full_bleed_slots(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"] * 5)
        with using_options(fake.options):
            find_image("wetland", 0.7)
            find_image("marsh", 1.9)

        full, band = fake.searches()[0], fake.searches()[-1]
        assert "fileres:>" in full and "fileres:>" not in band

    def test_should_search_depicted_item_first_when_wikidata_knows_the_query(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, answers=["wetland_many.json"])
        with using_options(fake.options):
            find_image("wetland", 1.5)

        assert fake.searches()[0].startswith("haswbstatement:P180=Q170321") and "Quality_images" in fake.searches()[0]
        assert fake.calls[0][0] == images.WIKIDATA_API

    def test_should_fall_back_down_the_ladder_in_order(self, monkeypatch, tmp_path):
        fake = wetland(monkeypatch, tmp_path, wikidata="wikidata_none.json")
        with using_options(fake.options):
            assert find_image("reed wetland", 1.5) is None

        steps = [text.split(" filetype")[0] for text in fake.searches()]
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
