import time
from pathlib import Path
from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AUDIO_CACHE_DIR
from app.core.audio_processing import validate_audio_sample
from app.core.voice_manager import VoiceProfileManager
from app.ui.audio_player_widget import AudioPlayerWidget
from app.ui.workers import AudioRecordWorker

CALIBRATION_SCRIPTS = {
    "en": {
        "Executive Briefing (Recommended)": (
            "Welcome to our annual executive briefing. Today, we examine our strategic roadmap, "
            "market developments, and core performance metrics. Strong collaboration and innovative "
            "technology allow our teams to deliver reliable, high-impact results with precision and speed "
            "across global operations."
        ),
        "Phonetic Studio Calibration": (
            "The quick brown fox jumps over the lazy dog. A large fawn jumped quickly over white zinc boxes. "
            "Clear vocal pitch, natural breathing cadence, and steady pacing ensure optimal voice cloning "
            "for enterprise presentations, executive briefings, and video narration."
        ),
    },
    "de": {
        "Executive Briefing (Empfohlen)": (
            "Herzlich willkommen zu unserem heutigen Strategiebericht. Wir analysieren aktuelle "
            "Marktentwicklungen, betriebliche Kennzahlen und unsere wichtigsten Meilensteine. "
            "Durch verlässliche Zusammenarbeit und moderne Technologien schaffen wir nachhaltige Werte "
            "und höchste Präzision für unsere Kunden und Partner."
        ),
        "Phonetische Studio-Kalibrierung": (
            "Der Nordwind und die Sonne stritten sich, wer von ihnen beiden wohl der Stärkere wäre. "
            "Zwölf Boxkämpfer jagen Viktor quer über den großen Sylter Deich. Präzise Aussprache, "
            "ruhige Atmung und ein gleichmäßiges Sprechtempo garantieren eine natürliche Stimmwiedergabe."
        ),
    },
}


