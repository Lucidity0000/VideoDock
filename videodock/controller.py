from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .caption_models import is_ready, model_spec, remove_model, storage_folder
from .dependencies import resource_directory, subprocess_flags, worker_command
from .models import ACTIVE, CAPTION_PENDING, PENDING, DownloadSettings
from .queue_policy import transient_failure
from .store import Store
from .windows_job import WindowsJob


class WorkerProcess(QObject):
    event = Signal(dict)
    ended = Signal(int)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = request
        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("VIDEODOCK_RESOURCE_DIR", str(resource_directory()))
        self.process.setProcessEnvironment(environment)
        self.buffer = b""
        self.errors = ""
        self.finished = False
        self.request_sent = False
        self.cancel_requested = False
        self.job = WindowsJob()
        self.cancel_timer = QTimer(self)
        self.cancel_timer.setSingleShot(True)
        self.cancel_timer.timeout.connect(self.force_stop)
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)

    def start(self):
        command = worker_command()
        self.process.start(command[0], command[1:])

    def _started(self):
        try:
            self.job.assign_pid(self.process.processId())
        except OSError as exc:
            self.event.emit({"type": "error", "message": str(exc)})
            self.force_stop()
            return
        self.process.write((json.dumps(self.request, ensure_ascii=False) + "\n").encode("utf-8"))
        self.request_sent = True
        if self.cancel_requested:
            self.process.write(b"cancel\n")

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    self.event.emit(event)
            except (ValueError, UnicodeError):
                self.errors = (self.errors + "\n" + line.decode("utf-8", "replace"))[-4000:]

    def _stderr(self):
        self.errors = (self.errors + bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))[
            -4000:
        ]

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.event.emit(
                {"type": "error", "message": "Cannot start download worker: " + self.process.errorString()}
            )
            self._finished(1)

    def _finished(self, code, *_):
        if self.finished:
            return
        self._read()
        self._stderr()
        self.finished = True
        self.cancel_timer.stop()
        self.job.close()
        self.ended.emit(code)

    def cancel(self):
        if self.finished:
            return
        self.cancel_requested = True
        if self.request_sent:
            self.process.write(b"cancel\n")
        self.cancel_timer.start(5000)

    def submit(self, request):
        self.cancel_requested = False
        self.process.write((json.dumps(request, ensure_ascii=True) + "\n").encode("utf-8"))

    def force_stop(self):
        if self.finished or self.process.state() == QProcess.ProcessState.NotRunning:
            return
        pid = self.process.processId()
        if os.name == "nt" and self.job.handle:
            self.job.close()
        elif os.name == "nt" and pid:
            # Start asynchronously so the GUI stays responsive while the whole process tree is stopped.
            killer = subprocess.Popen(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_flags(),
            )
            QTimer.singleShot(1000, lambda: killer.poll())
        else:
            try:
                # Child tools each own a process group; graceful cancellation normally handles these first.
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.process.kill()


