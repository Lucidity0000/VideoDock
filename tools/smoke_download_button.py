"""Verify the real translation download button using cached isolated package bytes."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / ".test-artifacts/ui-refresh/download-button"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["VIDEODOCK_DATA_DIR"] = str(OUTPUT / "appdata")


def main():
    from PySide6.QtWidgets import QApplication

    from videodock.caption_models import is_ready, model_path, model_spec
    from videodock.store import Store
    from videodock.ui import MainWindow

    app = QApplication([])
    store = Store(OUTPUT / "appdata/videodock.sqlite3")
    models = OUTPUT / "models"
    store.set_preference("model_folder", str(models))
    spec = model_spec("m2m100-418m")
    source = ROOT / ".test-artifacts/local-captions/models"
    assert is_ready(source, spec), "Cached translation package is required"
    assert not is_ready(models, spec), "Use a fresh smoke folder to exercise the button"
    # Fully staged files exercise the actual worker's SHA-256 verification/publication
    # without another network download or touching the user's model library.
    stage = models / ".staging" / spec["id"] / spec["revision"]
    stage.mkdir(parents=True, exist_ok=True)
    for entry in spec["files"]:
        destination = stage / entry["name"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(model_path(source, spec) / entry["name"], destination)
    window = MainWindow(store)
    panel = window.settings_panel.translation_panel
    assert "Not downloaded" in panel.model_status.text()
    assert panel.download_button.isEnabled()
    panel.download_button.click()
    assert spec["id"] in window.controller.model_workers
    assert not panel.download_button.isEnabled()
    end = time.monotonic() + 60
    while window.controller.model_workers and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window.controller.model_workers, "Model worker did not finish"
    assert is_ready(models, spec), window.controller.model_states
    assert panel.download_button.text() == "Installed"
    assert "Installed" in panel.model_status.text()
    assert window.model_library.controls[spec["id"]][5].isEnabled()
    result = {"button": "Download translation model", "model": spec["id"],
              "verified_bytes": spec["bytes"], "status": panel.model_status.text(),
              "use_enabled": True, "network_download": False}
    (OUTPUT / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    window.close()
    store.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