class VoiceStudioTab(QWidget):
    profiles_changed = Signal()

    def __init__(self, voice_mgr: VoiceProfileManager, parent=None):
        super().__init__(parent)
        self.voice_mgr = voice_mgr
        self.selected_audio_file = None
        self.record_worker = None
        self.record_start_time = 0
        self.countdown_val = 0
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self._on_elapsed_tick)

        self._init_ui()
        self._refresh_microphones()
        self.refresh_profiles_table()
        self._update_teleprompter_script()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ----------------- LEFT PANE: Create Profile & Teleprompter -----------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        grp_create = QGroupBox("Create New Voice Profile")
        grp_layout = QVBoxLayout(grp_create)
        grp_layout.setSpacing(8)

        # Name & Language row
        name_lang_layout = QHBoxLayout()
        name_col = QVBoxLayout()
        name_col.addWidget(QLabel("Profile Name:"))
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("e.g. My Executive Voice")
        name_col.addWidget(self.txt_name)
        name_lang_layout.addLayout(name_col)

        lang_col = QVBoxLayout()
        lang_col.addWidget(QLabel("Primary Language:"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("English (EN)", "en")
        self.cmb_lang.addItem("German (DE)", "de")
        self.cmb_lang.currentIndexChanged.connect(self._on_language_changed)
        lang_col.addWidget(self.cmb_lang)
        name_lang_layout.addLayout(lang_col)
        grp_layout.addLayout(name_lang_layout)

        # Description
        grp_layout.addWidget(QLabel("Description / Notes (Optional):"))
        self.txt_desc = QLineEdit()
        self.txt_desc.setPlaceholderText("e.g. Clear tone, recorded with headset mic")
        grp_layout.addWidget(self.txt_desc)

        # ================= TELEPROMPTER SCRIPT BOX =================
        self.grp_teleprompter = QGroupBox("📖 Calibration Reading Script (Read Aloud to Clone)")
        self.grp_teleprompter.setStyleSheet(
            "QGroupBox { border: 1px solid #0284c7; background-color: #0f172a; border-radius: 8px; margin-top: 10px; } "
            "QGroupBox::title { color: #38bdf8; font-weight: bold; padding: 0 6px; }"
        )
        tele_layout = QVBoxLayout(self.grp_teleprompter)
        tele_layout.setSpacing(6)

        tele_header = QHBoxLayout()
        tele_header.addWidget(QLabel("Script Preset:"))
        self.cmb_script_preset = QComboBox()
        self.cmb_script_preset.currentIndexChanged.connect(self._on_preset_changed)
        tele_header.addWidget(self.cmb_script_preset)
        tele_header.addStretch()

        self.btn_copy_script = QPushButton("📋 Copy Script")
        self.btn_copy_script.clicked.connect(self._copy_script_text)
        tele_header.addWidget(self.btn_copy_script)
        tele_layout.addLayout(tele_header)

        # Reading Text Display (Teleprompter card)
        self.txt_teleprompter = QTextEdit()
        self.txt_teleprompter.setReadOnly(True)
        self.txt_teleprompter.setFixedHeight(115)
        self.txt_teleprompter.setFont(QFont("Segoe UI", 12))
        self.txt_teleprompter.setStyleSheet(
            "background-color: #0b1120; color: #f8fafc; border: 1px solid #1e293b; "
            "border-radius: 6px; padding: 8px; line-height: 1.5;"
        )
        tele_layout.addWidget(self.txt_teleprompter)

        lbl_tip = QLabel("💡 Tip: Read naturally with steady pace and breathing pauses (approx. 15–25 seconds).")
        lbl_tip.setStyleSheet("color: #94a3b8; font-size: 11px;")
        tele_layout.addWidget(lbl_tip)

        grp_layout.addWidget(self.grp_teleprompter)

        # Audio Source & Recording Bar
        grp_layout.addWidget(QLabel("Voice Capture:"))

        # Microphone input selector row
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Microphone:"))
        self.cmb_mic = QComboBox()
        mic_row.addWidget(self.cmb_mic, stretch=1)
        self.btn_refresh_mic = QPushButton("🔄")
        self.btn_refresh_mic.setToolTip("Refresh Audio Input Devices")
        self.btn_refresh_mic.setFixedWidth(32)
        self.btn_refresh_mic.clicked.connect(self._refresh_microphones)
        mic_row.addWidget(self.btn_refresh_mic)
        grp_layout.addLayout(mic_row)

        audio_btn_layout = QHBoxLayout()

        self.btn_record = QPushButton("🎙️ Start Recording")
        self.btn_record.setObjectName("primaryBtn")
        self.btn_record.setFixedHeight(36)
        self.btn_record.clicked.connect(self._toggle_record)
        audio_btn_layout.addWidget(self.btn_record)

        self.btn_import = QPushButton("📁 Or Browse Audio File...")
        self.btn_import.setFixedHeight(36)
        self.btn_import.clicked.connect(self._on_browse_file)
        audio_btn_layout.addWidget(self.btn_import)
        grp_layout.addLayout(audio_btn_layout)

        # Live Recording Level & Timer Banner
        self.rec_progress = QProgressBar()
        self.rec_progress.setRange(0, 100)
        self.rec_progress.setValue(0)
        self.rec_progress.setTextVisible(False)
        self.rec_progress.setFixedHeight(8)
        self.rec_progress.setVisible(False)
        grp_layout.addWidget(self.rec_progress)

        self.lbl_rec_status = QLabel("Ready. Click 'Start Recording' and read the script aloud.")
        self.lbl_rec_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;")
        grp_layout.addWidget(self.lbl_rec_status)

        # Quality Audit Box
        grp_audit = QGroupBox("Audio Quality & Validation")
        audit_layout = QVBoxLayout(grp_audit)
        audit_row = QHBoxLayout()
        self.lbl_audit_dur = QLabel("Duration: —")
        self.lbl_audit_rms = QLabel("Loudness (RMS): —")
        self.lbl_audit_peak = QLabel("Peak Level: —")
        audit_row.addWidget(self.lbl_audit_dur)
        audit_row.addWidget(self.lbl_audit_rms)
        audit_row.addWidget(self.lbl_audit_peak)
        audit_layout.addLayout(audit_row)

        self.lbl_audit_status = QLabel("Status: No sample captured yet")
        self.lbl_audit_status.setStyleSheet("color: #94a3b8; font-weight: bold;")
        audit_layout.addWidget(self.lbl_audit_status)
        grp_layout.addWidget(grp_audit)

        # Create Profile Button
        self.btn_save_profile = QPushButton("✨ Save & Create Voice Profile")
        self.btn_save_profile.setObjectName("primaryBtn")
        self.btn_save_profile.setFixedHeight(40)
        self.btn_save_profile.setEnabled(False)
        self.btn_save_profile.clicked.connect(self._on_save_profile)
        grp_layout.addWidget(self.btn_save_profile)

        left_layout.addWidget(grp_create)
        left_layout.addStretch()

        # ----------------- RIGHT PANE: Saved Profiles -----------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        grp_saved = QGroupBox("Saved Voice Profiles")
        saved_layout = QVBoxLayout(grp_saved)

        self.table_profiles = QTableWidget()
        self.table_profiles.setColumnCount(5)
        self.table_profiles.setHorizontalHeaderLabels(["Name", "Language", "Duration", "Created", "ID"])
        self.table_profiles.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_profiles.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_profiles.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_profiles.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_profiles.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_profiles.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_profiles.itemSelectionChanged.connect(self._on_profile_selected)
        saved_layout.addWidget(self.table_profiles)

        # Audio Player Preview
        self.player_widget = AudioPlayerWidget()
        saved_layout.addWidget(self.player_widget)

        # Action buttons
        btn_action_layout = QHBoxLayout()
        self.btn_set_default = QPushButton("⭐ Set as Default Voice")
        self.btn_set_default.setEnabled(False)
        self.btn_set_default.clicked.connect(self._on_set_default_profile)
        btn_action_layout.addWidget(self.btn_set_default)

        self.btn_delete_profile = QPushButton("🗑️ Delete Selected Profile")
        self.btn_delete_profile.setObjectName("dangerBtn")
        self.btn_delete_profile.setEnabled(False)
        self.btn_delete_profile.clicked.connect(self._on_delete_profile)
        btn_action_layout.addWidget(self.btn_delete_profile)

        saved_layout.addLayout(btn_action_layout)
        right_layout.addWidget(grp_saved)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([420, 580])
        main_layout.addWidget(splitter)

    def _on_browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Voice Reference Audio",
            "",
            "Audio Files (*.wav *.mp3 *.m4a *.flac *.ogg)",
        )
        if file_path:
            self._set_audio_sample(file_path)

    def _set_audio_sample(self, file_path: str):
        self.selected_audio_file = file_path
        self.lbl_rec_status.setText(f"Loaded: {Path(file_path).name}")

        val = validate_audio_sample(file_path)
        if val.get("valid", False):
            self.lbl_audit_dur.setText(f"Duration: {val['duration']:.1f}s (Optimal)")
            self.lbl_audit_rms.setText(f"Loudness (RMS): {val['rms_db']:.1f} dBFS")
            self.lbl_audit_peak.setText(f"Peak Level: {val['peak_db']:.1f} dBFS")
            warnings = val.get("warnings", [])
            if warnings:
                self.lbl_audit_status.setText("Status: Good (" + "; ".join(warnings) + ")")
                self.lbl_audit_status.setStyleSheet("color: #f59e0b; font-weight: bold;")
            else:
                self.lbl_audit_status.setText("Status: Excellent (Studio Ready)")
                self.lbl_audit_status.setStyleSheet("color: #10b981; font-weight: bold;")
            self.btn_save_profile.setEnabled(True)
        else:
            err = val.get("error", "Sample too short or silent")
            self.lbl_audit_status.setText(f"Status: Invalid ({err})")
            self.lbl_audit_status.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.btn_save_profile.setEnabled(False)

    def _on_language_changed(self):
        self._update_teleprompter_script()

    def _update_teleprompter_script(self):
        lang = self.cmb_lang.currentData() or "en"
        scripts_map = CALIBRATION_SCRIPTS.get(lang, CALIBRATION_SCRIPTS["en"])

        self.cmb_script_preset.blockSignals(True)
        self.cmb_script_preset.clear()
        for preset_name in scripts_map.keys():
            self.cmb_script_preset.addItem(preset_name)
        self.cmb_script_preset.blockSignals(False)

        self._on_preset_changed()

    def _on_preset_changed(self):
        lang = self.cmb_lang.currentData() or "en"
        preset_name = self.cmb_script_preset.currentText()
        scripts_map = CALIBRATION_SCRIPTS.get(lang, CALIBRATION_SCRIPTS["en"])
        script_text = scripts_map.get(preset_name, list(scripts_map.values())[0])
        self.txt_teleprompter.setPlainText(script_text)

    def _copy_script_text(self):
        text = self.txt_teleprompter.toPlainText()
        if text:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
            self.lbl_rec_status.setText("Script copied to clipboard!")

    def _toggle_record(self):
        # If currently recording, stop
        if self.record_worker and self.record_worker.isRunning():
            self._stop_recording()
            return

        # If countdown is active, cancel it
        if self.countdown_timer.isActive():
            self.countdown_timer.stop()
            self.btn_record.setText("🎙️ Start Recording")
            self.lbl_rec_status.setText("Recording cancelled.")
            return

        # Start 3-second countdown
        self.countdown_val = 3
        self.btn_record.setText("Cancel Countdown")
        self.btn_record.setObjectName("dangerBtn")
        self.btn_record.setStyle(self.btn_record.style())
        self.lbl_rec_status.setText(f"Get ready to read... Starting in {self.countdown_val} seconds!")
        self.lbl_rec_status.setStyleSheet("color: #38bdf8; font-size: 13px; font-weight: bold;")
        self.grp_teleprompter.setStyleSheet(
            "QGroupBox { border: 2px solid #f59e0b; background-color: #172554; border-radius: 8px; margin-top: 10px; } "
            "QGroupBox::title { color: #f59e0b; font-weight: bold; padding: 0 6px; }"
        )
        self.countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self.countdown_val -= 1
        if self.countdown_val > 0:
            self.lbl_rec_status.setText(f"Get ready... Starting in {self.countdown_val} seconds!")
        else:
            self.countdown_timer.stop()
            self._start_recording_now()

    def _refresh_microphones(self):
        self.cmb_mic.blockSignals(True)
        self.cmb_mic.clear()
        import sounddevice as sd

        input_devs = []
        try:
            devices = sd.query_devices()
            for idx, d in enumerate(devices):
                if d.get("max_input_channels", 0) > 0:
                    name = d.get("name", f"Device {idx}")
                    input_devs.append((idx, name))
        except Exception:
            pass

        if not input_devs:
            self.cmb_mic.addItem("No microphone detected", -1)
        else:
            self.cmb_mic.addItem("Auto-Detect Best Microphone", -1)
            for idx, name in input_devs:
                self.cmb_mic.addItem(f"{name} (ID: {idx})", idx)

            try:
                def_in = sd.default.device[0]
                if def_in >= 0:
                    for i in range(self.cmb_mic.count()):
                        if self.cmb_mic.itemData(i) == def_in:
                            self.cmb_mic.setCurrentIndex(i)
                            break
            except Exception:
                pass
        self.cmb_mic.blockSignals(False)

    def _start_recording_now(self):
        out_wav = str((AUDIO_CACHE_DIR / f"mic_rec_{int(time.time())}.wav").resolve())
        mic_dev = self.cmb_mic.currentData()
        self.record_worker = AudioRecordWorker(output_wav_path=out_wav, device=mic_dev, max_duration_sec=35)
        self.record_worker.level.connect(self._on_record_level)
        self.record_worker.finished.connect(self._on_record_finished)
        self.record_worker.error.connect(self._on_record_error)

        self.record_start_time = time.time()
        self.btn_record.setText("⏹️ Stop Recording")
        self.btn_record.setObjectName("dangerBtn")
        self.btn_record.setStyle(self.btn_record.style())

        self.rec_progress.setVisible(True)
        self.grp_teleprompter.setStyleSheet(
            "QGroupBox { border: 2px solid #38bdf8; background-color: #0f172a; border-radius: 8px; margin-top: 10px; } "
            "QGroupBox::title { color: #38bdf8; font-weight: bold; padding: 0 6px; }"
        )
        self.lbl_rec_status.setText("🔴 Recording in progress... Read the highlighted script above!")
        self.lbl_rec_status.setStyleSheet("color: #ef4444; font-size: 13px; font-weight: bold;")

        self.elapsed_timer.start(500)
        self.record_worker.start()

    def _on_elapsed_tick(self):
        if self.record_worker and self.record_worker.isRunning():
            elapsed = time.time() - self.record_start_time
            self.lbl_rec_status.setText(f"🔴 Recording: {elapsed:.1f}s / 25s target — Read script above")

    def _stop_recording(self):
        self.elapsed_timer.stop()
        if self.record_worker and self.record_worker.isRunning():
            self.record_worker.stop_recording()
        self.btn_record.setText("🎙️ Start Recording")
        self.btn_record.setObjectName("primaryBtn")
        self.btn_record.setStyle(self.btn_record.style())
        self.rec_progress.setVisible(False)
        self.grp_teleprompter.setStyleSheet(
            "QGroupBox { border: 1px solid #0284c7; background-color: #0f172a; border-radius: 8px; margin-top: 10px; } "
            "QGroupBox::title { color: #38bdf8; font-weight: bold; padding: 0 6px; }"
        )

    def _on_record_level(self, rms_val: float):
        # Scale RMS level for visual meter
        meter_val = min(100, int(rms_val * 350))
        self.rec_progress.setValue(meter_val)

    def _on_record_finished(self, wav_path: str):
        self._stop_recording()
        self.lbl_rec_status.setText("Audio captured! Auditing quality...")
        self.lbl_rec_status.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 500;")
        self._set_audio_sample(wav_path)

    def _on_record_error(self, err_msg: str):
        self._stop_recording()
        self.lbl_rec_status.setText(f"Recording error: {err_msg}")
        self.lbl_rec_status.setStyleSheet("color: #ef4444; font-size: 12px;")
        QMessageBox.warning(self, "Recording Error", f"Could not record audio: {err_msg}")

    def _on_save_profile(self):
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a profile name.")
            return

        if not self.selected_audio_file or not Path(self.selected_audio_file).exists():
            QMessageBox.warning(self, "Missing Audio", "Please select or record a reference audio sample.")
            return

        lang = self.cmb_lang.currentData()
        desc = self.txt_desc.text().strip()

        try:
            profile = self.voice_mgr.create_profile(
                name=name,
                source_audio_path=self.selected_audio_file,
                primary_language=lang,
                description=desc,
            )
            QMessageBox.information(self, "Success", f"Voice Profile '{profile['name']}' created successfully!")
            self.txt_name.clear()
            self.txt_desc.clear()
            self.btn_save_profile.setEnabled(False)
            self.refresh_profiles_table()
            self.profiles_changed.emit()
        except Exception as e:
            QMessageBox.critical(self, "Profile Creation Failed", str(e))

    def refresh_profiles_table(self):
        profiles = self.voice_mgr.list_profiles()
        default_id = self.voice_mgr.get_default_profile_id()
        self.table_profiles.setRowCount(len(profiles))

        for row, p in enumerate(profiles):
            name_str = p.get("name", "")
            if p.get("id") == default_id:
                name_str = f"⭐ {name_str} [Default]"
            self.table_profiles.setItem(row, 0, QTableWidgetItem(name_str))
            self.table_profiles.setItem(row, 1, QTableWidgetItem(p.get("primary_language", "").upper()))
            dur = p.get("duration_sec", 0)
            self.table_profiles.setItem(row, 2, QTableWidgetItem(f"{dur:.1f}s"))
            created = p.get("created_at", "")[:10]
            self.table_profiles.setItem(row, 3, QTableWidgetItem(created))
            self.table_profiles.setItem(row, 4, QTableWidgetItem(p.get("id", "")))

        self.btn_delete_profile.setEnabled(False)
        self.btn_set_default.setEnabled(False)

    def _on_profile_selected(self):
        sel_rows = self.table_profiles.selectionModel().selectedRows()
        if not sel_rows:
            self.btn_delete_profile.setEnabled(False)
            self.btn_set_default.setEnabled(False)
            return

        self.btn_delete_profile.setEnabled(True)
        self.btn_set_default.setEnabled(True)
        row = sel_rows[0].row()
        profile_id_item = self.table_profiles.item(row, 4)
        if profile_id_item:
            profile = self.voice_mgr.get_profile(profile_id_item.text())
            if profile and "reference_audio" in profile:
                self.player_widget.load_audio(profile["reference_audio"])

    def _on_set_default_profile(self):
        sel_rows = self.table_profiles.selectionModel().selectedRows()
        if not sel_rows:
            return
        row = sel_rows[0].row()
        profile_id = self.table_profiles.item(row, 4).text()
        self.voice_mgr.set_default_profile(profile_id)
        self.refresh_profiles_table()
        self.profiles_changed.emit()

    def _on_delete_profile(self):
        sel_rows = self.table_profiles.selectionModel().selectedRows()
        if not sel_rows:
            return
        row = sel_rows[0].row()
        profile_id = self.table_profiles.item(row, 4).text()
        profile_name = self.table_profiles.item(row, 0).text()

        res = QMessageBox.question(
            self,
            "Delete Profile",
            f"Are you sure you want to delete profile '{profile_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self.voice_mgr.delete_profile(profile_id)
            self.refresh_profiles_table()
            self.player_widget.stop()
            self.profiles_changed.emit()
