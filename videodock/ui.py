from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .caption_models import model_spec, storage_folder, task_models
from .caption_ui import CaptionEditor, ModelLibrary
from .controller import QueueController, WorkerProcess
from .dependencies import dependency_report
from .media import check_destination
from .model_ui import refresh_download, refresh_selector
from .models import ACTIVE, PENDING, DownloadSettings, parse_intervals, parse_urls
from .saved_lists_ui import SavedListEditor, SaveListDialog
from .store import Store
from .theme import ASSETS, STYLE, apply_palette, status_color
from .translation_ui import TranslationPanel
from .widgets import EmptyStateTable


def label(text: str, name: str = "") -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        result.setObjectName(name)
    result.setWordWrap(True)
    return result


def button(text: str, callback, primary=False) -> QPushButton:
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(callback)
    return result


def table(headers: list[str]) -> QTableWidget:
    result = EmptyStateTable(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setAlternatingRowColors(True)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    result.setShowGrid(False)
    result.verticalHeader().setVisible(False)
    result.verticalHeader().setDefaultSectionSize(39)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return result


def duration_text(value) -> str:
    if value is None:
        return "—"
    seconds = int(value)
    return (
        f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
        if seconds >= 3600
        else f"{seconds // 60}:{seconds % 60:02d}"
    )


class SettingsPanel(QFrame):
    download_model = Signal(str)

    def __init__(self, settings: DownloadSettings, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        self.pages = QTabWidget()
        layout.addWidget(self.pages)
        self.model_root = None
        self.model_workers = {}
        self.model_states = {}
        self.format = QComboBox()
        for fmt, description in [
            ("mp4", "MP4 · video"),
            ("webm", "WebM · video"),
            ("mp3", "MP3 · audio"),
            ("m4a", "M4A · audio"),
        ]:
            self.format.addItem(description, fmt)
        self.height = QComboBox()
        for height in [0, 4320, 2160, 1440, 1080, 720, 480, 360, 240, 144]:
            self.height.addItem("Best available" if not height else f"{height}p", height)
        self.bitrate = QComboBox()
        for bitrate in [96, 128, 192, 256, 320]:
            self.bitrate.addItem(f"{bitrate} kbps", bitrate)
        self.mode = QComboBox()
        for value, title in [
            ("none", "No captions"),
            ("sidecar", "Save separate files"),
            ("embed", "Embed + save separate files"),
            ("burn", "Burn into video + save files"),
        ]:
            self.mode.addItem(title, value)
        self.source = QComboBox()
        self.source.addItem("Creator-provided", "creator")
        self.source.addItem("Automatic (YouTube)", "auto")
        self.source.addItem("Local model", "local")
        self.source.addItem("YouTube creator → local fallback", "fallback_creator")
        self.source.addItem("YouTube automatic → local fallback", "fallback_auto")
        self.source.addItem("Off", "off")
        self.source.addItem("Imported SRT/VTT", "import")
        self.local_model = QComboBox()
        for spec in task_models("speech", usable_only=True):
            self.local_model.addItem(spec["title"], spec["id"])
        self.alignment_model = QComboBox()
        self.alignment_model.addItem("Off · model timestamps / estimated timing", "")
        for spec in task_models("alignment", usable_only=True):
            self.alignment_model.addItem(spec["title"], spec["id"])
        self.spoken = QComboBox()
        self.spoken.setEditable(True)
        self.spoken.addItems(["auto", "en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru", "ar", "hi"])
        self.device = QComboBox()
        self.device.addItem("CPU", "cpu")
        self.device.addItem("NVIDIA GPU · CUDA", "cuda")
        for combo in [self.source, self.local_model, self.spoken, self.device]:
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(14)
        self.cpu_fallback = QCheckBox("Use CPU if GPU is unavailable")
        self.fallback_model = QComboBox()
        self.fallback_model.addItem("Off · report failed speech segments", "")
        for spec in task_models("speech", usable_only=True):
            self.fallback_model.addItem(spec["title"], spec["id"])
        self.retry_checks = {}
        for key, title in (("network", "Connection failures / timeouts"), ("rate_limit", "HTTP 429 rate limits"), ("server", "HTTP 500 / 502 / 503 / 504")):
            self.retry_checks[key] = QCheckBox(title)
        self.retry_limit = QSpinBox()
        self.retry_limit.setRange(0, 10)
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(1, 3600)
        self.retry_delay.setSuffix(" seconds")
        self.line_length = QSpinBox()
        self.line_length.setRange(20, 100)
        self.cue_duration = QSpinBox()
        self.cue_duration.setRange(2, 15)
        self.cue_duration.setSuffix(" seconds")
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItem("en")
        self.language.setToolTip(
            "Exact source language code. Inspect a selected video to see available languages."
        )
        self.chinese = QComboBox()
        for text, value in [
            ("Keep original script", "original"),
            ("Simplified Chinese · 简体", "zh-Hans"),
            ("Traditional Chinese · 繁體", "zh-Hant"),
        ]:
            self.chinese.addItem(text, value)
        self.caption_format = QComboBox()
        self.caption_format.addItems(["SRT", "VTT"])
        self.convert = QCheckBox("Convert incompatible streams")
        self.convert.setToolTip("FFmpeg encodes incompatible codecs. This can take longer than downloading.")
        self.convert.setChecked(settings.allow_conversion)
        self.template = QLineEdit(settings.filename_template)
        self.template.setToolTip("Filename only; include %(id)s. Example: %(title).160s [%(id)s]")
        media, form = self._page("Media", "Output format and filenames")
        self._rows(form, [("Format", self.format), ("Resolution limit", self.height),
                          ("Audio quality", self.bitrate), ("Filename", self.template)])
        form.addRow("", self.convert)
        form.addRow("", label("Audio downloads save captions as separate files.", "muted"))
        form.addRow(label("Automatic retries (initially off)", "section"))
        for control in self.retry_checks.values():
            form.addRow("", control)
        self._rows(form, [("Maximum retries per stage", self.retry_limit), ("Initial delay (exponential backoff)", self.retry_delay)])
        captions, form = self._page("Captions", "Source and subtitle files")
        self._rows(form, [("Captions", self.mode), ("Caption source", self.source),
                          ("YouTube language", self.language), ("Caption file", self.caption_format),
                          ("Chinese script", self.chinese)])
        form.addRow(label("Local speech recognition", "section"))
        self._rows(form, [("Speech model", self.local_model)])
        self.model_status = label("", "modelStatus")
        self.download_button = button(
            "Download selected model", lambda: self.download_model.emit(self.local_model.currentData())
        )
        form.addRow("", self._model_row(self.model_status, self.download_button))
        self._rows(form, [("Word alignment", self.alignment_model)])
        self.alignment_status = label("", "modelStatus")
        self.alignment_download = button(
            "Download selected model", lambda: self.download_model.emit(self.alignment_model.currentData())
        )
        form.addRow("", self._model_row(self.alignment_status, self.alignment_download))
        self._rows(form, [("Spoken language", self.spoken), ("Inference device", self.device)])
        form.addRow("", self.cpu_fallback)
        self._rows(form, [("Failed segment fallback", self.fallback_model)])
        form.addRow("", label("Retries only failed 30-second speech segments with the selected installed model. Completed segments are checkpointed. No model is downloaded automatically.", "muted"))
        form.addRow("", label("Install and select models on the Models page. ARK needs an explicit spoken language for translation or alignment.", "muted"))
        form.addRow(label("Cue timing and readability", "section"))
        self._rows(form, [("Characters per line", self.line_length), ("Maximum cue duration", self.cue_duration)])
        self.availability = label("Inspect a video to see available resolutions and captions.", "muted")
        form.addRow("", self.availability)
        self.translation_panel = TranslationPanel()
        self.translation_panel.download_model.connect(self.download_model.emit)
        self.translation_panel.enabled.toggled.connect(self._translation_changed)
        self._add_page(self.translation_panel, "Translation")
        self._add_page(self.translation_panel.style_panel, "Subtitle style")
        self.details: dict | None = None
        self.preferred_language = settings.caption_language
        self.load(settings)
        self.format.currentIndexChanged.connect(self._enabled)
        self.mode.currentIndexChanged.connect(self._enabled)
        self.source.currentIndexChanged.connect(self._languages)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.device.currentIndexChanged.connect(self._device_changed)
        self.local_model.currentIndexChanged.connect(self.refresh_models)
        self.alignment_model.currentIndexChanged.connect(self.refresh_models)
        self.fallback_model.currentIndexChanged.connect(self.refresh_models)
        self.language.currentTextChanged.connect(self._availability)
        self._enabled()
        self._languages()

    @staticmethod
    def _rows(form, rows):
        for title, control in rows:
            form.addRow(title, control)
            control.setAccessibleName(title)
            if isinstance(control, QComboBox):
                control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                control.setMinimumContentsLength(16)

    @staticmethod
    def _model_row(status, download):
        row = QHBoxLayout()
        row.addWidget(status, 1)
        row.addWidget(download)
        return row

    def _add_page(self, body, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        self.pages.addTab(scroll, title)

    def _page(self, title, heading):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(label(heading, "section"))
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        layout.addStretch()
        self._add_page(body, title)
        return body, form

    def refresh_models(self, root=None, workers=None, states=None):
        if root is None and hasattr(self, "model_store"):
            root = storage_folder(self.model_store)
            workers, states = self.model_controller.model_workers, self.model_controller.model_states
        if isinstance(root, Path):
            self.model_root = root
            self.model_workers = workers if workers is not None else {}
            self.model_states = states if states is not None else {}
        if self.model_root is None:
            return
        for combo, status, download in [(self.local_model, self.model_status, self.download_button),
                                        (self.alignment_model, self.alignment_status, self.alignment_download)]:
            refresh_selector(combo, self.model_root, self.model_workers, self.model_states)
            refresh_download(combo, status, download, self.model_root, self.model_workers, self.model_states)
        self.translation_panel.refresh_model(self.model_root, self.model_workers, self.model_states)
        refresh_selector(self.fallback_model, self.model_root, self.model_workers, self.model_states)

    def bind_models(self, store, controller):
        self.model_store, self.model_controller = store, controller
        controller.models_changed.connect(self.refresh_models)
        self.refresh_models()

    def load(self, settings: DownloadSettings):
        for combo, value in [
            (self.format, settings.format),
            (self.height, settings.height),
            (self.bitrate, settings.audio_bitrate),
            (self.mode, settings.caption_mode),
            (self.source, settings.caption_source),
            (self.local_model, settings.caption_model),
            (self.alignment_model, settings.alignment_model),
            (self.fallback_model, settings.fallback_model),
            (self.device, settings.caption_device),
            (self.chinese, settings.chinese_script),
        ]:
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.language.setCurrentText(settings.caption_language)
        self.caption_format.setCurrentText(settings.caption_format.upper())
        self.convert.setChecked(settings.allow_conversion)
        self.template.setText(settings.filename_template)
        self.spoken.setCurrentText(settings.spoken_language)
        self.cpu_fallback.setChecked(settings.cpu_fallback)
        for key, control in self.retry_checks.items():
            control.setChecked(key in settings.retry_categories)
        self.retry_limit.setValue(settings.retry_limit)
        self.retry_delay.setValue(settings.retry_delay)
        self.line_length.setValue(settings.caption_line_length)
        self.cue_duration.setValue(settings.caption_max_duration)
        self.translation_panel.load(settings)
        self.refresh_models()

    def settings(self) -> DownloadSettings:
        result = DownloadSettings(
            format=self.format.currentData(),
            height=self.height.currentData(),
            audio_bitrate=self.bitrate.currentData(),
            caption_mode="none" if self.source.currentData() == "off" else self.mode.currentData(),
            caption_source=self.source.currentData(),
            caption_language=(self.preferred_language if self.details is None else "")
            if self.language.currentText() == "N/A"
            else self.language.currentText().strip(),
            caption_format=self.caption_format.currentText().lower(),
            allow_conversion=self.convert.isChecked(),
            filename_template=self.template.text().strip(),
            caption_model=self.local_model.currentData(),
            alignment_model=self.alignment_model.currentData(),
            spoken_language=self.spoken.currentText().strip().lower(),
            caption_device=self.device.currentData(),
            cpu_fallback=self.cpu_fallback.isChecked(),
            fallback_model=self.fallback_model.currentData(),
            retry_categories=tuple(key for key, control in self.retry_checks.items() if control.isChecked()),
            retry_limit=self.retry_limit.value(),
            retry_delay=self.retry_delay.value(),
            caption_line_length=self.line_length.value(),
            caption_max_duration=self.cue_duration.value(),
            chinese_script=self.chinese.currentData(),
            **self.translation_panel.settings(),
        )
        result.validate()
        return result

    def _enabled(self):
        audio = self.format.currentData() in {"mp3", "m4a"}
        self.height.setEnabled(not audio)
        self.bitrate.setEnabled(audio)
        model = self.mode.model()
        for index in [2, 3]:
            model.item(index).setEnabled(not audio)
        if audio and self.mode.currentData() in {"embed", "burn"}:
            self.mode.setCurrentIndex(1)
        captions = self.mode.currentData() != "none" and self.source.currentData() != "off"
        self.mode.setEnabled(self.source.currentData() != "off")
        for widget in [self.language, self.caption_format, self.chinese]:
            widget.setEnabled(captions)
        local = captions and self.source.currentData() in {"local", "fallback_creator", "fallback_auto"}
        for widget in [
            self.local_model,
            self.alignment_model,
            self.spoken,
            self.device,
            self.cpu_fallback,
            self.line_length,
            self.cue_duration,
        ]:
            widget.setEnabled(local)
        self.language.setEnabled(captions and self.source.currentData() != "local")
        inference = local or (captions and self.translation_panel.enabled.isChecked())
        for widget in [self.device, self.cpu_fallback, self.line_length]:
            widget.setEnabled(inference)
        self.alignment_model.setEnabled(captions and self.source.currentData() != "import")
        self.translation_panel.set_caption_mode(self.mode.currentData(), self.source.currentData())
        if self.language.currentText() == "N/A":
            self.language.setEnabled(False)
        self._availability()

    def _source_changed(self):
        if (
            self.source.currentData() in {"local", "fallback_creator", "fallback_auto", "import"}
            and self.mode.currentData() == "none"
        ):
            self.mode.setCurrentIndex(1)
        self._enabled()

    def _translation_changed(self):
        if self.translation_panel.enabled.isChecked() and self.mode.currentData() == "none":
            self.mode.setCurrentIndex(1)
        self._enabled()

    def _device_changed(self):
        self._enabled()

    def use_model(self, key):
        spec = model_spec(key)
        if spec.get("format"):
            self.device.blockSignals(True)
            self.device.setCurrentIndex(self.device.findData("cuda"))
            self.device.blockSignals(False)
        if spec.get("task") == "translation":
            self.translation_panel.model.setCurrentIndex(self.translation_panel.model.findData(key))
            self.translation_panel.enabled.setChecked(True)
        elif spec.get("task") == "alignment":
            self.alignment_model.setCurrentIndex(self.alignment_model.findData(key))
            if self.mode.currentData() == "none":
                self.mode.setCurrentIndex(self.mode.findData("sidecar"))
        else:
            self.local_model.setCurrentIndex(self.local_model.findData(key))
            self.source.setCurrentIndex(self.source.findData("local"))
        self._enabled()

    def set_details(self, details: dict | None):
        self.details = details
        self._languages()

    def _languages(self):
        current = self.language.currentText()
        if current not in {"", "N/A"}:
            self.preferred_language = current
        else:
            current = self.preferred_language
        self.language.blockSignals(True)
        self.language.clear()
        languages = []
        if self.details:
            source = self.source.currentData().removeprefix("fallback_")
            languages = self.details.get("captions", {}).get(source, [])
        self.language.setEditable(bool(languages) or self.details is None)
        if languages:
            self.language.addItems(languages)
            self.language.setCurrentText(current if current not in {"", "N/A"} else languages[0])
        else:
            self.language.setEditable(False)
            self.language.addItem("N/A", "")
        self.language.blockSignals(False)
        self._availability()
        self._enabled()

    def _availability(self):
        if not self.details or not self.details.get("detailed"):
            self.availability.setText(
                "Select a video and click Inspect selected for available resolutions and captions."
            )
            return
        heights = ", ".join(f"{height}p" for height in self.details.get("heights", [])) or "No video streams"
        source = self.source.currentData().removeprefix("fallback_")
        languages = self.details.get("captions", {}).get(source, [])
        text = f"Available video: {heights}.\n{len(languages)} caption languages from this source."
        if self.source.currentData() == "local":
            text = f"Available video: {heights}.\nGenerate same-language captions locally from audio."
        elif (
            self.source.currentData().startswith("fallback_") and self.language.currentText() not in languages
        ):
            text += "\nSelected YouTube language is missing; local transcription will be used."
        elif (
            self.mode.currentData() != "none"
            and self.source.currentData() != "off"
            and self.language.currentText() not in languages
        ):
            text += f"\n⚠ {self.language.currentText()} captions are unavailable for this video."
        if self.format.currentData() in {"mp3", "m4a"}:
            text += "\nAudio captions are saved as separate files."
        self.availability.setText(text)


class OverrideDialog(QDialog):
    def __init__(self, settings: DownloadSettings, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Item settings — " + item["title"])
        self.resize(760, 720)
        layout = QVBoxLayout(self)
        self.panel = SettingsPanel(settings)
        if parent:
            self.panel.download_model.connect(parent.controller.start_model_download)
            self.panel.bind_models(parent.store, parent.controller)
        self.panel.set_details(item)
        layout.addWidget(self.panel)
        controls = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        controls.accepted.connect(self.validate)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def validate(self):
        try:
            self.panel.settings()
        except ValueError as exc:
            QMessageBox.warning(self, "Check item settings", str(exc))
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.controller = QueueController(store, self)
        self.items: list[dict] = []
        self.preview_errors: list[str] = []
        self.preview_warnings: list[str] = []
        self.overrides: dict[int, DownloadSettings] = {}
        self.background: WorkerProcess | None = None
        self.closing = False
        self.release: dict | None = None
        self.thumbnail_generation = 0
        self.network = QNetworkAccessManager(self)
        self.setWindowTitle("VideoDock")
        apply_palette(QApplication.instance())
        self.setMinimumSize(1100, 680)
        available = self.screen().availableGeometry()
        self.resize(max(1100, min(1380, available.width() - 40)), max(680, min(980, available.height() - 60)))
        self.setStyleSheet(STYLE)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 14, 22, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(QPixmap(f"{ASSETS}/mark.svg"))
        mark.setFixedSize(44, 44)
        header.addWidget(mark)
        header.addSpacing(4)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("VideoDock", "brand"))
        tagline = label("A home for your videos, captions and translations.", "subtitle")
        tagline.setWordWrap(False)
        titles.addWidget(tagline)
        header.addLayout(titles)
        header.addStretch()
        self.summary = label("Queue paused", "summary")
        self.summary.setWordWrap(False)
        header.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("navigation")
        self.tabs.setUsesScrollButtons(True)
        self.tabs.addTab(self._downloads(), "Downloads")
        self.download_settings_page = self._download_settings()
        self.tabs.addTab(self.download_settings_page, "Download settings")
        self.model_library = ModelLibrary(self.store, self.controller, self.use_model)
        self.tabs.addTab(self.model_library, "Models")
        self.tabs.addTab(self._history(), "History")
        self.tabs.addTab(self._preferences(), "Settings and dependencies")
        self.settings_panel.download_model.connect(self.controller.start_model_download)
        layout.addWidget(self.tabs)
        self.notice = label("Paste links to begin. Downloads start when you click Start queue.", "notice")
        self.notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.notice)
        self.setCentralWidget(root)
        self.controller.changed.connect(self.refresh_jobs)
        self.controller.models_changed.connect(self.refresh_models)
        self.controller.message.connect(self.show_notice)
        self.controller.idle.connect(self._close_when_idle)
        from .desktop import DesktopIntegration
        self.desktop = DesktopIntegration(self)
        recovered = store.recover()
        self.refresh_jobs()
        if recovered:
            self.show_notice(f"Recovered {recovered} interrupted jobs. Click Start queue to resume.")

    def _downloads(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        left = QFrame()
        left.setObjectName("sourceCard")
        pane = QVBoxLayout(left)
        pane.setContentsMargins(12, 8, 12, 8)
        pane.setSpacing(4)
        self.saved_list_controls = QWidget()
        saved = QHBoxLayout(self.saved_list_controls)
        saved.setContentsMargins(0, 0, 0, 0)
        saved.addWidget(label("Saved lists"))
        self.saved_lists = QComboBox()
        self.saved_lists.setMinimumContentsLength(18)
        self.saved_lists.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.saved_lists.setAccessibleName("Favorite playlists and custom lists")
        saved.addWidget(self.saved_lists, 1)
        self.load_list_button = button("Load list", self.load_saved_list)
        self.save_list_button = button("Save as…", self.save_preview_list)
        self.add_to_list_button = button("Add selected", self.add_to_saved_list)
        self.edit_list_button = button("Edit list…", self.edit_saved_list)
        self.add_to_list_button.setToolTip("Append checked preview entries from any link to the chosen saved list.")
        for control in (self.load_list_button, self.save_list_button, self.add_to_list_button, self.edit_list_button):
            saved.addWidget(control)
        pane.addWidget(self.saved_list_controls)
        self.saved_list_controls.hide()
        self.saved_lists.currentIndexChanged.connect(self.saved_list_selected)
        self.refresh_saved_lists()
        top = QHBoxLayout()
        links = QVBoxLayout()
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("Paste video or playlist links, one per line…")
        self.urls.setAccessibleName("Video and playlist links")
        self.urls.setFixedHeight(44)
        links.addWidget(self.urls)
        actions = QHBoxLayout()
        self.preview_button = button("Preview links", self.inspect, True)
        self.preview_button.setShortcut("Ctrl+Return")
        actions.addWidget(self.preview_button)
        actions.addWidget(button("Import .txt", self.import_urls))
        self.stop_preview = button("Stop preview", self.cancel_background)
        self.stop_preview.setEnabled(False)
        actions.addWidget(self.stop_preview)
        actions.addStretch()
        top.addLayout(links, 3)
        detail = QHBoxLayout()
        self.thumbnail = QLabel("VIDEO")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(96, 44)
        self.thumbnail.setStyleSheet("background:#203249; color:#a4bdd7; border-radius:7px;")
        detail.addWidget(self.thumbnail)
        self.preview_description = label(
            "Preview titles, choose playlist entries, then add them to the queue.", "muted"
        )
        self.preview_description.setMaximumHeight(44)
        detail.addWidget(self.preview_description, 1)
        self.saved_lists_button = button("Saved lists…", lambda: None)
        self.saved_lists_button.setCheckable(True)
        self.saved_lists_button.setToolTip("Save favorite playlists, create custom lists and edit their entries.")
        self.saved_lists_button.toggled.connect(self.saved_list_controls.setVisible)
        detail.addWidget(self.saved_lists_button)
        top.addLayout(detail, 2)
        pane.addLayout(top)
        pane.addLayout(actions)
        self.preview = table(["✓", "#", "Title", "Duration", "Playlist"])
        self.preview.set_empty_message("Your next download starts here", "Preview links above to choose videos.")
        self.preview.setAccessibleName("Preview videos; first column selects each download")
        self.preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview.itemSelectionChanged.connect(self.preview_selected)
        self.preview.setMinimumHeight(80)
        pane.addWidget(self.preview, 1)
        selection = actions
        selection.addWidget(button("Select all", lambda: self.select_all(True)))
        selection.addWidget(button("Select none", lambda: self.select_all(False)))
        self.detail_button = button("Inspect selected", self.inspect_selected)
        self.override_button = button("Item settings…", self.override_selected)
        self.detail_button.setEnabled(False)
        self.override_button.setEnabled(False)
        selection.addWidget(self.detail_button)
        selection.addWidget(self.override_button)
        self.preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview.customContextMenuRequested.connect(self.preview_settings_menu)
        self.ranges_button = button("Ranges…", lambda: None)
        self.ranges_button.setCheckable(True)
        self.ranges_button.setToolTip("Show inclusive playlist position controls.")
        selection.addWidget(self.ranges_button)
        self.preview_count = label("0 selected", "muted")
        selection.addWidget(self.preview_count)
        self.preview.itemChanged.connect(self.update_preview_controls)
        self.range_controls = QWidget()
        intervals = QHBoxLayout(self.range_controls)
        intervals.setContentsMargins(0, 0, 0, 0)
        self.range_playlist = QComboBox()
        self.range_playlist.addItem("All playlists", "")
        self.range_playlist.setAccessibleName("Playlist for interval selection")
        intervals.addWidget(self.range_playlist)
        self.intervals = QLineEdit()
        self.intervals.setPlaceholderText("Positions: 1-5, 8, 12-20")
        self.intervals.setAccessibleName("Inclusive playlist intervals")
        self.intervals.setToolTip(
            "Original playlist positions, inclusive. Multiple ranges are separated by commas."
        )
        intervals.addWidget(self.intervals, 1)
        intervals.addWidget(button("Select ranges", self.select_intervals))
        intervals.addWidget(button("Add ranges", self.enqueue_intervals))
        pane.addWidget(self.range_controls)
        self.range_controls.hide()
        self.ranges_button.toggled.connect(self.range_controls.setVisible)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left)
        self.preview_scroll = left_scroll
        self.saved_lists_button.toggled.connect(
            lambda visible: QTimer.singleShot(0, lambda: left_scroll.ensureWidgetVisible(self.saved_list_controls))
            if visible else None
        )
        self.ranges_button.toggled.connect(
            lambda visible: QTimer.singleShot(
                0, lambda: left_scroll.ensureWidgetVisible(self.range_controls)
                if self.range_controls.isVisible() else None
            ) if visible else None
        )
        layout.addWidget(left_scroll, 3)
        destination = QHBoxLayout()
        destination.addWidget(label("Save to"))
        self.destination = QLineEdit(
            self.store.preference("destination", str(Path.home() / "Videos" / "VideoDock"))
        )
        self.destination.setAccessibleName("Batch destination folder")
        destination.addWidget(self.destination, 1)
        destination.addWidget(button("Browse…", self.browse_destination))
        self.open_destination_button = button("Open", self.open_destination)
        self.open_destination_button.setToolTip("Open the Save to folder in File Explorer to inspect its files.")
        destination.addWidget(self.open_destination_button)
        layout.addLayout(destination)
        options = QHBoxLayout()
        self.playlist_folders = QCheckBox("Create playlist folders")
        self.playlist_folders.setChecked(self.store.preference("playlist_folders", True))
        self.remember_destination = QCheckBox("Remember destination")
        self.remember_destination.setChecked(True)
        self.duplicates = QCheckBox("Allow duplicate downloads")
        options.addWidget(self.playlist_folders)
        options.addWidget(self.remember_destination)
        options.addWidget(self.duplicates)
        options.addStretch()
        layout.addLayout(options)
        automation = QHBoxLayout()
        self.auto_caption = QCheckBox("Auto-start captioning after download")
        self.auto_translation = QCheckBox("Auto-start translation after captioning")
        for control, stage in ((self.auto_caption, "caption"), (self.auto_translation, "translation")):
            control.setChecked(self.store.preference(f"auto_start_{stage}", False))
            control.setToolTip("Resume this queue at the next successful handoff. Pause queue holds it until "
                               "you start it or re-enable this option. The app always opens paused.")
            control.toggled.connect(lambda checked, value=stage: self.controller.set_auto_start(value, checked))
            automation.addWidget(control)
        automation.addStretch()
        layout.addLayout(automation)
        shared = QHBoxLayout()
        self.settings_summary = label("", "muted")
        shared.addWidget(self.settings_summary, 1)
        shared.addWidget(button("Edit download settings", lambda: self.tabs.setCurrentWidget(self.download_settings_page)))
        self.enqueue_button = button("Add selected to queue", self.enqueue, True)
        self.enqueue_button.setEnabled(False)
        shared.addWidget(self.enqueue_button)
        layout.addLayout(shared)
        queue_header = QHBoxLayout()
        queue_header.addWidget(label("Queues", "section"))
        queue_header.addStretch()
        self.start_button = button("Start queue", lambda: self.controller.start(self.current_stage()), True)
        self.pause_button = button("Pause queue", lambda: self.controller.pause(self.current_stage()))
        self.pause_button.setToolTip("Pause this queue after its active job finishes.")
        self.cancel_button = button("Cancel selected", self.cancel_jobs)
        self.retry_button = button("Retry selected", self.retry_jobs)
        self.remove_button = button("Remove selected", self.remove_jobs)
        self.remove_button.setToolTip(
            "Stop active work and remove entries from the queue. Keep history and media files."
        )
        self.required_model_button = button("Download required model", self.download_required_model)
        for control in [
            self.start_button,
            self.pause_button,
            self.cancel_button,
            self.retry_button,
            self.remove_button,
        ]:
            queue_header.addWidget(control)
        self.queue_tools = button("More…", lambda: None)
        menu = QMenu(self.queue_tools)
        menu.addAction("Edit selected pending jobs…", self.bulk_edit_jobs)
        menu.addAction("Compare selected with shared settings…", self.compare_jobs)
        menu.addAction("Pause selected jobs", lambda: self.controller.pause_jobs(self.selected_job_ids()))
        menu.addAction("Resume selected jobs", lambda: self.controller.resume_jobs(self.selected_job_ids()))
        menu.addAction("Job timeline…", self.show_timeline)
        menu.addSeparator()
        menu.addAction("Queue schedules…", self.queue_schedules)
        menu.addAction("Background and completion…", self.queue_options)
        menu.addAction("Hide to tray", self.hide_to_tray)
        self.queue_tools.setMenu(menu)
        queue_header.addWidget(self.queue_tools)
        layout.addLayout(queue_header)
        caption_row = QHBoxLayout()
        caption_row.addWidget(self.required_model_button)
        self.caption_progress = label("", "muted")
        caption_row.addWidget(self.caption_progress, 1)
        layout.addLayout(caption_row)
        self.queue_tabs = QTabWidget()
        self.stage_queues = {}
        for stage, title in (("download", "Downloading"), ("caption", "Captioning"), ("translation", "Translating")):
            queue = table(["#", "Title", "Format", "Status", "Progress", "Speed", "ETA", "Settings"])
            empty = {
                "download": ("Ready for your next video", "Add videos above, then start this queue."),
                "caption": ("Give your videos a voice", "Caption jobs appear after downloads or Generate captions in History."),
                "translation": ("Take your captions further", "Enable translation in Download settings to add languages."),
            }
            queue.set_empty_message(*empty[stage])
            queue.setAccessibleName(f"Persistent {stage} queue")
            queue.enable_queue_drag()
            queue.reorder_requested.connect(lambda identifiers, before, stage=stage: self.reorder_jobs(identifiers, before, stage))
            queue.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            queue.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
            queue.setColumnWidth(4, 160)
            queue.setMinimumHeight(120)
            queue.itemSelectionChanged.connect(self.job_selected)
            queue.itemDoubleClicked.connect(self.show_job_details)
            self.stage_queues[stage] = queue
            self.queue_tabs.addTab(queue, title)
        self.queue = self.stage_queues["download"]
        self.caption_queue = self.stage_queues["caption"]
        self.translation_queue = self.stage_queues["translation"]
        self.queue_tabs.currentChanged.connect(self.queue_changed)
        layout.addWidget(self.queue_tabs, 1)
        self.queue_tabs.setToolTip("Start each queue or enable the automatic handoffs above. Captioning and translation share one inference slot.")
        return widget

    def _download_settings(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(label("Download settings", "section"))
        layout.addWidget(label("Shared settings apply to new queue entries. Use Item settings in Downloads for individual overrides.", "muted"))
        self.settings_panel = SettingsPanel(DownloadSettings.from_dict(self.store.preference("settings", {})))
        layout.addWidget(self.settings_panel, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Save defaults", self.save_defaults, True))
        actions.addWidget(label("Already queued items keep their saved settings.", "muted"), 1)
        layout.addLayout(actions)
        self.tabs.currentChanged.connect(self.update_settings_summary)
        return widget

    def save_defaults(self):
        try:
            self.store.set_preference("settings", self.settings_panel.settings().to_dict())
            self.update_settings_summary()
            self.show_notice("Download defaults saved.")
        except ValueError as exc:
            self.show_notice(str(exc))

    def update_settings_summary(self, *_, refresh_indicators=True):
        panel = self.settings_panel
        resolution = panel.height.currentText() if panel.format.currentData() in {"mp4", "webm"} else panel.bitrate.currentText()
        self.settings_summary.setText(f"{panel.format.currentData().upper()} · {resolution} · {panel.mode.currentText()}")
        if refresh_indicators:
            self.refresh_queue_settings()

    def shared_comparison_settings(self):
        try:
            return self.settings_panel.settings().to_dict()
        except ValueError:
            return None

    @staticmethod
    def queue_settings_indicator(settings, shared):
        from .queue_ui import differences, display

        if shared is None:
            return "—", "Complete the shared settings to compare this job's saved values."
        changes = differences(settings, shared)
        if not changes:
            return "Shared", "Matches the current shared settings. Queued jobs keep their saved values."
        return "Custom", "Differences from current shared settings (shared → job):\n" + "\n".join(
            f"{key.replace('_', ' ')}: {display(baseline)} → {display(value)}" for key, baseline, value in changes)

    def refresh_queue_settings(self):
        shared = self.shared_comparison_settings()
        for queue in self.stage_queues.values():
            for row in range(queue.rowCount()):
                identifier = queue.item(row, 0)
                cell = queue.item(row, 7)
                job = self.store.get(identifier.data(Qt.ItemDataRole.UserRole)) if identifier else None
                if job and cell:
                    text, detail = self.queue_settings_indicator(job["settings"], shared)
                    cell.setText(text)
                    cell.setToolTip(detail)

    def refresh_models(self):
        self.settings_panel.refresh_models(storage_folder(self.store), self.controller.model_workers,
                                           self.controller.model_states)

    def use_model(self, key):
        self.settings_panel.use_model(key)
        self.tabs.setCurrentWidget(self.download_settings_page)
        self.settings_panel.pages.setCurrentIndex(2 if model_spec(key).get("task") == "translation" else 1)
        self.update_settings_summary()
        self.show_notice(f"Selected {model_spec(key)['title']}. Save defaults or add a batch to remember it.")

    def _history(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(label("History", "section"))
        layout.addWidget(label("Completed, failed and cancelled jobs are retained across restarts.", "muted"))
        controls = QHBoxLayout()
        controls.addWidget(label("Sort by"))
        self.history_sort = QComboBox()
        for title, column, descending in (("Updated · newest first", 8, True), ("Updated · oldest first", 8, False),
                                           ("Added · newest first", 0, True), ("Added · oldest first", 0, False),
                                           ("Title · A–Z", 1, False), ("Title · Z–A", 1, True),
                                           ("Result · A–Z", 6, False), ("Format · A–Z", 2, False)):
            self.history_sort.addItem(title, [column, descending])
        self.history_sort.setAccessibleName("History sorting method")
        self.history_sort.setPlaceholderText("Column sorting")
        controls.addWidget(self.history_sort)
        controls.addStretch()
        self.clear_selected_button = button("Clear selected history", self.clear_selected_history)
        self.clear_cancelled_button = button("Clear cancelled history", self.clear_cancelled_history)
        for control in (self.clear_selected_button, self.clear_cancelled_button):
            control.setToolTip("Clear history records only. Saved media, subtitles and partial files are kept.")
            controls.addWidget(control)
        layout.addLayout(controls)
        self.history = table(["#", "Title", "Format", "Download", "Captions", "Translation", "Result", "Output / error", "Updated"])
        self.history.set_empty_message("Your library begins here", "Finished downloads and caption jobs will appear in History.")
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.history.setColumnWidth(0, 48)
        for column in (2, 3, 4, 5, 6):
            self.history.setColumnWidth(column, 95)
        self.history.setColumnWidth(8, 170)
        self.history.setSortingEnabled(True)
        self.history_sort.currentIndexChanged.connect(self.change_history_sort)
        self.history.horizontalHeader().sortIndicatorChanged.connect(self.history_sort_changed)
        self.history.itemSelectionChanged.connect(self.history_selected)
        self.history.itemDoubleClicked.connect(self.show_history_details)
        layout.addWidget(self.history)
        row = QHBoxLayout()
        row.addWidget(button("Open selected file", self.open_history_file))
        row.addWidget(button("Open its folder", self.open_history_folder))
        self.generate_captions_button = button("Generate captions", self.generate_history_captions)
        self.generate_captions_button.setToolTip("Queue captions for all selected history items using current local model settings.")
        row.addWidget(self.generate_captions_button)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Correct / re-export captions", self.edit_history_captions))
        row.addWidget(button("Translate / add languages", self.translate_history))
        row.addWidget(button("Retry / regenerate language", self.retry_language))
        row.addStretch()
        layout.addLayout(row)
        return widget

    def _preferences(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(label("Preferences", "section"))
        form = QFormLayout()
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setMaximumWidth(110)
        self.concurrency.setValue(self.controller.limit)
        self.concurrency.valueChanged.connect(self.set_concurrency)
        form.addRow("Concurrent downloads", self.concurrency)
        layout.addLayout(form)
        queue_options = button("Background, notifications and completion…", self.queue_options)
        layout.addWidget(queue_options)
        caption_actions = QHBoxLayout()
        caption_actions.addWidget(button("Import local media for captions…", self.import_local_media))
        caption_actions.addWidget(button("Import SRT/VTT…", self.import_subtitles))
        caption_actions.addStretch()
        layout.addLayout(caption_actions)
        layout.addWidget(
            label(
                "Save defaults on Download settings, or add a batch to remember them. The queue opens paused after restart.",
                "muted",
            )
        )
        layout.addWidget(label("Dependencies", "section"))
        self.dependencies = QPlainTextEdit()
        self.dependencies.setReadOnly(True)
        self.dependencies.setPlainText(
            "\n\n".join(f"{name}: {value}" for name, value in dependency_report().items())
        )
        layout.addWidget(self.dependencies)
        layout.addWidget(
            label(
                "Windows builds bundle FFmpeg, ffprobe, a JavaScript runtime, and the YouTube engine. "
                "Source installations can place these executables in vendor/ or on PATH.",
                "muted",
            )
        )
        row = QHBoxLayout()
        row.addWidget(button("Refresh dependencies", self.refresh_dependencies))
        self.check_update_button = button("Check engine update", self.check_update)
        self.install_update_button = button("Install verified update", self.install_update)
        self.install_update_button.setEnabled(False)
        row.addWidget(self.check_update_button)
        row.addWidget(self.install_update_button)
        row.addStretch()
        layout.addLayout(row)
        self.update_info = label(
            "Updates use official yt-dlp releases and verify SHA-256 before installation.", "muted"
        )
        layout.addWidget(self.update_info)
        layout.addStretch()
        layout.addWidget(label(f"VideoDock {__version__}", "muted"))
        return widget

    def show_notice(self, message: str):
        self.notice.setText(message[:1200])

    def _background_request(self, request: dict, handler):
        if self.background:
            self.show_notice("A preview or engine operation is already running.")
            return
        worker = WorkerProcess(request, self)
        self.background = worker
        self.saved_list_selected()
        worker.event.connect(handler)
        worker.ended.connect(lambda code: self._background_done(worker, code))
        self.preview_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        self.stop_preview.setEnabled(request["action"] in {"inspect", "detail"})
        self.check_update_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        worker.start()

    def _background_done(self, worker: WorkerProcess, code: int):
        self.background = None
        self.saved_list_selected()
        if worker.request["action"] == "update_install":
            self.controller.maintenance = False
            self.refresh_jobs()
        self.preview_button.setEnabled(True)
        self.detail_button.setEnabled(0 <= self.preview.currentRow() < len(self.items))
        self.stop_preview.setEnabled(False)
        self.check_update_button.setEnabled(True)
        self.install_update_button.setEnabled(self.release is not None)
        if code and worker.errors:
            self.show_notice(worker.errors)
        worker.deleteLater()
        self._close_when_idle()

    def cancel_background(self):
        if self.background:
            self.background.cancel()
            self.show_notice("Stopping preview…")

    def inspect(self):
        try:
            urls = parse_urls(self.urls.toPlainText())
        except ValueError as exc:
            self.show_notice(str(exc))
            return
        if self.background:
            return
        self.reset_preview()
        self.show_notice("Inspecting links and playlists…")
        self._background_request({"action": "inspect", "urls": urls}, self._preview_event)

    def reset_preview(self):
        self.items.clear()
        self.preview_errors.clear()
        self.preview_warnings.clear()
        self.overrides.clear()
        self.preview.setRowCount(0)
        self.preview_selected()
        self.update_preview_controls()
        self.range_playlist.clear()
        self.range_playlist.addItem("All playlists", "")

    def checked_preview_items(self):
        return [item for row, item in enumerate(self.items)
                if self.preview.item(row, 0).checkState() == Qt.CheckState.Checked]

    def refresh_saved_lists(self, selected_id=None):
        selected_id = selected_id or self.saved_lists.currentData() or self.store.preference("selected_saved_list", "")
        self.saved_lists.blockSignals(True)
        self.saved_lists.clear()
        self.saved_lists.addItem("Choose a saved list…", "")
        for saved in self.store.saved_lists():
            kind = "Favorite" if saved["kind"] == "favorite" else "Custom"
            # Limit the display length while retaining the full name in the tooltip/editor.
            self.saved_lists.addItem(f"{kind} · {saved['name'][:55]} ({saved['count']})", saved["id"])
            self.saved_lists.setItemData(self.saved_lists.count() - 1, saved["name"], Qt.ItemDataRole.ToolTipRole)
        self.saved_lists.setCurrentIndex(max(0, self.saved_lists.findData(selected_id)))
        self.saved_lists.blockSignals(False)
        self.saved_list_selected()

    def saved_list_selected(self, *_):
        selected = bool(self.saved_lists.currentData())
        identifier = self.saved_lists.currentData() or ""
        if self.store.preference("selected_saved_list", "") != identifier:
            self.store.set_preference("selected_saved_list", identifier)
        self.load_list_button.setEnabled(selected and self.background is None)
        self.edit_list_button.setEnabled(selected)
        self.add_to_list_button.setEnabled(selected and hasattr(self, "preview") and bool(self.checked_preview_items()))

    def save_preview_list(self):
        items = self.checked_preview_items()
        playlists = list(dict.fromkeys(item["playlist"] for item in items if item.get("playlist")))
        dialog = SaveListDialog(bool(items), playlists[0] if len(playlists) == 1 else "", self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                included = items if dialog.include_selected.isChecked() else []
                try:
                    sources = parse_urls(self.urls.toPlainText()) if included else []
                except ValueError:
                    sources = []
                identifier = self.store.create_saved_list(dialog.name.text(), dialog.kind.currentData(), sources, included)
                self.refresh_saved_lists(identifier)
                self.show_notice(f"Saved {len(self.store.saved_list(identifier)['items'])} entries. "
                                 "Preview any links and use Add selected to extend this list.")
            except ValueError as exc:
                self.show_notice(str(exc))
        dialog.deleteLater()

    def add_to_saved_list(self):
        identifier = self.saved_lists.currentData()
        if not identifier:
            self.show_notice("Choose a saved list first, or use Save as… to create one.")
            return
        try:
            added, skipped = self.store.add_saved_items(identifier, self.checked_preview_items())
            self.refresh_saved_lists(identifier)
            self.show_notice(f"Added {added} entries to the saved list; {skipped} already present. "
                             "Load list to preview the saved entries.")
        except ValueError as exc:
            self.show_notice(str(exc))

    def load_saved_list(self):
        if self.background:
            self.show_notice("Wait for the current preview or engine operation to finish before loading a list.")
            return
        saved = self.store.saved_list(self.saved_lists.currentData())
        if not saved:
            return
        self.reset_preview()
        self.urls.setPlainText("\n".join(item["url"] for item in saved["items"]))
        for item in saved["items"]:
            self._preview_event({"type": "item", "item": item})
        self.saved_lists_button.setChecked(False)
        self.preview_scroll.verticalScrollBar().setValue(0)
        self.show_notice(f"Loaded {len(saved['items'])} saved entries from {saved['name']}. "
                         "Current download settings apply. Inspect selected to refresh formats and caption languages.")

    def edit_saved_list(self):
        identifier = self.saved_lists.currentData()
        if not identifier or not self.store.saved_list(identifier):
            return
        dialog = SavedListEditor(self.store, identifier, self)
        dialog.changed.connect(self.refresh_saved_lists)
        dialog.exec()
        dialog.deleteLater()

    def _preview_event(self, event: dict):
        if event["type"] == "item":
            item = event["item"]
            if not item.get("url", "").startswith(("http://", "https://")):
                self.show_notice("An unavailable playlist entry was skipped.")
                return
            row = len(self.items)
            self.items.append(item)
            if item.get("playlist"):
                key = item.get("playlist_key") or item["playlist"]
                if self.range_playlist.findData(key) < 0:
                    self.range_playlist.addItem(item["playlist"], key)
            self.preview.insertRow(row)
            selected = QTableWidgetItem()
            selected.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            selected.setCheckState(Qt.CheckState.Checked)
            self.preview.setItem(row, 0, selected)
            for col, text in enumerate(
                [
                    str(item["index"] or row + 1),
                    item["title"],
                    duration_text(item["duration"]),
                    item["playlist"],
                ],
                1,
            ):
                self.preview.setItem(row, col, QTableWidgetItem(text))
            self.show_notice(f"{len(self.items)} videos found. Select entries to download.")
            self.update_preview_controls()
        elif event["type"] in {"error", "inspection_error"}:
            self.preview_errors.append(event["message"])
            self.show_notice(event["message"])
        elif event["type"] == "warning":
            self.preview_warnings.append(event["message"])
            self.show_notice(event["message"])
        elif event["type"] == "done":
            if self.preview_errors:
                self.show_notice(
                    f"{len(self.items)} videos found; {len(self.preview_errors)} links failed. "
                    + "\n".join(self.preview_errors)
                )
            elif self.preview_warnings:
                self.show_notice(f"{len(self.items)} videos found. " + "\n".join(self.preview_warnings))
            elif not self.items:
                self.show_notice("No downloadable videos found. Check the links or source availability.")

    def import_urls(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import links", "", "Text files (*.txt);;All files (*)")
        if path:
            try:
                self.urls.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError) as exc:
                self.show_notice(f"Cannot read the link file: {exc}")

    def select_all(self, checked: bool):
        for row in range(self.preview.rowCount()):
            self.preview.item(row, 0).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def update_preview_controls(self, item=None):
        if item is not None and item.column() != 0:
            return
        count = sum(self.preview.item(row, 0) is not None
                    and self.preview.item(row, 0).checkState() == Qt.CheckState.Checked
                    for row in range(self.preview.rowCount()))
        self.preview_count.setText(f"{count} selected")
        self.enqueue_button.setEnabled(count > 0)
        self.saved_list_selected()

    def interval_rows(self) -> list[int]:
        ranges = parse_intervals(self.intervals.text())
        playlist = self.range_playlist.currentData()
        matches = [
            row
            for row, item in enumerate(self.items)
            if item.get("playlist")
            and (not playlist or (item.get("playlist_key") or item["playlist"]) == playlist)
            and any(start <= item.get("index", 0) <= end for start, end in ranges)
        ]
        if not matches:
            raise ValueError("No loaded playlist entries match these positions. Preview the playlist first.")
        return matches

    def select_intervals(self):
        try:
            selected = set(self.interval_rows())
            playlist = self.range_playlist.currentData()
            for row, item in enumerate(self.items):
                if item.get("playlist") and (
                    not playlist or (item.get("playlist_key") or item["playlist"]) == playlist
                ):
                    self.preview.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if row in selected else Qt.CheckState.Unchecked
                    )
            self.show_notice(f"Selected {len(selected)} playlist entries in the requested ranges.")
        except ValueError as exc:
            self.show_notice(str(exc))

    def enqueue_intervals(self):
        try:
            self.enqueue(self.interval_rows())
        except ValueError as exc:
            self.show_notice(str(exc))

    def preview_selected(self):
        row = self.preview.currentRow()
        has_item = 0 <= row < len(self.items)
        self.detail_button.setEnabled(has_item and self.background is None)
        self.override_button.setEnabled(has_item)
        if row < 0 or row >= len(self.items):
            self.thumbnail_generation += 1
            self.thumbnail.clear()
            self.thumbnail.setText("VIDEO")
            self.preview_description.setText("Preview titles, choose playlist entries, then add them to the queue.")
            self.preview_description.setToolTip("")
            if hasattr(self, "settings_panel"):
                self.settings_panel.set_details(None)
            return
        item = self.items[row]
        self.preview_description.setText(
            f"{item['title']}\n{item.get('uploader') or item.get('playlist') or ''}"
        )
        self.preview_description.setToolTip(self.preview_description.text())
        self.settings_panel.set_details(item)
        self.thumbnail_generation += 1
        generation = self.thumbnail_generation
        self.thumbnail.clear()
        self.thumbnail.setText("VIDEO")
        url = item.get("thumbnail", "")
        if url.startswith(("http://", "https://")):
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(15000)
            reply = self.network.get(request)

            def finish():
                if generation == self.thumbnail_generation:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(bytes(reply.readAll())):
                        self.thumbnail.setPixmap(
                            pixmap.scaled(
                                self.thumbnail.size(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                reply.deleteLater()

            reply.finished.connect(finish)

    def inspect_selected(self):
        row = self.preview.currentRow()
        if row < 0:
            self.show_notice("Select a preview row to inspect available formats and captions.")
            return
        self.show_notice("Inspecting the selected video…")

        def handler(event: dict):
            if event["type"] == "detail":
                item = event["item"]
                item.update(
                    playlist=self.items[row]["playlist"],
                    index=self.items[row]["index"],
                    playlist_key=self.items[row].get("playlist_key", ""),
                )
                self.items[row] = item
                self.preview.item(row, 2).setText(item["title"])
                self.preview.item(row, 3).setText(duration_text(item["duration"]))
                self.preview_selected()
                self.show_notice("Formats and caption languages loaded for the selected video.")
            elif event["type"] == "error":
                self.show_notice(event["message"])

        self._background_request({"action": "detail", "url": self.items[row]["url"]}, handler)

    def override_selected(self):
        row = self.preview.currentRow()
        if row < 0:
            self.show_notice("Select a preview row to change its download settings.")
            return
        try:
            settings = self.overrides.get(row) or self.settings_panel.settings()
        except ValueError as exc:
            self.show_notice(str(exc))
            return
        dialog = OverrideDialog(settings, self.items[row], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.overrides[row] = dialog.panel.settings()
        dialog.deleteLater()

    def preview_settings_menu(self, position):
        menu = QMenu(self.preview)
        menu.addAction("Compare item settings with shared…", self.compare_preview)
        menu.exec(self.preview.viewport().mapToGlobal(position))

    def compare_preview(self):
        from .queue_ui import ComparisonDialog
        try:
            shared = self.settings_panel.settings().to_dict()
            rows = [index.row() for index in self.preview.selectionModel().selectedRows()]
            if not rows:
                rows = list(range(len(self.items)))
            entries = [(self.items[row]["title"], self.overrides[row].to_dict() if row in self.overrides else shared)
                       for row in rows]
            ComparisonDialog(entries, shared, self).exec()
        except ValueError as exc:
            self.show_notice(str(exc))

    def bulk_edit_jobs(self):
        from .queue_ui import BulkSettingsDialog
        jobs = [self.store.get(identifier) for identifier in self.selected_job_ids()]
        if not jobs or any(not job or job["status"] not in PENDING or job["removed"]
                           or job["id"] in self.controller.worker_ids() for job in jobs):
            self.show_notice("Select pending jobs without active workers to edit their settings.")
            return
        try:
            BulkSettingsDialog(jobs, self.settings_panel.settings().to_dict(), self).exec()
        except ValueError as exc:
            self.show_notice(str(exc))

    def compare_jobs(self):
        from .queue_ui import ComparisonDialog
        jobs = [self.store.get(identifier) for identifier in self.selected_job_ids()]
        if not jobs:
            self.show_notice("Select queue entries to compare their saved settings.")
            return
        try:
            ComparisonDialog([(job["title"], job["settings"]) for job in jobs if job],
                             self.settings_panel.settings().to_dict(), self).exec()
        except ValueError as exc:
            self.show_notice(str(exc))

    def reorder_jobs(self, identifiers, before, stage):
        try:
            self.store.reorder(identifiers, before, stage=stage, exclude=self.controller.worker_ids())
        except ValueError as exc:
            self.show_notice(str(exc))
        self.refresh_jobs()

    def queue_schedules(self):
        from .queue_ui import ScheduleDialog
        ScheduleDialog(self.store, self).exec()

    def queue_options(self):
        from .queue_ui import QueueOptionsDialog
        QueueOptionsDialog(self).exec()

    def hide_to_tray(self):
        if self.desktop.available:
            self.hide()
        else:
            self.show_notice("A system tray is unavailable. Keep VideoDock open for background work.")

    def show_timeline(self):
        identifiers = self.selected_job_ids()
        if identifiers:
            self.timeline_dialog(identifiers[0])
        else:
            self.show_notice("Select a job to view its timeline.")

    def timeline_dialog(self, identifier):
        job = self.store.get(identifier)
        if not job:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Job timeline — " + job["title"])
        dialog.resize(900, 580)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        details = (f"Status: {job['status']} · Stage: {job['stage']} · Download attempts: {job['attempts']}\n"
                   f"Download: {job['download_status']} · Captions: {job['caption_status']} · Translation: {job['translation_status']}\n"
                   f"Source: {job['url']}\nFolder: {job['destination']}\nOutput: {job['output']}\n"
                   f"Subtitles: {', '.join(job['caption_paths'])}\nLanguage: {job['caption_language_result']}\n"
                   f"Processed: {duration_text(job['processed_duration'])}\n{job['caption_preview']}\n{job['error']}\n\n")
        text.setPlainText(details + ("\n\n".join(f"{event['at']} · {event['stage']} · {event['kind']}\n{event['detail']}"
                                              for event in self.store.timeline(identifier)) or "No recorded events for this older job."))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def browse_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose destination", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def enqueue(self, selected=None):
        if selected is None or isinstance(selected, bool):
            selected = [
                index
                for index in range(len(self.items))
                if self.preview.item(index, 0).checkState() == Qt.CheckState.Checked
            ]
        if not selected:
            self.show_notice("Select at least one preview entry.")
            return
        try:
            settings = self.settings_panel.settings()
            destination = self.destination.text().strip()
            if not destination:
                raise ValueError("Choose a destination folder.")
            check_destination(Path(destination).expanduser().resolve())
            added, skipped = self.store.enqueue(
                [self.items[index] for index in selected],
                settings,
                destination,
                {
                    position: self.overrides[index]
                    for position, index in enumerate(selected)
                    if index in self.overrides
                },
                self.playlist_folders.isChecked(),
                self.duplicates.isChecked(),
            )
            self.store.set_preference("settings", settings.to_dict())
            self.store.set_preference("playlist_folders", self.playlist_folders.isChecked())
            if self.remember_destination.isChecked():
                self.store.set_preference("destination", str(Path(destination).expanduser().resolve()))
            self.show_notice(
                f"Added {added} jobs. Skipped {skipped} duplicates. "
                + ("Queue is running." if self.controller.running else "Click Start queue to download.")
            )
            self.refresh_jobs()
            self.controller.pump()
        except (OSError, ValueError) as exc:
            self.show_notice(str(exc))

    def selected_job_ids(self) -> list[str]:
        queue = self.queue_tabs.currentWidget()
        return [
            queue.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in queue.selectionModel().selectedRows()
        ]

    def current_stage(self):
        return tuple(self.stage_queues)[self.queue_tabs.currentIndex()]

    def queue_changed(self, *_):
        self.refresh_jobs()

    def show_queue(self, stage):
        self.tabs.setCurrentIndex(0)
        self.queue_tabs.setCurrentWidget(self.stage_queues[stage])

    def open_destination(self):
        path = Path(self.destination.text().strip()).expanduser().resolve()
        if not self.destination.text().strip() or not path.is_dir():
            self.show_notice("Choose an existing Save to folder before opening it.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_notice("Windows could not open the Save to folder.")

    def selected_history_ids(self):
        return [self.history.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.history.selectionModel().selectedRows()]

    def history_selected(self):
        owned = set(self.controller.active) | {self.controller.caption_id}
        self.clear_selected_button.setEnabled(any(identifier not in owned for identifier in self.selected_history_ids()))

    def clear_selected_history(self):
        count = self.store.clear_history(self.selected_history_ids(), exclude=(*self.controller.active, self.controller.caption_id))
        self.refresh_jobs()
        self.show_notice(f"Cleared {count} selected history records. Saved files are retained.")

    def clear_cancelled_history(self):
        count = self.store.clear_history(cancelled_only=True, exclude=(*self.controller.active, self.controller.caption_id))
        self.refresh_jobs()
        self.show_notice(f"Cleared {count} cancelled history records. Saved files are retained.")

    def change_history_sort(self, *_):
        value = self.history_sort.currentData()
        if value is not None:
            self.store.set_preference("history_sort", value)
            self.refresh_jobs()

    def history_sort_changed(self, column, order):
        value = [column, order == Qt.SortOrder.DescendingOrder]
        self.store.set_preference("history_sort", value)
        self.history_sort.blockSignals(True)
        self.history_sort.setCurrentIndex(self.history_sort.findData(value))
        self.history_sort.blockSignals(False)

    def refresh_jobs(self):
        self.refresh_models()
        self.update_settings_summary(refresh_indicators=False)
        jobs = self.store.jobs()
        shared = self.shared_comparison_settings()
        for index, (stage, queue) in enumerate(self.stage_queues.items()):
            selected = {queue.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
                        for item in queue.selectionModel().selectedRows()}
            pending = [job for job in jobs if job["stage"] == stage
                       and job["status"] not in {"completed", "partial"} and not job["removed"]]
            queue.blockSignals(True)
            queue.clearSelection()
            queue.setRowCount(len(pending))
            for row, job in enumerate(pending):
                settings_text, settings_detail = self.queue_settings_indicator(job["settings"], shared)
                values = [str(job["sequence"]), job["title"], job["settings"]["format"].upper(),
                          ("Pausing" if job["held"] and job["status"] == "cancelling" else
                           job[self.store.stage_status_field(stage)] or job["status"]).replace("_", " ").capitalize(), "",
                          f"{job['speed'] / 1024**2:.1f} MB/s" if stage == "download" and job.get("speed") else "—",
                          duration_text(job.get("eta")) if stage == "download" else "—", settings_text]
                for col, value in enumerate(values):
                    if col == 4:
                        bar = queue.cellWidget(row, col)
                        if not isinstance(bar, QProgressBar):
                            bar = QProgressBar()
                            queue.setCellWidget(row, col, bar)
                        bar.setValue(int(job["progress"]))
                        continue
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, job["id"])
                    if col == 3:
                        item.setForeground(status_color(job[self.store.stage_status_field(stage)] or job["status"]))
                    item.setToolTip((f"Retry {job['retry_count']} at {job['retry_at']}\n" if job["retry_at"] else "") + (job["error"] or (f"Processed {duration_text(job['processed_duration'])}\n{job['caption_preview']}"
                                                     if job["caption_preview"] else job["destination"]))
                                    )
                    if col == 7:
                        item.setToolTip(settings_detail)
                    queue.setItem(row, col, item)
                if job["id"] in selected:
                    queue.selectionModel().select(queue.model().index(row, 0),
                                                  QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            queue.blockSignals(False)
            self.queue_tabs.setTabText(index, f"{('Downloading', 'Captioning', 'Translating')[index]} ({len(pending)})")
        history_selected = set(self.selected_history_ids())
        current = self._history_job()
        current_id = current["id"] if current else None
        self.history.blockSignals(True)
        self.history.setSortingEnabled(False)
        self.history.clearContents()
        history = [
            job for job in reversed(jobs) if job["status"] in {"completed", "partial", "failed", "cancelled"}
        ]
        self.history.setRowCount(len(history))
        for row, job in enumerate(history):
            for col, value in enumerate(
                [
                    job["sequence"],
                    job["title"],
                    job["settings"]["format"].upper(),
                    job["download_status"].replace("_", " ").capitalize() or "—",
                    job["caption_status"].replace("_", " ").capitalize() or "—",
                    job["translation_status"].replace("_", " ").capitalize() or "—",
                    job["status"].capitalize(),
                    job["error"] or job["output"],
                    job["updated"][:19].replace("T", " ") + " UTC",
                ]
            ):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                item.setData(Qt.ItemDataRole.UserRole, job["id"])
                if col in (3, 4, 5, 6):
                    item.setForeground(status_color(job[{3: "download_status", 4: "caption_status",
                                                         5: "translation_status", 6: "status"}[col]]))
                item.setToolTip(f"{job['output']}\n{job['error']}" if col == 7 else str(value))
                self.history.setItem(row, col, item)
            if job["id"] == current_id:
                self.history.setCurrentCell(row, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            if job["id"] in history_selected:
                for col in range(self.history.columnCount()):
                    self.history.item(row, col).setSelected(True)
        column, descending = self.store.preference("history_sort", [8, True])
        if not isinstance(column, int) or not 0 <= column < self.history.columnCount():
            column = 8
        self.history.sortItems(column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        self.history.setSortingEnabled(True)
        self.history.blockSignals(False)
        self.history_sort.blockSignals(True)
        self.history_sort.setCurrentIndex(self.history_sort.findData([column, descending]))
        self.history_sort.blockSignals(False)
        self.history_selected()
        self.clear_cancelled_button.setEnabled(any(job["status"] == "cancelled" and job["id"] != self.controller.caption_id for job in jobs))
        active = len(self.controller.active) + bool(self.controller.caption_id)
        queued = sum(job["status"] in PENDING and not job["removed"] for job in jobs)
        complete = sum(job["status"] == "completed" for job in jobs)
        caption_job = self.store.get(self.controller.caption_id) if self.controller.caption_id else None
        self.required_model_button.setVisible(
            any(job["status"] == "waiting_model" and not job["removed"] for job in jobs)
        )
        self.caption_progress.setVisible(bool(caption_job))
        self.caption_progress.setText(
            f"{caption_job['stage'].capitalize()} · {caption_job['title']} · processed {duration_text(caption_job['processed_duration'])}\n"
            f"{caption_job['caption_preview']}"
            if caption_job
            else ""
        )
        self.summary.setText(f"{active} active · {queued} queued · {complete} completed")
        self.start_button.setEnabled(not self.controller.stage_running(self.current_stage()) and not self.controller.maintenance)
        self.pause_button.setEnabled(self.controller.stage_running(self.current_stage()))
        self.job_selected()

    def job_selected(self):
        jobs = [self.store.get(job_id) for job_id in self.selected_job_ids()]
        self.cancel_button.setEnabled(
            any(job and job["status"] in ACTIVE | PENDING for job in jobs)
        )
        self.retry_button.setEnabled(
            any(job and job["status"] in {"partial", "failed", "cancelled"} for job in jobs)
        )
        self.remove_button.setEnabled(bool(jobs))
        self.required_model_button.setEnabled(any(job and job["status"] == "waiting_model" for job in jobs))
        if len(jobs) == 1 and jobs[0] and jobs[0]["error"]:
            self.show_notice(jobs[0]["error"])

    def cancel_jobs(self):
        self.controller.cancel(self.selected_job_ids())

    def remove_jobs(self):
        self.controller.remove(self.selected_job_ids())
        self.show_notice("Removed selected entries from the queue. History and saved files are retained.")

    def download_required_model(self):
        for identifier in self.selected_job_ids():
            job = self.store.get(identifier)
            if job and job["status"] == "waiting_model":
                self.controller.start_model_download(
                    job.get("waiting_model_id") or job["settings"]["caption_model"]
                )

    def import_subtitles(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import subtitles", "", "Subtitles (*.srt *.vtt)")
        if not files:
            return
        try:
            from dataclasses import replace

            settings = self.settings_panel.settings()
            if settings.translation_source_language == "auto":
                raise ValueError("Set Source language override before importing subtitles.")
            destination = self.destination.text().strip()
            if not destination:
                raise ValueError("Choose a destination in Downloads first.")
            check_destination(Path(destination).resolve())
            settings = replace(settings, caption_mode="sidecar")
            self.store.queue_subtitles(files, settings, destination)
            self.show_queue("translation" if settings.translate else "caption")
            self.refresh_jobs()
            self.controller.pump()
            self.show_notice("Subtitle jobs added. Click Start queue to process them.")
        except (ValueError, OSError) as exc:
            self.show_notice(str(exc))

    def translate_history(self):
        job = self._history_job()
        if not job:
            self.show_notice("Select a history item with saved subtitles.")
            return
        try:
            from dataclasses import replace

            settings = self.settings_panel.settings()
            self.store.queue_translation(
                job,
                replace(
                    settings,
                    caption_mode=("sidecar" if settings.caption_mode == "none" else settings.caption_mode),
                ),
            )
            self.show_queue("translation")
            self.refresh_jobs()
            self.controller.pump()
            self.show_notice("Translation queued from saved source subtitles. Click Start queue.")
        except (ValueError, OSError) as exc:
            self.show_notice(str(exc))

    def retry_language(self):
        from PySide6.QtWidgets import QInputDialog

        job = self._history_job()
        if not job or not job["settings"].get("target_languages"):
            self.show_notice("Select a history item with translation targets.")
            return
        language, ok = QInputDialog.getItem(
            self, "Retry language", "Language", job["settings"]["target_languages"], 0, False
        )
        if ok:
            try:
                choice, selected = QInputDialog.getItem(
                    self,
                    "Manual translations",
                    "Regeneration",
                    ["Keep manual edits", "Regenerate manual edits too"],
                    0,
                    False,
                )
                if not selected:
                    return
                overwrite = choice == "Regenerate manual edits too"
                self.store.retry_language(job["id"], language, overwrite_manual=overwrite)
                self.show_queue("translation")
                self.refresh_jobs()
                self.controller.pump()
                self.show_notice("Language queued for regeneration.")
            except (ValueError, OSError) as exc:
                self.show_notice(str(exc))

    def import_local_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import audio/video for captions",
            "",
            "Media (*.mp4 *.webm *.mkv *.mov *.mp3 *.m4a *.wav *.flac *.ogg);;All files (*)",
        )
        if files:
            try:
                settings = self.settings_panel.settings()
                destination = self.destination.text().strip()
                if not destination:
                    raise ValueError("Choose a destination in Downloads first.")
                check_destination(Path(destination).resolve())
                count = self.store.queue_captions(files, settings, destination)
                self.show_queue("caption")
                self.show_notice(f"Added {count} local caption jobs. Click Start queue to process them.")
                self.refresh_jobs()
                self.controller.pump()
            except (ValueError, OSError) as exc:
                self.show_notice(str(exc))

    def generate_history_captions(self):
        selected = self.selected_history_ids()
        if not selected:
            self.show_notice("Select one or more history items with saved media to generate captions.")
            return
        try:
            from dataclasses import replace

            settings = self.settings_panel.settings()
        except ValueError as exc:
            self.show_notice(str(exc))
            return
        added, skipped = 0, []
        owned = set(self.controller.active) | {self.controller.caption_id}
        for identifier in selected:
            job = self.store.get(identifier)
            if not job:
                skipped.append("A selected history item no longer exists")
                continue
            try:
                if identifier in owned:
                    raise ValueError("The job is still finishing; try again when it is idle")
                actual = next((Path(job[field]) for field in ("media_path", "output")
                               if job[field] and Path(job[field]).is_file()), None)
                if actual is None:
                    raise ValueError("Saved media is missing")
                current = settings
                if actual.suffix.lower() in {".mp3", ".m4a"}:
                    current = replace(settings, format=actual.suffix[1:], caption_mode="sidecar")
                added += self.store.queue_captions([str(actual)], current, job["destination"])
            except (ValueError, OSError) as exc:
                skipped.append(f"#{job['sequence']}: {exc}")
        if added:
            self.show_queue("caption")
            self.refresh_jobs()
            self.controller.pump()
        message = f"Added {added} caption jobs from {len(selected)} selected history items."
        if added and not self.controller.stage_running("caption"):
            message += " Click Start queue in Captioning to process them."
        if skipped:
            message += f" Skipped {len(skipped)}: " + "; ".join(skipped) + "."
        self.show_notice(message)

    def edit_history_captions(self):
        job = self._history_job()
        if not job or not job["cues_path"] or not Path(job["cues_path"]).is_file():
            self.show_notice("Select a completed job with local captions to correct text and timing.")
            return
        if job["id"] == self.controller.caption_id:
            return
        try:
            dialog = CaptionEditor(job, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.controller.reexport(job, dialog.cues())
            dialog.deleteLater()
        except (ValueError, OSError) as exc:
            self.show_notice(str(exc))

    def retry_jobs(self):
        for job_id in self.selected_job_ids():
            self.store.retry(job_id)
        self.refresh_jobs()
        self.controller.pump()

    def set_concurrency(self, value: int):
        self.controller.limit = value
        self.store.set_preference("concurrency", value)
        self.controller.pump()

    def _history_job(self) -> dict | None:
        row = self.history.currentRow()
        return self.store.get(self.history.item(row, 0).data(Qt.ItemDataRole.UserRole)) if row >= 0 else None

    def open_history_file(self):
        job = self._history_job()
        if job and job["output"] and Path(job["output"]).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(job["output"]))
        else:
            self.show_notice("Select a completed job with an existing output file.")

    def open_history_folder(self):
        job = self._history_job()
        if job:
            QDesktopServices.openUrl(QUrl.fromLocalFile(job["destination"]))

    def show_job_details(self, *_):
        selected = self.selected_job_ids()
        if selected:
            self._job_details(self.store.get(selected[0]))

    def show_history_details(self, *_):
        self._job_details(self._history_job())

    def _job_details(self, job: dict | None):
        if job:
            self.timeline_dialog(job["id"])

    def refresh_dependencies(self):
        self.dependencies.setPlainText(
            "\n\n".join(f"{key}: {value}" for key, value in dependency_report().items())
        )

    def check_update(self):
        self.update_info.setText("Checking the official release…")
        self._background_request({"action": "update_check"}, self._update_event)

    def install_update(self):
        if self.controller.active:
            self.show_notice("Pause the queue and wait for active jobs to finish before updating the engine.")
            return
        if self.release:
            self.controller.pause()
            self.controller.maintenance = True
            self.refresh_jobs()
            self.update_info.setText("Downloading and verifying the engine…")
            self._background_request(
                {"action": "update_install", "release": self.release}, self._update_event
            )

    def _update_event(self, event: dict):
        if event["type"] == "update_available":
            self.release = event["release"]
            self.update_info.setText(
                f"Installed: {self.release['current']} · Latest: {self.release['version']}. "
                "Click Install verified update to install this release."
            )
        elif event["type"] == "update_installed":
            self.update_info.setText("Verified engine installed. New jobs will use it.")
            self.release = None
            self.refresh_dependencies()
        elif event["type"] == "error":
            self.update_info.setText(event["message"])

    def closeEvent(self, event):
        if (hasattr(self, "desktop") and not self.desktop.exiting and not self.closing
                and self.desktop.available and self.store.preference("close_to_tray", False)):
            event.ignore()
            self.hide()
            return
        if self.controller.busy or self.background:
            event.ignore()
            self.closing = True
            self.setEnabled(False)
            self.show_notice("Stopping workers and preserving partial downloads…")
            self.controller.shutdown()
            if self.background:
                self.background.cancel()
            QTimer.singleShot(100, self._close_when_idle)
        else:
            self.controller.pause()
            if hasattr(self, "desktop"):
                self.desktop.arm("none")
                self.desktop.tray.hide()
            event.accept()

    def _close_when_idle(self):
        if self.closing and not self.controller.busy and not self.background:
            self.close()