class QueueController(QObject):
    changed = Signal()
    message = Signal(str)
    idle = Signal()
    models_changed = Signal()
    notification = Signal(str, str, str)
    completed_run = Signal()
    run_finished = Signal(bool)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.active: dict[str, WorkerProcess] = {}
        self.caption_worker: WorkerProcess | None = None
        self.caption_id: str | None = None
        self.model_workers: dict[str, WorkerProcess] = {}
        self.model_states: dict[str, dict] = {}
        self.removing: set[str] = set()
        self.running = False
        self.paused_stages = {"download", "caption", "translation"}
        self.auto_suppressed: set[str] = set()
        self.started_stages: set[str] = set()
        self.shutting_down = False
        self.maintenance = False
        self.limit = int(store.preference("concurrency", 2))
        self.run_jobs = set()
        self.notified = set()
        # A closed app never silently replays an overdue start at next launch.
        for item in store.schedules():
            if item["state"] == "pending" and datetime.fromisoformat(item["due"]) <= datetime.now(UTC):
                store.schedule_state(item["id"], "missed")
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def start(self, stage=None, *, dispatch=True):
        if stage is not None and stage not in {"download", "caption", "translation"}:
            raise ValueError("Unknown queue stage")
        if self.maintenance or self.shutting_down:
            return
        self.running = True
        self.started_stages.update({"download", "caption", "translation"} if stage is None else {stage})
        if stage is None:
            self.paused_stages.clear()
            self.auto_suppressed.clear()
        else:
            self.paused_stages.discard(stage)
            self.auto_suppressed.discard(stage)
        if dispatch:
            self.pump()
        self.changed.emit()

    def pause(self, stage=None):
        if stage is None:
            self.paused_stages = {"download", "caption", "translation"}
            self.auto_suppressed.update(self.paused_stages)
        else:
            self.paused_stages.add(stage)
            self.auto_suppressed.add(stage)
        self.running = len(self.paused_stages) < 3
        self.changed.emit()

    def stage_running(self, stage):
        return self.running and stage not in self.paused_stages

    def set_auto_start(self, stage: str, enabled: bool):
        if stage not in {"caption", "translation"}:
            raise ValueError("Only captioning and translation support automatic handoffs.")
        self.store.set_preference(f"auto_start_{stage}", bool(enabled))
        if enabled:
            self.auto_suppressed.discard(stage)
        self.changed.emit()

    def _auto_start(self, stage: str, upstream: str):
        # A handoff only arms the next queue. Its previous worker must finish
        # cleanup before pump() can claim the shared job/inference slot.
        if (not self.shutting_down and not self.maintenance and upstream in self.started_stages
                and stage not in self.auto_suppressed
                and self.store.preference(f"auto_start_{stage}", False)):
            self.paused_stages.discard(stage)
            self.started_stages.add(stage)
            self.running = True

    def pump(self):
        if self.store.closed or not self.running or self.shutting_down or self.maintenance:
            return
        while self.stage_running("download") and len(self.active) < self.limit:
            job = self.store.next_queued()
            if not job:
                break
            self.store.update(
                job["id"], stage="download", status="inspecting", download_status="inspecting",
                attempts=job["attempts"] + 1, error="", speed=None, eta=None
            )
            worker = WorkerProcess({"action": "download", "job": {**job, "split_stages": True}}, self)
            self.active[job["id"]] = worker
            self.run_jobs.add(job["id"])
            self.notified.discard(job["id"])
            worker.event.connect(lambda event, job_id=job["id"]: self._event(job_id, event))
            worker.ended.connect(lambda code, job_id=job["id"]: self._ended(job_id, code))
            worker.start()
            self.changed.emit()
        self._pump_captions()
        self._check_completion()

    def tick(self, instant=None):
        if self.store.closed:
            self.timer.stop()
            return
        instant = instant or datetime.now(UTC)
        if self.shutting_down or self.maintenance:
            return
        for item in self.store.schedules():
            if item["state"] == "pending" and datetime.fromisoformat(item["due"]) <= instant:
                if self.store.schedule_state(item["id"], "executed"):
                    if item["action"] == "pause":
                        self.pause(item["stage"])
                    else:
                        self.start(item["stage"], dispatch=False)
                    self.message.emit(f"Scheduled {item['action']}: {item['stage']} queue")
        for job in self.store.jobs():
            if (job["status"] == "retry_wait" and not job["held"] and not job["removed"]
                    and self.stage_running(job["stage"]) and datetime.fromisoformat(job["retry_at"]) <= instant
                    and job["id"] not in self.active and job["id"] != self.caption_id):
                self.store.update(job["id"], status=self.store.queued_status(job["stage"]), retry_at="",
                                  **{self.store.stage_status_field(job["stage"]): "queued"})
                self.changed.emit()
        self.pump()
        self._check_completion()

    def _settled(self, identifier):
        job = self.store.get(identifier)
        if not job or job["removed"] or self.shutting_down:
            return
        if job["held"] and job["status"] in PENDING | {"cancelled"}:
            self.store.update(identifier, status="paused", **{self.store.stage_status_field(job["stage"]): "paused"})
            return
        if job["status"] == "failed":
            settings = DownloadSettings.from_dict(job["settings"])
            category = transient_failure(job["error"])
            if category and category in settings.retry_categories and job["retry_count"] < settings.retry_limit:
                count = job["retry_count"] + 1
                delay = min(3600, settings.retry_delay * 2 ** (count - 1))
                due = datetime.now(UTC) + timedelta(seconds=delay)
                self.store.update(identifier, status="retry_wait", retry_count=count, retry_at=due.isoformat(),
                                  **{self.store.stage_status_field(job["stage"]): "retry_wait"})
                self.store.add_event(identifier, "retry", f"Automatic {category} retry {count}/{settings.retry_limit} at {due.isoformat()}")
                return
        if job["status"] in {"completed", "partial", "failed"} and identifier not in self.notified:
            self.notified.add(identifier)
            self.notification.emit("completion" if job["status"] == "completed" else "failure",
                                   job["title"], job["error"] or "Job completed")

    def _check_completion(self):
        if (not self.run_jobs or self.active or self.caption_id or self.model_workers
                or self.shutting_down or self.maintenance):
            return
        jobs = self.store.jobs()
        if any(not job["removed"] and job["status"] in ACTIVE | PENDING for job in jobs):
            return
        outcomes = [job for job in jobs if job["id"] in self.run_jobs]
        success = len(outcomes) == len(self.run_jobs) and all(job["status"] == "completed" and not job["removed"]
                                                           for job in outcomes)
        self.run_jobs.clear()
        self.notification.emit("completion" if success else "failure", "Queue finished",
                               "All jobs completed." if success else "Queue finished with failed or cancelled jobs.")
        ready = success and not any(item["state"] == "pending" for item in self.store.schedules())
        self.run_finished.emit(ready)
        if ready:
            self.completed_run.emit()

    def worker_ids(self):
        return set(self.active) | ({self.caption_id} if self.caption_id else set())

    def edit_pending(self, identifiers, patch):
        count = self.store.bulk_settings(identifiers, patch, exclude=self.worker_ids())
        self.changed.emit()
        return count

    def pause_jobs(self, identifiers):
        for identifier in identifiers:
            job = self.store.get(identifier)
            if not job or job["removed"]:
                continue
            if job["status"] in PENDING:
                self.store.update(identifier, held=1, status="paused",
                                  **{self.store.stage_status_field(job["stage"]): "paused"})
            elif job["status"] in {"inspecting", "downloading", "preparing", "transcribing", "translating"}:
                self.store.update(identifier, held=1)
                self.cancel([identifier], for_pause=True)
            else:
                self.message.emit("This stage cannot pause safely. Wait for processing/export to finish.")
                continue
            self.store.add_event(identifier, "pause", "Individual pause; partial files and completed segments retained")
        self.changed.emit()

    def resume_jobs(self, identifiers):
        for identifier in identifiers:
            job = self.store.get(identifier)
            if job and job["held"] and job["status"] == "paused" and identifier not in self.worker_ids():
                self.store.update(identifier, held=0, status=self.store.queued_status(job["stage"]), retry_at="",
                                  **{self.store.stage_status_field(job["stage"]): "queued"})
                self.store.add_event(identifier, "resume", "Individual hold released; queue start/pause still applies")
        self.changed.emit()
        self.pump()

    @property
    def busy(self):
        return bool(self.active or self.caption_worker or self.model_workers)

    def _pump_captions(self):
        if self.caption_id:
            return
        root = storage_folder(self.store)
        for job in self.store.jobs():
            if job["removed"] or job["held"] or job["id"] in self.active or job["status"] not in CAPTION_PENDING:
                continue
            stage = job["stage"]
            if not self.stage_running(stage):
                continue
            settings = DownloadSettings.from_dict(job["settings"])
            model_id = job.get("waiting_model_id") or (settings.translation_model if stage == "translation" else settings.caption_model)
            revision = (
                settings.translation_revision
                if model_id == settings.translation_model
                else settings.alignment_revision if model_id == settings.alignment_model
                else settings.fallback_revision if model_id == settings.fallback_model
                else settings.model_revision
            )
            spec = model_spec(model_id, revision)
            needs_speech = stage == "caption" and settings.caption_source == "local" and not job.get("cues_path")
            if (
                needs_speech or (job["status"] == "waiting_model" and job.get("waiting_model_id"))
            ) and not is_ready(root, spec):
                if job["status"] != "waiting_model":
                    self.store.update(
                        job["id"],
                        status="waiting_model",
                        **{self.store.stage_status_field(stage): "waiting_model"},
                        error="Waiting for model. Click Download required model.",
                        waiting_model_id=model_id,
                    )
                    self.changed.emit()
                continue
            self.caption_id = job["id"]
            self.run_jobs.add(job["id"])
            self.notified.discard(job["id"])
            self.store.update(job["id"], status="preparing", **{self.store.stage_status_field(stage): "preparing"}, progress=0, error="")
            request = {"action": "caption_service", "job": {**job, "defer_translation": stage == "caption" and settings.translate}, "model_folder": str(root)}
            if self.caption_worker:
                self.caption_worker.submit(request)
            else:
                worker = WorkerProcess(request, self)
                self.caption_worker = worker
                worker.event.connect(self._caption_event)
                worker.ended.connect(self._caption_ended)
                worker.start()
            self.changed.emit()
            break

    def _caption_event(self, event):
        job_id = event.get("job_id")
        if event.get("type") == "caption_idle":
            if self.caption_worker:
                self.caption_worker.cancel_timer.stop()
            self.caption_id = None
            self._settled(job_id)
            if job_id in self.removing:
                self.store.remove(job_id)
                self.removing.discard(job_id)
            if self.shutting_down and self.caption_worker:
                self.caption_worker.process.closeWriteChannel()
            self.changed.emit()
            self.pump()
        elif job_id:
            self._event(job_id, event)
        elif event.get("type") == "error" and self.caption_id:
            self._event(self.caption_id, event)

    def _caption_ended(self, code):
        worker = self.caption_worker
        identifier = self.caption_id
        self.caption_worker = None
        self.caption_id = None
        if identifier:
            self._ended(identifier, code, worker)
        elif worker:
            worker.deleteLater()
        self.changed.emit()
        self.idle.emit()
        self.pump()

    def start_model_download(self, model_id):
        if model_id in self.model_workers:
            return
        if self.model_in_use(model_id):
            self.message.emit("This model is in use. Wait for captioning to finish before repairing it.")
            return
        root = storage_folder(self.store)
        worker = WorkerProcess(
            {"action": "model_download", "model_id": model_id, "model_folder": str(root)}, self
        )
        self.model_workers[model_id] = worker
        self.model_states[model_id] = {
            "state": "Downloading…",
            "bytes": 0,
            "total": model_spec(model_id)["bytes"],
        }
        worker.event.connect(lambda event: self._model_event(model_id, event))
        worker.ended.connect(lambda code: self._model_ended(model_id, code))
        worker.start()
        self.models_changed.emit()
        self.message.emit(f"Downloading {model_spec(model_id)['title']}. Follow progress on Models.")

    def model_in_use(self, model_id):
        if not self.caption_id:
            return False
        settings = DownloadSettings.from_dict(self.store.get(self.caption_id)["settings"])
        return (settings.uses_local and model_id in {settings.caption_model, settings.fallback_model}) or (
            settings.translate and settings.translation_model == model_id
        ) or (settings.alignment_model == model_id)

    def _model_event(self, model_id, event):
        if event["type"] == "model_ready":
            self.store.register_model(model_id, event["revision"], event["path"])
            self.model_states[model_id] = {
                "state": "Installed",
                "bytes": model_spec(model_id)["bytes"],
                "total": model_spec(model_id)["bytes"],
            }
        elif event["type"] == "model_progress":
            self.model_states[model_id] = event
        elif event["type"] in {"error", "cancelled"}:
            self.model_states[model_id] = {
                "state": "Retry / resume",
                "message": event.get("message", "Download cancelled; partial files retained."),
            }
            self.message.emit(self.model_states[model_id]["message"])
        self.models_changed.emit()

    def _model_ended(self, model_id, code):
        worker = self.model_workers.pop(model_id)
        if code and self.model_states[model_id]["state"] in {"Downloading…", "Verify"}:
            self.model_states[model_id] = {
                "state": "Retry / resume",
                "message": worker.errors or "Model worker stopped. Retry to resume.",
            }
        worker.deleteLater()
        self.models_changed.emit()
        self.idle.emit()
        self.pump()

    def cancel_model_download(self, model_id):
        if model_id in self.model_workers:
            self.model_workers[model_id].cancel()

    def remove_model(self, model_id):
        root = storage_folder(self.store)
        remove_model(root, model_id)
        self.store.forget_model(model_id, root)
        self.model_states.pop(model_id, None)
        self.models_changed.emit()

    def _event(self, job_id: str, event: dict):
        kind = event.get("type")
        job = self.store.get(job_id)
        if not job:
            return
        cancelling = job["status"] == "cancelling"
        stage = job["stage"]
        stage_field = self.store.stage_status_field(stage)
        if kind == "status" and not cancelling:
            fields = {"status": event["status"], "progress": 0, "speed": None, "eta": None}
            if job_id == self.caption_id:
                fields[stage_field] = "exporting" if event["status"] == "processing" else event["status"]
                if event["status"] == "processing":
                    fields["status"] = "exporting"
            else:
                fields["download_status"] = event["status"]
            self.store.update(job_id, **fields)
        elif kind == "progress" and not cancelling:

            def number(value):
                return value if isinstance(value, (int, float)) else None

            self.store.update(
                job_id,
                progress=number(event.get("progress")) or 0,
                speed=number(event.get("speed")),
                eta=number(event.get("eta")),
            )
        elif kind == "title":
            self.store.update(job_id, title=event["title"])
        elif kind == "completed":
            self.store.update(
                job_id,
                status="partial" if "partial" in (event.get("caption_status"), event.get("translation_status")) else "completed",
                progress=100,
                output=event["output"],
                error=event.get("error", ""),
                waiting_model_id="",
                regenerate_languages=[],
                retry_languages=[],
                speed=None,
                eta=None,
                **{
                    key: event[key]
                    for key in [
                        "caption_paths",
                        "cues_path",
                        "media_path",
                        "caption_status",
                        "caption_language_result",
                        "translation_status",
                    ]
                    if key in event
                },
                **({stage_field: "complete"} if stage_field not in event else {}),
                **({"caption_status": "complete"} if stage == "download" and event.get("caption_paths") and "caption_status" not in event else {}),
            )
            for track in event.get("tracks", []):
                self.store.upsert_track(job_id, track)
        elif kind == "media_ready":
            self.store.update(
                job_id,
                status="paused" if job["held"] else "cancelled" if cancelling else "caption_queued",
                stage="caption",
                download_status="complete",
                caption_status="paused" if job["held"] else "cancelled" if cancelling else "queued",
                retry_count=0, retry_at="",
                media_path=event["output"],
                output=event["output"],
                progress=0,
            )
            if not cancelling and not job["removed"]:
                self._auto_start("caption", "download")
        elif kind == "translation_ready":
            self.store.update(job_id, stage="translation", status="paused" if job["held"] else "cancelled" if cancelling else "translation_queued", caption_status="complete",
                              translation_status="paused" if job["held"] else "cancelled" if cancelling else "queued", progress=0, error="", cues_path=event["cues_path"],
                              retry_count=0, retry_at="",
                              caption_language_result=event["caption_language_result"])
            if not cancelling and not job["removed"]:
                self._auto_start("translation", "caption")
        elif kind == "caption_waiting":
            self.store.update(
                job_id,
                status="paused" if job["held"] else "cancelled" if cancelling else "waiting_model",
                **{stage_field: "paused" if job["held"] else "cancelled" if cancelling else "waiting_model"},
                error="" if cancelling else event["message"],
                waiting_model_id="" if cancelling else event.get("model_id", ""),
            )
        elif kind == "caption_source":
            self.store.update(
                job_id, cues_path=event["cues_path"], caption_language_result=event["caption_language_result"],
                caption_status="imported" if job["settings"]["caption_source"] == "import" else "complete",
            )
        elif kind == "caption_track":
            self.store.upsert_track(job_id, event["track"])
            paths = [path for track in self.store.tracks(job_id) for path in track.get("export_paths", [])]
            self.store.update(job_id, caption_paths=paths)
        elif kind == "translation_progress" and not cancelling:
            total = event["total"]
            self.store.update(
                job_id,
                progress=event["done"] / total * 100 if total else 100,
                caption_preview=f"Translating {event['language']}: {event['done']}/{total} cues\n{event['preview']}",
            )
        elif kind == "caption_progress" and not cancelling:
            self.store.update(
                job_id,
                progress=event["progress"],
                processed_duration=event["processed"],
                caption_preview=event["preview"],
            )
        elif kind in {"error", "cancelled"}:
            status = (
                "paused" if job["held"] else self.store.queued_status(stage)
                if self.shutting_down
                else ("paused" if job["held"] else "cancelled" if cancelling or kind == "cancelled" else "failed")
            )
            self.store.update(
                job_id,
                status=status,
                error=event.get("message", ""),
                speed=None,
                eta=None,
                **{stage_field: (
                    "queued" if self.shutting_down and status != "paused" else status
                )},
            )
        elif kind == "warning":
            self.store.add_event(job_id, "warning", event["message"])
            self.message.emit(event["message"])
        elif kind in {"segment_checkpoint", "segment_fallback", "checkpoint_resume"}:
            self.store.add_event(job_id, kind, event.get("message", ""))
        elif kind == "model_runtime":
            detail = f"{event['model_id']}: {event['backend']} · {event['device'].upper()}"
            if event.get("cpu_offload"):
                detail += " with CPU offloading"
            if event.get("disk_offload"):
                detail += " and disk offloading"
            if event.get("gpu_name"):
                detail += " · " + event["gpu_name"]
            self.message.emit(detail)
        self.changed.emit()

    def _ended(self, job_id: str, code: int, caption_worker=None):
        worker = caption_worker or self.active.pop(job_id, None)
        job = self.store.get(job_id)
        if job and job["status"] in ACTIVE:
            status = (
                "paused" if job["held"] else self.store.queued_status(job["stage"])
                if self.shutting_down
                else ("paused" if job["held"] else "cancelled" if job["status"] == "cancelling" else "failed")
            )
            error = worker.errors if worker else ""
            self.store.update(
                job_id,
                status=status,
                error=error or f"Worker stopped (code {code}). Retry to resume.",
                speed=None,
                eta=None,
                **{self.store.stage_status_field(job["stage"]): "queued" if self.shutting_down and status != "paused" else status},
            )
        if worker:
            worker.deleteLater()
        if job_id in self.removing:
            self.store.remove(job_id)
            self.removing.discard(job_id)
        self._settled(job_id)
        self.changed.emit()
        if not self.active:
            self.idle.emit()
        self.pump()

    def cancel(self, job_ids: list[str], for_pause=False):
        for job_id in job_ids:
            job = self.store.get(job_id)
            if not job or job["status"] not in ACTIVE | PENDING:
                continue
            if not for_pause:
                self.store.update(job_id, held=0, retry_at="")
            if job["status"] in PENDING:
                # The previous stage may still own a worker while cleaning up.
                # Cancel the pending stage without interrupting completed work.
                self.store.update(job_id, status="cancelled", **{self.store.stage_status_field(job["stage"]): "cancelled"})
            elif job_id == self.caption_id and self.caption_worker:
                self.store.update(job_id, status="cancelling", **{self.store.stage_status_field(job["stage"]): "cancelling"})
                self.caption_worker.cancel()
            elif job_id in self.active:
                self.store.update(job_id, status="cancelling", **{self.store.stage_status_field(job["stage"]): "cancelling"})
                self.active[job_id].cancel()
        self.changed.emit()

    def remove(self, job_ids):
        for job_id in job_ids:
            if job_id in self.active or job_id == self.caption_id:
                self.removing.add(job_id)
                self.store.update(job_id, removed=1)
                self.cancel([job_id])
            else:
                self.store.remove(job_id)
        self.changed.emit()

    def reexport(self, job, cues):
        if self.caption_id:
            raise ValueError("Wait for the active caption job to finish before re-exporting.")
        self.caption_id = job["id"]
        self.store.update(job["id"], stage="caption", status="exporting", caption_status="exporting", error="")
        request = {
            "action": "caption_service",
            "job": job,
            "model_folder": str(storage_folder(self.store)),
            "cues": cues,
        }
        if self.caption_worker:
            self.caption_worker.submit(request)
        else:
            self.caption_worker = WorkerProcess(request, self)
            self.caption_worker.event.connect(self._caption_event)
            self.caption_worker.ended.connect(self._caption_ended)
            self.caption_worker.start()
        self.changed.emit()

    def shutdown(self):
        self.shutting_down = True
        self.running = False
        for worker in list(self.active.values()):
            worker.cancel()
        if self.caption_worker:
            if self.caption_id:
                self.caption_worker.cancel()
            self.caption_worker.process.closeWriteChannel()
        for worker in list(self.model_workers.values()):
            worker.cancel()
