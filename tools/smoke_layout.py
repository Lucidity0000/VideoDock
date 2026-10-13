"""Capture every source UI page using an isolated queue and model library."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = Path(os.environ.get("VIDEODOCK_LAYOUT_OUTPUT", str(ROOT / ".test-artifacts/ui-refresh/layout")))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["VIDEODOCK_DATA_DIR"] = str(OUTPUT / "appdata")


def main():
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from videodock.caption_ui import CaptionEditor
    from videodock.models import DownloadSettings
    from videodock.store import Store
    from videodock.ui import MainWindow, OverrideDialog

    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    for name in ("segoeui.ttf", "msjh.ttc", "arial.ttf"):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    store = Store(OUTPUT / "appdata/videodock.sqlite3")
    # Read only: cached verified packages stay in the isolated inference test library.
    store.set_preference("model_folder", str(ROOT / ".test-artifacts/model-resources/source/models"))
    settings = DownloadSettings(caption_source="local", caption_mode="burn",
                                caption_model="qwen3-asr-1.7b-q4-k-m", translate=True,
                                translation_model="index-translate-9b-q4-k-m",
                                target_languages=("ja", "zh-Hant"), bilingual_language="zh-Hant")
    store.set_preference("settings", settings.to_dict())
    window = MainWindow(store)
    window.destination.setText(str(OUTPUT / "輸出影片"))
    for index in range(1, 5):
        window._preview_event({"type": "item", "item": {
            "url": f"https://youtu.be/layout{index}", "title": f"Playlist {index} · 機器學習基石",
            "playlist": "Learning · 學習", "index": index, "duration": 123,
            "detailed": True, "heights": [720, 1080], "captions": {"creator": ["en", "zh-Hant"]},
        }})
    window.preview.selectRow(0)
    # No worker is started by adding these diagnostic rows.
    if not store.jobs():
        store.enqueue(window.items, settings, str(OUTPUT / "輸出影片"))
        job = store.jobs()[-1]
        store.update(job["id"], stage="caption", status="failed", download_status="complete", caption_status="failed",
                     error="Example: caption source is unavailable.")
        store.update(store.jobs()[1]["id"], stage="caption", status="caption_queued", download_status="complete", caption_status="queued")
        store.update(store.jobs()[2]["id"], stage="translation", status="translation_queued", download_status="complete", caption_status="complete", translation_status="queued")
    window.refresh_jobs()
    shots = []

    def capture(widget, name):
        app.processEvents()
        path = OUTPUT / f"{name}.png"
        assert widget.grab().save(str(path))
        shots.append(str(path))

    window.show()
    for width, height in ((1100, 680), (1100, 740), (1380, 900)):
        window.resize(width, height)
        size = f"{width}x{height}"
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            capture(window, f"{size}-page-{index}")
        window.tabs.setCurrentIndex(0)
        window.ranges_button.setChecked(True)
        app.processEvents()
        capture(window, f"{size}-playlist-ranges")
        window.ranges_button.setChecked(False)
        window.preview_scroll.verticalScrollBar().setValue(0)
        for index in range(window.queue_tabs.count()):
            window.queue_tabs.setCurrentIndex(index)
            capture(window, f"{size}-queue-{index}")
        window.tabs.setCurrentWidget(window.download_settings_page)
        for index in range(window.settings_panel.pages.count()):
            window.settings_panel.pages.setCurrentIndex(index)
            capture(window, f"{size}-settings-{index}")
            scroll = window.settings_panel.pages.widget(index)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            capture(window, f"{size}-settings-{index}-bottom")
            scroll.verticalScrollBar().setValue(0)
        window.tabs.setCurrentWidget(window.model_library)
        for index in range(window.model_library.tabs.count()):
            window.model_library.tabs.setCurrentIndex(index)
            scroll = window.model_library.tabs.widget(index)
            for position in (0, 1):
                scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() * position)
                capture(window, f"{size}-models-{index}-{position}")
    override = OverrideDialog(replace(settings, translate=False), window.items[0], window)
    override.show()
    for index in range(override.panel.pages.count()):
        override.panel.pages.setCurrentIndex(index)
        capture(override, f"item-settings-{index}")
    override.close()
    override.deleteLater()
    source = OUTPUT / "source.json"
    source.write_text(json.dumps([{"id": "cue-1", "start": 1, "end": 3,
                                   "text": "Hello 世界. Caption correction preview."}],
                                  ensure_ascii=False), encoding="utf-8")
    editor = CaptionEditor({"title": "Example · 字幕", "settings": settings.to_dict(),
                            "cues_path": str(source), "caption_language_result": "en"}, window)
    editor.show()
    capture(editor, "caption-editor")
    editor.close()
    window.close()
    store.close()
    (OUTPUT / "report.json").write_text(json.dumps({"screenshots": shots}, indent=2), encoding="utf-8")
    print(f"Captured {len(shots)} screens in {OUTPUT}")


if __name__ == "__main__":
    main()
