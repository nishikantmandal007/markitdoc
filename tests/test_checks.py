import json

from markitdoc import check_document
from markitdoc.cli import main


def test_should_suggest_the_closest_known_key_for_a_block_typo():
    findings = check_document('::: cover titel="Hi"\n:::')

    assert [(f.line, f.severity) for f in findings] == [(1, "warning")]
    assert "titel" in findings[0].message and "'title'" in findings[0].fix


def test_should_warn_about_unknown_keys_on_paragraph_and_table_style_lines():
    findings = check_document("Text\n{sise=half .lined}\n\n```\n{sise=half}\n```\n")

    assert [f.line for f in findings] == [2]


def test_should_report_unbalanced_fences_as_errors():
    unclosed = check_document("::: box\ntext\n")
    stray = check_document("text\n:::\n")

    assert [(f.line, f.severity) for f in unclosed] == [(1, "error")]
    assert [(f.line, f.severity) for f in stray] == [(2, "error")]
    assert check_document("::: box\n::: columns\n:::\n:::\n") == []


def test_should_say_a_markitdoc_front_matter_key_is_not_needed():
    finding = check_document("---\nmarkitdoc: 3\n---\n# T")[0]

    assert (finding.line, finding.severity, finding.message) == (2, "info", "'markitdoc:' is not needed: every feature is always on")
    assert check_document("# T") == []


def test_should_never_raise_on_bad_input():
    assert check_document(None) == [] and check_document("{{{ ::: \"\"") is not None


def test_should_exit_one_only_when_there_is_an_error(tmp_path, capsys):
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text("::: box titel=x\n:::\n")
    bad.write_text("::: box\n")

    assert main(["check", str(good)]) == 0
    assert "line 1: warning: unknown attribute 'titel' (did you mean 'title'?)" in capsys.readouterr().out
    assert main(["check", str(bad)]) == 1


def test_should_print_findings_as_json(tmp_path, capsys):
    source = tmp_path / "bad.md"
    source.write_text("::: box\n")

    assert main(["check", str(source), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == [
        {"line": 1, "severity": "error", "message": "::: block is never closed", "fix": "add a closing ::: line"}]


def test_should_suggest_the_closest_key_for_a_misspelt_one():
    finding = check_document("::: box bordr=thin\n:::")[0]

    assert finding.message == "unknown attribute 'bordr'"
    assert finding.fix == "did you mean 'border'?"


def test_should_print_nothing_and_exit_zero_when_there_are_no_findings(tmp_path, capsys):
    source = tmp_path / "clean.md"
    source.write_text("# Title\n\nText\n")

    assert main(["check", str(source)]) == 0
    assert capsys.readouterr().out == ""


def test_should_report_front_matter_names_the_renderer_would_silently_ignore():
    findings = check_document("---\npalette: oceans\nfonts: helvetica\npaper: a4\n---\n# Report\n")

    assert [(finding.line, finding.severity, finding.message) for finding in findings] == [
        (2, "error", "unknown palette 'oceans'"), (3, "error", "unknown fonts 'helvetica'")]
    assert findings[0].fix == "did you mean 'ocean'?"
    assert check_document('---\nfonts: {display: "PT Serif"}\npalette: forest\n---\n# Report\n') == []


def test_should_report_charts_that_would_be_left_out():
    chart = '```chart {{size=half}}\n{{"type": "bar", "labels": ["a", "b"], "datasets": [{{"values": {values}}}]}}\n```\n'

    assert check_document("# Report\n\n" + chart.format(values="[5, 3]")) == []
    for values in ('["5%", 3]', "[5]", "[5, 3, 1]"):
        assert [finding.severity for finding in check_document("# Report\n\n" + chart.format(values=values))] == ["error"]


def test_should_ask_for_short_photo_queries_only_when_photos_are_on():
    long_query = "modern surveillance camera mounted on urban lamppost"
    markdown = f"---\nimages: true\n---\n# City\n\n![{long_query}](figure)\n\n::: {{.cover image=\"Lisbon tram 28\"}}\ntitle: City\n:::\n"

    assert [(finding.line, finding.severity) for finding in check_document(markdown) if "photo query" in finding.message] == [(6, "error")]
    assert not [finding for finding in check_document(markdown.replace("images: true", "images: false")) if "photo query" in finding.message]


def test_should_report_what_a_render_left_out_so_the_writer_can_fix_it(tmp_path, monkeypatch):
    import markitdoc
    from markitdoc import rendering

    monkeypatch.setattr(rendering, "find_images", lambda wanted, ratios: {})
    markdown = ("---\nimages: true\n---\n# Review\n\n::: {.figures}\ntitle: Numbers\n42% — Growth — Up from last year.\n:::\n\n"
                "## Body\n\nText.\n\n![Lisbon tram 28](figure)\n")
    report = []

    markitdoc.render(markdown, "pdf", tmp_path / "doc.pdf", report=report)

    assert any("No relevant photo was found for 'Lisbon tram 28'" in problem for problem in report)
    assert any("printed as plain text" in problem for problem in report)
    assert markitdoc.render(markdown, "pdf", tmp_path / "again.pdf").stat().st_size > 0
