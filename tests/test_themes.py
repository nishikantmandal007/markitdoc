import pytest

from markitdoc.errors import ThemeError
from markitdoc.themes import available_themes, contrast, load_theme, theme_for
from markitdoc.themes.theme_constants import ACCENTS, COLOR_ROLES


class TestLoadTheme:
    @pytest.mark.parametrize("name", ["professional", "editorial"])
    def test_should_load_every_shipped_theme_with_all_colours_fonts_and_moods(self, name):
        theme = load_theme(name)

        assert set(theme.colors) == {*COLOR_ROLES, "mood", "second", "glow"}
        assert all(path.is_file() for path in theme.fonts.values())
        assert {"calm", "urgent", "optimistic", "analytical", "instructional", "strategic"} <= set(theme.moods)

    def test_should_ship_the_two_neutral_themes_beside_registered_brands(self):
        assert available_themes() == ["acme", "editorial", "professional"]

    def test_should_keep_the_brand_colour_of_a_locked_theme_whatever_the_mood(self):
        assert load_theme("acme", mood="urgent").colors["mood"] == load_theme("acme").colors["primary"]

    def test_should_let_a_locked_brand_template_win_over_paper_and_tone(self):
        assert theme_for({"tone": "warm"}, "acme").name == "acme"

    def test_should_find_brand_files_next_to_the_theme_and_fonts_in_the_bundle(self):
        theme = load_theme("acme")

        assert theme.logo.name.startswith("logo-") and theme.logo.is_file() and theme.master.is_file()
        assert all(path.is_file() for path in theme.fonts.values())

    def test_should_map_the_legacy_default_name_to_professional(self):
        assert load_theme("default").name == "professional"

    def test_should_fall_back_to_professional_for_an_unknown_theme(self):
        assert load_theme("neon").name == "professional"

    def test_should_set_the_mood_colour_and_keep_every_brand_colour(self):
        professional = load_theme("professional")
        urgent = load_theme("professional", mood="urgent")

        assert urgent.colors["mood"] == professional.moods["urgent"]
        assert {role: value for role, value in urgent.colors.items() if role not in ("mood", "second", "night", "glow")} == \
            {role: value for role, value in professional.colors.items() if role not in ("mood", "second", "night", "glow")}

    def test_should_darken_an_accent_until_it_is_readable_on_the_page(self):
        for name in ("professional", "editorial"):
            theme = load_theme(name, mood="strategic")
            assert contrast(theme.colors["mood"], theme.colors["paper"]) >= 4.5

    def test_should_pick_theme_and_palette_from_paper_palette_or_legacy_tone(self):
        warm = theme_for({"tone": "warm"}, "default")
        assert warm.name == "editorial" and warm.colors["mood"] == ACCENTS["terracotta"]
        chosen = theme_for({"palette": "forest", "paper": "warm"}, "default")
        assert chosen.name == "editorial" and chosen.colors["mood"] == ACCENTS["forest"]

    def test_should_use_the_primary_colour_as_mood_when_none_is_given(self):
        professional = load_theme("professional")

        assert professional.colors["mood"] == professional.colors["primary"]

    def test_should_ignore_an_unknown_mood(self):
        assert load_theme("professional", mood="sleepy") == load_theme("professional")

    def test_should_give_rgb_tuples_for_renderers(self):
        assert load_theme("professional").rgb("primary") == (0x1E, 0x3A, 0x8A)

    def test_should_raise_a_theme_error_that_is_still_a_value_error(self):
        assert issubclass(ThemeError, ValueError)
