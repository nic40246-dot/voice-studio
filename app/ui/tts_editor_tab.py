from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import EXPORTS_DIR
from app.core.audio_processing import convert_wav_to_mp3
from app.core.pronunciation import PronunciationManager
from app.core.voice_manager import VoiceProfileManager
from app.ui.audio_player_widget import AudioPlayerWidget
from app.ui.workers import HumanizeWorker, TTSWorker

SAMPLE_EN = (
    "Good morning and welcome to our Q3 financial review. "
    "Today, we will cover our strategic enterprise roadmap, "
    "our key customer success metrics, and our projected growth trajectory."
)

SAMPLE_DE = (
    "Guten Tag und herzlich willkommen zu unserer Quartalsübersicht. "
    "Heute präsentieren wir Ihnen unsere wichtigsten Meilensteine, "
    "die operative Entwicklung und unsere strategischen Ziele für das kommende Jahr."
)


class PronunciationDialog(QDialog):
    def __init__(self, pron_mgr: PronunciationManager, parent=None):
        super().__init__(parent)
        self.pron_mgr = pron_mgr
        self.setWindowTitle("Pronunciation Dictionary")
        self.setMinimumSize(540, 420)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Language selector
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Language:"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("English", "en")
        self.cmb_lang.addItem("German", "de")
        self.cmb_lang.currentIndexChanged.connect(self._load_table)
        top_layout.addWidget(self.cmb_lang)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # Rules table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Original Term / Acronym", "Phonetic Spoken Replacement"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemClicked.connect(self._on_table_row_clicked)
        layout.addWidget(self.table)

        # Add rule inputs
        add_layout = QHBoxLayout()
        self.txt_term = QLineEdit()
        self.txt_term.setPlaceholderText("e.g. AWS")
        self.txt_rep = QLineEdit()
        self.txt_rep.setPlaceholderText("e.g. A W S")
        self.btn_add = QPushButton("➕ Add / Update Rule")
        self.btn_add.clicked.connect(self._on_add_rule)
        add_layout.addWidget(self.txt_term)
        add_layout.addWidget(self.txt_rep)
        add_layout.addWidget(self.btn_add)
        layout.addLayout(add_layout)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton("🗑️ Remove Selected")
        self.btn_delete.clicked.connect(self._on_remove_rule)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self._load_table()

    def _load_table(self):
        self.pron_mgr.rules = self.pron_mgr._load_rules()
        lang = self.cmb_lang.currentData()
        rules = self.pron_mgr.get_rules_for_language(lang)
        self.table.setRowCount(len(rules))
        for row, (k, v) in enumerate(rules.items()):
            self.table.setItem(row, 0, QTableWidgetItem(k))
            self.table.setItem(row, 1, QTableWidgetItem(v))

    def _on_table_row_clicked(self, item):
        row = item.row()
        term_item = self.table.item(row, 0)
        rep_item = self.table.item(row, 1)
        if term_item and rep_item:
            self.txt_term.setText(term_item.text())
            self.txt_rep.setText(rep_item.text())

    def _on_add_rule(self):
        term = self.txt_term.text().strip()
        rep = self.txt_rep.text().strip()
        if not term or not rep:
            return
        lang = self.cmb_lang.currentData()
        self.pron_mgr.set_rule(lang, term, rep)
        self.txt_term.clear()
        self.txt_rep.clear()
        self._load_table()

    def _on_remove_rule(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return
        row = sel[0].row()
        term = self.table.item(row, 0).text()
        lang = self.cmb_lang.currentData()
        self.pron_mgr.remove_rule(lang, term)
        self._load_table()


class TTSEditorTab(QWidget):
    def __init__(self, voice_mgr: VoiceProfileManager, parent=None):
        super().__init__(parent)
        self.voice_mgr = voice_mgr
        self.pron_mgr = PronunciationManager()
        self.tts_worker = None
        self.humanize_worker = None
        self.latest_generated_wav = None
        self._init_ui()
        self.refresh_voices()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ----------------- LEFT PANE: Text Input & Controls -----------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # Voice & Language Bar
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Voice Profile:"))
        self.cmb_voice = QComboBox()
        self.cmb_voice.setMinimumWidth(180)
        top_bar.addWidget(self.cmb_voice)

        top_bar.addWidget(QLabel("Language:"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("English", "en")
        self.cmb_lang.addItem("German", "de")
        top_bar.addWidget(self.cmb_lang)

        top_bar.addWidget(QLabel("Accent:"))
        self.cmb_accent = QComboBox()
        self.cmb_accent.addItem("🌐 Neutral Dialect (Studio Model - Recommended)", False)
        self.cmb_accent.addItem("🎙️ Recording Accent (Energy Mirror)", True)
        self.cmb_accent.setCurrentIndex(0)
        self.cmb_accent.setToolTip("Neutral Dialect produces crisp standard pronunciation without mic artifact loops.")
        top_bar.addWidget(self.cmb_accent)

        self.btn_pron = QPushButton("📖 Pronunciation Rules")
        self.btn_pron.clicked.connect(self._open_pronunciation_dialog)
        top_bar.addWidget(self.btn_pron)

        top_bar.addStretch()
        left_layout.addLayout(top_bar)

        # Text Editor
        grp_text = QGroupBox("Script & Narration Text")
        text_layout = QVBoxLayout(grp_text)

        preset_bar = QHBoxLayout()
        self.btn_demo_en = QPushButton("Insert EN Sample")
        self.btn_demo_en.clicked.connect(lambda: self.txt_editor.setPlainText(SAMPLE_EN))
        preset_bar.addWidget(self.btn_demo_en)

        self.btn_demo_de = QPushButton("Insert DE Sample")
        self.btn_demo_de.clicked.connect(lambda: self.txt_editor.setPlainText(SAMPLE_DE))
        preset_bar.addWidget(self.btn_demo_de)

        self.btn_humanize = QPushButton("✨ Direct Narration (Gemini)")
        self.btn_humanize.setObjectName("primaryBtn")
        self.btn_humanize.setToolTip("Transform plain text into lively spoken narration with natural speech rhythm and inflection")
        self.btn_humanize.clicked.connect(self._on_humanize_editor_text)
        preset_bar.addWidget(self.btn_humanize)

        preset_bar.addStretch()
        self.lbl_char_count = QLabel("0 characters | 0 words")
        self.lbl_char_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
        preset_bar.addWidget(self.lbl_char_count)
        text_layout.addLayout(preset_bar)

        self.txt_editor = QPlainTextEdit()
        self.txt_editor.setPlaceholderText("Paste or type your presentation narration script here...")
        self.txt_editor.textChanged.connect(self._on_text_changed)
        text_layout.addWidget(self.txt_editor)
        left_layout.addWidget(grp_text)

        # Speech Parameters Group
        grp_params = QGroupBox("Speech Cadence & Prosody Controls")
        params_layout = QVBoxLayout(grp_params)

        # Speed slider
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Pacing / Speed:"))
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(70, 140)
        self.slider_speed.setValue(100)
        self.slider_speed.valueChanged.connect(self._update_speed_label)
        speed_row.addWidget(self.slider_speed)
        self.lbl_speed_val = QLabel("1.00x (Natural)")
        self.lbl_speed_val.setFixedWidth(90)
        speed_row.addWidget(self.lbl_speed_val)
        params_layout.addLayout(speed_row)

        # Micro-Pause slider
        pause_row = QHBoxLayout()
        pause_row.addWidget(QLabel("Inter-Sentence Pause:"))
        self.slider_pause = QSlider(Qt.Orientation.Horizontal)
        self.slider_pause.setRange(150, 750)
        self.slider_pause.setValue(250)
        self.slider_pause.valueChanged.connect(self._update_pause_label)
        pause_row.addWidget(self.slider_pause)
        self.lbl_pause_val = QLabel("250 ms (Natural)")
        self.lbl_pause_val.setFixedWidth(130)
        pause_row.addWidget(self.lbl_pause_val)
        params_layout.addLayout(pause_row)

        # Human Expressiveness / Inflection slider
        express_row = QHBoxLayout()
        express_row.addWidget(QLabel("Human Expressiveness:"))
        self.slider_exaggeration = QSlider(Qt.Orientation.Horizontal)
        self.slider_exaggeration.setRange(30, 120)
        self.slider_exaggeration.setValue(65)
        self.slider_exaggeration.valueChanged.connect(self._update_express_label)
        express_row.addWidget(self.slider_exaggeration)
        self.lbl_express_val = QLabel("0.65 (Natural Dynamic)")
        self.lbl_express_val.setFixedWidth(150)
        express_row.addWidget(self.lbl_express_val)
        params_layout.addLayout(express_row)

        # Generation Speed / Quality Preset
        speed_mode_row = QHBoxLayout()
        speed_mode_row.addWidget(QLabel("Engine Speed & Quality:"))
        self.cmb_quality_mode = QComboBox()
        self.cmb_quality_mode.addItem("⚡ Fast (2.5x Faster, Fluid Human)", 4)
        self.cmb_quality_mode.addItem("🎯 Studio Master (Maximum Precision)", 8)
        self.cmb_quality_mode.setCurrentIndex(1)
        speed_mode_row.addWidget(self.cmb_quality_mode, stretch=1)
        params_layout.addLayout(speed_mode_row)

        left_layout.addWidget(grp_params)

        # Generation Button & Progress
        gen_bar = QHBoxLayout()
        self.btn_generate = QPushButton("⚡ Generate Speech")
        self.btn_generate.setObjectName("primaryBtn")
        self.btn_generate.setFixedHeight(40)
        self.btn_generate.clicked.connect(self._on_generate)
        gen_bar.addWidget(self.btn_generate)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        gen_bar.addWidget(self.btn_cancel)
        left_layout.addLayout(gen_bar)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(14)
        self.prog_bar.setVisible(False)
        left_layout.addWidget(self.prog_bar)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        left_layout.addWidget(self.lbl_status)

        # ----------------- RIGHT PANE: Audio Player & Exports -----------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        grp_output = QGroupBox("Generated Audio & Playback")
        output_layout = QVBoxLayout(grp_output)

        self.player_widget = AudioPlayerWidget()
        output_layout.addWidget(self.player_widget)

        # Export buttons
        export_layout = QHBoxLayout()
        self.btn_export_wav = QPushButton("💾 Export WAV")
        self.btn_export_wav.setEnabled(False)
        self.btn_export_wav.clicked.connect(self._on_export_wav)
        export_layout.addWidget(self.btn_export_wav)

        self.btn_export_mp3 = QPushButton("🎵 Export MP3")
        self.btn_export_mp3.setObjectName("successBtn")
        self.btn_export_mp3.setEnabled(False)
        self.btn_export_mp3.clicked.connect(self._on_export_mp3)
        export_layout.addWidget(self.btn_export_mp3)

        output_layout.addLayout(export_layout)
        right_layout.addWidget(grp_output)

        # Quick Tips / Presentation Notice
        grp_tips = QGroupBox("Professional Narration Tips")
        tips_layout = QVBoxLayout(grp_tips)
        tip_text = (
            "• Use standard punctuation (periods, commas, dashes) for natural breathing pauses.\n"
            "• Numbers like 'Q3' or '$50M' should be written phonetically or registered in Pronunciation Rules.\n"
            "• For slide voiceovers, 120–140 words per minute matches comfortable executive listening.\n"
            "• Use the PowerPoint Studio tab to embed generated audio directly into slides with autoplay."
        )
        lbl_tips = QLabel(tip_text)
        lbl_tips.setWordWrap(True)
        lbl_tips.setStyleSheet("color: #94a3b8; line-height: 1.4;")
        tips_layout.addWidget(lbl_tips)
        right_layout.addWidget(grp_tips)
        right_layout.addStretch()

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([580, 420])
        main_layout.addWidget(splitter)

    def refresh_voices(self):
        curr_id = self.cmb_voice.currentData()
        self.cmb_voice.clear()

        self.cmb_voice.addItem("Default Chatterbox Voice", "")
        profiles = self.voice_mgr.list_profiles()
        for p in profiles:
            label = f"{p['name']} ({p.get('primary_language','').upper()})"
            self.cmb_voice.addItem(label, p["id"])

        if curr_id:
            idx = self.cmb_voice.findData(curr_id)
            if idx >= 0:
                self.cmb_voice.setCurrentIndex(idx)
        elif profiles:
            # Auto-select the first user voice profile by default
            self.cmb_voice.setCurrentIndex(1)

    def _update_speed_label(self, val):
        factor = val / 100.0
        self.lbl_speed_val.setText(f"{factor:.2f}x")

    def _update_pause_label(self, val):
        self.lbl_pause_val.setText(f"{val} ms")

    def _update_express_label(self, val):
        factor = val / 100.0
        if factor >= 1.00:
            desc = "Highly Animated"
        elif factor >= 0.80:
            desc = "Dynamic & Expressive"
        elif factor >= 0.65:
            desc = "Conversational"
        else:
            desc = "Formal Flat"
        self.lbl_express_val.setText(f"{factor:.2f} ({desc})")

    def _on_text_changed(self):
        text = self.txt_editor.toPlainText().strip()
        chars = len(text)
        words = len(text.split()) if text else 0
        self.lbl_char_count.setText(f"{chars} characters | {words} words")

    def _on_humanize_editor_text(self):
        text = self.txt_editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty Text", "Please enter or paste text to direct into spoken narration.")
            return

        lang = self.cmb_lang.currentData() or "en"
        self.btn_humanize.setEnabled(False)
        self.btn_humanize.setText("✨ Directing...")
        self.lbl_status.setText("Gemini is directing oral cadence & speech markers...")

        self.humanize_worker = HumanizeWorker(
            raw_text=text,
            language=lang,
            tone="engaging",
        )
        self.humanize_worker.finished.connect(self._on_humanize_editor_finished)
        self.humanize_worker.error.connect(self._on_humanize_editor_error)
        self.humanize_worker.start()

    def _on_humanize_editor_finished(self, result_text: str):
        self.btn_humanize.setEnabled(True)
        self.btn_humanize.setText("✨ Direct Narration (Gemini)")
        self.txt_editor.setPlainText(result_text)
        if self.slider_exaggeration.value() < 85:
            self.slider_exaggeration.setValue(85)
        self.lbl_status.setText("Spoken narration directed with dynamic pitch contours!")

    def _on_humanize_editor_error(self, err_msg: str):
        self.btn_humanize.setEnabled(True)
        self.btn_humanize.setText("✨ Direct Narration (Gemini)")
        self.lbl_status.setText("Direction failed")
        QMessageBox.warning(self, "Gemini Script Director", f"Could not direct narration:\n{err_msg}")

    def _open_pronunciation_dialog(self):
        dlg = PronunciationDialog(self.pron_mgr, self)
        dlg.exec()

    def _on_generate(self):
        text = self.txt_editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty Text", "Please enter some text to generate speech.")
            return

        lang = self.cmb_lang.currentData()
        profile_id = self.cmb_voice.currentData()
        ref_audio = None
        if profile_id:
            profile = self.voice_mgr.get_profile(profile_id)
            if profile and "reference_audio" in profile:
                ref_audio = profile["reference_audio"]

        speed = self.slider_speed.value() / 100.0
        pause_ms = self.slider_pause.value()
        exaggeration = self.slider_exaggeration.value() / 100.0
        n_cfm = self.cmb_quality_mode.currentData() or 8
        native_accent = self.cmb_accent.currentData() if hasattr(self, "cmb_accent") else False

        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.prog_bar.setVisible(True)
        self.prog_bar.setValue(0)
        self.lbl_status.setText("Initializing speech synthesis...")

        self.tts_worker = TTSWorker(
            text=text,
            language=lang,
            reference_audio_path=ref_audio,
            speed=speed,
            pause_duration_ms=pause_ms,
            temperature=0.82,
            cfg_weight=0.35,
            exaggeration=exaggeration,
            native_accent=native_accent,
            n_cfm_timesteps=n_cfm,
        )
        self.tts_worker.progress.connect(self._on_worker_progress)
        self.tts_worker.finished.connect(self._on_worker_finished)
        self.tts_worker.error.connect(self._on_worker_error)
        self.tts_worker.start()

    def _on_cancel(self):
        if self.tts_worker and self.tts_worker.isRunning():
            self.tts_worker.cancel()
            self.lbl_status.setText("Cancelling...")
            self.btn_cancel.setEnabled(False)

    def _on_worker_progress(self, cur, tot, msg):
        pct = int((cur / tot) * 100) if tot > 0 else 0
        self.prog_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_worker_finished(self, wav_path):
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.prog_bar.setVisible(False)
        self.lbl_status.setText("Synthesis complete!")

        self.latest_generated_wav = wav_path
        self.player_widget.load_audio(wav_path)
        self.btn_export_wav.setEnabled(True)
        self.btn_export_mp3.setEnabled(True)

    def _on_worker_error(self, err_msg):
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.prog_bar.setVisible(False)
        self.lbl_status.setText(f"Error: {err_msg}")
        QMessageBox.critical(self, "Generation Failed", err_msg)

    def _on_export_wav(self):
        if not self.latest_generated_wav or not Path(self.latest_generated_wav).exists():
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export WAV Audio", str(EXPORTS_DIR / "speech.wav"), "WAV Files (*.wav)")
        if dest:
            import shutil
            shutil.copy2(self.latest_generated_wav, dest)
            QMessageBox.information(self, "Export Successful", f"Saved: {Path(dest).name}")

    def _on_export_mp3(self):
        if not self.latest_generated_wav or not Path(self.latest_generated_wav).exists():
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export MP3 Audio", str(EXPORTS_DIR / "speech.mp3"), "MP3 Files (*.mp3)")
        if dest:
            try:
                convert_wav_to_mp3(self.latest_generated_wav, dest)
                QMessageBox.information(self, "Export Successful", f"Saved: {Path(dest).name}")
            except Exception as e:
                QMessageBox.critical(self, "MP3 Export Failed", str(e))
