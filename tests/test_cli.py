from markitdoc.cli import main


def test_should_render_a_markdown_file_to_the_format_of_the_output_suffix(tmp_path, capsys):
    source = tmp_path / "note.md"
    source.write_text("# Note\n\nA short note.")

    assert main(["render", str(source), "-o", str(tmp_path / "note.docx")]) == 0
    assert (tmp_path / "note.docx").stat().st_size > 0 and "note.docx" in capsys.readouterr().out


def test_should_print_the_guide_and_fail_cleanly_on_an_unknown_suffix(tmp_path, capsys):
    assert main(["guide", "pptx"]) == 0 and capsys.readouterr().out.startswith("SLIDE DESIGN GUIDE")
    source = tmp_path / "note.md"
    source.write_text("# Note")

    assert main(["render", str(source), "-o", str(tmp_path / "note.odt")]) == 1
    assert "Unsupported format" in capsys.readouterr().err


def test_should_pass_gotenberg_and_cache_options_to_render(tmp_path, monkeypatch):
    from markitdoc import Options, cli

    source, output = tmp_path / "note.md", tmp_path / "out.pdf"
    source.write_text("# Note")
    captured = {}

    def capture_render(*args, **kwargs):
        captured["options"] = kwargs["options"]
        return output

    monkeypatch.setattr(cli, "render", capture_render)

    assert main(["render", str(source), "-o", str(output), "--gotenberg", "http://renderer.test",
                 "--cache", str(tmp_path)]) == 0
    assert captured["options"] == Options(gotenberg_url="http://renderer.test", cache_folder=tmp_path, style_folders=(tmp_path,))
