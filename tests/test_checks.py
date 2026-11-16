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


def test_should_warn_about_a_language_version_other_than_one_or_two():
    assert check_document("---\nmarkitdoc: 3\n---\n# T")[0].severity == "warning"
    assert check_document("---\nmarkitdoc: 2\n---\n# T") == []


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


def test_should_name_planned_keys_instead_of_suggesting_another_key():
    finding = check_document("::: box border=thin\n:::")[0]

    assert finding.message == "'border' is planned for MarkitDoc language v2 and is ignored for now"
    assert finding.fix == "remove it or keep it for a later version"


def test_should_print_nothing_and_exit_zero_when_there_are_no_findings(tmp_path, capsys):
    source = tmp_path / "clean.md"
    source.write_text("# Title\n\nText\n")

    assert main(["check", str(source)]) == 0
    assert capsys.readouterr().out == ""
