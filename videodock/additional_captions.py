"""Speech and alignment adapters for the locally installed additional models."""

from __future__ import annotations

import re
from types import SimpleNamespace

from .caption_models import check_cancel, is_ready, model_lock, model_spec, verify_model
from .captions import WaitingForModel, build_cues
from .inference_client import InferenceClient


def timed_words(words, text, start, end):
    """Keep the original punctuation/spacing while attaching the aligner's word times."""
    positions, cursor = [], 0
    for word in words:
        match = re.search(re.escape(word["text"]), text[cursor:], re.IGNORECASE)
        if not match:
            raise ValueError(
                "Alignment tokens do not match the transcript. Disable alignment or correct the text."
            )
        positions.append(cursor + match.start())
        cursor += match.end()
    positions.append(len(text))
    return [
        SimpleNamespace(
            start=start + float(word["start_time"]),
            end=min(end, start + float(word["end_time"])),
            word=text[0 if index == 0 else positions[index] : positions[index + 1]],
        )
        for index, word in enumerate(words)
    ]


def transcribe(engine, audio, root, spec, settings, cancel, emit, duration):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pcm = decode_audio(str(audio), sampling_rate=16000)
    spans = get_speech_timestamps(
        pcm, VadOptions(min_silence_duration_ms=500, speech_pad_ms=150, max_speech_duration_s=25)
    )
    if not spans:
        return [], settings.spoken_language if settings.spoken_language != "auto" else "und"
    key = (str(root), spec["id"], spec["revision"], settings.caption_device, settings.cpu_fallback)
    if engine.cache_key != key or not engine.inference or engine.inference.process is None:
        engine.release_speech()
        engine.inference = InferenceClient(spec, verify_model(root, spec, cancel), settings, cancel, emit)
        engine.cache_key = key
    else:
        engine.inference.cancel, engine.inference.emit = cancel, emit
    language = settings.spoken_language if settings.spoken_language != "auto" else "und"
    engine.alignment_segments = []

    def segments():
        nonlocal language
        for span in spans:
            check_cancel(cancel)
            start, end = span["start"] / 16000, span["end"] / 16000
            try:
                result = engine.inference.call(
                    {"action": "transcribe", "audio": str(audio), "start": start,
                     "end": end, "language": settings.spoken_language}
                )
            except ValueError as exc:
                if "output repetition" not in str(exc).lower():
                    raise
                raise ValueError(
                    f"{spec['title']} repeated its output while transcribing {start:.3f}–{end:.3f} seconds. "
                    "Saved media is retained. Select another speech model in Download settings, then use "
                    "History → Generate captions. Retrying unchanged may repeat this failure. "
                    f"Backend: {exc}"
                ) from exc
            detected = result.get("language")
            if detected and detected not in {"auto", "und"}:
                language = detected
            if result["text"].strip():
                engine.alignment_segments.append({"start": start, "end": end, "text": result["text"]})
                yield SimpleNamespace(start=start, end=end, text=result["text"], words=[])

    cues = build_cues(segments(), settings, cancel, emit, duration)
    if settings.alignment_model:
        emit({"type": "warning", "message": "Applying forced alignment to the VAD-based speech captions."})
    else:
        emit(
            {
                "type": "warning",
                "message": "This speech model provides text without word timestamps. "
                "Cue timing is estimated within VAD speech spans; choose an alignment model for word timing.",
            }
        )
    return cues, language


def align(engine, cues, audio, root, settings, language, cancel, emit, duration):
    from .captions import validate_cues

    spec = model_spec(settings.alignment_model, settings.alignment_revision)
    if not is_ready(root, spec):
        raise WaitingForModel("Waiting for alignment model. Click Download required model.", spec["id"])
    language = language.replace("_", "-").split("-")[0].lower()
    if language not in spec["supported_sources"]:
        raise ValueError(
            f"The alignment model does not support {language}. Choose a supported source language."
        )
    engine.release_speech()
    segments = []
    with model_lock(root, spec):
        client = InferenceClient(spec, verify_model(root, spec, cancel), settings, cancel, emit)
        try:
            for cue in cues:
                check_cancel(cancel)
                # Small padding lets the aligner recover words adjacent to estimated cue boundaries.
                start, end = max(0, cue["start"] - 0.15), min(duration, cue["end"] + 0.15)
                words = client.call(
                    {
                        "action": "align",
                        "audio": str(audio),
                        "start": start,
                        "end": end,
                        "text": cue["text"].replace("\n", " "),
                        "language": language,
                    }
                )
                if not words:
                    raise ValueError("The forced aligner returned no word times for a non-empty cue.")
                aligned = timed_words(words, cue["text"].replace("\n", " "), start, end)
                segments.append(SimpleNamespace(start=start, end=end, text=cue["text"], words=aligned))
        finally:
            client.close()
    output = build_cues(segments, settings, cancel, emit, duration)
    validate_cues(output)
    return output
