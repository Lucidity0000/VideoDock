"""Cancel a real CUDA translation, check child cleanup, then use a fresh GPU helper."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    from videodock import __version__
    from videodock.caption_models import model_spec, verify_model
    from videodock.inference_client import InferenceClient
    from videodock.models import DownloadSettings
    from videodock.processes import Cancelled

    output = ROOT / ".test-artifacts/gpu/cancellation"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["VIDEODOCK_DATA_DIR"] = str(output / "appdata")
    os.environ["VIDEODOCK_RESOURCE_DIR"] = str(ROOT / "dist" / f"VideoDock-{__version__}" / "_internal")
    models = ROOT / ".test-artifacts/model-resources/source/models"
    cancel, events, outcomes = threading.Event(), [], []
    settings = DownloadSettings(caption_device="cuda", cpu_fallback=False)
    spec = model_spec("index-translate-9b-q4-k-m")
    path = verify_model(models, spec, cancel)
    client = InferenceClient(spec, path, settings, cancel, events.append)
    owned = psutil.Process(client.process.pid)
    processes = [owned, *owned.children(recursive=True)]
    assert len(processes) >= 2, "Expected the inference worker and its llama.cpp child"
    assert client.device == "cuda", client.runtime

    def translate():
        try:
            client.call({"action": "translate", "text": "\n".join(
                f"Sentence {i}: The download is complete and the model is ready to use on the graphics card."
                for i in range(1, 41)
            ), "source": "en", "target": "ja"})
            outcomes.append("completed")
        except Cancelled:
            outcomes.append("cancelled")
        except Exception as exc:
            outcomes.append(str(exc))

    thread = threading.Thread(target=translate)
    thread.start()
    try:
        time.sleep(0.2)
        started = time.monotonic()
        cancel.set()
        thread.join(timeout=12)
        assert not thread.is_alive() and outcomes == ["cancelled"], outcomes
        assert client.process is None
        _, alive = psutil.wait_procs(processes, timeout=5)
        assert not alive, [(process.pid, process.name()) for process in alive]
        elapsed = round(time.monotonic() - started, 2)
    finally:
        cancel.set()
        thread.join(timeout=12)
        client.close()
    cancel.clear()
    fresh = InferenceClient(spec, path, settings, cancel, events.append)
    try:
        result = fresh.call({"action": "translate", "text": "Good morning.", "source": "en", "target": "ja"})
        assert fresh.device == "cuda" and result.strip(), (fresh.runtime, result)
        report = {"passed": True, "cancel_seconds": elapsed, "owned_pids": [process.pid for process in processes],
                  "restart_runtime": fresh.runtime, "translation": result, "events": events}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        fresh.close()


if __name__ == "__main__":
    main()
