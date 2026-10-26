import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from videodock.models import DownloadSettings
from videodock.saved_lists_ui import SavedListEditor, SaveListDialog
from videodock.store import Store
from videodock.ui import MainWindow


def entry(video, **extra):
    return {"url": f"https://youtu.be/{video}", "title": f"Video {video}",
            "playlist": "Original playlist", "playlist_key": "original", "index": 3,
            "duration": 42, **extra}


def test_saved_lists_persist_independent_edits_and_original_links(tmp_path):
    path = tmp_path / "saved.sqlite3"
    store = Store(path)
    source = "https://youtube.com/playlist?list=original"
    first = store.create_saved_list("最愛 <lecture>", "favorite", [source], [entry("a"), entry("b")])
    custom = store.create_saved_list("My own list")
    original = store.saved_list(first)
    assert store.add_saved_items(first, [entry("external", playlist="Other", index=20),
                                         entry("a", url="https://www.youtube.com/watch?v=a&list=other")]) == (1, 1)
    assert store.remove_saved_items(custom, [original["items"][0]["id"]]) == 0
    assert store.remove_saved_items(first, [original["items"][0]["id"]]) == 1
    assert store.add_saved_items(first, [entry("a")]) == (1, 0)
    store.rename_saved_list(first, "Renamed 中文")
    store.close()
    reopened = Store(path)
    saved = reopened.saved_list(first)
    assert saved["name"] == "Renamed 中文" and saved["source_urls"] == [source]
    assert [item["title"] for item in saved["items"]] == ["Video b", "Video external", "Video a"]
    assert saved["items"][1]["index"] == 20 and saved["items"][1]["playlist"] == "Other"
    assert [row["count"] for row in reopened.saved_lists()] == [0, 3]
    reopened.close()


def test_list_validation_is_atomic_and_duplicates_use_video_identity(store):
    for name in (" ", "a\nb", "a" * 161):
        with pytest.raises(ValueError):
            store.create_saved_list(name)
    with pytest.raises(ValueError):
        store.create_saved_list("Invalid", items=[entry("ok"), entry("bad", url="file:///private")])
    assert not store.saved_lists()
    identifier = store.create_saved_list("Custom", items=[entry("a"), entry("a")])
    with pytest.raises(ValueError):
        store.add_saved_items(identifier, [entry("new"), entry("bad", url="https://user:pass@example.com")])
    assert len(store.saved_list(identifier)["items"]) == 1
    with pytest.raises(ValueError):
        store.add_saved_items("missing", [entry("new")])
    with pytest.raises(ValueError):
        store.create_saved_list("Invalid", kind="unsupported")


def test_delete_list_keeps_jobs_files_and_other_lists(store, tmp_path):
    media = tmp_path / "saved.mp4"
    media.write_bytes(b"saved media")
    store.enqueue([entry("a")], DownloadSettings(), str(tmp_path))
    identifier = store.create_saved_list("Delete", items=[entry("a")])
    keep = store.create_saved_list("Keep", items=[entry("a")])
    store.delete_saved_list(identifier)
    assert store.saved_list(identifier) is None
    assert len(store.saved_list(keep)["items"]) == len(store.jobs()) == 1
    assert media.read_bytes() == b"saved media"
    assert not store.db.execute("SELECT 1 FROM saved_list_items WHERE list_id=?", (identifier,)).fetchone()


