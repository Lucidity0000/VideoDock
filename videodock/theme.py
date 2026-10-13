"""Shared desktop colors and lightweight, code-native UI assets."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

ASSETS = Path(__file__).with_name("assets").as_posix()

STYLE = """
QWidget { background: #0e141c; color: #e7eef7; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #0e141c; }
QLabel { background: transparent; }
QLabel#brand { font-size: 26px; font-weight: 700; letter-spacing: -1px; }
QLabel#subtitle, QLabel#muted { color: #9eafc3; }
QLabel#section { font-size: 15px; font-weight: 600; color: #e7eef7; }
QLabel#summary { background: #172b2b; color: #9ce7d0; border: 1px solid #28483f;
  border-radius: 13px; padding: 7px 12px; }
QLabel#notice { color: #a8b8cc; border-top: 1px solid #263243; padding-top: 7px; }
QFrame#card { background: #17212e; border: 1px solid #2b3a4d; border-radius: 12px; }
QFrame#sourceCard { background: #131d29; border: 1px solid #29384a; border-radius: 10px; }
QLabel#modelTitle { font-size: 15px; font-weight: 600; }
QPushButton { background: #223247; border: 1px solid #364b64; border-radius: 7px;
  padding: 7px 10px; font-weight: 500; }
QPushButton:hover { background: #2c4059; border-color: #7795b5; }
QPushButton:pressed { background: #18283b; }
QPushButton:focus { border: 1px solid #78dfc1; }
QPushButton#primary { background: #77dfbf; color: #092b23; font-weight: 600; border-color: #77dfbf; }
QPushButton#primary:hover { background: #a0edd5; border-color: #b7f5e2; }
QPushButton#primary:pressed { background: #51c8a3; }
QPushButton#primary:focus { border: 1px solid #ecfff9; }
QPushButton:disabled, QPushButton#primary:disabled { color: #74869c; background: #172332;
  border-color: #2a394c; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
  background: #0e1825; border: 1px solid #364b64; border-radius: 6px; padding: 6px 8px;
  selection-background-color: #365b77; selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
  border: 1px solid #77dfbf;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
  color: #74869c; background: #131d2b; border-color: #29384a;
}
QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: 0; width: 26px; }
QComboBox::down-arrow { image: url(@ASSETS@/chevron-down.svg); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #1a293b; border: 1px solid #4b6685;
  selection-background-color: #365b77; selection-color: #ffffff; outline: 0; }
QComboBox QAbstractItemView::item { min-height: 26px; }
QComboBox QAbstractItemView::item:disabled { color: #74869c; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
  width: 23px; border: 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
  width: 23px; border: 0; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@ASSETS@/chevron-up.svg); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@ASSETS@/chevron-down.svg); width: 10px; height: 10px; }
QTableWidget { background: #111c2a; alternate-background-color: #152233;
  border: 1px solid #2c3d52; border-radius: 7px; gridline-color: #233349;
  selection-background-color: #294e65; selection-color: #ffffff; }
QTableWidget::item { padding: 0 5px; border: 0; }
QTableWidget::item:selected { background: #294e65; color: #ffffff; }
QHeaderView::section { background: #1c2b3e; border: 0; border-bottom: 1px solid #34465e;
  padding: 7px 8px; color: #b8c9dd; font-weight: 600; }
QProgressBar { border: 1px solid #344b62; border-radius: 5px; background: #132334;
  text-align: center; min-height: 18px; color: #ecf7f4; margin: 6px; }
QProgressBar::chunk { background: #267b65; border-radius: 4px; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 8px 17px; margin: 2px 3px 6px 0; background: #152030;
  color: #a4b5ca; border: 1px solid transparent; border-radius: 7px; }
QTabBar::tab:hover { background: #203249; color: #edf5ff; }
QTabBar::tab:selected { background: #203d3b; color: #a0efd7; border-color: #386559; }
QTabWidget#navigation > QTabBar::tab { padding: 10px 19px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListWidget::indicator, QTableWidget::indicator {
  width: 15px; height: 15px; border: 1px solid #607a98; border-radius: 4px; background: #122033;
}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTableWidget::indicator:checked {
  background: #77dfbf; border-color: #77dfbf; image: url(@ASSETS@/check.svg);
}
QCheckBox::indicator:focus { border-color: #b6ffe7; }
QCheckBox:disabled { color: #74869c; }
QCheckBox::indicator:disabled { border-color: #35465b; background: #1a2939; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #0e141c; width: 9px; margin: 2px; }
QScrollBar:horizontal { background: #0e141c; height: 9px; margin: 2px; }
QScrollBar::handle { background: #41556f; border-radius: 3px; min-height: 26px; min-width: 26px; }
QScrollBar::handle:hover { background: #6986a8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QListWidget { background: #0e1825; border: 1px solid #364b64; border-radius: 6px; padding: 4px; }
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background: #294e65; color: #ffffff; }
QWidget#emptyState { background: transparent; }
QLabel#emptyTitle { color: #aebfd3; font-size: 14px; font-weight: 600; }
QLabel#emptyDetail { color: #8196af; font-size: 12px; }
QLabel#modelStatus { color: #a4b5ca; }
QLabel#modelStatus[ready="true"] { color: #8ce6c6; }
QToolTip { background: #24374f; color: #f2f7ff; border: 1px solid #6787a8; padding: 5px; }
""".replace("@ASSETS@", ASSETS)


def apply_palette(application):
    """Keep popup menus and Qt dialogs readable alongside the styled window."""
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#0e141c",
        QPalette.ColorRole.WindowText: "#e7eef7",
        QPalette.ColorRole.Base: "#0e1825",
        QPalette.ColorRole.AlternateBase: "#152233",
        QPalette.ColorRole.Text: "#e7eef7",
        QPalette.ColorRole.Button: "#223247",
        QPalette.ColorRole.ButtonText: "#e7eef7",
        QPalette.ColorRole.Highlight: "#294e65",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#8196af",
        QPalette.ColorRole.ToolTipBase: "#24374f",
        QPalette.ColorRole.ToolTipText: "#f2f7ff",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#74869c"))
    application.setPalette(palette)


def status_color(status: str) -> QColor:
    if status in {"completed", "complete", "installed"}:
        return QColor("#8ce6c6")
    if status == "failed":
        return QColor("#ffaaaa")
    if status in {"partial", "waiting_model", "cancelled"}:
        return QColor("#eac389")
    if status in {"downloading", "captioning", "translating"}:
        return QColor("#9ecbff")
    return QColor("#afc0d5")
