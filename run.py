"""
Personal AI Voice Studio
Updated: 2026-10-24
Features: Zero-word-skipping neural synthesis, automatic storyline arc detection,
dynamic prosody tuning, and direct PowerPoint slide embedding.
"""

import ctypes
import os
import sys

# High DPI and Windows Taskbar integration
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
try:
    myappid = "personal.aivoicestudio.windows.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Personal AI Voice Studio")
    app.setOrganizationName("VoiceStudio")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
