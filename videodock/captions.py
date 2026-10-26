from __future__ import annotations

import math
import os
import re
import threading
from dataclasses import replace
from pathlib import Path

from .caption_models import check_cancel, is_ready, model_lock, model_spec, verify_model
from .dependencies import find_binary
from .models import DownloadSettings
from .processes import run_lines


class WaitingForModel(Exception):
    def __init__(self, message, model_id=""):
        super().__init__(message)
        self.model_id = model_id


def timestamp(seconds: float, vtt: bool = False) -> str:
    value = round(seconds * 1000)
    return f"{value // 3600000:02d}:{value // 60000 % 60:02d}:{value // 1000 % 60:02d}{'.' if vtt else ','}{value % 1000:03d}"


def wrap_text(text: str, width: int) -> str:
    lines = []
    text = text.strip()
    while len(text) > width:
        split = text.rfind(" ", 0, width + 1)
        split = split if split > width // 2 else width
        lines.append(text[:split].strip())
        text = text[split:].strip()
    if text:
        lines.append(text)
    return "\n".join(lines)


def build_cues(
    segments, settings: DownloadSettings, cancel: threading.Event, emit, duration: float
) -> list[dict]:
    cues = []
    for segment in segments:
        check_cancel(cancel)
        words = list(segment.words or [])
        if not words:
            words = [type("Word", (), {"start": segment.start, "end": segment.end, "word": segment.text})()]
        text = ""
        start = end = 0.0

        def flush(start, end):
            nonlocal text
            if text.strip() and end > start:
                cues.append(
                    {
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "text": wrap_text(text, settings.caption_line_length),
                    }
                )
            text = ""

        for word in words:
            check_cancel(cancel)
            token = word.word
            # Split long unspaced tokens (e.g. Chinese) using the word's original span.
            pieces = max(
                1,
                math.ceil(len(token) / (settings.caption_line_length * 2)),
                math.ceil((word.end - word.start) / settings.caption_max_duration),
            )
            for index in range(pieces):
                left = word.start + (word.end - word.start) * index / pieces
                right = word.start + (word.end - word.start) * (index + 1) / pieces
                part = token[len(token) * index // pieces : len(token) * (index + 1) // pieces]
                if text and (
                    len(text + part) > settings.caption_line_length * 2
                    or len(wrap_text(text + part, settings.caption_line_length).splitlines()) > 2
                    or right - start > settings.caption_max_duration
                    or left - end > 1.0
                ):
                    flush(start, end)
                if not text:
                    start = max(0.0, left, cues[-1]["end"] if cues else 0.0)
                if right <= start:
                    continue
                text += part
                end = max(start, right)
                if re.search(r"[.!?。！？]\s*$", part):
                    flush(start, end)
        flush(start, end)
        processed = min(duration, float(segment.end)) if duration else float(segment.end)
        emit(
            {
                "type": "caption_progress",
                "processed": processed,
                "duration": duration,
                "progress": min(99, processed / duration * 100) if duration else 0,
                "preview": cues[-1]["text"] if cues else "",
            }
        )
    return cues


def validate_cues(cues: list[dict]):
    previous = 0.0
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < previous or end <= start:
            raise ValueError(
                "Caption times must be finite, ordered, and have end after start without overlaps."
            )
        if not isinstance(cue["text"], str) or not cue["text"].strip() or "-->" in cue["text"]:
            raise ValueError("Each caption needs text without a timestamp arrow.")
        previous = end


def subtitle_text(cues: list[dict], fmt: str) -> str:
    validate_cues(cues)
    vtt = fmt == "vtt"
    blocks = ["WEBVTT\n"] if vtt else []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{timestamp(cue['start'], vtt)} --> {timestamp(cue['end'], vtt)}\n{cue['text'].strip()}\n"
        )
    return "\n".join(blocks) + "\n"


def atomic_text(path: Path, text: str):
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def reserve_sidecar(source: Path, destination: Path, language: str, fmt: str) -> Path:
    path = destination / f"{source.stem}.{language}.{fmt}"
    counter = 1
    while True:
        try:
            with path.open("xb"):
                pass
            return path
        except FileExistsError:
            path = destination / f"{source.stem}.{language} ({counter}).{fmt}"
            counter += 1


