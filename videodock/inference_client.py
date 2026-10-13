"""Isolate Torch/GGUF CUDA runtimes from the persistent CTranslate2 worker."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

from .caption_models import check_cancel
from .dependencies import data_directory, resource_directory, subprocess_flags
from .processes import Cancelled


def inference_command():
    root = resource_directory()
    packaged = root / "vendor/inference/VideoDockInferenceWorker.exe"
    if packaged.is_file():
        return [str(packaged)]
    python = root / ".venv-inference/Scripts/python.exe"
    if python.is_file() and not getattr(sys, "frozen", False):
        return [str(python), "-m", "videodock.inference_worker"]
    raise ValueError("The additional model runtime is missing. Install the current VideoDock release.")


class InferenceClient:
    def __init__(self, spec, path, settings, cancel, emit):
        self.spec, self.path, self.settings = spec, path, settings
        self.cancel, self.emit = cancel, emit
        self.process = None
        self.events = queue.Queue()
        self.errors = ""
        self.device = settings.caption_device
        self.runtime = {}
        try:
            self._start()
        except (ValueError, RuntimeError, OSError) as exc:
            self.close()
            if self.device != "cuda" or not settings.cpu_fallback:
                raise
            self.emit({"type": "warning", "message": f"GPU model could not start; using CPU. {exc}"})
            self.device = "cpu"
            try:
                self._start()
            except BaseException:
                self.close()
                raise

    def _start(self):
        check_cancel(self.cancel)
        self.events = queue.Queue()
        self.errors = ""
        env = os.environ.copy()
        env.update(
            PYTHONIOENCODING="utf-8",
            PYTHONUNBUFFERED="1",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            VIDEODOCK_RESOURCE_DIR=str(resource_directory()),
            TOKENIZERS_PARALLELISM="false",
            HF_MODULES_CACHE=str(data_directory() / "runtime-cache/modules"),
        )
        self.process = subprocess.Popen(
            inference_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **subprocess_flags(),
        )
        process, events = self.process, self.events

        def read():
            for line in process.stdout:
                try:
                    events.put(json.loads(line))
                except (ValueError, UnicodeError):
                    self.errors = (self.errors + line.decode("utf-8", "replace"))[-6000:]
            events.put({"type": "exit"})

        def errors():
            for line in process.stderr:
                self.errors = (self.errors + line.decode("utf-8", "replace"))[-6000:]

        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()
        self.call({"action": "load", "spec": self.spec, "path": str(self.path), "device": self.device})

    def call(self, request):
        try:
            return self._call(request)
        except RuntimeError as exc:
            if request["action"] == "load" or self.device != "cuda" or not self.settings.cpu_fallback:
                self.close()
                raise
            self.close()
            self.emit({"type": "warning", "message": f"GPU inference failed; using CPU. {exc}"})
            self.device = "cpu"
            self._start()
            return self._call(request)

    def _call(self, request):
        check_cancel(self.cancel)
        self.process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            if self.cancel.is_set():
                self.close()
                raise Cancelled()
            try:
                event = self.events.get(timeout=0.05)
            except queue.Empty:
                continue
            if event["type"] == "result":
                return event.get("value")
            if event["type"] == "runtime":
                self.runtime = event
                self.device = event["device"]
                self.emit({**event, "type": "model_runtime", "model_id": self.spec["id"]})
            elif event["type"] == "error":
                if event.get("device_error"):
                    raise RuntimeError(event["message"])
                raise ValueError(event["message"])
            elif event["type"] == "exit":
                raise ValueError("Model runtime stopped. " + self.errors)
        self.close()
        raise ValueError("Model runtime timed out. Try a smaller model or free GPU memory.")

    def encode(self, text, **kwargs):
        return self.call({"action": "tokenize", "text": text})

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.stdin.write(b"cancel\n")
                process.stdin.flush()
                process.stdin.close()
                process.wait(timeout=2)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
