"""Accessibility/color audit over the theme tokens."""
from __future__ import annotations

import colorsys

import pytest
from PySide6.QtCore import QSettings

from neuroedit_desktop.ui import styles


def _relative_luminance(color_hex: str) -> float:
    value = color_hex.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


def _hue_sat(color_hex: str) -> tuple[float, float]:
    value = color_hex.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, sat, _v = colorsys.rgb_to_hsv(r, g, b)
    return hue * 360.0, sat


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_body_text_meets_aa_on_every_surface(theme):
    for surface in (theme.bg_primary, theme.bg_secondary, theme.bg_card, theme.bg_tertiary):
        assert contrast_ratio(theme.text_primary, surface) >= 4.5
        assert contrast_ratio(theme.text_secondary, surface) >= 4.5


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_muted_text_meets_aa_on_common_surfaces(theme):
    for surface in (theme.bg_primary, theme.bg_secondary, theme.bg_card):
        assert contrast_ratio(theme.text_muted, surface) >= 4.5


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_dim_text_meets_auxiliary_floor(theme):
    assert contrast_ratio(theme.text_dim, theme.bg_tertiary) >= 3.0


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_status_colors_readable_as_text(theme):
    for status in (theme.accent_red, theme.accent_amber, theme.accent_emerald):
        assert contrast_ratio(status, theme.bg_secondary) >= 4.5
        assert contrast_ratio(status, theme.bg_card) >= 4.0


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_accent_fill_button_labels(theme):
    assert contrast_ratio(theme.on_primary, theme.primary) >= 3.0
    assert contrast_ratio(theme.on_primary_hover, theme.primary_hover) >= 3.0
    assert contrast_ratio(theme.on_success, theme.accent_emerald) >= 4.5


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_selection_focus_and_video_canvas(theme):
    assert contrast_ratio(theme.selection_outline, theme.bg_secondary) >= 3.0
    assert contrast_ratio(theme.primary, theme.bg_card) >= 1.5
    if theme is styles.LIGHT_THEME:
        assert contrast_ratio(theme.bg_primary, theme.video_canvas) >= 3.0


@pytest.mark.parametrize("theme", styles.THEMES.values(), ids=styles.THEMES.keys())
def test_danger_is_hue_distinct_from_primary_accent(theme):
    danger_hue, danger_sat = _hue_sat(theme.accent_red)
    primary_hue, primary_sat = _hue_sat(theme.primary)
    assert danger_sat > 0.5
    if primary_sat < 0.2 or _relative_luminance(theme.primary) < 0.03:
        return
    diff = abs(danger_hue - primary_hue)
    assert min(diff, 360 - diff) >= 35, (
        "Destructive red must remain visually distinct from primary actions"
    )


def test_mask_palette_contains_no_red():
    from neuroedit_desktop.ui.main_window import MASK_PALETTE

    for color in MASK_PALETTE:
        hue, sat = _hue_sat(color)
        is_red = (hue <= 20 or hue >= 340) and sat > 0.5
        assert not is_red, f"{color} reads as red - reserved for danger states"


def test_theme_preference_defaults_to_light(tmp_path):
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)

    assert not styles.theme_preference_exists(settings)
    assert styles.stored_theme_mode(settings) == "light"
    assert styles.resolve_theme_mode("light", system_mode="dark") == "light"


def test_theme_preference_round_trip(tmp_path):
    settings = QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)

    styles.save_theme_mode("dark", settings)
    assert styles.theme_preference_exists(settings)
    assert styles.stored_theme_mode(settings) == "dark"
    assert styles.resolve_theme_mode("dark", system_mode="light") == "dark"
    assert styles.resolve_theme_mode("system", system_mode="dark") == "dark"
