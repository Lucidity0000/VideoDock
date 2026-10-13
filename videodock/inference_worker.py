"""Private offline helper: BF16 Transformers, CUDA llama.cpp and transcribe.cpp."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from .dependencies import data_directory, resource_directory, subprocess_flags
from .languages import NAMES
from .windows_job import WindowsJob


def control_lines():
    # Native runtime initialization must never compete with a blocking Windows stdin read.
    if os.name != "nt":
        yield from sys.stdin
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.PeekNamedPipe.restype = kernel.ReadFile.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    block, pending = ctypes.create_string_buffer(4096), b""
    while True:
        available = wintypes.DWORD()
        if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            break
        if not available.value:
            time.sleep(0.025)
            continue
        count = wintypes.DWORD()
        if not kernel.ReadFile(handle, block, min(len(block), available.value), ctypes.byref(count), None):
            break
        pending += block.raw[: count.value]
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            yield line.decode("utf-8").rstrip("\r")


def language_code(value):
    names = {name.lower(): tag for tag, name in NAMES.items() if "-" not in tag}
    names.update(
        {
            "chinese": "zh",
            "cantonese": "yue",
            "filipino": "tl",
            "persian": "fa",
            "turkish": "tr",
            "greek": "el",
            "hungarian": "hu",
            "romanian": "ro",
            "swedish": "sv",
            "danish": "da",
            "finnish": "fi",
            "polish": "pl",
            "czech": "cs",
            "malay": "ms",
            "macedonian": "mk",
        }
    )
    value = (value or "").lower().strip()
    return names.get(value, value or "und")


def read_audio(path, start=0, end=None):
    import numpy as np

    with wave.open(str(path), "rb") as source:
        if source.getframerate() != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Inference audio must be 16 kHz mono PCM16 WAV.")
        source.setpos(min(source.getnframes(), int(start * 16000)))
        count = source.getnframes() - source.tell() if end is None else max(0, int((end - start) * 16000))
        return np.frombuffer(source.readframes(count), dtype="<i2").astype(np.float32) / 32768.0


class TensorRuntime:
    def __init__(self, spec, path, device, cancel):
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoModelForTokenClassification,
            AutoProcessor,
            AutoTokenizer,
        )

        self.torch, self.spec, self.device, self.cancel = torch, spec, device, cancel
        self.offload_folder = None
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("The CUDA runtime cannot access an NVIDIA GPU. Update the driver or choose CPU.")
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        kwargs = dict(local_files_only=True, dtype=dtype, attn_implementation="sdpa")
        self.task = spec["task"]
        if self.task == "translation":
            from transformers import Qwen3_5ForConditionalGeneration

            self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
            cls = Qwen3_5ForConditionalGeneration
            if device == "cuda":
                free, _ = torch.cuda.mem_get_info()
                import psutil

                kwargs.update(
                    device_map="auto",
                    max_memory={
                        0: max(512 * 1024**2, free - 1536 * 1024**2),
                        "cpu": max(1024**3, psutil.virtual_memory().available - 3 * 1024**3),
                    },
                )
                self.offload_folder = data_directory() / "runtime-cache/offload" / str(os.getpid())
                kwargs["offload_folder"] = str(self.offload_folder)
            else:
                kwargs["device_map"] = "cpu"
        else:
            custom = spec["architecture"] == "arkasr"
            self.processor = AutoProcessor.from_pretrained(
                path, local_files_only=True, trust_remote_code=custom
            )
            self.tokenizer = AutoTokenizer.from_pretrained(
                path, local_files_only=True, trust_remote_code=custom
            )
            if self.task == "alignment":
                cls = AutoModelForTokenClassification
            elif custom:
                cls = AutoModelForCausalLM
                kwargs["trust_remote_code"] = True
                # Published ARK custom code uses the older keyword explicitly.
                kwargs["torch_dtype"] = kwargs.pop("dtype")
            else:
                from transformers import AutoModelForMultimodalLM

                cls = AutoModelForMultimodalLM
            kwargs["device_map"] = device
        self.model = cls.from_pretrained(str(path), **kwargs).eval()
        gpu = sum(p.numel() * p.element_size() for p in self.model.parameters() if p.device.type == "cuda")
        cpu = sum(p.numel() * p.element_size() for p in self.model.parameters() if p.device.type == "cpu")
        if device == "cuda" and not gpu:
            raise ValueError(
                "The model has no tensors on the GPU; reduce memory use or choose a 4-bit model."
            )
        self.info = {
            "device": device,
            "backend": "Transformers",
            "gpu_tensor_bytes": gpu,
            "cpu_tensor_bytes": cpu,
            "cpu_offload": bool(gpu and cpu),
            "disk_offload": "disk" in getattr(self.model, "hf_device_map", {}).values(),
            "gpu_name": torch.cuda.get_device_name(0) if device == "cuda" else "",
        }

    def generate(self, inputs, **generation):
        from transformers import StoppingCriteria, StoppingCriteriaList

        cancel = self.cancel

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancel.is_set()

        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                stopping_criteria=StoppingCriteriaList([Stop()]),
                **generation,
            )
        produced = output[:, inputs["input_ids"].shape[1] :]
        if produced.shape[-1] >= 1024:
            raise ValueError("Model reached its output limit. Split the input and retry.")
        if self.device == "cuda":
            self.torch.cuda.synchronize()
        return produced

    def run(self, request):
        action = request["action"]
        if action == "tokenize":
            return self.tokenizer.encode(request["text"], add_special_tokens=False)
        if action == "translate":
            target = NAMES.get(request["target"], request["target"])
            source = NAMES.get(request["source"], request["source"])
            prompt = f"请将以下{source}文本翻译为{target}，直接输出翻译结果，不要进行任何解释。\n\n{request['text']}"
            inputs = self.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                return_tensors="pt",
                return_dict=True,
            ).to(self.model.device)
            return self.tokenizer.decode(self.generate(inputs)[0], skip_special_tokens=True).strip()
        audio = read_audio(request["audio"], request.get("start", 0), request.get("end"))
        if action == "align":
            language = NAMES.get(request["language"], request["language"])
            inputs, words = self.processor.prepare_forced_aligner_inputs(
                audio=audio, transcript=request["text"], language=language, return_tensors="pt"
            )
            inputs = inputs.to(self.model.device, self.model.dtype)
            with self.torch.inference_mode():
                output = self.model(**inputs)
            return self.processor.decode_forced_alignment(
                logits=output.logits,
                input_ids=inputs["input_ids"],
                word_lists=words,
                timestamp_token_id=self.model.config.timestamp_token_id,
            )[0]
        if self.spec["architecture"] == "arkasr":
            inputs = self.processor.apply_chat_template(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "audio", "array": audio},
                            {"type": "text", "text": "Please transcribe this audio."},
                        ],
                    }
                ],
                add_generation_prompt=True,
                return_tensors="pt",
                sampling_rate=16000,
                audio_padding="longest",
                text_kwargs={"padding": "longest"},
                audio_max_length=30 * 16000,
            )
            inputs = inputs.to(self.model.device)
            if "audios" in inputs:
                inputs["audios"] = inputs["audios"].to(dtype=self.model.dtype)
            eos = self.tokenizer.eos_token_id
            keep = {eos} if isinstance(eos, int) else set(eos or [])
            blocked = set(self.tokenizer.all_special_ids) - keep
            blocked.update(
                token_id
                for token, token_id in self.tokenizer.get_added_vocab().items()
                if token.startswith("<") and token.endswith(">") and token_id not in keep
            )
            generated = self.generate(
                inputs,
                eos_token_id=eos,
                pad_token_id=self.tokenizer.pad_token_id,
                bad_words_ids=[[token_id] for token_id in sorted(blocked)],
            )
            text = self.tokenizer.decode(generated[0], skip_special_tokens=True).strip()
            return {"text": text, "language": request.get("language", "auto")}
        kwargs = {} if request.get("language", "auto") == "auto" else {"language": request["language"]}
        inputs = self.processor.apply_transcription_request(audio=audio, return_tensors="pt", **kwargs).to(
            self.model.device, self.model.dtype
        )
        parsed = self.processor.decode(self.generate(inputs)[0], return_format="parsed")
        return {"text": parsed["transcription"].strip(), "language": language_code(parsed.get("language"))}

    def close(self):
        self.model = None
        if self.offload_folder:
            shutil.rmtree(self.offload_folder, ignore_errors=True)


class GGSpeechRuntime:
    def __init__(self, spec, path, device, cancel):
        self.dll_dirs = []
        self.cuda_dlls = []
        if os.name == "nt":
            folder = resource_directory() / "vendor/cuda12"
            if folder.is_dir():
                self.dll_dirs.append(os.add_dll_directory(str(folder)))
                if device == "cuda":
                    import ctypes
                    for name in ("cudart64_12.dll", "cublasLt64_12.dll", "cublas64_12.dll"):
                        self.cuda_dlls.append(ctypes.CDLL(str(folder / name)))
        import transcribe_cpp as tc

        self.cancel = cancel
        devices = [
            item
            for item in tc.backends()
            if (str(item.kind) == "cuda" if device == "cuda" else str(item.device_type) == "cpu")
        ]
        if not devices:
            raise ValueError("The GGUF speech runtime cannot access the selected device.")
        self.model = tc.Model(str(next(path.glob("*.gguf"))), device=devices[0])
        self.session = self.model.session()
        self.info = {"device": device, "backend": "transcribe.cpp", "gpu_name": str(devices[0].description)}

    def run(self, request):
        audio = read_audio(request["audio"], request.get("start", 0), request.get("end"))
        language = request.get("language", "auto")
        result = self.session.run(audio, language=None if language == "auto" else language, timestamps="none")
        return {"text": result.text.strip(), "language": language_code(result.language)}

    def close(self):
        self.session.close()
        self.model.close()
        for directory in self.dll_dirs:
            directory.close()


class GGTranslationRuntime:
    def __init__(self, spec, path, device, cancel):
        self.cancel, self.token = cancel, secrets.token_urlsafe(24)
        binary = resource_directory() / "vendor/llama/llama-server.exe"
        if not binary.is_file():
            raise ValueError("Bundled llama.cpp runtime is missing. Reinstall VideoDock.")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.opener = build_opener(ProxyHandler({}))
        self.log = []
        self.process = subprocess.Popen(
            [
                str(binary),
                "-m",
                str(next(path.glob("*.gguf"))),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--api-key",
                self.token,
                "--device",
                "CUDA0" if device == "cuda" else "none",
                "-ngl",
                "99" if device == "cuda" else "0",
                "-c",
                "4096",
                "--parallel",
                "1",
                "--jinja",
                "--reasoning",
                "off",
                "-lv",
                "4",
                "--no-webui",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **subprocess_flags(),
        )

        def read_log():
            for line in self.process.stderr:
                self.log.append(line.decode("utf-8", "replace"))
                self.log[:] = self.log[-250:]

        threading.Thread(target=read_log, daemon=True).start()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise ValueError("Model loading cancelled.")
            if self.process.poll() is not None:
                raise ValueError("Cannot start llama.cpp: " + "".join(self.log)[-3000:])
            try:
                self.http("/health")
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise ValueError("llama.cpp model loading timed out.")
        offload = re.search(r"offloaded (\d+)/(\d+) layers", "".join(self.log))
        if device == "cuda" and (not offload or int(offload[1]) < 1):
            raise ValueError(
                "llama.cpp loaded no GPU layers. Free GPU memory or choose CPU. " + "".join(self.log)[-6000:]
            )
        self.info = {
            "device": device,
            "backend": "llama.cpp",
            "gpu_layers": int(offload[1]) if offload else 0,
        }

    def http(self, path, data=None):
        request = Request(
            self.url + path,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token},
        )
        with self.opener.open(request, timeout=300 if data else 1) as response:
            return json.load(response)

    def run(self, request):
        if request["action"] == "tokenize":
            return self.http("/tokenize", {"content": request["text"]})["tokens"]
        target, source = (
            NAMES.get(request["target"], request["target"]),
            NAMES.get(request["source"], request["source"]),
        )
        prompt = (
            f"请将以下{source}文本翻译为{target}，直接输出翻译结果，不要进行任何解释。\n\n{request['text']}"
        )
        result = self.http(
            "/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 1024,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        choice = result["choices"][0]
        if choice["finish_reason"] == "length":
            raise ValueError("Translation reached its output limit. Split the input and retry.")
        return choice["message"]["content"].strip()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    wire = sys.stdout
    lifetime = WindowsJob()
    lifetime.assign_current()
    cancel, requests = threading.Event(), queue.Queue()
    controls = control_lines()
    first = json.loads(next(controls))
    requests.put(first)
    runtime = None

    def control():
        for line in controls:
            if line == "cancel":
                cancel.set()
                if runtime and hasattr(runtime, "session"):
                    runtime.session.cancel()
            elif line.startswith("{"):
                requests.put(json.loads(line))
        cancel.set()
        requests.put(None)

    threading.Thread(target=control, daemon=True).start()

    def emit(event):
        wire.write(json.dumps(event, ensure_ascii=True) + "\n")
        wire.flush()

    try:
        while (request := requests.get()) is not None:
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    if request["action"] == "load":
                        spec, path, device = request["spec"], Path(request["path"]), request["device"]
                        cls = (
                            (GGSpeechRuntime if spec["task"] == "speech" else GGTranslationRuntime)
                            if spec.get("format") == "GGUF"
                            else TensorRuntime
                        )
                        runtime = cls(spec, path, device, cancel)
                        emit({"type": "runtime", **runtime.info})
                        value = None
                    else:
                        value = runtime.run(request)
                    emit({"type": "result", "value": value})
            except Exception as exc:
                message = str(exc)
                emit(
                    {
                        "type": "error",
                        "message": message,
                        "device_error": any(
                            token in message.lower()
                            for token in ("cuda", "cublas", "out of memory", "device-side")
                        ),
                    }
                )
    finally:
        if runtime:
            runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
