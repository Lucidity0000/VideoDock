"""Tray and opt-in power actions. Tests inject the process boundary; never suspend a test host."""

import os
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout

from .models import ACTIVE, PENDING
from .queue_ui import plain_label
from .theme import ASSETS


def power_command(action):
    if os.name != "nt":
        raise ValueError("Power actions are supported on Windows.")
    system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
    if action == "shutdown":
        return [str(system / "shutdown.exe"), "/s", "/t", "0"]
    if action == "hibernate":
        return [str(system / "shutdown.exe"), "/h"]
    if action == "sleep":
        return [str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "if (-not [System.Windows.Forms.Application]::SetSuspendState("
                "[System.Windows.Forms.PowerState]::Suspend, $false, $false)) { exit 1 }"]
    raise ValueError("Unknown power action.")


class DesktopIntegration:
    def __init__(self, window):
        self.window = window
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.exiting = False
        self.power_action = "none"
        self.countdown = None
        self.process = None
        self.tray = QSystemTrayIcon(QIcon(f"{ASSETS}/mark.svg"), window)
        self.menu = QMenu(window)
        self.menu.addAction("Show VideoDock", self.show)
        self.menu.addSeparator()
        for stage, title in (("download", "Downloading"), ("caption", "Captioning"), ("translation", "Translating")):
            menu = self.menu.addMenu(title)
            menu.addAction("Start / resume queue", lambda stage=stage: window.controller.start(stage))
            menu.addAction("Pause queue after active jobs", lambda stage=stage: window.controller.pause(stage))
        self.menu.addAction("Queue schedules…", window.queue_schedules)
        self.menu.addAction("Background and completion…", window.queue_options)
        self.menu.addAction("Cancel power action", lambda: self.arm("none"))
        self.menu.addSeparator()
        self.menu.addAction("Exit VideoDock", self.exit)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("VideoDock")
        self.tray.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.messageClicked.connect(self.show)
        if self.available:
            self.tray.show()
        window.controller.notification.connect(self.notify)
        window.controller.run_finished.connect(self.run_finished)
        window.controller.changed.connect(self.check_countdown)

    def show(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def exit(self):
        self.exiting = True
        self.arm("none")
        self.window.close()

    def notify(self, kind, title, message):
        if not self.window.store.preference("notify_" + kind, True):
            return
        self.window.show_notice(f"{title}: {message}")
        if self.available and self.tray.supportsMessages():
            icon = QSystemTrayIcon.MessageIcon.Warning if kind == "failure" else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage(title, message[:1200], icon, 8000)

    def arm(self, action):
        if self.countdown:
            self.countdown.reject()
        self.power_action = action

    def ready(self):
        window = self.window
        return (not window.controller.active and not window.controller.caption_id and not window.controller.model_workers
                and not window.background and not window.controller.shutting_down and not window.closing
                and not any(not job["removed"] and job["status"] in ACTIVE | PENDING for job in window.store.jobs())
                and not any(item["state"] == "pending" for item in window.store.schedules()))

    def check_countdown(self):
        self.tray.setToolTip("VideoDock · " + self.window.summary.text())
        if self.countdown and not self.ready():
            self.arm("none")

    def queue_completed(self):
        if self.power_action == "none" or not self.ready():
            self.arm("none")
            return
        self.show()
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Queue complete — scheduled power action")
        layout = QVBoxLayout(dialog)
        text = plain_label("")
        layout.addWidget(text)
        cancel = QPushButton("Cancel power action")
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(cancel)
        self.countdown = dialog
        remaining = 60
        action = self.power_action
        timer = QTimer(dialog)

        def disarm(*_):
            timer.stop()
            self.countdown = None
            self.power_action = "none"

        def tick():
            nonlocal remaining
            if not self.ready() or self.power_action != action:
                dialog.reject()
                return
            text.setText(f"All queues completed successfully. {action.capitalize()} in {remaining} seconds.")
            if remaining <= 0:
                dialog.accept()
                self.perform(action)
            remaining -= 1

        dialog.finished.connect(disarm)
        timer.timeout.connect(tick)
        tick()
        timer.start(1000)
        dialog.show()

    def run_finished(self, success):
        if success:
            self.queue_completed()
        else:
            self.arm("none")

    def perform(self, action):
        try:
            command = power_command(action)
        except ValueError as exc:
            self.window.show_notice(str(exc))
            return
        self.process = QProcess(self.window)
        self.process.errorOccurred.connect(lambda _: self.window.show_notice("Could not start the power action: " + self.process.errorString()))
        self.process.finished.connect(lambda code, *_: self.window.show_notice(
            "Power action failed. Check Windows power settings and permissions." if code else "Power action requested."))
        self.process.start(command[0], command[1:])