def prepare_audio(source, work, cancel, emit):
    audio = work / "audio.wav"
    if audio.is_file():
        return audio
    binary = find_binary("ffmpeg")
    if not binary:
        raise ValueError("FFmpeg is required to prepare audio.")
    emit({"type": "status", "status": "preparing"})
    run_lines([binary, "-y", "-nostdin", "-v", "error", "-i", str(source),
               "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)],
              cancel, lambda _: None)
    return audio


class CaptionEngine:
    """Lives in the caption process. Reuses one local model across playlist entries."""

    def __init__(self):
        self.model = None
        self.cache_key = None
        self.loaded_device = "cpu"
        self.translation = None
        self.inference = None

    def release_speech(self):
        if self.inference:
            self.inference.close()
            self.inference = None
        self.model = self.cache_key = None

    def _load(self, root, spec, settings, cancel, emit):
        from faster_whisper import WhisperModel

        key = (str(root), spec["revision"], settings.caption_device, settings.cpu_fallback)
        if key == self.cache_key:
            return self.model
        self.release_speech()
        path = verify_model(root, spec, cancel)
        check_cancel(cancel)
        device = settings.caption_device
        if device == "cuda":
            import ctranslate2

            from .translation import gpu_library_error

            if ctranslate2.get_cuda_device_count() < 1:
                if not settings.cpu_fallback:
                    raise ValueError("NVIDIA GPU is unavailable. Enable CPU fallback or choose CPU.")
                emit({"type": "warning", "message": "NVIDIA GPU unavailable; using CPU INT8."})
                device = "cpu"
            elif error := gpu_library_error():
                if not settings.cpu_fallback:
                    raise ValueError(
                        "CUDA cuBLAS is unavailable. Choose CPU or enable CPU fallback. " + error
                    )
                emit({"type": "warning", "message": "CUDA cuBLAS unavailable; using CPU INT8. " + error})
                device = "cpu"
        try:
            self.model = WhisperModel(
                str(path),
                device=device,
                compute_type="int8" if device == "cpu" else "float16",
                local_files_only=True,
                cpu_threads=max(1, min(8, os.cpu_count() or 4)),
            )
        except (RuntimeError, OSError) as exc:
            if device != "cuda" or not settings.cpu_fallback:
                raise ValueError(
                    f"Cannot load caption model: {exc}. Try Base on CPU or free memory."
                ) from exc
            emit(
                {
                    "type": "warning",
                    "message": f"GPU dependencies or memory unavailable; using CPU INT8. {exc}",
                }
            )
            self.model = WhisperModel(str(path), device="cpu", compute_type="int8", local_files_only=True)
            device = "cpu"
        self.cache_key = key
        self.loaded_device = device
        return self.model

    def generate(self, job: dict, root: Path, cancel: threading.Event, emit):
        from .caption_pipeline import generate

        return generate(self, job, root, cancel, emit)

    def transcribe(self, source, work, root, settings, cancel, emit, duration):
        from .transcription import transcribe_segments

        return transcribe_segments(self, source, work, root, settings, cancel, emit, duration)

    def _transcribe_segment(self, source, work, root, settings, cancel, emit, duration):
        self.alignment_segments = []
        spec = model_spec(settings.caption_model, settings.model_revision)
        if not is_ready(root, spec):
            raise WaitingForModel("Waiting for speech model. Click Download required model.", spec["id"])
        with model_lock(root, spec):
            emit({"type": "status", "status": "preparing"})
            audio = work / "audio.wav"
            command = [
                find_binary("ffmpeg"),
                "-y",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ]
            if not command[0]:
                raise ValueError("FFmpeg is required to prepare audio.")
            run_lines(command, cancel, lambda _: None)
            emit({"type": "status", "status": "transcribing"})
            if spec.get("format"):
                from .additional_captions import transcribe
                return transcribe(self, audio, root, spec, settings, cancel, emit, duration)
            model = self._load(root, spec, settings, cancel, emit)
            language_arg = (
                "en"
                if spec["languages"] == "English only"
                else (None if settings.spoken_language == "auto" else settings.spoken_language)
            )

            def run(model):
                segments, detected = model.transcribe(
                    str(audio),
                    language=language_arg,
                    task="transcribe",
                    vad_filter=True,
                    word_timestamps=True,
                    condition_on_previous_text=spec["languages"] != "English only",
                )
                return build_cues(segments, settings, cancel, emit, duration), detected.language

            try:
                return run(model)
            except (RuntimeError, OSError) as exc:
                self.model = None
                self.cache_key = None
                if self.loaded_device != "cuda" or not settings.cpu_fallback:
                    raise ValueError(f"Transcription failed: {exc}. Try CPU or a smaller model.") from exc
                check_cancel(cancel)
                emit({"type": "warning", "message": f"GPU execution failed; using CPU INT8. {exc}"})
                model = self._load(root, spec, replace(settings, caption_device="cpu"), cancel, emit)
                return run(model)

    @staticmethod
    def _youtube_caption(job, settings, work, cancel, emit):
        if settings.caption_source == "local" or job["url"].startswith("file:"):
            return None
        from .engine import base_args, extract

        source = "auto" if settings.caption_source in {"auto", "fallback_auto"} else "creator"
        info = extract(job["url"], cancel)
        key = "automatic_captions" if source == "auto" else "subtitles"
        if settings.caption_language not in (info.get(key) or {}):
            if settings.uses_local:
                return None
            raise ValueError("The selected YouTube caption language is unavailable.")
        emit({"type": "status", "status": "preparing"})
        command = base_args() + [
            "--no-playlist",
            "--skip-download",
            "--write-auto-subs" if source == "auto" else "--write-subs",
            "--sub-langs",
            settings.caption_language,
            "--sub-format",
            "vtt/srt/best",
            "--convert-subs",
            settings.caption_format,
            "--output",
            str(work / "source.%(ext)s"),
            "--",
            job["url"],
        ]
        run_lines(command, cancel, lambda _: None)
        paths = list(work.glob(f"*.{settings.caption_language}.{settings.caption_format}"))
        if not paths:
            raise ValueError("YouTube caption download produced no subtitle file. Retry captions.")
        return paths[0]


def reexport(job: dict, cues, cancel: threading.Event, emit):
    from .caption_pipeline import reexport_tracks

    return reexport_tracks(job, cues, cancel, emit)
