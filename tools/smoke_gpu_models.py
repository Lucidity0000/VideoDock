"""Run real model inference with CPU fallback disabled in an isolated library."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videodock.caption_models import model_spec, verify_model
from videodock.inference_client import InferenceClient
from videodock.models import DownloadSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--root", type=Path, default=Path(".test-artifacts/model-resources/source/models"))
    parser.add_argument("--audio", type=Path, default=Path(".test-artifacts/gpu/jfk.wav"))
    parser.add_argument("--report", type=Path, default=Path(".test-artifacts/gpu/inference.json"))
    args = parser.parse_args()
    os.environ["VIDEODOCK_DATA_DIR"] = str(Path(".test-artifacts/gpu/data").resolve())
    results = []
    for model_id in args.models:
        spec, cancel = model_spec(model_id), threading.Event()
        events = []
        started = time.monotonic()
        client = None
        try:
            path = verify_model(args.root, spec, cancel)
            client = InferenceClient(
                spec, path, DownloadSettings(caption_device="cuda", cpu_fallback=False), cancel, events.append
            )
            assert client.device == "cuda", client.runtime
            if spec["task"] == "translation":
                outputs = [
                    client.call({"action": "translate", "text": text, "source": "en", "target": target})
                    for text, target in [
                        ("The download has finished. You can now use the model.", "zh-Hant"),
                        ("Good morning.", "ja"),
                    ]
                ]
            elif spec["task"] == "speech":
                outputs = [
                    client.call(
                        {"action": "transcribe", "audio": str(args.audio.resolve()), "language": "auto"}
                    )
                    for _ in range(2)
                ]
                assert all("country" in item["text"].lower() for item in outputs), outputs
            else:
                outputs = [
                    client.call(
                        {
                            "action": "align",
                            "audio": str(args.audio.resolve()),
                            "language": "en",
                            "text": "And so my fellow Americans ask not what your country can do for you ask what you can do for your country.",
                        }
                    )
                ]
            assert all(outputs), outputs
            result = {"model": model_id, "passed": True, "runtime": client.runtime, "outputs": outputs}
        except Exception as exc:
            result = {"model": model_id, "passed": False, "error": str(exc), "events": events}
        finally:
            if client:
                client.close()
        result["seconds"] = round(time.monotonic() - started, 2)
        results.append(result)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)
    return int(any(not item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
