"""Durable source/target tracks survive temporary audio cleanup and worker restarts."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

from .caption_models import check_cancel, is_ready, model_lock, model_spec
from .captions import WaitingForModel, atomic_text, reserve_sidecar, subtitle_text, validate_cues
from .languages import chinese_text, model_language, source_tag
from .media import MIN_FREE, check_destination, probe, process_media, publish
from .models import DownloadSettings, safe_component
from .processes import Cancelled
from .subtitles import ass_text, bilingual_cues, parse_subtitles
from .translation import TranslationEngine


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def checkpoint(folder, tracks, language, provenance):
    atomic_text(
        folder / "manifest.json",
        json.dumps(
            {"tracks": tracks, "language": language, "provenance": provenance}, ensure_ascii=False, indent=2
        ),
    )


def save_track(folder, track, cues, emit):
    path = folder / (safe_component(track["language"]) + ".json")
    validate_cues(cues)
    atomic_text(path, json.dumps(cues, ensure_ascii=False, indent=2))
    track["cues_path"] = str(path)
    emit({"type": "caption_track", "track": track})


def export_sidecar(source, destination, settings, track, cues, emit):
    if not any(Path(path).is_file() for path in track.get("export_paths", [])):
        sidecar = reserve_sidecar(source, destination, track["language"], settings.caption_format)
        try:
            atomic_text(sidecar, subtitle_text(cues, settings.caption_format))
            atomic_text(
                sidecar.with_name(sidecar.name + ".cues.json"), json.dumps(cues, ensure_ascii=False, indent=2)
            )
        except BaseException:
            sidecar.unlink(missing_ok=True)
            raise
        track["export_paths"] = [str(sidecar)]
    emit({"type": "caption_track", "track": track})


def generate(engine, job, root, cancel, emit):
    settings = DownloadSettings.from_dict(job["settings"])
    settings.validate()
    source = Path(job.get("media_path") or job.get("output", ""))
    imported = settings.caption_source == "import"
    if not source.is_file():
        raise ValueError("Saved media/subtitles are missing. Restore the source file before retrying.")
    destination = Path(job["destination"]).resolve()
    info = {} if source.suffix.lower() in {".srt", ".vtt"} else probe(source)
    duration = float(info.get("format", {}).get("duration") or 0)
    check_destination(destination, max(MIN_FREE, int(duration * 32000) + MIN_FREE))
    folder = destination / ".videodock-captions" / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    work = destination / ".videodock" / (job["id"] + "-captions")
    work.mkdir(parents=True, exist_ok=True)
    manifest = read_json(folder / "manifest.json", {})
    tracks = manifest.get("tracks", job.get("tracks", []))
    source_file = folder / "source.json"
    try:
        if source_file.is_file():
            cues = read_json(source_file, [])
            language, provenance = manifest["language"], manifest["provenance"]
        else:
            if imported:
                cues = parse_subtitles(Path(settings.subtitle_import))
                language = settings.translation_source_language
                if language == "auto":
                    raise ValueError(
                        "Imported subtitles have no language metadata. Set Source language override."
                    )
                provenance = "Imported " + str(Path(settings.subtitle_import).resolve())
            else:
                caption = engine._youtube_caption(job, settings, work, cancel, emit)
                if caption:
                    cues = parse_subtitles(caption, rolling=True)
                    language = source_tag(settings.caption_language)
                    provenance = "YouTube " + settings.caption_source
                else:
                    # Speech and translation models are never retained simultaneously.
                    if engine.translation:
                        engine.translation.release()
                    engine.checkpoint_path = folder / "transcription.json"
                    cues, language = engine.transcribe(source, work, root, settings, cancel, emit, duration)
                    provenance = "Local transcription " + model_spec(settings.caption_model)["revision"]
            if settings.alignment_model and cues:
                from .additional_captions import align
                from .captions import prepare_audio
                align_language = settings.translation_source_language if settings.translation_source_language != "auto" else language
                audio = prepare_audio(source, work, cancel, emit)
                cues = align(engine, getattr(engine, "alignment_segments", None) or cues, audio, root,
                             settings, align_language, cancel, emit, duration)
                provenance += " · Forced alignment " + model_spec(settings.alignment_model)["revision"]
            cues = [{**cue, "id": cue.get("id", f"cue-{index:06d}")} for index, cue in enumerate(cues, 1)]
            language = source_tag(language)
            checkpoint(folder, tracks, language, provenance)
            atomic_text(source_file, json.dumps(cues, ensure_ascii=False, indent=2))
        if settings.translation_source_language != "auto":
            language = source_tag(settings.translation_source_language)
        if model_language_safe(language) == "zh" and settings.chinese_script != "original":
            language = settings.chinese_script
            cues = [{**cue, "text": chinese_text(cue["text"], language)} for cue in cues]
            atomic_text(source_file, json.dumps(cues, ensure_ascii=False, indent=2))
            provenance += " · OpenCC " + language
        validate_cues(cues)
        original = next((track for track in tracks if track["role"] == "source"), None)
        if original is None:
            original = {
                "language": language,
                "role": "source",
                "status": "complete",
                "error": "",
                "model_revision": settings.model_revision,
                "provenance": provenance,
                "export_paths": [],
            }
            tracks.insert(0, original)
        original.update(
            language=language, cues_path=str(source_file), provenance=provenance, status="complete"
        )
        original["model_revision"] = (
            model_spec(settings.caption_model, settings.model_revision)["revision"]
            if provenance.startswith("Local transcription")
            else ""
        )
        emit({"type": "caption_source", "cues_path": str(source_file), "caption_language_result": language})
        if settings.keep_original or not settings.translate or language in settings.target_languages:
            export_sidecar(source, destination, settings, original, cues, emit)
        else:
            emit({"type": "caption_track", "track": original})
        checkpoint(folder, tracks, language, provenance)
        if settings.translate and job.get("defer_translation"):
            engine.release_speech()
            emit({"type": "translation_ready", "cues_path": str(source_file), "caption_language_result": language})
            return
        errors = []
        if settings.translate:
            spec = model_spec(settings.translation_model, settings.translation_revision)
            cache_path = folder / "translation-cache.json"
            cache = read_json(cache_path, {})
            if engine.translation is None:
                engine.translation = TranslationEngine()
            engine.release_speech()
            for target in settings.target_languages:
                check_cancel(cancel)
                if job.get("retry_languages") and target not in job["retry_languages"]:
                    continue
                if target == language and all(
                    not cue.get("language") or cue["language"] == language for cue in cues
                ):
                    continue
                track = next((t for t in tracks if t["language"] == target and t["role"] == "target"), None)
                if track is None:
                    track = {
                        "language": target,
                        "role": "target",
                        "status": "queued",
                        "error": "",
                        "model_revision": spec["revision"],
                        "provenance": spec["title"] + " translation"
                        + (" + OpenCC " + target if target.startswith("zh-") else ""),
                        "export_paths": [],
                    }
                    tracks.append(track)
                regenerate = target in job.get("regenerate_languages", [])
                if (
                    track["status"] == "complete"
                    and not regenerate
                    and Path(track.get("cues_path", "")).is_file()
                ):
                    export_sidecar(
                        source, destination, settings, track, read_json(Path(track["cues_path"]), []), emit
                    )
                    continue
                previous = read_json(Path(track.get("cues_path") or folder / (target + ".json")), [])
                try:
                    needs_model = any(
                        model_language(cue.get("language") or language) != model_language(target)
                        for cue in cues
                    )
                    if needs_model and not is_ready(root, spec):
                        checkpoint(folder, tracks, language, provenance)
                        raise WaitingForModel(
                            "Waiting for translation model. Click Download required model.", spec["id"]
                        )
                    emit({"type": "status", "status": "translating"})
                    with model_lock(root, spec):
                        translated = engine.translation.translate(
                            cues,
                            language,
                            target,
                            spec,
                            root,
                            settings,
                            cancel,
                            emit,
                            cache,
                            lambda: atomic_text(cache_path, json.dumps(cache, ensure_ascii=False)),
                            previous,
                            regenerate,
                        )
                    check_cancel(cancel)
                    track.update(status="complete", error="", export_paths=[])
                    save_track(folder, track, translated, emit)
                    export_sidecar(source, destination, settings, track, translated, emit)
                except Cancelled:
                    checkpoint(folder, tracks, language, provenance)
                    raise
                except (ValueError, RuntimeError, OSError) as exc:
                    track.update(status="failed", error=str(exc))
                    errors.append(f"{target}: {exc}")
                    emit({"type": "caption_track", "track": track})
                checkpoint(folder, tracks, language, provenance)
        for target in settings.target_languages:
            failed = next(
                (track for track in tracks if track["language"] == target and track["status"] == "failed"),
                None,
            )
            if failed and f"{target}: {failed['error']}" not in errors:
                errors.append(f"{target}: {failed['error']}")
        if settings.bilingual_language:
            target = next(
                (
                    t
                    for t in tracks
                    if t["language"] == settings.bilingual_language and t["status"] == "complete"
                ),
                None,
            )
            if target:
                pair = language + "+" + target["language"]
                track = next((t for t in tracks if t["language"] == pair), None)
                if track is None:
                    track = {"language": pair, "role": "bilingual", "export_paths": []}
                    tracks.append(track)
                track.update(
                    status="complete",
                    error="",
                    provenance="Bilingual " + settings.bilingual_order,
                    model_revision=target.get("model_revision", ""),
                )
                combined = bilingual_cues(
                    cues, read_json(Path(target["cues_path"]), []), settings.bilingual_order
                )
                if (
                    read_json(Path(track.get("cues_path") or folder / (safe_component(pair) + ".json")), [])
                    != combined
                ):
                    track["export_paths"] = []
                save_track(folder, track, combined, emit)
                export_sidecar(source, destination, settings, track, combined, emit)
        check_cancel(cancel)
        output, paths = export_video(source, work, destination, settings, tracks, info, job, cancel, emit)
        checkpoint(folder, tracks, language, provenance)
        emit(
            {
                "type": "completed",
                "output": str(output),
                "media_path": str(source),
                "caption_paths": paths,
                "cues_path": str(source_file),
                "caption_language_result": language,
                "caption_status": "complete",
                "translation_status": ("partial" if errors else "complete") if settings.translate else "",
                "tracks": tracks,
                "error": "\n".join(errors),
            }
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def model_language_safe(language):
    try:
        return model_language(language)
    except ValueError:
        return language


def selected_tracks(settings, tracks):
    selected = [
        t
        for t in tracks
        if t["status"] in {"complete", "stale"}
        and (
            (
                t["role"] == "source"
                and (
                    settings.keep_original
                    or not settings.translate
                    or t["language"] in settings.target_languages
                )
            )
            or (t["role"] == "target" and t["language"] in settings.target_languages)
            or (
                t["role"] == "bilingual"
                and settings.bilingual_language
                and t["language"].endswith("+" + settings.bilingual_language)
            )
        )
    ]
    order = {tag: index for index, tag in enumerate(settings.track_order)}
    return sorted(selected, key=lambda track: order.get(track["language"], len(order)))


def export_video(source, work, destination, settings, tracks, info, job, cancel, emit):
    selected = selected_tracks(settings, tracks)
    paths = [path for track in selected for path in track.get("export_paths", [])]
    output = source
    video = any(stream.get("codec_type") == "video" for stream in info.get("streams", []))
    if settings.caption_mode in {"embed", "burn"} and video and (selected or settings.caption_mode == "burn"):
        emit({"type": "status", "status": "exporting"})
        if settings.caption_mode == "embed":
            inputs = [
                {"path": Path(t["export_paths"][-1]), "language": t["language"], "title": t["language"]}
                for t in selected
                if read_json(Path(t["cues_path"]), [])
            ]
            if (
                inputs
                and settings.default_language
                and settings.default_language not in {track["language"] for track in inputs}
            ):
                if settings.default_language in settings.target_languages:
                    emit(
                        {
                            "type": "warning",
                            "message": "Default language is unavailable in this partial result; using the first successful track.",
                        }
                    )
                    settings = replace(settings, default_language="")
                else:
                    raise ValueError(
                        "The default language is not among the exported tracks. Choose an exported language."
                    )
            caption = inputs or None
        else:
            candidates = [t for t in tracks if t["status"] in {"complete", "stale"}]
            chosen = next(
                (
                    t
                    for t in candidates
                    if t["language"] == settings.burn_language or t["role"] == settings.burn_language
                ),
                selected[0] if selected else candidates[0],
            )
            if (
                settings.burn_language
                and chosen["language"] != settings.burn_language
                and chosen["role"] != settings.burn_language
            ):
                raise ValueError(
                    "The chosen burn language failed. Successful subtitle sidecars are retained."
                )
            burn_cues = read_json(Path(chosen["cues_path"]), [])
            caption = work / "captions.ass" if burn_cues else None
            if caption:
                atomic_text(caption, ass_text(burn_cues, settings))
        if caption:
            check_destination(destination, max(MIN_FREE, source.stat().st_size * 2))
            rendered = process_media(source, work, settings, caption, cancel, emit)
            check_cancel(cancel)
            output = publish(
                rendered,
                destination,
                source.stem + (" - burned" if settings.caption_mode == "burn" else " - captioned"),
                None,
                settings,
                job["id"],
            )
    return output, paths


def reexport_tracks(job, edits, cancel, emit):
    settings = DownloadSettings.from_dict(job["settings"])
    source = Path(job["media_path"])
    folder = Path(job["destination"]) / ".videodock-captions" / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    manifest = read_json(folder / "manifest.json", {})
    tracks = manifest.get("tracks", job.get("tracks", []))
    if not tracks:
        tracks = [
            {
                "language": job.get("caption_language_result") or settings.caption_language,
                "role": "source",
                "cues_path": job["cues_path"],
                "status": "complete",
                "export_paths": job["caption_paths"],
                "provenance": "Legacy captions",
            }
        ]
    edits = edits if isinstance(edits, dict) else {tracks[0]["language"]: edits}
    original = next(track for track in tracks if track["role"] == "source")
    source_changed = False
    for track in tracks:
        if track["language"] not in edits:
            continue
        cues = edits[track["language"]]
        validate_cues(cues)
        previous = read_json(Path(track["cues_path"]), [])
        changed = [
            index
            for index, cue in enumerate(cues)
            if index >= len(previous)
            or any(
                cue.get(field) != previous[index].get(field) for field in ("start", "end", "text", "language")
            )
        ]
        for index, cue in enumerate(cues):
            cue.setdefault(
                "id",
                previous[index].get("id", f"cue-{index + 1:06d}")
                if index < len(previous)
                else f"cue-{index + 1:06d}",
            )
            if track["role"] == "target" and index in changed:
                cue["manual"] = True
        source_changed |= track["role"] == "source" and bool(changed)
        if changed:
            check_cancel(cancel)
            # Editable state is durable; old exported sidecars/media remain immutable.
            save_track(folder, track, cues, emit)
            track["export_paths"] = []
            export_sidecar(source, Path(job["destination"]), settings, track, cues, emit)
    source_cues = read_json(Path(original["cues_path"]), [])
    source_cues = [
        {**cue, "id": cue.get("id", f"cue-{index:06d}")} for index, cue in enumerate(source_cues, 1)
    ]
    canonical_source = folder / "source.json"
    atomic_text(canonical_source, json.dumps(source_cues, ensure_ascii=False, indent=2))
    original["cues_path"] = str(canonical_source)
    if source_changed:
        for track in tracks:
            if track["role"] != "source":
                track["status"] = "stale"
                track["error"] = "Source edited. Regenerate this language; manual target edits are preserved."
                emit({"type": "caption_track", "track": track})
    for track in tracks:
        if track["role"] != "bilingual":
            continue
        target = next(
            (t for t in tracks if t["role"] == "target" and track["language"].endswith("+" + t["language"])),
            None,
        )
        if target:
            combined = bilingual_cues(
                source_cues, read_json(Path(target["cues_path"]), []), settings.bilingual_order
            )
            if combined != read_json(Path(track["cues_path"]), []):
                save_track(folder, track, combined, emit)
                track["export_paths"] = []
                export_sidecar(source, Path(job["destination"]), settings, track, combined, emit)
    checkpoint(folder, tracks, original["language"], original.get("provenance", ""))
    emit(
        {
            "type": "caption_source",
            "cues_path": str(canonical_source),
            "caption_language_result": original["language"],
        }
    )
    work = Path(job["destination"]) / ".videodock" / (job["id"] + "-edit")
    work.mkdir(parents=True, exist_ok=True)
    try:
        info = {} if source.suffix.lower() in {".srt", ".vtt"} else probe(source)
        output, paths = export_video(
            source, work, Path(job["destination"]), settings, tracks, info, job, cancel, emit
        )
        language = original["language"]
        checkpoint(folder, tracks, language, original.get("provenance", ""))
        emit(
            {
                "type": "completed",
                "output": str(output),
                "caption_paths": paths,
                "cues_path": original["cues_path"],
                "tracks": tracks,
                "caption_status": "complete",
                "translation_status": "stale" if source_changed and settings.translate else job.get("translation_status", ""),
            }
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
