"""Export preset recommendation: source-resolution + intended-use driven
default, with the dialog preselecting it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.models import ProjectState, VideoClip, new_id  # noqa: E402
from neuroedit_desktop.ui.main_window import (  # noqa: E402
    ExportDialog,
    recommended_preset_key,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(height: int | None = None, goal: str = "talk-adjunct") -> ProjectState:
    project = ProjectState()
    project.video_goal = goal
    if height is not None:
        width = {720: 1280, 1080: 1920, 2160: 3840}.get(height, 1920)
        project.clips.append(
            VideoClip(id=new_id(), path="/tmp/a.mp4", name="A", duration=10.0,
                      start_time=0.0, trim_start=0.0, trim_end=10.0,
                      width=width, height=height)
        )
    return project


def test_no_clips_recommends_1080p():
    key, _reason = recommended_preset_key(_project())
    assert key == "1080p"
    assert recommended_preset_key(None)[0] == "1080p"


def test_sub_1080_source_recommends_720p_not_upscale():
    key, reason = recommended_preset_key(_project(height=720))
    assert key == "720p"
    assert "upscal" in reason


def test_4k_source_big_screen_goal_recommends_4k():
    assert recommended_preset_key(_project(height=2160, goal="conference"))[0] == "4k"
    assert (
        recommended_preset_key(_project(height=2160, goal="standalone-publication"))[0]
        == "4k"
    )


def test_4k_source_talk_adjunct_stays_1080p():
    assert recommended_preset_key(_project(height=2160, goal="talk-adjunct"))[0] == "1080p"


def test_dialog_preselects_recommendation(app):
    dialog = ExportDialog(_project(height=720))
    assert dialog.preset_combo.currentData()[0] == "720p"
    assert "Recommended for this project" in dialog.recommend_label.text()
    # Advanced fields re-glued to the recommended preset.
    assert dialog.height_spin.value() == 720


def test_dialog_defaults_keep_simple_path(app):
    dialog = ExportDialog(_project(height=1080))
    assert dialog.preset_combo.currentData()[0] == "1080p"
    assert not dialog.advanced_widget.isVisible()  # advanced stays collapsed
    assert dialog.mute_source_audio_check.isChecked()  # privacy default intact
