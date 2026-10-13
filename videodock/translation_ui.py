from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .caption_models import task_models
from .languages import language_name, supported_targets
from .model_ui import refresh_download, refresh_selector


class TranslationPanel(QWidget):
    download_model = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_root = None
        self.model_workers = {}
        self.model_states = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        heading = QLabel("Translation & languages")
        heading.setObjectName("section")
        layout.addWidget(heading)
        self.enabled = QCheckBox("Translate subtitles")
        layout.addWidget(self.enabled)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(12)
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(16)
        self.source.addItem("auto")
        for tag in supported_targets():
            self.source.addItem(tag)
        self.source.setToolTip(
            "Actual language is detected by Whisper or read from the source track. Imported text needs an override."
        )
        form.addRow("Source language override", self.source)
        self.import_path = QLineEdit()
        self.import_path.setPlaceholderText("SRT/VTT source file")
        imported = QHBoxLayout()
        imported.addWidget(self.import_path, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        imported.addWidget(browse)
        form.addRow("Imported subtitles", imported)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search target languages…")
        form.addRow("Target languages", self.search)
        self.targets = QListWidget()
        self.targets.setMaximumHeight(165)
        ordered = sorted(
            supported_targets(),
            key=lambda tag: (tag not in {"en", "ja", "zh-Hans", "zh-Hant"}, language_name(tag)),
        )
        for tag in ordered:
            name = language_name(tag)
            if name == tag:
                locale = QLocale(tag)
                if locale.language() != QLocale.Language.C:
                    name = QLocale.languageToString(locale.language())
            item = QListWidgetItem(f"{name} · {tag}")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        form.addRow("", self.targets)
        self.model = QComboBox()
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(16)
        for spec in task_models("translation", usable_only=True):
            self.model.addItem(spec["title"], spec["id"])
        form.addRow("Translation model", self.model)
        self.model_status = QLabel("Download once; translation then runs offline.")
        self.model_status.setObjectName("modelStatus")
        self.model_status.setWordWrap(True)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_status, 1)
        self.download_button = QPushButton("Download translation model")
        self.download_button.clicked.connect(lambda: self.download_model.emit(self.model.currentData()))
        model_row.addWidget(self.download_button)
        form.addRow("", model_row)
        self.keep = QCheckBox("Keep original subtitles")
        self.keep.setChecked(True)
        form.addRow("", self.keep)
        self.bilingual = QComboBox()
        self.bilingual.addItem("Off", "")
        self.order = QComboBox()
        self.order.addItem("Original first", "source_first")
        self.order.addItem("Translation first", "translation_first")
        form.addRow("Bilingual translation", self.bilingual)
        form.addRow("Bilingual order", self.order)
        self.track_order = QLineEdit()
        self.track_order.setPlaceholderText("e.g. en, zh-Hant, ja")
        form.addRow("Embedded track order", self.track_order)
        self.default = QLineEdit()
        self.default.setPlaceholderText("Blank: first embedded track")
        form.addRow("Default track language", self.default)
        layout.addLayout(form)
        note = QLabel("Chinese translations use the selected script. Choose the inference device under Captions. Review translations before sharing.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.style_panel = QWidget()
        style_layout = QVBoxLayout(self.style_panel)
        style_layout.setContentsMargins(18, 18, 18, 18)
        heading = QLabel("Burned subtitle appearance")
        heading.setObjectName("section")
        style_layout.addWidget(heading)
        note = QLabel("Choose Burn into video under Captions to apply this style. The preview illustrates text placement.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        style_layout.addWidget(note)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(12)
        self.burn = QComboBox()
        self.burn.addItem("First exported language", "")
        self.burn.addItem("Original", "source")
        self.burn.addItem("Bilingual pair", "bilingual")
        form.addRow("Burn language", self.burn)
        self.font = QFontComboBox()
        self.font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font.setMinimumContentsLength(14)
        self.size = QSpinBox()
        self.size.setRange(10, 96)
        self.color = QLineEdit("#FFFFFF")
        self.position = QComboBox()
        for pos in ("bottom", "middle", "top"):
            self.position.addItem(pos.capitalize(), pos)
        form.addRow("Burn font", self.font)
        form.addRow("Burn size", self.size)
        form.addRow("Burn color", self.color)
        form.addRow("Burn position", self.position)
        self.preview = QLabel("English subtitle\n繁體中文字幕 · 简体中文字幕\nالعربية")
        self.preview.setMinimumHeight(140)
        self.preview.setWordWrap(True)
        form.addRow("Style preview", self.preview)
        style_layout.addLayout(form)
        style_layout.addStretch()
        self.search.textChanged.connect(self.filter)
        self.targets.itemChanged.connect(self.languages_changed)
        self.font.currentFontChanged.connect(self.style_preview)
        self.size.valueChanged.connect(self.style_preview)
        self.color.textChanged.connect(self.style_preview)
        self.position.currentIndexChanged.connect(self.style_preview)
        self.enabled.toggled.connect(self.enable_translation)
        self.model.currentIndexChanged.connect(lambda: self.refresh_model())

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose subtitle source", "", "Subtitles (*.srt *.vtt)")
        if path:
            self.import_path.setText(path)

    def filter(self, text):
        for index in range(self.targets.count()):
            item = self.targets.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def selected(self):
        return tuple(
            self.targets.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.targets.count())
            if self.targets.item(i).checkState() == Qt.CheckState.Checked
        )

    def languages_changed(self):
        targets = self.selected()
        bilingual, burn = self.bilingual.currentData(), self.burn.currentData()
        self.bilingual.clear()
        self.bilingual.addItem("Off", "")
        while self.burn.count() > 3:
            self.burn.removeItem(3)
        for tag in targets:
            self.bilingual.addItem(language_name(tag), tag)
            self.burn.addItem(language_name(tag), tag)
        self.bilingual.setCurrentIndex(max(0, self.bilingual.findData(bilingual)))
        self.burn.setCurrentIndex(max(0, self.burn.findData(burn)))

    def enable_translation(self):
        for widget in (
            self.search,
            self.targets,
            self.model,
            self.keep,
            self.bilingual,
            self.order,
        ):
            widget.setEnabled(self.enabled.isChecked())

    def set_caption_mode(self, mode, source):
        captions = mode != "none" and source != "off"
        for widget in (self.track_order, self.default):
            widget.setEnabled(captions and mode == "embed")
        self.style_panel.setEnabled(captions and mode == "burn")
        self.import_path.setEnabled(source == "import")

    def style_preview(self):
        font = self.font.currentFont()
        font.setPointSize(min(self.size.value(), 28))
        self.preview.setFont(font)
        self.preview.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
            | {
                "top": Qt.AlignmentFlag.AlignTop,
                "middle": Qt.AlignmentFlag.AlignVCenter,
                "bottom": Qt.AlignmentFlag.AlignBottom,
            }[self.position.currentData() or "bottom"]
        )
        import re

        color = self.color.text() if re.fullmatch(r"#[0-9A-Fa-f]{6}", self.color.text()) else "#FFFFFF"
        self.preview.setStyleSheet(f"background: #202020; color: {color}; padding: 8px;")

    def load(self, settings):
        from PySide6.QtGui import QFont

        self.enabled.setChecked(settings.translate)
        self.model.setCurrentIndex(max(0, self.model.findData(settings.translation_model)))
        self.source.setCurrentText(settings.translation_source_language)
        self.import_path.setText(settings.subtitle_import)
        self.targets.blockSignals(True)
        for index in range(self.targets.count()):
            item = self.targets.item(index)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in settings.target_languages
                else Qt.CheckState.Unchecked
            )
        self.targets.blockSignals(False)
        self.languages_changed()
        self.keep.setChecked(settings.keep_original)
        self.bilingual.setCurrentIndex(max(0, self.bilingual.findData(settings.bilingual_language)))
        self.order.setCurrentIndex(self.order.findData(settings.bilingual_order))
        self.track_order.setText(", ".join(settings.track_order))
        self.default.setText(settings.default_language)
        self.burn.setCurrentIndex(max(0, self.burn.findData(settings.burn_language)))
        self.font.setCurrentFont(QFont(settings.burn_font))
        self.size.setValue(settings.burn_size)
        self.color.setText(settings.burn_color)
        self.position.setCurrentIndex(self.position.findData(settings.burn_position))
        self.style_preview()
        self.enable_translation()
        self.refresh_model()

    def settings(self):
        return dict(
            translate=self.enabled.isChecked(),
            translation_source_language=self.source.currentText().strip(),
            subtitle_import=self.import_path.text().strip(),
            target_languages=self.selected(),
            translation_model=self.model.currentData(),
            keep_original=self.keep.isChecked(),
            bilingual_language=self.bilingual.currentData() if self.enabled.isChecked() else "",
            bilingual_order=self.order.currentData(),
            track_order=tuple(tag.strip() for tag in self.track_order.text().split(",") if tag.strip()),
            default_language=self.default.text().strip(),
            burn_language=self.burn.currentData(),
            burn_font=self.font.currentFont().family(),
            burn_size=self.size.value(),
            burn_color=self.color.text().strip(),
            burn_position=self.position.currentData(),
        )

    def refresh_model(self, root=None, workers=None, states=None):
        if root is not None:
            self.model_root = root
            self.model_workers = workers if workers is not None else {}
            self.model_states = states if states is not None else {}
        if self.model_root is not None:
            refresh_selector(self.model, self.model_root, self.model_workers, self.model_states)
            refresh_download(self.model, self.model_status, self.download_button,
                             self.model_root, self.model_workers, self.model_states)
            if self.download_button.isEnabled():
                self.download_button.setText("Download translation model" if
                                            self.model_status.text().startswith("Not downloaded") else
                                            "Resume translation download")
