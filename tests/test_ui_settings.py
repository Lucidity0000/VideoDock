from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QPushButton

from videodock import caption_ui, controller, model_ui
from videodock.caption_models import model_spec
from videodock.models import DownloadSettings
from videodock.ui import MainWindow, OverrideDialog


def test_independent_settings_and_single_model_library(app, store):
    window = MainWindow(store)
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Downloads", "Download settings", "Models", "History", "Settings and dependencies",
    ]
    assert window.settings_panel not in window.tabs.widget(0).findChildren(type(window.settings_panel))
    assert [window.settings_panel.pages.tabText(i) for i in range(4)] == [
        "Media", "Captions", "Translation", "Subtitle style",
    ]
    names = [button.text() for button in window.findChildren(QPushButton)]
    assert "Caption models…" not in names and "Open destination" not in names
    window.close()


def test_model_selection_refreshes_installation_and_storage(app, store, tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    store.set_preference("model_folder", str(old))
    installed = {("old", "qwen3-asr-1.7b-q4-k-m"), ("old", "index-translate-9b-q4-k-m")}

    def ready(root, spec):
        return (root.name, spec["id"]) in installed

    monkeypatch.setattr(model_ui, "is_ready", ready)
    monkeypatch.setattr(caption_ui, "is_ready", ready)
    window = MainWindow(store)
    panel = window.settings_panel
    panel.use_model("qwen3-asr-1.7b-q4-k-m")
    assert "Installed" in panel.model_status.text()
    assert not panel.download_button.isEnabled()
    absent = panel.local_model.findData("small")
    assert "Not downloaded" in panel.local_model.itemText(absent)
    assert not panel.local_model.model().item(absent).isEnabled()
    translation = panel.translation_panel
    translation.model.setCurrentIndex(translation.model.findData("index-translate-9b-q4-k-m"))
    assert "Installed" in translation.model_status.text()
    translation.model.setCurrentIndex(translation.model.findData("m2m100-418m"))
    assert "Not downloaded" in translation.model_status.text()
    assert translation.download_button.isEnabled()
    panel.alignment_model.setCurrentIndex(1)
    assert "Not downloaded" in panel.alignment_status.text()
    # A stale session state must not claim installation in a different library.
    window.controller.model_states[panel.local_model.currentData()] = {"state": "Installed"}
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(new))
    window.model_library.choose_folder()
    assert store.preference("model_folder") == str(new)
    assert "Not downloaded" in panel.model_status.text()
    assert panel.download_button.isEnabled()
    assert not window.model_library.controls[panel.local_model.currentData()][5].isEnabled()
    window.close()


def test_translation_download_button_drives_worker_and_completion(app, store, tmp_path, monkeypatch):
    workers = []
    installed = set()
    monkeypatch.setattr(model_ui, "is_ready", lambda root, spec: spec["id"] in installed)
    monkeypatch.setattr(caption_ui, "is_ready", lambda root, spec: spec["id"] in installed)

    class Worker(QObject):
        event = Signal(dict)
        ended = Signal(int)

        def __init__(self, request, parent):
            super().__init__(parent)
            self.request, self.errors = request, ""
            workers.append(self)

        def start(self):
            pass

    monkeypatch.setattr(controller, "WorkerProcess", Worker)
    store.set_preference("model_folder", str(tmp_path / "models"))
    window = MainWindow(store)
    translation = window.settings_panel.translation_panel
    # The explicit download works even before translation is enabled.
    assert not translation.enabled.isChecked()
    translation.download_button.click()
    assert len(workers) == 1
    worker = workers[0]
    key = "m2m100-418m"
    assert worker.request == {"action": "model_download", "model_id": key,
                              "model_folder": str(tmp_path / "models")}
    assert "Downloading" in translation.download_button.text()
    assert not translation.download_button.isEnabled()
    assert "Downloading" in window.notice.text()
    worker.event.emit({"type": "model_progress", "state": "Verify", "bytes": 1, "total": 2})
    assert "50%" in translation.model_status.text()
    worker.event.emit({"type": "cancelled"})
    worker.ended.emit(0)
    assert "Retry / resume" in translation.model_status.text()
    assert translation.download_button.isEnabled()
    translation.download_button.click()
    assert len(workers) == 2
    installed.add(key)
    workers[1].event.emit({"type": "model_ready", "revision": model_spec(key)["revision"],
                           "path": str(tmp_path / "models" / key)})
    workers[1].ended.emit(0)
    assert "Installed" in translation.model_status.text()
    assert not translation.download_button.isEnabled()
    assert translation.model.model().item(translation.model.findData(key)).isEnabled()
    assert window.model_library.controls[key][5].isEnabled()
    installed.clear()
    window.controller.models_changed.emit()
    assert "Not downloaded" in translation.model_status.text()
    assert translation.download_button.isEnabled()
    window.close()


def test_browse_destination_and_save_defaults_preserve_queued_settings(app, store, tmp_path, monkeypatch):
    window = MainWindow(store)
    folder = tmp_path / "影片輸出"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    window.browse_destination()
    assert Path(window.destination.text()) == folder
    store.enqueue([{"url": "https://youtu.be/a", "title": "A"}], DownloadSettings(), str(folder))
    window.settings_panel.format.setCurrentIndex(window.settings_panel.format.findData("mp3"))
    window.save_defaults()
    assert store.preference("settings")["format"] == "mp3"
    assert store.jobs()[0]["settings"]["format"] == "mp4"
    assert "MP3" in window.settings_summary.text()
    window.close()


def test_override_model_updates_and_format_controls(app, store):
    window = MainWindow(store)
    dialog = OverrideDialog(DownloadSettings(), {"title": "A"}, window)
    window.controller.models_changed.emit()
    assert "Not downloaded" in dialog.panel.model_status.text()
    panel = window.settings_panel
    panel.source.setCurrentIndex(panel.source.findData("local"))
    panel.mode.setCurrentIndex(panel.mode.findData("burn"))
    assert panel.translation_panel.style_panel.isEnabled()
    panel.format.setCurrentIndex(panel.format.findData("mp3"))
    assert panel.mode.currentData() == "sidecar"
    assert not panel.translation_panel.style_panel.isEnabled()
    dialog.deleteLater()
    app.processEvents()
    window.controller.models_changed.emit()
    window.close()