def test_saved_lists_migrate_existing_database_without_touching_queue(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = Store(path)
    store.enqueue([entry("old")], DownloadSettings(), str(tmp_path))
    before = store.jobs()
    store.db.executescript("DROP TABLE saved_list_items; DROP TABLE saved_lists;")
    store.close()
    migrated = Store(path)
    assert migrated.jobs() == before
    assert migrated.saved_lists() == []
    migrated.create_saved_list("New")
    migrated.close()


def test_downloads_save_load_append_and_edit_list(app, store, tmp_path, monkeypatch):
    window = MainWindow(store)
    window.urls.setPlainText("https://youtube.com/playlist?list=original")
    window._preview_event({"type": "item", "item": entry("a")})
    window._preview_event({"type": "item", "item": entry("b")})
    window.preview.item(1, 0).setCheckState(Qt.CheckState.Unchecked)

    def save(dialog):
        dialog.name.setText("Favorites 中文")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SaveListDialog, "exec", save)
    window.save_list_button.click()
    identifier = window.saved_lists.currentData()
    assert store.saved_list(identifier)["kind"] == "favorite"
    assert len(store.saved_list(identifier)["items"]) == 1
    window.reset_preview()
    window.urls.setPlainText("https://youtu.be/external")
    window._preview_event({"type": "item", "item": entry("external", playlist="", index=0)})
    window.add_to_list_button.click()
    window.load_list_button.click()
    assert [item["title"] for item in window.items] == ["Video a", "Video external"]
    assert window.preview_count.text() == "2 selected"
    assert len(store.saved_list(identifier)["source_urls"]) == 1
    window.destination.setText(str(tmp_path / "output"))
    window.enqueue()
    assert len(store.jobs()) == 2 and not window.controller.running
    editor = SavedListEditor(store, identifier, window)
    editor.changed.connect(window.refresh_saved_lists)
    editor.entries.selectRow(0)
    editor.remove_button.click()
    assert len(store.saved_list(identifier)["items"]) == 1
    assert len(store.jobs()) == 2
    editor.close()
    window.load_list_button.click()
    assert [item["title"] for item in window.items] == ["Video external"]
    window.overrides[0] = DownloadSettings(format="mp3")
    window.load_list_button.click()
    assert window.overrides == {} and window.settings_panel.details is None
    window.close()
    reopened = MainWindow(store)
    assert reopened.saved_lists.currentData() == identifier
    reopened.load_list_button.click()
    assert len(reopened.items) == 1
    reopened.close()


def test_list_editor_multiselection_rename_delete_and_empty(app, store, monkeypatch):
    identifier = store.create_saved_list("<b>Favorite</b>", source_urls=["https://example.com/?a=<b>"],
                                         items=[entry("a"), entry("b"), entry("c")])
    editor = SavedListEditor(store, identifier)
    assert editor.origin.textFormat() == Qt.TextFormat.PlainText
    editor.entries.selectRow(0)
    editor.entries.selectionModel().select(editor.entries.model().index(2, 0),
                                          QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    editor.remove_selected()
    assert [item["title"] for item in store.saved_list(identifier)["items"]] == ["Video b"]
    editor.name.setText(" ")
    editor.rename()
    assert store.saved_list(identifier)["name"] == "<b>Favorite</b>"
    editor.name.setText("Changed")
    editor.rename()
    assert store.saved_list(identifier)["name"] == "Changed"
    editor.entries.selectRow(0)
    editor.remove_selected()
    assert editor.entries.rowCount() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    editor.delete_list()
    assert store.saved_list(identifier) is None
    editor.close()


def test_loading_list_during_inspection_cannot_mix_results(app, store):
    identifier = store.create_saved_list("Saved", items=[entry("a")])
    window = MainWindow(store)
    window.refresh_saved_lists(identifier)
    window._preview_event({"type": "item", "item": entry("current")})
    window.background = object()
    window.saved_list_selected()
    assert not window.load_list_button.isEnabled()
    window.load_saved_list()
    assert window.items[0]["title"] == "Video current"
    window.background = None
    window.close()


def test_create_empty_list_and_name_validation(app, store, monkeypatch):
    window = MainWindow(store)

    def save(dialog):
        assert not dialog.include_selected.isEnabled()
        dialog.name.setText(" ")
        dialog.validate()
        assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
        dialog.name.setText("Empty custom list")
        dialog.validate()
        return dialog.result()

    monkeypatch.setattr(SaveListDialog, "exec", save)
    window.save_preview_list()
    saved = store.saved_list(window.saved_lists.currentData())
    assert saved["kind"] == "custom" and saved["items"] == []
    window.load_saved_list()
    assert not window.items and window.preview_count.text() == "0 selected"
    assert not window.add_to_list_button.isEnabled()
    window.close()
