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
