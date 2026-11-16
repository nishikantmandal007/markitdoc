import io

import pytest
from PIL import Image

import markitdoc.rendering as rendering
from markitdoc import Options
from markitdoc.options import options_in_use, using_options
from markitdoc.visuals import diagrams
from markitdoc.visuals.images import search


# makes a small nonblank PNG for mocked renderer responses
def png_bytes():
    picture = Image.new("RGB", (400, 200), "white")
    picture.paste((20, 90, 60), (100, 60, 300, 140))
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return buffer.getvalue()


class FakeResponse:
    status_code = 200
    content = png_bytes()


class TestOptions:
    # applies render options to the diagram request and cache
    def test_should_use_options_and_reset_after_successful_render(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.delenv("GOTENBERG_ENDPOINT", raising=False)
        monkeypatch.setattr(diagrams.requests, "post", lambda *args, **kwargs: calls.append(args[0]) or FakeResponse())
        markdown = "# Diagram\n\n```mermaid\nflowchart LR\n A --> B\n```\n"

        rendering.render(markdown, "pdf", tmp_path / "out.pdf", options=Options(
            gotenberg_url="http://renderer.test", cache_folder=tmp_path))

        assert calls == ["http://renderer.test/forms/chromium/screenshot/html"]
        assert len(list((tmp_path / "diagrams").glob("*.png"))) == 1
        assert options_in_use() == Options()

    # restores the default options when rendering raises
    def test_should_reset_options_after_render_error(self, monkeypatch, tmp_path):
        # raises during rendering to exercise context cleanup
        def fail(_):
            raise RuntimeError("render failed")

        monkeypatch.setattr(rendering, "parse_document", fail)
        with pytest.raises(RuntimeError, match="render failed"):
            rendering.render("# Test", "pdf", tmp_path / "out.pdf", options=Options(gotenberg_url="http://renderer.test"))

        assert options_in_use() == Options()

    # sends the configured user agent to Wikimedia
    def test_should_use_configured_user_agent_for_photo_search(self, monkeypatch):
        calls = []
        monkeypatch.setattr("markitdoc.visuals.images.requests.get", lambda *args, **kwargs: calls.append(kwargs) or type(
            "Response", (), {"json": lambda self: {}})())

        with using_options(Options(user_agent="X/1")):
            search("mountain")

        assert calls[0]["headers"]["User-Agent"] == "X/1"
