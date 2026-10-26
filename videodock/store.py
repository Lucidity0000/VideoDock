from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    ACTIVE,
    CAPTION_PENDING,
    PENDING,
    TERMINAL,
    DownloadSettings,
    canonical_url,
    duplicate_key,
    validate_url,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """One connection guarded by a lock; workers never write the GUI's database."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS saved_lists (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                source_urls TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saved_list_items (
                id TEXT PRIMARY KEY, list_id TEXT NOT NULL, position INTEGER NOT NULL,
                identity TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(list_id, identity)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
                settings TEXT NOT NULL, destination TEXT NOT NULL,
                playlist TEXT NOT NULL DEFAULT '', playlist_index INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
                speed REAL, eta REAL, error TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
                duplicate_key TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, sequence);
            CREATE INDEX IF NOT EXISTS jobs_duplicate ON jobs(duplicate_key);
            CREATE TABLE IF NOT EXISTS installed_models (
                model_id TEXT NOT NULL, revision TEXT NOT NULL, path TEXT NOT NULL,
                installed TEXT NOT NULL, PRIMARY KEY(model_id,revision,path)
            );
            CREATE TABLE IF NOT EXISTS caption_tracks (
                job_id TEXT NOT NULL, language TEXT NOT NULL, role TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(job_id,language,role)
            );
            CREATE TABLE IF NOT EXISTS job_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                at TEXT NOT NULL, stage TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_job ON job_events(job_id,sequence);
            CREATE TABLE IF NOT EXISTS queue_schedules (
                id TEXT PRIMARY KEY, stage TEXT NOT NULL, action TEXT NOT NULL,
                due TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending'
            );
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
        migrated = False
        for name, definition in {
            "media_path": "TEXT NOT NULL DEFAULT ''",
            "caption_status": "TEXT NOT NULL DEFAULT ''",
            "caption_paths": "TEXT NOT NULL DEFAULT '[]'",
            "cues_path": "TEXT NOT NULL DEFAULT ''",
            "processed_duration": "REAL NOT NULL DEFAULT 0",
            "caption_preview": "TEXT NOT NULL DEFAULT ''",
            "caption_language_result": "TEXT NOT NULL DEFAULT ''",
            "removed": "INTEGER NOT NULL DEFAULT 0",
            "caption_only": "INTEGER NOT NULL DEFAULT 0",
            "waiting_model_id": "TEXT NOT NULL DEFAULT ''",
            "regenerate_languages": "TEXT NOT NULL DEFAULT '[]'",
            "retry_languages": "TEXT NOT NULL DEFAULT '[]'",
            "stage": "TEXT NOT NULL DEFAULT 'download'",
            "download_status": "TEXT NOT NULL DEFAULT 'queued'",
            "translation_status": "TEXT NOT NULL DEFAULT ''",
            "held": "INTEGER NOT NULL DEFAULT 0",
            "queue_order": "INTEGER NOT NULL DEFAULT 0",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "retry_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
                migrated = True
        self.db.execute("UPDATE jobs SET queue_order=sequence WHERE queue_order=0")
        if migrated or self.preference("settings_schema_version", 0) < 5:
            # New setting fields change fingerprints even for old caption-free jobs.
            # Normalize existing fingerprints so a 0.1.x queue still detects duplicates.
            for row in self.db.execute("SELECT id,url,settings,destination FROM jobs").fetchall():
                settings = DownloadSettings.from_dict(json.loads(row["settings"]))
                self.db.execute(
                    "UPDATE jobs SET duplicate_key=? WHERE id=?",
                    (duplicate_key(row["url"], settings, row["destination"]), row["id"]),
                )
            for row in self.db.execute("SELECT * FROM jobs").fetchall():
                settings = DownloadSettings.from_dict(json.loads(row["settings"]))
                paths = json.loads(row["caption_paths"])
                if not paths and settings.caption_mode != "none" and row["output"]:
                    sidecar = Path(row["output"]).with_suffix(
                        f".{settings.caption_language}.{settings.caption_format}"
                    )
                    if sidecar.is_file():
                        paths = [str(sidecar)]
                        self.db.execute(
                            "UPDATE jobs SET caption_paths=? WHERE id=?", (json.dumps(paths), row["id"])
                        )
                if not paths:
                    continue
                if self.tracks(row["id"]):
                    continue
                language = row["caption_language_result"] or settings.caption_language
                self.upsert_track(
                    row["id"],
                    {
                        "language": language,
                        "role": "source",
                        "cues_path": row["cues_path"],
                        "export_paths": paths,
                        "status": "complete",
                        "provenance": "Migrated 0.2.0 captions",
                        "model_revision": settings.model_revision,
                        "error": "",
                    },
                )
            self.set_preference("settings_schema_version", 5)
        self.db.commit()
        if "stage" not in columns:
            for job in self.jobs():
                saved_source = bool(job["cues_path"])
                postprocess = bool(job["media_path"] or job["caption_only"])
                translating = postprocess and saved_source and job["settings"].get("translate", False)
                stage = "translation" if translating else "caption" if postprocess else "download"
                status = job["status"]
                self.db.execute(
                    "UPDATE jobs SET stage=?,download_status=?,caption_status=?,translation_status=? WHERE id=?",
                    (stage, "skipped" if job["caption_only"] else "complete" if postprocess or status == "completed" else status,
                     "complete" if translating or status == "completed" and job["caption_paths"] else job["caption_status"],
                     ("complete" if status == "completed" else "queued" if status in CAPTION_PENDING else status)
                     if translating else "pending" if job["settings"].get("translate", False) else "",
                     job["id"]),
                )
                if translating and status == "caption_queued":
                    self.db.execute("UPDATE jobs SET status='translation_queued' WHERE id=?", (job["id"],))
            self.db.commit()

    def preference(self, key: str, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_preference(self, key: str, value) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, json.dumps(value)))

    def recover(self) -> int:
        with self.lock, self.db:
            jobs = [job for job in self.jobs() if job["status"] in ACTIVE]
            for job in jobs:
                stage = job["stage"] if job["stage"] != "download" else "caption" if job["media_path"] else "download"
                self.update(job["id"], stage=stage, status="paused" if job["held"] else self.queued_status(stage),
                            **{self.stage_status_field(stage): "paused" if job["held"] else "queued"}, speed=None, eta=None,
                            error="Interrupted on last run. Ready to resume; partial files are preserved.")
            return len(jobs)

    @staticmethod
    def _list_name(name: str) -> str:
        name = name.strip()
        if not name or len(name) > 160 or any(ord(c) < 32 for c in name):
            raise ValueError("Use a list name of 1–160 characters without control characters.")
        return name

    @staticmethod
    def _list_item(item: dict) -> tuple[str, str]:
        url = validate_url(item["url"])
        data = {key: item[key] for key in (
            "title", "playlist", "playlist_key", "index", "duration", "uploader", "thumbnail"
        ) if key in item}
        data.update(url=url, title=str(data.get("title") or url),
                    playlist=str(data.get("playlist") or ""),
                    index=max(0, int(data.get("index") or 0)),
                    duration=data.get("duration"), detailed=False)
        return canonical_url(url), json.dumps(data, ensure_ascii=False)

    def saved_lists(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT l.*, (SELECT COUNT(*) FROM saved_list_items i WHERE i.list_id=l.id) AS count "
                "FROM saved_lists l ORDER BY l.name COLLATE NOCASE,l.created,l.id"
            )]

    def saved_list(self, list_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM saved_lists WHERE id=?", (list_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["source_urls"] = json.loads(result["source_urls"])
            result["items"] = [{"id": item["id"], **json.loads(item["data"])} for item in self.db.execute(
                "SELECT * FROM saved_list_items WHERE list_id=? ORDER BY position,id", (list_id,)
            )]
            return result

    def create_saved_list(self, name: str, kind="custom", source_urls=(), items=()) -> str:
        name = self._list_name(name)
        if kind not in {"favorite", "custom"}:
            raise ValueError("Choose a favorite playlist or a custom list.")
        urls = list(dict.fromkeys(validate_url(url) for url in source_urls))
        # Validate every item before touching the database, including duplicates.
        prepared = [self._list_item(item) for item in items]
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO saved_lists VALUES (?,?,?,?,?,?)",
                            (identifier, name, kind, json.dumps(urls), timestamp, timestamp))
            for position, (identity, data) in enumerate(prepared):
                self.db.execute("INSERT OR IGNORE INTO saved_list_items VALUES (?,?,?,?,?)",
                                (uuid.uuid4().hex, identifier, position, identity, data))
        return identifier

    def add_saved_items(self, list_id: str, items: list[dict]) -> tuple[int, int]:
        prepared = [self._list_item(item) for item in items]
        added = 0
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM saved_lists WHERE id=?", (list_id,)).fetchone():
                raise ValueError("The saved list no longer exists.")
            position = self.db.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM saved_list_items WHERE list_id=?", (list_id,)
            ).fetchone()[0]
            for identity, data in prepared:
                cursor = self.db.execute("INSERT OR IGNORE INTO saved_list_items VALUES (?,?,?,?,?)",
                                         (uuid.uuid4().hex, list_id, position, identity, data))
                added += cursor.rowcount
                position += 1
            self.db.execute("UPDATE saved_lists SET updated=? WHERE id=?", (now(), list_id))
        return added, len(prepared) - added

    def remove_saved_items(self, list_id: str, item_ids: list[str]) -> int:
        removed = 0
        with self.lock, self.db:
            for item_id in set(item_ids):
                removed += self.db.execute("DELETE FROM saved_list_items WHERE id=? AND list_id=?",
                                           (item_id, list_id)).rowcount
            self.db.execute("UPDATE saved_lists SET updated=? WHERE id=?", (now(), list_id))
        return removed

    def rename_saved_list(self, list_id: str, name: str):
        name = self._list_name(name)
        with self.lock, self.db:
            if not self.db.execute("UPDATE saved_lists SET name=?,updated=? WHERE id=?",
                                   (name, now(), list_id)).rowcount:
                raise ValueError("The saved list no longer exists.")

    def delete_saved_list(self, list_id: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM saved_list_items WHERE list_id=?", (list_id,))
            self.db.execute("DELETE FROM saved_lists WHERE id=?", (list_id,))

    @staticmethod
    def queued_status(stage):
        return "queued" if stage == "download" else stage + "_queued"

    @staticmethod
    def stage_status_field(stage):
        return {"download": "download_status", "caption": "caption_status", "translation": "translation_status"}[stage]

    def enqueue(
        self,
        items: list[dict],
        settings: DownloadSettings,
        destination: str,
        overrides: dict[int, DownloadSettings] | None = None,
        playlist_folders: bool = True,
        allow_duplicates: bool = False,
    ) -> tuple[int, int]:
        added = skipped = 0
        with self.lock, self.db:
            for index, item in enumerate(items):
                current = (overrides or {}).get(index, settings)
                current.validate()
                if current.uses_local:
                    from .caption_models import model_spec

                    current = replace(
                        current,
                        model_revision=model_spec(current.caption_model, current.model_revision)["revision"],
                    )
                if current.translate:
                    from .caption_models import model_spec

                    current = replace(
                        current,
                        translation_revision=model_spec(
                            current.translation_model, current.translation_revision
                        )["revision"],
                    )
                if current.alignment_model:
                    from .caption_models import model_spec
                    current = replace(current, alignment_revision=model_spec(current.alignment_model, current.alignment_revision)["revision"])
                current = self.pin_settings(current)
                folder = Path(destination).expanduser().resolve()
                if playlist_folders and item.get("playlist"):
                    from .models import safe_component

                    folder /= safe_component(item["playlist"])
                key = duplicate_key(item["url"], current, str(folder))
                matches = self.db.execute(
                    "SELECT status, output FROM jobs WHERE duplicate_key=? AND removed=0", (key,)
                ).fetchall()
                if not allow_duplicates and any(
                    row["status"] in ACTIVE | PENDING
                    or (row["status"] in {"completed", "partial"} and Path(row["output"]).is_file())
                    for row in matches
                ):
                    skipped += 1
                    continue
                timestamp = now()
                self.db.execute(
                    """INSERT INTO jobs
                    (id,url,title,settings,destination,playlist,playlist_index,duplicate_key,created,updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid.uuid4().hex,
                        item["url"],
                        item["title"],
                        json.dumps(current.to_dict()),
                        str(folder),
                        item.get("playlist", ""),
                        item.get("index", 0),
                        key,
                        timestamp,
                        timestamp,
                    ),
                )
                added += 1
                self.db.execute("UPDATE jobs SET translation_status=? WHERE id=(SELECT id FROM jobs ORDER BY sequence DESC LIMIT 1)",
                                ("pending" if current.translate else "",))
                self.db.execute("UPDATE jobs SET queue_order=sequence WHERE queue_order=0")
                identifier = self.db.execute("SELECT id FROM jobs ORDER BY sequence DESC LIMIT 1").fetchone()[0]
                self.add_event(identifier, "queued", "Added to queue")
        return added, skipped

    def jobs(self) -> list[dict]:
        with self.lock:
            return [self._decode(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY queue_order,sequence")]

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return self._decode(row) if row else None

    def next_queued(self) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM jobs WHERE status='queued' AND held=0 AND removed=0 ORDER BY queue_order,sequence LIMIT 1"
            ).fetchone()
            return self._decode(row) if row else None

    def _decode(self, row) -> dict:
        result = dict(row)
        result["settings"] = json.loads(result["settings"])
        result["caption_paths"] = json.loads(result["caption_paths"])
        result["regenerate_languages"] = json.loads(result["regenerate_languages"])
        result["retry_languages"] = json.loads(result["retry_languages"])
        result["tracks"] = self.tracks(result["id"])
        return result

    def update(self, job_id: str, **fields) -> None:
        allowed = {
            "status",
            "progress",
            "speed",
            "eta",
            "error",
            "output",
            "title",
            "attempts",
            "media_path",
            "caption_status",
            "caption_paths",
            "cues_path",
            "processed_duration",
            "caption_preview",
            "caption_language_result",
            "removed",
            "caption_only",
            "waiting_model_id",
            "regenerate_languages",
            "retry_languages",
            "stage",
            "download_status",
            "translation_status",
            "held", "retry_count", "retry_at",
        }
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported job fields")
        fields["updated"] = now()
        if "caption_paths" in fields:
            fields["caption_paths"] = json.dumps(fields["caption_paths"])
        if "regenerate_languages" in fields:
            fields["regenerate_languages"] = json.dumps(fields["regenerate_languages"])
        if "retry_languages" in fields:
            fields["retry_languages"] = json.dumps(fields["retry_languages"])
        with self.lock, self.db:
            previous = self.get(job_id)
            self.db.execute(
                f"UPDATE jobs SET {','.join(key + '=?' for key in fields)} WHERE id=?",
                (*fields.values(), job_id),
            )
            if previous:
                transitions = [f"{key}: {previous[key]} → {value}" for key, value in fields.items()
                               if key in {"stage", "status", "download_status", "caption_status", "translation_status"}
                               and previous[key] != value]
                if transitions:
                    self.add_event(job_id, "transition", "; ".join(transitions), fields.get("stage", previous["stage"]))
                if fields.get("error") and fields["error"] != previous["error"]:
                    self.add_event(job_id, "error", fields["error"], fields.get("stage", previous["stage"]))

    def retry(self, job_id: str) -> None:
        job = self.get(job_id)
        if job and job["status"] in {"partial", "failed", "cancelled"}:
            caption = bool(job["media_path"])
            stage = "translation" if caption and job["cues_path"] and job["settings"].get("translate") else "caption" if caption else "download"
            self.update(
                job_id,
                stage=stage,
                status=self.queued_status(stage),
                **{self.stage_status_field(stage): "queued"},
                error="",
                speed=None,
                eta=None,
                removed=0,
                held=0, retry_count=0, retry_at="",
            )
            self.add_event(job_id, "retry", "Manual retry; saved work retained")

    def remove(self, job_id: str) -> None:
        job = self.get(job_id)
        if job and job["status"] not in ACTIVE:
            # Keep history and all media/partial files. Removing pending work releases duplicate detection.
            self.update(
                job_id,
                removed=1,
                status="cancelled" if job["status"] in PENDING else job["status"],
                held=0, retry_at="",
                **({self.stage_status_field(job["stage"]): "cancelled"} if job["status"] in PENDING else {}),
            )

    def queue_captions(self, paths: list[str], settings: DownloadSettings, destination: str) -> int:
        settings = replace(
            settings,
            caption_source="local",
            caption_mode="sidecar" if settings.caption_mode == "none" else settings.caption_mode,
        )
        from .caption_models import model_spec

        settings = replace(settings, model_revision=model_spec(settings.caption_model)["revision"])
        if settings.alignment_model:
            settings = replace(settings, alignment_revision=model_spec(settings.alignment_model)["revision"])
        if settings.translate:
            settings = replace(
                settings, translation_revision=model_spec(settings.translation_model)["revision"]
            )
        settings = self.pin_settings(settings)
        settings.validate()
        files = [Path(path).resolve() for path in paths]
        if any(not path.is_file() for path in files):
            raise ValueError("Every imported media file must exist.")
        with self.lock, self.db:
            for path in files:
                current = settings
                if path.suffix.lower() in {
                    ".mp3",
                    ".m4a",
                    ".wav",
                    ".flac",
                    ".ogg",
                    ".aac",
                    ".opus",
                    ".wma",
                    ".aiff",
                }:
                    current = replace(settings, caption_mode="sidecar")
                identifier = uuid.uuid4().hex
                folder = str(Path(destination).resolve())
                self.db.execute(
                    """INSERT INTO jobs
                    (id,url,title,settings,destination,duplicate_key,created,updated,status,media_path,output,caption_status,caption_only)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        path.as_uri(),
                        path.stem,
                        json.dumps(current.to_dict()),
                        folder,
                        duplicate_key(path.as_uri(), current, folder),
                        now(),
                        now(),
                        "caption_queued",
                        str(path),
                        str(path),
                        "queued",
                        1,
                    ),
                )
                self.update(identifier, stage="caption", download_status="skipped",
                            translation_status="pending" if current.translate else "")
                self.db.execute("UPDATE jobs SET queue_order=sequence WHERE id=?", (identifier,))
        return len(files)

    def tracks(self, job_id):
        with self.lock:
            return [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT data FROM caption_tracks WHERE job_id=? ORDER BY rowid", (job_id,)
                )
            ]

    def upsert_track(self, job_id, track):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO caption_tracks VALUES (?,?,?,?)",
                (job_id, track["language"], track["role"], json.dumps(track)),
            )

    def queue_subtitles(self, paths, settings, destination, media=""):
        from .caption_models import model_spec

        for value in paths:
            path = Path(value).resolve()
            if not path.is_file() or path.suffix.lower() not in {".srt", ".vtt"}:
                raise ValueError("Choose an existing SRT or VTT file.")
            current = replace(
                settings,
                caption_source="import",
                subtitle_import=str(path),
                caption_mode=settings.caption_mode if media else "sidecar",
                translation_revision=model_spec(settings.translation_model)["revision"]
                if settings.translate
                else "",
            )
            current.validate()
            current = self.pin_settings(current)
            actual = Path(media).resolve() if media else path
            if not actual.is_file():
                raise ValueError("The selected media file is missing.")
            identifier = uuid.uuid4().hex
            folder = str(Path(destination).resolve())
            with self.lock, self.db:
                self.db.execute(
                    """INSERT INTO jobs
                    (id,url,title,settings,destination,duplicate_key,created,updated,status,media_path,output,caption_status,caption_only)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        actual.as_uri(),
                        path.stem,
                        json.dumps(current.to_dict()),
                        folder,
                        duplicate_key(path.as_uri(), current, folder),
                        now(),
                        now(),
                        "caption_queued",
                        str(actual),
                        str(actual),
                        "queued",
                        1,
                    ),
                )
                stage = "translation" if current.translate else "caption"
                self.update(identifier, stage=stage, status=self.queued_status(stage), download_status="skipped",
                            translation_status="queued" if current.translate else "", caption_status="imported")
                self.db.execute("UPDATE jobs SET queue_order=sequence WHERE id=?", (identifier,))
        return len(paths)

    def queue_translation(self, job, settings):
        source = next((t for t in job.get("tracks", []) if t["role"] == "source"), None)
        files = source.get("export_paths", []) if source else job["caption_paths"]
        if not files or not Path(files[-1]).is_file():
            raise ValueError("This history item has no saved source subtitles to translate.")
        language = job.get("caption_language_result") or job["settings"]["caption_language"]
        current = replace(
            settings,
            translate=True,
            translation_source_language=language
            if settings.translation_source_language == "auto"
            else settings.translation_source_language,
        )
        count = self.queue_subtitles(
            [files[-1]], current, job["destination"], job["media_path"] or job["output"]
        )
        if source and Path(source.get("cues_path") or "").is_file():
            from .caption_pipeline import checkpoint
            from .captions import atomic_text

            queued = self.jobs()[-1]
            folder = Path(queued["destination"]) / ".videodock-captions" / queued["id"]
            folder.mkdir(parents=True, exist_ok=True)
            checkpoint(
                folder,
                [],
                current.translation_source_language,
                "Saved source cues · " + source.get("provenance", ""),
            )
            atomic_text(folder / "source.json", Path(source["cues_path"]).read_text(encoding="utf-8"))
        return count

    def retry_language(self, job_id, language, overwrite_manual=False):
        job = self.get(job_id)
        if not job or job["status"] in ACTIVE | PENDING:
            raise ValueError("Wait for this caption job to finish.")
        if language not in job["settings"].get("target_languages", []):
            raise ValueError("Choose one of this job's target languages.")
        folder = Path(job["cues_path"]).parent
        manifest_path = folder / "manifest.json"
        from .captions import atomic_text

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for track in manifest["tracks"]:
            if track["language"] == language:
                track["status"] = "queued"
                self.update(
                    job_id,
                    regenerate_languages=[language] if overwrite_manual else [],
                    retry_languages=[language],
                )
                self.upsert_track(job_id, track)
        atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False))
        self.update(job_id, stage="translation", status="translation_queued", translation_status="queued", error="", removed=0)

    def clear_history(self, job_ids=None, *, cancelled_only=False, exclude=()):
        """Remove terminal records and track metadata; never touch saved or partial files."""
        selected = set(job_ids) if job_ids is not None else None
        excluded = set(exclude)
        with self.lock, self.db:
            identifiers = [job["id"] for job in self.jobs()
                           if job["status"] in TERMINAL and job["id"] not in excluded
                           and (selected is None or job["id"] in selected)
                           and (not cancelled_only or job["status"] == "cancelled")]
            for identifier in identifiers:
                self.db.execute("DELETE FROM caption_tracks WHERE job_id=?", (identifier,))
                self.db.execute("DELETE FROM job_events WHERE job_id=?", (identifier,))
                self.db.execute("DELETE FROM jobs WHERE id=?", (identifier,))
            return len(identifiers)

    @staticmethod
    def pin_settings(settings):
        from .caption_models import model_spec

        fields = {}
        for model, revision in (("caption_model", "model_revision"), ("fallback_model", "fallback_revision"),
                                ("translation_model", "translation_revision"), ("alignment_model", "alignment_revision")):
            key = getattr(settings, model)
            needed = (settings.uses_local if model == "caption_model" else settings.translate
                      if model == "translation_model" else bool(key))
            fields[revision] = model_spec(key, getattr(settings, revision))["revision"] if key and needed else ""
        return replace(settings, **fields)

    def add_event(self, job_id, kind, detail, stage=None):
        with self.lock:
            nested = self.db.in_transaction
            job = self.get(job_id)
            if job:
                self.db.execute("INSERT INTO job_events(job_id,at,stage,kind,detail) VALUES (?,?,?,?,?)",
                                (job_id, now(), stage or job["stage"], kind, str(detail)))
                if not nested:
                    self.db.commit()

    def timeline(self, job_id):
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT * FROM job_events WHERE job_id=? ORDER BY sequence", (job_id,))]

    def bulk_settings(self, job_ids, patch, *, exclude=()):
        if not patch or not patch.keys() <= DownloadSettings.__dataclass_fields__.keys():
            raise ValueError("Select at least one valid setting to apply.")
        prepared = []
        media_fields = {"format", "height", "audio_bitrate", "allow_conversion", "filename_template"}
        source_fields = {"caption_source", "caption_language", "caption_model", "model_revision", "fallback_model",
                         "fallback_revision", "spoken_language", "alignment_model", "alignment_revision",
                         "caption_line_length", "caption_max_duration", "subtitle_import", "chinese_script"}
        with self.lock:
            for identifier in dict.fromkeys(job_ids):
                job = self.get(identifier)
                if not job or job["removed"] or job["status"] not in PENDING or identifier in exclude:
                    raise ValueError("Only pending jobs without an active worker can be edited. Refresh the selection.")
                changes = dict(patch)
                current = DownloadSettings.from_dict(job["settings"])
                changed = {key for key, value in changes.items() if getattr(current, key) != value}
                if job["stage"] != "download" and changed & media_fields:
                    raise ValueError("Media settings are locked after download. Select only caption/translation fields.")
                if job["cues_path"] and changed & source_fields:
                    raise ValueError("Source captions are already saved. Generate a new caption job to change their settings.")
                for model, revision in (("caption_model", "model_revision"), ("fallback_model", "fallback_revision"),
                                        ("translation_model", "translation_revision"), ("alignment_model", "alignment_revision")):
                    if model in changed:
                        changes[revision] = ""
                settings = self.pin_settings(replace(current, **changes))
                settings.validate()
                if job["stage"] != "download" and (settings.caption_mode == "none" or settings.caption_source == "off"):
                    raise ValueError("This job has already reached caption processing. Cancel it to skip captions.")
                if job["stage"] == "translation" and not settings.translate:
                    raise ValueError("This job is in the translation queue. Cancel it to skip translation.")
                prepared.append((job, settings))
            if not prepared:
                raise ValueError("Select pending jobs first.")
            # Validate the entire selection before committing any row.
            with self.db:
                for job, settings in prepared:
                    self.db.execute("UPDATE jobs SET settings=?,duplicate_key=?,updated=?,waiting_model_id='' WHERE id=?",
                                    (json.dumps(settings.to_dict()), duplicate_key(job["url"], settings, job["destination"]),
                                     now(), job["id"]))
                    self.db.execute("INSERT INTO job_events(job_id,at,stage,kind,detail) VALUES (?,?,?,?,?)",
                                    (job["id"], now(), job["stage"], "settings", "Bulk edit: " + ", ".join(patch)))
        return len(prepared)

    def reorder(self, job_ids, before_id=None, *, stage, exclude=()):
        with self.lock, self.db:
            jobs = [job for job in self.jobs() if job["stage"] == stage and not job["removed"]
                    and job["status"] not in {"completed", "partial"}]
            order = [job["id"] for job in jobs]
            selected = set(job_ids)
            if not selected or not selected <= set(order):
                raise ValueError("Select entries in this queue to move.")
            if any(job["id"] in selected and (job["status"] not in PENDING or job["id"] in exclude) for job in jobs):
                raise ValueError("Active jobs cannot be reordered.")
            if before_id in selected:
                return
            if before_id is not None and before_id not in order:
                raise ValueError("The drop target is no longer in this queue.")
            moving = [identifier for identifier in order if identifier in selected]
            remaining = [identifier for identifier in order if identifier not in selected]
            position = remaining.index(before_id) if before_id else len(remaining)
            revised = remaining[:position] + moving + remaining[position:]
            slots = sorted(job["queue_order"] for job in jobs)
            for identifier, slot in zip(revised, slots, strict=True):
                self.db.execute("UPDATE jobs SET queue_order=? WHERE id=?", (slot, identifier))
            for identifier in moving:
                self.db.execute("INSERT INTO job_events(job_id,at,stage,kind,detail) VALUES (?,?,?,?,?)",
                                (identifier, now(), stage, "order", "Queue position changed"))

    def add_schedule(self, stage, action, due):
        if stage not in {"download", "caption", "translation"} or action not in {"start", "pause", "resume"}:
            raise ValueError("Choose a queue and Start, Pause or Resume.")
        if due.tzinfo is None or due <= datetime.now(UTC):
            raise ValueError("Choose a future date and time with a timezone.")
        identifier = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT INTO queue_schedules VALUES (?,?,?,?,'pending')",
                            (identifier, stage, action, due.astimezone(UTC).isoformat()))
        return identifier

    def schedules(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM queue_schedules ORDER BY due,id")]

    def schedule_state(self, identifier, state):
        if state not in {"cancelled", "executed", "missed"}:
            raise ValueError("Invalid schedule state")
        with self.lock, self.db:
            return self.db.execute("UPDATE queue_schedules SET state=? WHERE id=? AND state='pending'",
                                   (state, identifier)).rowcount

    def register_model(self, model_id, revision, path):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO installed_models VALUES (?,?,?,?)", (model_id, revision, path, now())
            )

    def forget_model(self, model_id, root):
        with self.lock, self.db:
            rows = self.db.execute(
                "SELECT path FROM installed_models WHERE model_id=?", (model_id,)
            ).fetchall()
            for row in rows:
                if Path(row[0]).resolve().is_relative_to(Path(root).resolve()):
                    self.db.execute("DELETE FROM installed_models WHERE path=?", (row[0],))

    def close(self) -> None:
        self.closed = True
        self.db.close()
