from markitdoc import parse_attributes
from markitdoc.markup.elements import settings_from
from markitdoc.models.document import parse_document
from markitdoc.models.front_matter import language_version


def test_should_read_id_classes_quoted_values_and_flags():
    found = parse_attributes('{#intro .wide .dark title="Two words" size=m pinned}')

    assert found.id == "intro" and found.classes == ("wide", "dark")
    assert found.values == {"title": "Two words", "size": "m", "pinned": True}


def test_should_accept_attributes_with_or_without_braces_and_never_raise():
    assert parse_attributes("key=value").values == {"key": "value"}
    assert parse_attributes('{title="open').values
    assert parse_attributes(None) == parse_attributes("")


def test_should_normalise_aliases_silently():
    found = parse_attributes("{colour=grey text-align=centre font-size=large}")

    assert found.values == {"color": "gray", "align": "center", "size": "large"}


def test_should_keep_quoted_values_untouched():
    assert parse_attributes('{title="Grey centre"}').values == {"title": "Grey centre"}


def test_should_keep_the_paragraph_settings_shape():
    assert settings_from(".lined size=half pinned") == {"size": "half", "class": "lined"}
    assert settings_from("key=a-b") == {"key": "a-b"}


def test_should_read_block_header_values_through_the_same_grammar():
    block = parse_document('::: cover title="Two words" variant=dark\n:::').blocks[0]

    assert block.layout == "cover" and block.slots["title"] == "Two words" and block.slots["variant"] == "dark"


def test_should_default_the_language_version_to_one():
    assert language_version({}) == 1 and language_version({"markitdoc": "2"}) == 2 and language_version({"markitdoc": "9"}) == 1
    assert language_version(parse_document("---\nmarkitdoc: 2\n---\n# Title").meta) == 2
