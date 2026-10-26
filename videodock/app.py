from __future__ import annotations

import argparse
import sys


def main() -> int:
    if "--worker" in sys.argv:
        from .worker import main as worker_main

        return worker_main()
    parser = argparse.ArgumentParser(description="VideoDock desktop downloader")
    parser.add_argument(
        "--diagnose", action="store_true", help="Print dependency checks without starting the GUI"
    )
    parser.add_argument("--smoke-test", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.diagnose:
        from .dependencies import dependency_report

        for name, value in dependency_report().items():
            print(f"{name}: {value}")
        return 0
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .dependencies import data_directory
    from .store import Store
    from .ui import MainWindow

    application = QApplication(sys.argv)
    application.setApplicationName("VideoDock")
    application.setOrganizationName("VideoDock")
    application.setStyle("Fusion")
    if arguments.smoke_test and sys.platform == "win32":
        import os
        from pathlib import Path

        from PySide6.QtGui import QFontDatabase

        # The offscreen Windows plugin has no system font discovery of its own.
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    root = data_directory()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "VideoDock is already running", "Use the existing VideoDock window to manage the queue."
        )
        return 1
    store = Store(root / "videodock.sqlite3")
    try:
        window = MainWindow(store)
        window.show()
        if arguments.smoke_test:
            import json
            from pathlib import Path

            from PySide6.QtCore import QTimer

            from .caption_models import catalog
            from .dependencies import dependency_report, resource_directory, worker_command
            from .models import DownloadSettings
            from .queue_ui import BulkSettingsDialog, ComparisonDialog, QueueOptionsDialog, ScheduleDialog
            from .saved_lists_ui import SavedListEditor

            def capture():
                folder = Path(arguments.smoke_test).resolve()
                folder.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(folder / "window.png"))
                page_names = []
                for index in range(window.tabs.count()):
                    window.tabs.setCurrentIndex(index)
                    application.processEvents()
                    window.grab().save(str(folder / f"page-{index}.png"))
                    page_names.append(window.tabs.tabText(index))
                settings_tabs = []
                window.tabs.setCurrentWidget(window.download_settings_page)
                for index in range(window.settings_panel.pages.count()):
                    window.settings_panel.pages.setCurrentIndex(index)
                    application.processEvents()
                    window.grab().save(str(folder / f"settings-{index}.png"))
                    settings_tabs.append(window.settings_panel.pages.tabText(index))
                manager = window.model_library
                window.tabs.setCurrentWidget(manager)
                model_tabs = []
                for index in range(manager.tabs.count()):
                    manager.tabs.setCurrentIndex(index)
                    application.processEvents()
                    window.grab().save(str(folder / f"models-{index}.png"))
                    model_tabs.append(manager.tabs.tabText(index))
                use_enabled = {key: controls[5].isEnabled() for key, controls in manager.controls.items()}
                selections = []
                for key in ("index-translate-9b-q4-k-m", "qwen3-asr-1.7b-q4-k-m"):
                    if use_enabled[key]:
                        manager.controls[key][5].click()
                        panel = window.settings_panel
                        selections.append({"used": key, "speech": panel.local_model.currentData(),
                                           "translation": panel.translation_panel.model.currentData(),
                                           "device": panel.device.currentData()})
                # Exercise the frozen list/controller implementation in the smoke database.
                window.tabs.setCurrentIndex(0)
                window.saved_lists_button.setChecked(True)
                saved_id = store.create_saved_list("Smoke favorite · 最愛", "favorite",
                                                   ["https://youtube.com/playlist?list=smoke"], [{
                                                       "url": "https://youtu.be/smoke-original", "title": "Original entry"}])
                window.refresh_saved_lists(saved_id)
                window._preview_event({"type": "item", "item": {
                    "url": "https://youtu.be/smoke-external", "title": "Added elsewhere · 新影片",
                    "playlist": "", "index": 0, "duration": None}})
                window.add_to_list_button.click()
                assert len(store.saved_list(saved_id)["items"]) == 2
                window.load_list_button.click()
                assert len(window.items) == 2
                editor = SavedListEditor(store, saved_id, window)
                editor.changed.connect(window.refresh_saved_lists)
                editor.show()
                editor.entries.selectRow(0)
                editor.remove_button.click()
                editor.name.setText("Edited favorite · 自訂")
                editor.rename()
                application.processEvents()
                editor.grab().save(str(folder / "saved-list-editor.png"))
                editor.close()
                window.load_list_button.click()
                assert len(window.items) == 1 and window.items[0]["title"] == "Added elsewhere · 新影片"
                if not window.auto_caption.isChecked():
                    window.auto_caption.click()
                if not window.auto_translation.isChecked():
                    window.auto_translation.click()
                assert not window.controller.running
                # Exercise new frozen GUI/controller paths without starting workers or OS power actions.
                store.enqueue(window.items, DownloadSettings(), str(folder / "queue-output"), allow_duplicates=True)
                identifiers = [job["id"] for job in store.jobs()]
                bulk = BulkSettingsDialog(store.jobs(), DownloadSettings().to_dict(), window)
                bulk.panel.height.setCurrentIndex(bulk.panel.height.findData(480))
                bulk.show()
                application.processEvents()
                bulk.grab().save(str(folder / "bulk-settings.png"))
                bulk.apply_all_button.click()
                assert all(job["settings"]["height"] == 480 for job in store.jobs())
                assert window.preview.columnCount() == 5
                assert window.queue.horizontalHeaderItem(7).text() == "Settings"
                assert window.queue.item(0, 7).text() == "Custom"
                window.controller.pause_jobs(identifiers)
                assert all(store.get(key)["status"] == "paused" for key in identifiers)
                window.controller.resume_jobs(identifiers)
                assert not window.controller.running
                comparison = ComparisonDialog([(job["title"], job["settings"]) for job in store.jobs()], DownloadSettings().to_dict(), window)
                comparison.show()
                application.processEvents()
                comparison.grab().save(str(folder / "settings-comparison.png"))
                comparison.close()
                schedules = ScheduleDialog(store, window)
                schedules.add()
                schedules.show()
                application.processEvents()
                schedules.grab().save(str(folder / "queue-schedules.png"))
                schedules.entries.setCurrentRow(0)
                schedules.cancel_selected()
                assert store.schedules()[-1]["state"] == "cancelled"
                assert schedules.entries.count() == 0
                schedules.close()
                options = QueueOptionsDialog(window)
                options.show()
                application.processEvents()
                options.grab().save(str(folder / "background-completion-options.png"))
                options.close()
                window.reorder_jobs(identifiers, None, "download")
                assert all(store.timeline(key) for key in identifiers)
                application.processEvents()
                window.grab().save(str(folder / "saved-lists.png"))
                (folder / "report.json").write_text(
                    json.dumps(
                        {
                            "dependencies": dependency_report(),
                            "queue_controls": {"bulk_edit": True, "comparison": True, "job_pause_resume": True,
                                               "schedules": True, "timeline": True, "power_executed": False,
                                               "settings_in_queues": True, "apply_all_changed": True,
                                               "cancelled_schedules_hidden": True},
                            "resources": str(resource_directory()),
                            "worker": worker_command(),
                            "tabs": window.tabs.count(),
                            "page_names": page_names,
                            "queue_names": [window.queue_tabs.tabText(i).split(" (")[0] for i in range(window.queue_tabs.count())],
                            "open_destination": window.open_destination_button.text(),
                            "history_columns": [window.history.horizontalHeaderItem(i).text() for i in range(window.history.columnCount())],
                            "history_sort_options": [window.history_sort.itemText(i) for i in range(window.history_sort.count())],
                            "clear_history_actions": [window.clear_selected_button.text(), window.clear_cancelled_button.text()],
                            "settings_tabs": settings_tabs,
                            "model_tabs": model_tabs,
                            "use_enabled": use_enabled,
                            "selections": selections,
                            "saved_lists": {"name": store.saved_list(saved_id)["name"],
                                            "remaining_entries": len(window.items), "added_from_other_link": True,
                                            "original_links": store.saved_list(saved_id)["source_urls"]},
                            "auto_start": {"caption": store.preference("auto_start_caption"),
                                           "translation": store.preference("auto_start_translation"),
                                           "queues_paused": not window.controller.running},
                            "resource_models": [spec["id"] for spec in catalog() if spec.get("format")],
                            "speech_selector": [window.settings_panel.local_model.itemData(index)
                                                for index in range(window.settings_panel.local_model.count())],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                window.close()

            QTimer.singleShot(250, capture)
        return application.exec()
    finally:
        store.close()
        lock.unlock()
