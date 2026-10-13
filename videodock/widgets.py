"""Small presentation helpers; the underlying table selection model stays intact."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidget, QVBoxLayout, QWidget


class EmptyStateTable(QTableWidget):
    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self.empty_state = QWidget(self.viewport())
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self.empty_state)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)
        layout.addStretch()
        self.empty_title = QLabel()
        self.empty_detail = QLabel()
        for control, name in ((self.empty_title, "emptyTitle"), (self.empty_detail, "emptyDetail")):
            control.setObjectName(name)
            control.setTextFormat(Qt.TextFormat.PlainText)
            control.setAlignment(Qt.AlignmentFlag.AlignCenter)
            control.setWordWrap(True)
            layout.addWidget(control)
        layout.addStretch()
        self.model().rowsInserted.connect(self.update_empty_state)
        self.model().rowsRemoved.connect(self.update_empty_state)
        self.model().modelReset.connect(self.update_empty_state)
        self.empty_state.hide()

    def set_empty_message(self, title, detail):
        self.empty_title.setText(title)
        self.empty_detail.setText(detail)
        self.update_empty_state()

    def update_empty_state(self, *_):
        self.empty_state.setGeometry(self.viewport().rect())
        self.empty_detail.setVisible(self.viewport().height() >= 54)
        self.empty_state.setVisible(self.rowCount() == 0 and bool(self.empty_title.text()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_empty_state()
