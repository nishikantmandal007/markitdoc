import io
import os

import pymupdf as fitz
import pytest
import requests
from helpers import generate_document
from PIL import Image

from markitdoc.themes.themes import load_theme
from markitdoc.visuals import diagrams as document_diagrams
from markitdoc.visuals.diagrams import diagram_as_text, problems_in_diagram, render_diagram
from markitdoc.visuals.icons import icon_names, icon_svg, strip_icon


def text_of(path):
    with fitz.open(path) as pdf:
        return " ".join(" ".join(page.get_text().split()) for page in pdf)


def pictures_in(path):
    with fitz.open(path) as pdf:
        return sum(len(page.get_images()) + len(page.get_drawings()) for page in pdf)


def png_bytes():
    picture = Image.new("RGB", (400, 200), (255, 255, 255))
    picture.paste((20, 90, 60), (100, 60, 300, 140))
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return buffer.getvalue()


class FakeResponse:
    status_code = 200
    content = png_bytes()


def reachable(endpoint):
    try:
        return requests.get(f"{endpoint.rstrip('/')}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


class TestDiagrams:
    def test_should_accept_curated_types_and_explain_a_bad_first_line(self):
        assert problems_in_diagram("flowchart LR\n A --> B") == []
        assert problems_in_diagram("\nsequenceDiagram\n Alice->>Bob: Hi") == []
        assert problems_in_diagram("pie title Pets\n \"Dogs\" : 3") == []
        assert "flowchart TD" in problems_in_diagram("A --> B")[0]
        assert "direction" in problems_in_diagram("flowchart\n A --> B")[0]
        assert problems_in_diagram("") == ["the diagram is empty"]

    def test_should_describe_a_diagram_as_readable_lines_without_mermaid_syntax(self):
        lines = diagram_as_text("flowchart LR\n A[Login] --> B[Validate token]\n B -->|Yes| C{Open?}\n B -- No --> D((Stop))")

        assert lines == ["Login → Validate token", "Validate token → Open?: Yes", "Validate token → Stop: No"]
        assert diagram_as_text("sequenceDiagram\n participant A as Alice\n A->>Bob: Hello") == ["Alice → Bob: Hello"]
        assert diagram_as_text("stateDiagram-v2\n [*] --> Idle\n Idle --> [*]") == ["Start → Idle", "Idle → End"]

    def test_should_return_none_without_a_renderer(self, monkeypatch):
        monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)

        assert render_diagram("flowchart LR\n A --> B", load_theme(None)) is None

    def test_should_cache_a_rendered_diagram(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setenv("GOTENBERG_ENDPOINT", "http://renderer.test")
        monkeypatch.setattr(document_diagrams, "diagram_folder", tmp_path)
        monkeypatch.setattr(document_diagrams.requests, "post", lambda *args, **kwargs: calls.append(kwargs) or FakeResponse())
        theme = load_theme(None)

        first = render_diagram("flowchart LR\n A --> B", theme)
        second = render_diagram("flowchart LR\n A --> B", theme)

        assert first == second and first.parent == tmp_path and first.exists() and len(calls) == 1
        assert "securityLevel" in calls[0]["files"][2][1][1].decode()

    def test_should_return_none_for_a_blank_render(self, monkeypatch, tmp_path):
        blank = io.BytesIO()
        Image.new("RGB", (100, 100), (255, 255, 255)).save(blank, "PNG")
        monkeypatch.setenv("GOTENBERG_ENDPOINT", "http://renderer.test")
        monkeypatch.setattr(document_diagrams, "diagram_folder", tmp_path)
        monkeypatch.setattr(document_diagrams.requests, "post",
                            lambda *args, **kwargs: type("Blank", (), {"status_code": 200, "content": blank.getvalue()})())

        assert render_diagram("flowchart LR\n A --> B", load_theme(None)) is None

    def test_should_print_a_diagram_as_text_when_rendering_is_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
        markdown = "# Sign in\n\n```mermaid\nflowchart LR\n  A[Login] --> B[Validate token]\n  B --> C[Dashboard]\n```\n"

        text = text_of(generate_document(markdown, "pdf", filename_stem="diagram", output_dir=str(tmp_path)))

        assert "Login → Validate token" in text and "Validate token → Dashboard" in text
        assert "-->" not in text and "flowchart" not in text

    def test_should_place_a_rendered_diagram_as_a_picture(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOTENBERG_ENDPOINT", "http://renderer.test")
        monkeypatch.setattr(document_diagrams, "diagram_folder", tmp_path / "diagrams")
        monkeypatch.setattr(document_diagrams.requests, "post", lambda *args, **kwargs: FakeResponse())
        markdown = "# Sign in\n\n```mermaid\nflowchart LR\n  A[Login] --> B[Validate token]\n```\n"

        path = generate_document(markdown, "pdf", filename_stem="picture", output_dir=str(tmp_path))

        with fitz.open(path) as pdf:
            assert sum(len(page.get_images()) for page in pdf) == 1
        assert "Login" not in text_of(path)

    def test_should_render_a_real_diagram_when_gotenberg_is_running(self, monkeypatch, tmp_path):
        endpoint = os.getenv("GOTENBERG_ENDPOINT")
        if not endpoint or not reachable(endpoint):
            pytest.skip("Gotenberg is not running")
        monkeypatch.setattr(document_diagrams, "diagram_folder", tmp_path)

        path = render_diagram("flowchart LR\n  A[Login] --> B{Token valid?}\n  B -->|Yes| C[Dashboard]", load_theme(None, "forest"))

        assert path is not None
        with Image.open(path) as picture:
            assert picture.width > 200 and picture.height > 50
        assert render_diagram("flowchart LR\n  A[Login --> (((", load_theme(None, "forest")) is None


class TestIcons:
    def test_should_colour_a_known_icon_and_refuse_unknown_names(self):
        svg = icon_svg("shield", (255, 0, 16))

        assert len(icon_names) >= 100 and list(icon_names) == sorted(icon_names)
        assert svg.startswith(b"<svg ") and b'stroke="#ff0010"' in svg and b"currentColor" not in svg and b"license" not in svg
        assert icon_svg("no-such-icon", (0, 0, 0)) is None

    def test_should_strip_only_known_shortcodes(self):
        assert strip_icon(":shield: Encryption at rest") == ("shield", "Encryption at rest")
        assert strip_icon(":unknown: text") == (None, ":unknown: text")
        assert strip_icon("Plain :shield: text") == (None, "Plain :shield: text")

    def test_should_drop_icon_shortcodes_from_list_items(self, tmp_path):
        markdown = "# Controls\n\n- :shield: Encryption at rest\n- :lock: **Access** reviews\n"

        path = generate_document(markdown, "pdf", filename_stem="icons", output_dir=str(tmp_path))
        text = text_of(path)

        assert "Encryption at rest" in text and "Access reviews" in text and ":shield:" not in text and ":lock:" not in text
        assert text.count("•") == 2

    def test_should_never_print_icon_shortcodes_on_designed_pages(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
        markdown = """::: {.process}
title: How detection works
:search: Detect — We scan every document for personal data.
:shield-check: Protect — Sensitive values are replaced before sharing.
:file-check: Review — A person approves the final version.
:::

::: {.keypoints}
title: What we found
:users: Teams — Every team adopted the new process within a month.
:clock: Speed — Reviews now finish in two days instead of five.
:trending-up: Quality — Errors fell by a third across all departments.
:::

::: {.figures}
title: In numbers
:leaf: 410 ha — Wetland restored — Up from 120 hectares.
:percent: 64% — Fewer flood days — Across four towns.
:star: 2 — Species returned — Otters and kingfishers.
:::

::: {.matrix}
title: Options
:shield: Keep — Stay with the current tool.
Build — Write our own.
Buy — License a product.
Partner — Share the work.
:::"""

        path = generate_document(markdown, "pdf", filename_stem="designed", output_dir=str(tmp_path))
        text = text_of(path)

        assert all(word in text for word in ("Detect", "Teams", "410 ha", "Keep"))
        assert ":search:" not in text and ":users:" not in text and ":leaf:" not in text and ":shield:" not in text


class TestCompleteness:
    def test_should_ship_the_whole_icon_set_and_resolve_old_names(self):
        assert len(icon_names) > 1500
        assert strip_icon(":alert-triangle: Risk") == ("triangle-alert", "Risk")
        assert strip_icon(":check-circle: Done")[0] == "circle-check-big"
        assert icon_svg("help-circle", (0, 0, 0)) is not None

    def test_should_caption_a_titled_diagram_without_sending_the_title_to_mermaid(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setenv("GOTENBERG_ENDPOINT", "http://renderer.test")
        monkeypatch.setattr(document_diagrams, "diagram_folder", tmp_path / "diagrams")
        monkeypatch.setattr(document_diagrams.requests, "post", lambda *args, **kwargs: sent.append(kwargs) or FakeResponse())
        markdown = "# Sign in\n\n```mermaid\nflowchart LR\n  title Sign-in path\n  A[Login] --> B[Validate token]\n```\n"

        path = generate_document(markdown, "pdf", filename_stem="titled", output_dir=str(tmp_path))

        assert "Figure 1. Sign-in path" in text_of(path)
        assert all(b"Sign-in path" not in str(call).encode() for call in sent)

    def test_should_link_the_photo_credit_inside_the_figure_caption(self, monkeypatch, tmp_path):
        import markitdoc.rendering as service
        from markitdoc.visuals.images import DocumentImage

        photo = tmp_path / "photo.jpg"
        Image.new("RGB", (600, 400), (90, 120, 160)).save(photo)
        image = DocumentImage(photo, "File:Harbour at dawn.jpg", "Jane Doe", "CC BY 4.0")
        monkeypatch.setattr(service, "find_images", lambda wanted, ratios: {key: image for key in wanted})
        markdown = "---\nimages: true\n---\n# Port\n\nText.\n\n![harbour](figure)\n"

        path = generate_document(markdown, "pdf", filename_stem="credited", output_dir=str(tmp_path))

        text = text_of(path)
        assert "Photo: Jane Doe, CC BY 4.0, Wikimedia Commons" in text and "Image credits" not in text
        with fitz.open(path) as pdf:
            assert any(link.get("uri", "").startswith("https://commons.wikimedia.org/wiki/File:") for page in pdf for link in page.get_links())
