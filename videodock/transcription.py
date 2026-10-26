"""Durable bounded speech segments, shared by Whisper and additional speech backends."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import replace

from .caption_models import check_cancel, model_spec
from .captions import WaitingForModel, atomic_text, validate_cues
from .dependencies import find_binary
from .processes import run_lines

SEGMENT_SECONDS = 30


def transcribe_segments(engine, source, work, root, settings, cancel, emit, duration):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Cannot checkpoint transcription without a finite positive media duration.")
    source = source.resolve()
    stat = source.stat()
    identity = hashlib.sha256(json.dumps({
        "source": str(source), "size": stat.st_size, "modified_ns": stat.st_mtime_ns,
        "duration": duration, "segment_seconds": SEGMENT_SECONDS,
        "settings": {key: value for key, value in settings.to_dict().items() if key in {
            "caption_model", "model_revision", "fallback_model", "fallback_revision", "spoken_language",
            "caption_device", "cpu_fallback", "caption_line_length", "caption_max_duration"}}, "schema": 1,
    }, sort_keys=True).encode()).hexdigest()
    path = getattr(engine, "checkpoint_path", None) or work / "transcription.json"
    data = {"identity": identity, "segments": []}
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("identity") == identity:
            data = saved
    total = math.ceil(duration / SEGMENT_SECONDS)
    completed = data["segments"]
    if not isinstance(completed, list) or len(completed) > total:
        raise ValueError("Transcription checkpoint is invalid; preserve it and generate a new caption job.")
    for index, segment in enumerate(completed):
        start, end = index * SEGMENT_SECONDS, min(duration, (index + 1) * SEGMENT_SECONDS)
        validate_cues(segment["cues"])
        if segment["start"] != start or segment["end"] != end or any(
                cue["start"] < start or cue["end"] > end + .001 for cue in segment["cues"]):
            raise ValueError("Transcription checkpoint segment boundaries are invalid.")
    if completed:
        emit({"type": "checkpoint_resume", "message": f"Resuming after {len(completed)}/{total} completed segments"})
    for index in range(len(completed), total):
        check_cancel(cancel)
        start, end = index * SEGMENT_SECONDS, min(duration, (index + 1) * SEGMENT_SECONDS)
        clip = work / "segment.wav"
        part_work = work / "segment"
        part_work.mkdir(parents=True, exist_ok=True)
        binary = find_binary("ffmpeg")
        if not binary:
            raise ValueError("FFmpeg is required to prepare transcription segments.")
        emit({"type": "status", "status": "preparing"})
        run_lines([binary, "-y", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(source),
                   "-t", str(end - start), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)],
                  cancel, lambda _: None)

        def progress(event, start=start, end=end):
            if event.get("type") == "caption_progress":
                processed = start + min(end - start, max(0, event["processed"]))
                event = {**event, "processed": processed, "duration": duration,
                         "progress": min(99, processed / duration * 100)}
            emit(event)

        used = settings.caption_model
        try:
            cues, language = engine._transcribe_segment(clip, part_work, root, settings, cancel, progress, end - start)
        except WaitingForModel:
            raise
        except (ValueError, RuntimeError, OSError) as exc:
            check_cancel(cancel)
            if not settings.fallback_model:
                raise
            used = settings.fallback_model
            fallback = replace(settings, caption_model=used, model_revision=settings.fallback_revision,
                               fallback_model="", fallback_revision="")
            fallback.validate()
            emit({"type": "segment_fallback", "message":
                  f"{start:.3f}–{end:.3f}s: {settings.caption_model} failed: {exc}. Trying {used}."})
            try:
                cues, language = engine._transcribe_segment(clip, part_work, root, fallback, cancel, progress, end - start)
            except WaitingForModel:
                raise
            except (ValueError, RuntimeError, OSError) as fallback_error:
                raise ValueError(f"Speech segment {start:.3f}–{end:.3f}s failed with primary and fallback models. "
                                 f"Primary: {exc}. Fallback {used}: {fallback_error}") from fallback_error
        absolute = [{**cue, "start": round(start + max(0, cue["start"]), 3),
                     "end": round(min(end, start + cue["end"]), 3)} for cue in cues
                    if min(end - start, cue["end"]) > max(0, cue["start"])]
        validate_cues(absolute)
        completed.append({"start": start, "end": end, "cues": absolute, "language": language,
                          "model": used, "revision": model_spec(used)["revision"]})
        atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        emit({"type": "segment_checkpoint", "message": f"Saved segment {index + 1}/{total}: {start:.3f}–{end:.3f}s · {used}"})
        emit({"type": "caption_progress", "processed": end, "duration": duration,
              "progress": min(99, end / duration * 100), "preview": absolute[-1]["text"] if absolute else ""})
    # Rebuild alignment inputs in the original recording's coordinates, including resumed segments.
    check_cancel(cancel)
    cues = [cue for segment in completed for cue in segment["cues"]]
    engine.alignment_segments = cues
    validate_cues(cues)
    languages = Counter(segment["language"] for segment in completed if segment["language"] not in {"und", "auto"})
    return cues, languages.most_common(1)[0][0] if languages else settings.spoken_language
