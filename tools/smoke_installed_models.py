"""Check installed model selection in the packaged GUI using an isolated database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    from videodock.store import Store

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = ROOT / ".test-artifacts/releases" / version / "installed-ui"
    data = output / "appdata"
    models = ROOT / ".test-artifacts/model-resources/source/models"
    store = Store(data / "videodock.sqlite3")
    try:
        store.set_preference("model_folder", str(models))
    finally:
        store.close()
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM="offscreen", VIDEODOCK_DATA_DIR=str(data), PYTHONIOENCODING="utf-8")
    subprocess.run(
        [str(ROOT / "dist" / f"VideoDock-{version}" / "VideoDock.exe"), "--smoke-test", str(output)],
        env=environment, check=True, timeout=45,
    )
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert all(report["use_enabled"][key] for key in report["resource_models"]), report["use_enabled"]
    translation, speech = report["selections"]
    assert translation["translation"] == translation["used"] == "index-translate-9b-q4-k-m", translation
    assert speech["speech"] == speech["used"] == "qwen3-asr-1.7b-q4-k-m", speech
    assert translation["device"] == speech["device"] == "cuda", report["selections"]
    print("All nine installed Use buttons enabled; Q4 translation and speech select their model and CUDA.")


if __name__ == "__main__":
    main()
