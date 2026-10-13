from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .caption_models import catalog, is_ready, model_path, model_spec, storage_folder
from .captions import validate_cues
from .model_ui import model_state


class ModelLibrary(QWidget):
    def __init__(self, store, controller, use_model, parent=None):
        super().__init__(parent)
        self.store, self.controller, self.use_model = store, controller, use_model
        self.setObjectName("modelLibrary")
        layout = QVBoxLayout(self)
        note = QLabel(
            "Install models here, then choose them in Download settings. Use applies an installed model to your shared settings. "
            "Downloads are verified and run locally after installation."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        folder = QHBoxLayout()
        folder.addWidget(QLabel("Model storage"))
        self.folder = QLineEdit(str(storage_folder(store)))
        self.folder.setReadOnly(True)
        folder.addWidget(self.folder, 1)
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.choose_folder)
        folder.addWidget(choose)
        layout.addLayout(folder)
        self.tabs = QTabWidget()
        groups = {}
        for task, title in [
            ("speech", "Speech models"),
            ("translation", "Translation models"),
            ("alignment", "Alignment models"),
        ]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            body = QWidget()
            rows = QVBoxLayout(body)
            scroll.setWidget(body)
            self.tabs.addTab(scroll, title)
            groups[task] = rows
        layout.addWidget(self.tabs)
        self.controls = {}
        for spec in catalog():
            rows = groups[spec.get("task", "speech")]
            card = QFrame()
            card.setObjectName("card")
            rows.addWidget(card)
            rows = QVBoxLayout(card)
            rows.setContentsMargins(16, 14, 16, 14)
            rows.setSpacing(10)
            identifier = spec["id"]
            title = QLabel(
                f"<b>{spec['title']}</b> · {spec['languages']} · {spec['license']}"
            )
            title.setWordWrap(True)
            title.setObjectName("modelTitle")
            rows.addWidget(title)
            package = ""
            if spec.get("format"):
                precision = "Full precision (BF16)" if spec["precision"] == "bf16" else "4-bit (Q4_K_M)"
                package = f"{precision} · {spec['format']} · {spec['external_runtime']}\n"
            details = QLabel(
                f"{package}{spec['guidance']} · {spec['bytes']:,} bytes "
                f"({spec['bytes'] / 1024**3:,.2f} GiB)\n"
                "Package sizes describe storage, not memory use."
            )
            details.setObjectName("muted")
            details.setToolTip(f"{spec['repository']} @ {spec['revision']}")
            details.setWordWrap(True)
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            rows.addWidget(details)
            state = QLabel()
            state.setObjectName("modelStatus")
            state.setTextFormat(Qt.TextFormat.PlainText)
            state.setWordWrap(True)
            rows.addWidget(state)
            bar = QProgressBar()
            rows.addWidget(bar)
            actions = QHBoxLayout()
            download = QPushButton("Download")
            download.setObjectName("primary")
            download.clicked.connect(lambda _, key=identifier: controller.start_model_download(key))
            repair = QPushButton("Repair / retry")
            repair.clicked.connect(lambda _, key=identifier: controller.start_model_download(key))
            cancel = QPushButton("Cancel download")
            cancel.clicked.connect(lambda _, key=identifier: controller.cancel_model_download(key))
            use = QPushButton("Use")
            if spec.get("download_only", False):
                use.setToolTip("This package can be downloaded, but its inference runtime is not bundled.")
            use.clicked.connect(lambda _, key=identifier: self.select_model(key))
            open_folder = QPushButton("Open folder")
            open_folder.clicked.connect(lambda _, key=identifier: self.open_folder(key))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _, key=identifier: self.remove(key))
            for control in [download, repair, cancel, use, open_folder, remove]:
                actions.addWidget(control)
            actions.addStretch()
            rows.addLayout(actions)
            self.controls[identifier] = (state, bar, download, repair, cancel, use, remove, open_folder)
        for rows in groups.values():
            rows.addStretch()
        controller.models_changed.connect(self.refresh)
        controller.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        root = storage_folder(self.store)
        for spec in catalog():
            key = spec["id"]
            state, bar, download, repair, cancel, use, remove, open_folder = self.controls[key]
            installed = is_ready(root, spec)
            busy = key in self.controller.model_workers
            in_use = self.controller.model_in_use(key)
            progress = self.controller.model_states.get(key, {})
            text = model_state(root, spec, self.controller.model_workers, self.controller.model_states)
            state.setText(
                f"{text}" + (f"\n{progress['message']}" if progress.get("message") else "")
            )
            state.setToolTip(f"Installed revision: {spec['revision'] if installed else '—'}\nStorage: {model_path(root, spec)}")
            ready = installed and not busy
            if state.property("ready") != ready:
                state.setProperty("ready", ready)
                state.style().unpolish(state)
                state.style().polish(state)
            total = progress.get("total") or spec["bytes"]
            bar.setValue(100 if installed and not busy else int(progress.get("bytes", 0) / total * 100))
            bar.setVisible(busy or text == "Retry / resume")
            bar.setFormat("%p%")
            download.setText(
                "Downloading…" if busy else "Resume download" if text == "Retry / resume" else "Download"
            )
            download.setEnabled(not installed and not busy and not in_use)
            repair.setEnabled(not busy and not in_use)
            cancel.setEnabled(busy)
            use.setEnabled(installed and not busy and not spec.get("download_only", False))
            open_folder.setEnabled(installed and not busy)
            remove.setEnabled(
                not busy and not in_use and ((root / key).exists() or (root / ".staging" / key).exists())
            )

    def select_model(self, key):
        if not is_ready(storage_folder(self.store), model_spec(key)):
            return
        self.use_model(key)

    def open_folder(self, key):
        spec = model_spec(key)
        root = storage_folder(self.store)
        if is_ready(root, spec):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(model_path(root, spec))))

    def remove(self, key):
        try:
            self.controller.remove_model(key)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot remove model", str(exc))
        self.refresh()

    def choose_folder(self):
        if self.controller.caption_id or self.controller.model_workers:
            QMessageBox.information(
                self,
                "Model storage in use",
                "Wait for model downloads and captioning to finish before changing storage.",
            )
            return
        selected = QFileDialog.getExistingDirectory(self, "Choose model storage", self.folder.text())
        if selected:
            self.store.set_preference("model_folder", str(Path(selected).resolve()))
            self.controller.model_states.clear()
            self.folder.setText(selected)
            self.controller.models_changed.emit()


