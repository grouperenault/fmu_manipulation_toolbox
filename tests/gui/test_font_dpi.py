"""Fonts of the GUIs on Windows at a display scale of 125 % or 150 %: the application rounds the scale down to 1, the
fonts get the DPI of a scale of 100 %, as the widgets (`fonts_of_a_scale_of_100_percent`)."""
import os

import pytest

pytest.importorskip("PySide6")

from fmu_manipulation_toolbox.gui import helper  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("display_dpi, dpi", [(96, 96), (120, 96), (144, 96), (168, None), (192, None),
                                                (None, None)])
def test_fonts_of_a_scale_of_100_percent(display_dpi, dpi):
    """125 % and 150 % are rounded down to 1: the fonts get the DPI of 100 %, as the widgets. From 175 %, the scale
    is rounded up to 2: fonts and widgets are doubled alike."""
    assert helper.font_dpi(display_dpi) == dpi


@pytest.mark.parametrize("platform, display_dpi, seen", [("nt", 144, "96"), ("nt", 192, None), ("posix", 144, None)])
def test_font_dpi_on_windows_only(monkeypatch, platform, display_dpi, seen):
    """The DPI of the fonts is set while the application is created, then removed: the processes started by the
    application keep their own rendering."""
    monkeypatch.setattr(helper, "windows_display_dpi", lambda: display_dpi)
    monkeypatch.delenv(helper.FONT_DPI_VARIABLE, raising=False)
    monkeypatch.setattr(helper.os, "name", platform)
    with helper.fonts_of_a_scale_of_100_percent():
        found = os.environ.get(helper.FONT_DPI_VARIABLE)
    assert found == seen and helper.FONT_DPI_VARIABLE not in os.environ


def test_a_font_dpi_of_the_environment_is_kept(monkeypatch):
    monkeypatch.setattr(helper, "windows_display_dpi", lambda: 144)
    monkeypatch.setenv(helper.FONT_DPI_VARIABLE, "120")
    monkeypatch.setattr(helper.os, "name", "nt")
    with helper.fonts_of_a_scale_of_100_percent():
        pass
    assert os.environ[helper.FONT_DPI_VARIABLE] == "120"

