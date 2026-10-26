from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from .store import Store
from .widgets import EmptyStateTable


def plain_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class SaveListDialog(QDialog):
    def __init__(self, has_selection: bool, playlist_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save a list")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(playlist_name)
        self.name.setMaxLength(160)
        self.name.setAccessibleName("Saved list name")
        self.kind = QComboBox()
        self.kind.addItem("Custom list", "custom")
        self.kind.addItem("Favorite playlist", "favorite")
        self.kind.setCurrentIndex(1 if playlist_name else 0)
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        layout.addLayout(form)
        self.include_selected = QCheckBox("Include checked preview entries")
        self.include_selected.setChecked(has_selection)
        self.include_selected.setEnabled(has_selection)
        layout.addWidget(self.include_selected)
        layout.addWidget(plain_label("Both types are editable. To create an empty list, uncheck the option above."))
        self.error = plain_label("")
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.validate)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def validate(self):
        try:
            Store._list_name(self.name.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class SavedListEditor(QDialog):
    changed = Signal(str)

    def __init__(self, store: Store, list_id: str, parent=None):
        super().__init__(parent)
        self.store, self.list_id = store, list_id
        self.setWindowTitle("Edit saved list")
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(160)
        self.name.setAccessibleName("Saved list name")
        row.addWidget(self.name, 1)
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename)
        row.addWidget(rename)
        layout.addLayout(row)
        self.origin = plain_label("")
        self.origin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.origin)
        layout.addWidget(plain_label(
            "To add videos from any link: close this editor, Preview links on Downloads, "
            "choose this saved list, then click Add selected. Load list restores its saved entries."
        ))
        self.entries = EmptyStateTable(0, 3)
        self.entries.setHorizontalHeaderLabels(["#", "Title", "Link"])
        self.entries.set_empty_message("This list is empty", "Preview links on Downloads, then use Add selected.")
        self.entries.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entries.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.entries.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entries.verticalHeader().hide()
        self.entries.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.entries.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.entries.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.entries.setAccessibleName("Saved list entries")
        layout.addWidget(self.entries, 1)
        row = QHBoxLayout()
        self.remove_button = QPushButton("Remove selected entries")
        self.remove_button.clicked.connect(self.remove_selected)
        self.entries.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(bool(self.entries.selectionModel().selectedRows()))
        )
        row.addWidget(self.remove_button)
        delete = QPushButton("Delete list")
        delete.clicked.connect(self.delete_list)
        row.addWidget(delete)
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.message = plain_label("")
        layout.addWidget(self.message)
        self.refresh()

    def refresh(self):
        saved = self.store.saved_list(self.list_id)
        if saved is None:
            self.reject()
            return
        self.name.setText(saved["name"])
        origins = "\n".join(saved["source_urls"]) or "No original link; custom entries."
        # Keep long playlist URLs from expanding the dialog beyond the screen.
        self.origin.setText("Original links (reference only): " + origins[:400])
        self.origin.setToolTip(origins)
        self.entries.setRowCount(len(saved["items"]))
        for row, item in enumerate(saved["items"]):
            for col, value in enumerate((str(row + 1), item["title"], item["url"])):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                cell.setToolTip(value)
                self.entries.setItem(row, col, cell)
        self.entries.clearSelection()
        self.remove_button.setEnabled(False)

    def rename(self):
        try:
            self.store.rename_saved_list(self.list_id, self.name.text())
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.changed.emit(self.list_id)
        self.message.setText("List name saved.")

    def remove_selected(self):
        ids = [self.entries.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
               for index in self.entries.selectionModel().selectedRows()]
        removed = self.store.remove_saved_items(self.list_id, ids)
        self.refresh()
        self.changed.emit(self.list_id)
        self.message.setText(f"Removed {removed} entries. Downloads and queued jobs are kept.")

    def delete_list(self):
        if QMessageBox.question(self, "Delete saved list", "Delete this list and its saved entries? "
                                "Downloads and queued jobs are kept.") != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_saved_list(self.list_id)
        self.changed.emit("")
        self.accept()
