"""Queue editing, comparison, scheduling and completion preferences."""

from datetime import UTC, datetime

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .models import DownloadSettings


def plain_label(text):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result


def display(value):
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) or "—"
    return str(value) if value != "" else "—"


def differences(item, shared):
    current = DownloadSettings.from_dict(item).to_dict()
    baseline = DownloadSettings.from_dict(shared).to_dict()
    return [(key, baseline[key], value) for key, value in current.items()
            if not key.endswith("revision") and value != baseline[key]]


class ComparisonDialog(QDialog):
    def __init__(self, entries, shared, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Item settings compared with current shared settings")
        self.resize(920, 570)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Each row shows a saved item value that differs from the current shared settings. Shared changes do not alter queued items."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Item", "Setting", "Shared value", "Item value"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for title, settings in entries:
            rows = differences(settings, shared) or [("Matches shared settings", "", "")]
            for key, baseline, value in rows:
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, text in enumerate((title, key.replace("_", " "), display(baseline), display(value))):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(text)
                    self.table.setItem(row, column, cell)
        for column, width in enumerate((200, 210, 210, 280)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BulkSettingsDialog(QDialog):
    def __init__(self, jobs, shared, parent):
        super().__init__(parent)
        from .ui import SettingsPanel

        self.setWindowTitle(f"Edit settings for {len(jobs)} pending jobs")
        self.resize(1060, 740)
        self.identifiers = [job["id"] for job in jobs]
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Values start from the first selected job. Check fields and click Apply, or use Apply all changed to apply every edit made here. Unchanged fields keep each job's saved value. Media settings lock after download; source settings lock once captions are saved."))
        split = QSplitter()
        self.fields = QListWidget()
        for key in DownloadSettings.__dataclass_fields__:
            if key.endswith("revision"):
                continue
            item = QListWidgetItem(key.replace("_", " "))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.fields.addItem(item)
        split.addWidget(self.fields)
        self.panel = SettingsPanel(DownloadSettings.from_dict(jobs[0]["settings"]))
        self.panel.bind_models(parent.store, parent.controller)
        self.panel.download_model.connect(parent.controller.start_model_download)
        # Compare with the controls after loading: font/model selectors can normalize
        # saved values to what this system displays without the user editing them.
        self.initial_settings = self.panel.settings().to_dict()
        split.addWidget(self.panel)
        split.setSizes([240, 780])
        layout.addWidget(split, 1)
        controls = QHBoxLayout()
        compare = QPushButton("Compare selected with shared…")
        compare.clicked.connect(lambda: ComparisonDialog([(job["title"], job["settings"]) for job in jobs], shared, self).exec())
        controls.addWidget(compare)
        self.apply_all_button = QPushButton("Apply all changed")
        self.apply_all_button.setToolTip("Apply all settings edited since this dialog opened to every selected job. Other saved values are preserved.")
        self.apply_all_button.clicked.connect(self.apply_all_changed)
        controls.addWidget(self.apply_all_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)
        controls.addWidget(buttons)
        layout.addLayout(controls)

    def apply(self):
        try:
            candidate = self.panel.settings().to_dict()
            patch = {item.data(Qt.ItemDataRole.UserRole): candidate[item.data(Qt.ItemDataRole.UserRole)]
                     for index in range(self.fields.count()) if (item := self.fields.item(index)).checkState() == Qt.CheckState.Checked}
            self.apply_patch(patch)
        except ValueError as exc:
            QMessageBox.warning(self, "Check bulk settings", str(exc))
            return

    def apply_all_changed(self):
        try:
            candidate = self.panel.settings().to_dict()
            patch = {key: value for key, value in candidate.items()
                     if not key.endswith("revision") and value != self.initial_settings[key]}
            if not patch:
                QMessageBox.information(self, "Bulk settings", "No settings have changed since this dialog opened.")
                return
            self.apply_patch(patch)
        except ValueError as exc:
            QMessageBox.warning(self, "Check bulk settings", str(exc))

    def apply_patch(self, patch):
        count = self.parent().controller.edit_pending(self.identifiers, patch)
        self.parent().show_notice(f"Updated {count} pending jobs.")
        self.accept()


class ScheduleDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Queue schedules")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Choose a local date and time. VideoDock must remain open (the tray is supported). Schedules do not wake the computer. Overdue schedules from a closed app are marked missed on launch. Queue pause lets active work finish."))
        form = QFormLayout()
        self.stage, self.action = QComboBox(), QComboBox()
        for title, key in (("Downloading", "download"), ("Captioning", "caption"), ("Translating", "translation")):
            self.stage.addItem(title, key)
        for action in ("Start", "Pause", "Resume"):
            self.action.addItem(action, action.lower())
        self.due = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("yyyy-MM-dd HH:mm:ss t")
        form.addRow("Queue", self.stage)
        form.addRow("Action", self.action)
        form.addRow("Local date and time", self.due)
        layout.addLayout(form)
        add = QPushButton("Add schedule")
        add.clicked.connect(self.add)
        layout.addWidget(add)
        self.entries = QListWidget()
        layout.addWidget(self.entries)
        cancel = QPushButton("Cancel selected schedule")
        cancel.clicked.connect(self.cancel_selected)
        layout.addWidget(cancel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.entries.clear()
        for entry in self.store.schedules():
            if entry["state"] == "cancelled":
                continue
            local = datetime.fromisoformat(entry["due"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            item = QListWidgetItem(f"{local} · {entry['stage']} · {entry['action']} · {entry['state']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.entries.addItem(item)

    def add(self):
        try:
            due = datetime.fromtimestamp(self.due.dateTime().toSecsSinceEpoch(), UTC)
            self.store.add_schedule(self.stage.currentData(), self.action.currentData(), due)
        except ValueError as exc:
            QMessageBox.warning(self, "Check schedule", str(exc))
            return
        self.refresh()

    def cancel_selected(self):
        for item in self.entries.selectedItems():
            self.store.schedule_state(item.data(Qt.ItemDataRole.UserRole), "cancelled")
        self.refresh()


class QueueOptionsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Background operation and completion")
        layout = QVBoxLayout(self)
        self.tray = QCheckBox("Close window to tray and keep queues running")
        self.tray.setChecked(window.store.preference("close_to_tray", False))
        self.tray.setEnabled(window.desktop.available)
        layout.addWidget(self.tray)
        self.notifications = {}
        for key, title in (("completion", "Completion notifications"), ("failure", "Failure notifications")):
            control = QCheckBox(title)
            control.setChecked(window.store.preference("notify_" + key, True))
            self.notifications[key] = control
            layout.addWidget(control)
        layout.addWidget(plain_label("Desktop notifications depend on system notification settings. Errors and completion also appear inside VideoDock."))
        self.power = QComboBox()
        for title, value in (("Do nothing", "none"), ("Sleep", "sleep"), ("Hibernate", "hibernate"), ("Shut down", "shutdown")):
            self.power.addItem(title, value)
        self.power.setCurrentIndex(max(0, self.power.findData(window.desktop.power_action)))
        form = QFormLayout()
        form.addRow("After all jobs succeed (this run only)", self.power)
        layout.addLayout(form)
        layout.addWidget(plain_label("A power action requires every queue to finish successfully, no held/waiting jobs or future schedules, and a 60-second cancellable countdown. The action disarms after use or app exit. Hibernate requires Windows support."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        window = self.parent()
        window.store.set_preference("close_to_tray", self.tray.isChecked())
        for key, control in self.notifications.items():
            window.store.set_preference("notify_" + key, control.isChecked())
        window.desktop.arm(self.power.currentData())
        self.accept()