class ModelManager(QDialog):
    """Modal library used by per-item settings and isolated developer checks."""

    def __init__(self, store, controller, use_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Models")
        self.resize(960, 720)
        layout = QVBoxLayout(self)

        def select(key):
            use_model(key)
            self.accept()

        self.library = ModelLibrary(store, controller, select, self)
        layout.addWidget(self.library)
        self.controls, self.tabs = self.library.controls, self.library.tabs
        self.refresh, self.select_model = self.library.refresh, self.library.select_model
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)


class CaptionEditor(QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correct captions — " + job["title"])
        self.resize(1050, 680)
        self.job = job
        layout = QVBoxLayout(self)
        note = QLabel(
            "Edit source text, timing, or cue language overrides. Source edits mark translations stale. Manual target edits survive regeneration. Re-export preserves prior files."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        self.tables = {}
        tracks = job.get("tracks", []) or [
            {
                "language": job.get("caption_language_result") or job["settings"]["caption_language"],
                "role": "source",
                "cues_path": job["cues_path"],
                "status": "complete",
            }
        ]
        source_track = next(track for track in tracks if track["role"] == "source")
        source = json.loads(Path(source_track["cues_path"]).read_text(encoding="utf-8"))
        source_by_id = {cue.get("id", str(index)): cue for index, cue in enumerate(source)}
        self.original = {}
        for track in tracks:
            path = Path(track.get("cues_path") or "")
            if not path.is_file() or track["role"] == "bilingual":
                continue
            cues = json.loads(path.read_text(encoding="utf-8"))
            self.original[track["language"]] = cues
            table = QTableWidget(len(cues), 6)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(56)
            table.setAlternatingRowColors(True)
            table.setHorizontalHeaderLabels(
                ["Start", "End", "Cue source language", "Source text", "Text", "Readability"]
            )
            table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            )
            for column, width in [(0, 65), (1, 65), (2, 165), (5, 100)]:
                table.setColumnWidth(column, width)
            for column in (3, 4):
                table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            for row, cue in enumerate(cues):
                original = source_by_id.get(cue.get("id", str(row)), cue)
                warning = (
                    "Long cue"
                    if cue["end"] - cue["start"] > job["settings"].get("caption_max_duration", 6)
                    or len(cue["text"].splitlines()) > 2
                    else ""
                )
                values = [
                    cue["start"],
                    cue["end"],
                    cue.get("language", "") if track["role"] == "source" else original.get("language", ""),
                    original["text"],
                    cue["text"],
                    warning,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if col in {3, 5} or (track["role"] == "target" and col in {0, 1, 2}):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row, col, item)
            self.tables[track["language"]] = (table, track["role"])
            self.tabs.addTab(table, track["language"] + " · " + track["status"])
        self.table = next(iter(self.tables.values()))[0]
        layout.addWidget(self.tabs)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Re-export")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def cues(self):
        result = {}
        for language, (table, role) in self.tables.items():
            cues = []
            for row in range(table.rowCount()):
                cue = {
                    **self.original[language][row],
                    "start": float(table.item(row, 0).text()),
                    "end": float(table.item(row, 1).text()),
                    "text": table.item(row, 4).text(),
                }
                if role == "source":
                    override = table.item(row, 2).text().strip()
                    if override:
                        from .languages import model_language

                        model_language(override)
                        cue["language"] = override
                    else:
                        cue.pop("language", None)
                cues.append(cue)
            result[language] = cues
        return result

    def validate(self):
        try:
            for cues in self.cues().values():
                validate_cues(cues)
        except (ValueError, KeyError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
