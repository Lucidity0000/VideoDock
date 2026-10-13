from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt

from videodock.models import DownloadSettings
from videodock.ui import MainWindow


def history_jobs(store, tmp_path, count):
    for index in range(count):
        store.enqueue([{"url": f"https://youtu.be/history-batch-{index}", "title": f"Video {index}"}],
                      DownloadSettings(), str(tmp_path / f"destination-{index}"))
    jobs = store.jobs()
    for job in jobs:
        store.update(job["id"], status="completed", download_status="complete")
    return jobs


def select_jobs(window, identifiers):
    selection = window.history.selectionModel()
    selection.clearSelection()
    for row in range(window.history.rowCount()):
        if window.history.item(row, 0).data(Qt.ItemDataRole.UserRole) in identifiers:
            selection.select(window.history.model().index(row, 0),
                             QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def test_generate_captions_queues_all_selected_history_media(app, store, tmp_path, monkeypatch):
    jobs = history_jobs(store, tmp_path, 4)
    paths = [tmp_path / "原始影片.mp4", tmp_path / "audio.mp3", tmp_path / "saved.webm"]
    for index, (job, path) in enumerate(zip(jobs, paths, strict=False)):
        path.write_bytes(b"saved media")
        store.update(job["id"], media_path=str(path if index != 2 else tmp_path / "missing-original.webm"),
                     output=str(path if index != 0 else tmp_path / "missing-export.mp4"))
    store.update(jobs[3]["id"], title="Video 1.5")
    window = MainWindow(store)
    settings = DownloadSettings(caption_source="local", caption_mode="embed", caption_model="base", spoken_language="zh")
    monkeypatch.setattr(window.settings_panel, "settings", lambda: settings)
    pumps = []
    monkeypatch.setattr(window.controller, "pump", lambda: pumps.append(True))
    window.history_sort.setCurrentIndex(window.history_sort.findData([1, True]))
    select_jobs(window, {job["id"] for job in jobs[:3]})
    # A current row is distinct from the selected batch, including after refresh.
    current = next(row for row in range(4) if window.history.item(row, 0).data(Qt.ItemDataRole.UserRole) == jobs[3]["id"])
    window.history.setCurrentCell(current, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
    window.refresh_jobs()
    window.generate_captions_button.click()
    queued = [job for job in store.jobs() if job["status"] == "caption_queued"]
    assert len(queued) == 3 and window.caption_queue.rowCount() == 3
    assert window.current_stage() == "caption" and window.tabs.currentIndex() == 0
    assert pumps == [True] and not window.controller.stage_running("caption")
    by_media = {Path(job["media_path"]): job for job in queued}
    assert set(by_media) == set(paths)
    for index, path in enumerate(paths):
        job = by_media[path]
        assert job["destination"] == str(tmp_path / f"destination-{index}")
        assert job["settings"]["caption_model"] == "base" and job["settings"]["spoken_language"] == "zh"
        assert job["settings"]["caption_mode"] == ("sidecar" if index == 1 else "embed")
    assert by_media[paths[1]]["settings"]["format"] == "mp3"
    assert by_media[paths[2]]["settings"]["format"] == "mp4"
    assert "Added 3 caption jobs from 3 selected" in window.notice.text()
    assert "Start queue" in window.notice.text()
    assert all(store.get(job["id"])["status"] == "completed" for job in jobs)
    window.close()
    window.deleteLater()


def test_generate_captions_reports_missing_and_busy_history_without_dropping_valid_items(app, store, tmp_path, monkeypatch):
    jobs = history_jobs(store, tmp_path, 4)
    for job in jobs[1:]:
        path = tmp_path / f"{job['sequence']}.mp4"
        path.write_bytes(b"saved media")
        store.update(job["id"], media_path=str(path), output=str(path))
    window = MainWindow(store)
    monkeypatch.setattr(window.settings_panel, "settings", lambda: DownloadSettings(caption_model="base"))
    window.controller.caption_id = jobs[2]["id"]
    select_jobs(window, {job["id"] for job in jobs})
    window.generate_captions_button.click()
    queued = [job for job in store.jobs() if job["status"] == "caption_queued"]
    assert {job["media_path"] for job in queued} == {store.get(job["id"])["media_path"] for job in (jobs[1], jobs[3])}
    assert "Added 2 caption jobs from 4 selected" in window.notice.text()
    assert "Skipped 2" in window.notice.text()
    assert f"#{jobs[0]['sequence']}: Saved media is missing" in window.notice.text()
    assert f"#{jobs[2]['sequence']}: The job is still finishing" in window.notice.text()
    window.controller.caption_id = None
    window.close()
    window.deleteLater()


def test_generate_captions_requires_selection_and_rejects_invalid_batch_settings(app, store, tmp_path, monkeypatch):
    jobs = history_jobs(store, tmp_path, 1)
    window = MainWindow(store)
    window.history.setCurrentCell(0, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
    window.generate_captions_button.click()
    assert "Select one or more history items" in window.notice.text() and len(store.jobs()) == 1
    select_jobs(window, {jobs[0]["id"]})

    def invalid_settings():
        raise ValueError("Choose a supported speech language.")

    monkeypatch.setattr(window.settings_panel, "settings", invalid_settings)
    window.generate_captions_button.click()
    assert window.notice.text() == "Choose a supported speech language." and len(store.jobs()) == 1
    window.close()
    window.deleteLater()
