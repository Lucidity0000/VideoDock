import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase

from videodock.ui import MainWindow


def preview_item(title="A video"):
    return {"type": "item", "item": {"url": "https://youtu.be/presentation", "title": title,
                                    "playlist": "Playlist", "index": 1, "duration": 20,
                                    "detailed": False}}


def test_external_titles_and_errors_display_as_literal_text(app, store):
    window = MainWindow(store)
    title = "<b>Lecture</b> & <example>"
    window._preview_event(preview_item(title))
    window.preview.selectRow(0)
    assert window.preview_description.textFormat() == Qt.TextFormat.PlainText
    assert window.preview_description.text().startswith(title)
    message = "Cannot open <lecture>.mp4 & captions"
    window.show_notice(message)
    assert window.notice.textFormat() == Qt.TextFormat.PlainText
    assert window.notice.text() == message
    window.close()


def test_preview_reset_clears_actions_details_and_empty_state(app, store, monkeypatch):
    window = MainWindow(store)
    window.show()
    app.processEvents()
    assert window.preview.empty_state.isVisible()
    assert not window.enqueue_button.isEnabled()
    assert not window.detail_button.isEnabled()
    window._preview_event(preview_item())
    window.preview.selectRow(0)
    assert not window.preview.empty_state.isVisible()
    assert window.preview_count.text() == "1 selected"
    assert window.detail_button.isEnabled()
    window.select_all(False)
    assert window.preview_count.text() == "0 selected"
    assert not window.enqueue_button.isEnabled()
    window.select_all(True)
    assert window.enqueue_button.isEnabled()
    # Start a second inspection without launching a worker or touching user data.
    monkeypatch.setattr(window, "_background_request", lambda *_: None)
    window.urls.setPlainText("https://youtu.be/another")
    window.inspect()
    assert window.preview.empty_state.isVisible()
    assert window.preview_count.text() == "0 selected"
    assert not window.enqueue_button.isEnabled()
    assert not window.detail_button.isEnabled()
    assert not window.override_button.isEnabled()
    assert window.settings_panel.details is None
    assert window.preview_description.toolTip() == ""
    window.close()


def test_ranges_and_preview_actions_are_accessible_at_minimum_size(app, store):
    # Match the packaged Windows layout smoke's font discovery with offscreen Qt.
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    app.setStyle("Fusion")
    window = MainWindow(store)
    window.resize(1100, 680)
    window.show()
    window._preview_event(preview_item())
    window.preview.selectRow(0)
    app.processEvents()
    assert not window.range_controls.isVisible()
    viewport = window.preview_scroll.viewport()
    for control in (window.preview_button, window.detail_button, window.ranges_button):
        assert viewport.rect().contains(control.mapTo(viewport, control.rect().center()))
    # The first preview row, destination and independent queue stay on screen.
    row_rect = window.preview.visualItemRect(window.preview.item(0, 2))
    assert viewport.rect().contains(window.preview.viewport().mapTo(viewport, row_rect.center()))
    assert viewport.rect().contains(window.preview.viewport().mapTo(viewport, row_rect.bottomLeft()))
    assert window.queue.viewport().height() >= window.queue.rowHeight(0)
    window.ranges_button.click()
    app.processEvents()
    app.processEvents()
    assert window.range_controls.isVisible()
    assert viewport.rect().contains(window.intervals.mapTo(viewport, window.intervals.rect().center()))
    window.intervals.setText("1")
    window.select_intervals()
    assert window.preview.item(0, 0).checkState() == Qt.CheckState.Checked
    window.ranges_button.click()
    assert not window.range_controls.isVisible()
    window.close()
