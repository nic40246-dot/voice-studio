import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    APP_DIR,
    MODEL_DEVICE,
    MODEL_LICENSE,
    MODEL_NAME,
    SUPPORTED_LANGUAGES,
)
from app.core.voice_manager import VoiceProfileManager
from app.ui.pptx_studio_tab import PPTXStudioTab
from app.ui.theme import DARK_THEME_QSS
from app.ui.tts_editor_tab import TTSEditorTab
from app.ui.voice_studio_tab import VoiceStudioTab

LICENSE_AND_HELP_HTML = f"""
<h2>Commercial Workplace License & Architecture</h2>
<p><b>Model:</b> {MODEL_NAME} (500M Neural Codec & Flow Matching)</p>
<p><b>License:</b> <span style="color: #10b981; font-weight: bold;">{MODEL_LICENSE}</span></p>
<p>The code, architecture, and model weights are licensed under the MIT License, which explicitly grants permission for commercial workplace use, private company presentations, customer demos, and executive video voiceovers without royalties or external subscriptions.</p>
<hr/>
<h2>Microsoft Teams Autoplay Presentation Guide</h2>
<p>When presenting your narrated PowerPoint slides in a live Microsoft Teams meeting:</p>
<ol>
    <li>Open the generated presentation in Microsoft PowerPoint on Windows 11.</li>
    <li>Join your <b>Microsoft Teams</b> meeting.</li>
    <li>Click <b>Share</b> in Teams toolbar.</li>
    <li><b>CRITICAL:</b> Toggle ON the checkbox <b>"Include computer sound"</b> (top right of the Share tray).</li>
    <li>Select your PowerPoint window (or full screen).</li>
    <li>Start Slide Show (<b>F5</b>). As you advance through slides, each slide's synthesized voiceover will automatically play through the meeting audio stream with zero delay and crystal-clear clarity.</li>
</ol>
<hr/>
<h2>Hardware Acceleration & CPU Optimization</h2>
<p><b>Detected Host:</b> Intel Core i5-14500 (14 physical cores, 20 execution threads, 128 GB RAM).</p>
<p><b>Inference Engine:</b> Native PyTorch CPU vectorized AVX2/AVX-512 instructions across all 14 physical cores with zero GPU or cloud dependencies.</p>
"""


class HelpAndLicenseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        browser = QTextBrowser()
        browser.setHtml(LICENSE_AND_HELP_HTML)
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Personal AI Voice Studio — English & German Narration Suite")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 720)

        # Initialize core managers
        self.voice_mgr = VoiceProfileManager()

        self._init_ui()
        self._apply_theme()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # Header Title Bar
        header = QHBoxLayout()
        title_label = QLabel("🎙️ Personal AI Voice Studio")
        title_font = QFont("Segoe UI", 15, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #38bdf8;")
        header.addWidget(title_label)

        badge_label = QLabel("  Local Neural TTS • Commercial MIT • PowerPoint COM Autoplay  ")
        badge_label.setStyleSheet(
            "background-color: #1e293b; color: #10b981; border: 1px solid #334155; "
            "border-radius: 4px; padding: 4px 8px; font-weight: 600; font-size: 11px;"
        )
        header.addWidget(badge_label)

        header.addStretch()

        btn_teams_help = QPushButton("ℹ️ Teams Audio Guide")
        btn_teams_help.clicked.connect(lambda: self.tabs.setCurrentIndex(3))
        header.addWidget(btn_teams_help)

        main_layout.addLayout(header)

        # Tab Widget
        self.tabs = QTabWidget()

        # Tab 1: Voice Profiles
        self.tab_voices = VoiceStudioTab(self.voice_mgr)
        self.tabs.addTab(self.tab_voices, "🎙️ Voice Profiles")

        # Tab 2: Standalone TTS Editor
        self.tab_tts = TTSEditorTab(self.voice_mgr)
        self.tabs.addTab(self.tab_tts, "📝 Text-to-Speech Studio")

        # Tab 3: PowerPoint Studio
        self.tab_pptx = PPTXStudioTab(self.voice_mgr)
        self.tabs.addTab(self.tab_pptx, "📊 PowerPoint Studio")

        # Tab 4: Commercial License & Help
        self.tab_help = HelpAndLicenseTab()
        self.tabs.addTab(self.tab_help, "⚙️ Commercial License & Setup")

        # Wire profile changes to refresh TTS and PPTX dropdowns
        self.tab_voices.profiles_changed.connect(self.tab_tts.refresh_voices)
        self.tab_voices.profiles_changed.connect(self.tab_pptx.refresh_voices)

        main_layout.addWidget(self.tabs)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Engine ready • Intel Core i5-14500 (14 Cores CPU Mode) • 128 GB RAM")

    def _apply_theme(self):
        self.setStyleSheet(DARK_THEME_QSS)
