import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import EXPORTS_DIR
from app.core.gemini_director import TONE_STYLES, detect_slide_tone_heuristic
from app.core.pptx_service import PowerPointService
from app.core.project_storage import ProjectManager, ProjectModel
from app.core.voice_manager import VoiceProfileManager
from app.ui.audio_player_widget import AudioPlayerWidget
from app.ui.workers import (
    AutoDirectPresentationWorker,
    AutoDirectSlideWorker,
    BatchGenerateAudioWorker,
    HumanizeWorker,
    PPTXBatchExportWorker,
    PPTXExtractWorker,
    StorylineAnalysisWorker,
    TTSWorker,
)


class PPTXStudioTab(QWidget):
    def __init__(self, voice_mgr: VoiceProfileManager, parent=None):
        super().__init__(parent)
        self.voice_mgr = voice_mgr
        self.project_mgr = ProjectManager()
        self.current_project = ProjectModel()
        self.current_slide_idx = -1
        self.tts_worker = None
        self.batch_worker = None
        self.humanize_worker = None
        self.auto_direct_worker = None
        self.batch_tts_worker = None
        self._init_ui()
        self.refresh_voices()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ----------------- TOP TOOLBAR -----------------
        top_bar = QHBoxLayout()
        self.btn_open_pptx = QPushButton("📂 Open PowerPoint (.pptx)...")
        self.btn_open_pptx.setObjectName("primaryBtn")
        self.btn_open_pptx.clicked.connect(self._on_open_pptx)
        top_bar.addWidget(self.btn_open_pptx)

        self.btn_save_proj = QPushButton("💾 Save Project (.vsproj)")
        self.btn_save_proj.clicked.connect(self._on_save_project)
        top_bar.addWidget(self.btn_save_proj)

        self.btn_load_proj = QPushButton("📁 Load Project...")
        self.btn_load_proj.clicked.connect(self._on_load_project)
        top_bar.addWidget(self.btn_load_proj)

        top_bar.addSpacing(16)
        self.lbl_pptx_file = QLabel("No presentation loaded")
        self.lbl_pptx_file.setStyleSheet("color: #94a3b8; font-weight: bold;")
        top_bar.addWidget(self.lbl_pptx_file)

        top_bar.addStretch()

        self.btn_export_en = QPushButton("📤 Export EN Presentation (.pptx)")
        self.btn_export_en.setObjectName("successBtn")
        self.btn_export_en.clicked.connect(lambda: self._on_export_presentation("en"))
        top_bar.addWidget(self.btn_export_en)

        self.btn_export_de = QPushButton("📤 Export DE Presentation (.pptx)")
        self.btn_export_de.setObjectName("successBtn")
        self.btn_export_de.clicked.connect(lambda: self._on_export_presentation("de"))
        top_bar.addWidget(self.btn_export_de)

        main_layout.addLayout(top_bar)

        # ----------------- MAIN SPLITTER (3 PANES) -----------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === PANE 1: SLIDE NAVIGATOR ===
        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 4, 0)
        nav_layout.setSpacing(6)

        nav_header = QHBoxLayout()
        nav_header.addWidget(QLabel("Presentation Slides:"))
        self.lbl_slide_count = QLabel("0 slides")
        self.lbl_slide_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
        nav_header.addWidget(self.lbl_slide_count)
        nav_header.addStretch()
        nav_layout.addLayout(nav_header)

        self.slide_list = QListWidget()
        self.slide_list.setIconSize(self.slide_list.iconSize() * 2)
        self.slide_list.currentRowChanged.connect(self._on_slide_selected)
        nav_layout.addWidget(self.slide_list)

        # Storyline & Batch Controls
        self.btn_check_storyline = QPushButton("🔍 Auto-Detect Deck Storyline & Tones")
        self.btn_check_storyline.setObjectName("primaryBtn")
        self.btn_check_storyline.setToolTip("Analyzes your written scripts across the presentation to detect the opening hook, storytelling slides, technical data, and conclusion, auto-tuning prosody without changing your words.")
        self.btn_check_storyline.clicked.connect(self._on_check_storyline)
        nav_layout.addWidget(self.btn_check_storyline)

        self.btn_batch_generate_all = QPushButton("⚡ Synthesize All Slide Audios")
        self.btn_batch_generate_all.setToolTip("Synthesize audio for every slide in batch using each slide's individual tone and cadence settings")
        self.btn_batch_generate_all.clicked.connect(self._on_batch_generate_all_audios)
        nav_layout.addWidget(self.btn_batch_generate_all)

        self.batch_prog_bar = QProgressBar()
        self.batch_prog_bar.setRange(0, 100)
        self.batch_prog_bar.setValue(0)
        self.batch_prog_bar.setFixedHeight(12)
        self.batch_prog_bar.setVisible(False)
        nav_layout.addWidget(self.batch_prog_bar)

        self.lbl_batch_status = QLabel("")
        self.lbl_batch_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.lbl_batch_status.setWordWrap(True)
        nav_layout.addWidget(self.lbl_batch_status)

        splitter.addWidget(nav_widget)

        # === PANE 2: SLIDE SCRIPT & NARRATION EDITOR ===
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(4, 0, 4, 0)
        editor_layout.setSpacing(8)

        # Slide info banner
        self.lbl_current_slide_title = QLabel("Select a slide to edit narration")
        self.lbl_current_slide_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        editor_layout.addWidget(self.lbl_current_slide_title)

        # Reference text accordion / summary
        self.txt_slide_body = QPlainTextEdit()
        self.txt_slide_body.setReadOnly(True)
        self.txt_slide_body.setMaximumHeight(90)
        self.txt_slide_body.setPlaceholderText("Extracted slide text from PowerPoint presentation...")
        editor_layout.addWidget(QLabel("Slide Content (Read-Only Reference):"))
        editor_layout.addWidget(self.txt_slide_body)

        # Notes section with helper button
        notes_bar = QHBoxLayout()
        notes_bar.addWidget(QLabel("Speaker Notes in PowerPoint:"))
        notes_bar.addStretch()
        self.btn_copy_notes_en = QPushButton("📋 Copy Notes (EN)")
        self.btn_copy_notes_en.clicked.connect(lambda: self._copy_notes_to_script("en"))
        notes_bar.addWidget(self.btn_copy_notes_en)
        self.btn_copy_notes_de = QPushButton("📋 Copy Notes (DE)")
        self.btn_copy_notes_de.clicked.connect(lambda: self._copy_notes_to_script("de"))
        notes_bar.addWidget(self.btn_copy_notes_de)

        self.btn_humanize_script = QPushButton("✨ Direct Narration (Gemini)")
        self.btn_humanize_script.setObjectName("primaryBtn")
        self.btn_humanize_script.setToolTip("Transform bullet points into engaging spoken narration with natural inflection markers")
        self.btn_humanize_script.clicked.connect(self._on_humanize_script)
        notes_bar.addWidget(self.btn_humanize_script)

        editor_layout.addLayout(notes_bar)

        self.txt_slide_notes = QPlainTextEdit()
        self.txt_slide_notes.setReadOnly(True)
        self.txt_slide_notes.setMaximumHeight(70)
        self.txt_slide_notes.setPlaceholderText("No speaker notes on this slide...")
        editor_layout.addWidget(self.txt_slide_notes)

        # Narration Tabs: English vs German
        self.script_tabs = QTabWidget()

        # EN Tab
        en_widget = QWidget()
        en_layout = QVBoxLayout(en_widget)
        en_layout.setContentsMargins(4, 8, 4, 4)
        self.txt_script_en = QPlainTextEdit()
        self.txt_script_en.setPlaceholderText("Enter English narration voiceover script for this slide...")
        self.txt_script_en.textChanged.connect(self._on_script_en_changed)
        en_layout.addWidget(self.txt_script_en)
        self.script_tabs.addTab(en_widget, "🇬🇧 English Narration")

        # DE Tab
        de_widget = QWidget()
        de_layout = QVBoxLayout(de_widget)
        de_layout.setContentsMargins(4, 8, 4, 4)
        self.txt_script_de = QPlainTextEdit()
        self.txt_script_de.setPlaceholderText("Geben Sie das deutsche Skript für diese Folie ein...")
        self.txt_script_de.textChanged.connect(self._on_script_de_changed)
        de_layout.addWidget(self.txt_script_de)
        self.script_tabs.addTab(de_widget, "🇩🇪 German Narration")

        editor_layout.addWidget(self.script_tabs)

        splitter.addWidget(editor_widget)

        # === PANE 3: GENERATION, AUDIO & VIDEO ATTACHMENTS ===
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 0, 0, 0)
        action_layout.setSpacing(10)

        # Voice & Speech Controls
        grp_controls = QGroupBox("Voice & Pacing for Slide")
        ctrl_layout = QVBoxLayout(grp_controls)

        ctrl_layout.addWidget(QLabel("Voice Profile:"))
        self.cmb_voice = QComboBox()
        ctrl_layout.addWidget(self.cmb_voice)

        ctrl_layout.addWidget(QLabel("Tone & Dynamic Range:"))
        tone_bar = QHBoxLayout()
        self.cmb_tone_style = QComboBox()
        self.cmb_tone_style.addItem("🪄 Auto-Detect Tone (Dynamic)", "auto")
        for key, info in TONE_STYLES.items():
            self.cmb_tone_style.addItem(info["label"], key)
        self.cmb_tone_style.currentIndexChanged.connect(self._on_tone_style_changed)
        tone_bar.addWidget(self.cmb_tone_style)

        self.btn_auto_tone = QPushButton("🪄 Auto")
        self.btn_auto_tone.setToolTip("Auto-detect optimal tone, dynamic range, and speed for this slide")
        self.btn_auto_tone.setFixedWidth(60)
        self.btn_auto_tone.clicked.connect(self._on_auto_detect_current_slide)
        tone_bar.addWidget(self.btn_auto_tone)
        ctrl_layout.addLayout(tone_bar)

        self.lbl_tone_reason = QLabel("")
        self.lbl_tone_reason.setStyleSheet("color: #38bdf8; font-size: 11px; font-style: italic;")
        self.lbl_tone_reason.setWordWrap(True)
        ctrl_layout.addWidget(self.lbl_tone_reason)

        express_row = QHBoxLayout()
        express_row.addWidget(QLabel("Expressiveness:"))
        self.slider_exaggeration = QSlider(Qt.Orientation.Horizontal)
        self.slider_exaggeration.setRange(40, 120)
        self.slider_exaggeration.setValue(65)
        self.slider_exaggeration.valueChanged.connect(self._update_express_label)
        express_row.addWidget(self.slider_exaggeration)
        self.lbl_express_val = QLabel("0.65")
        self.lbl_express_val.setFixedWidth(40)
        express_row.addWidget(self.lbl_express_val)
        ctrl_layout.addLayout(express_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(70, 140)
        self.slider_speed.setValue(100)
        self.slider_speed.valueChanged.connect(self._update_speed_label)
        speed_row.addWidget(self.slider_speed)
        self.lbl_speed_val = QLabel("1.00x")
        self.lbl_speed_val.setFixedWidth(40)
        speed_row.addWidget(self.lbl_speed_val)
        ctrl_layout.addLayout(speed_row)

        action_layout.addWidget(grp_controls)

        # Slide Audio Generation
        grp_gen = QGroupBox("Slide Audio Synthesis")
        gen_box_layout = QVBoxLayout(grp_gen)

        self.btn_gen_slide_audio = QPushButton("⚡ Generate Slide Audio")
        self.btn_gen_slide_audio.setObjectName("primaryBtn")
        self.btn_gen_slide_audio.setFixedHeight(36)
        self.btn_gen_slide_audio.clicked.connect(self._on_generate_slide_audio)
        gen_box_layout.addWidget(self.btn_gen_slide_audio)

        self.slide_prog_bar = QProgressBar()
        self.slide_prog_bar.setRange(0, 100)
        self.slide_prog_bar.setValue(0)
        self.slide_prog_bar.setFixedHeight(12)
        self.slide_prog_bar.setVisible(False)
        gen_box_layout.addWidget(self.slide_prog_bar)

        self.lbl_slide_status = QLabel("Ready")
        self.lbl_slide_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        gen_box_layout.addWidget(self.lbl_slide_status)

        self.player_widget = AudioPlayerWidget()
        gen_box_layout.addWidget(self.player_widget)

        self.btn_embed_slide_audio = QPushButton("🔊 Embed Audio Into Slide Now (Autoplay)")
        self.btn_embed_slide_audio.clicked.connect(self._on_embed_slide_audio_live)
        gen_box_layout.addWidget(self.btn_embed_slide_audio)

        action_layout.addWidget(grp_gen)

        # Video Attachment Group
        grp_video = QGroupBox("Screen Recording Attachment")
        video_layout = QVBoxLayout(grp_video)
        self.lbl_attached_video = QLabel("No MP4 attached to this slide")
        self.lbl_attached_video.setStyleSheet("color: #94a3b8; font-size: 11px;")
        video_layout.addWidget(self.lbl_attached_video)

        vid_btn_layout = QHBoxLayout()
        self.btn_attach_video = QPushButton("🎬 Select MP4 Video...")
        self.btn_attach_video.clicked.connect(self._on_attach_video)
        vid_btn_layout.addWidget(self.btn_attach_video)

        self.btn_embed_video = QPushButton("Embed Video")
        self.btn_embed_video.setEnabled(False)
        self.btn_embed_video.clicked.connect(self._on_embed_video_live)
        vid_btn_layout.addWidget(self.btn_embed_video)
        video_layout.addLayout(vid_btn_layout)

        action_layout.addWidget(grp_video)
        action_layout.addStretch()

        splitter.addWidget(action_widget)
        splitter.setSizes([260, 480, 360])
        main_layout.addWidget(splitter)

    def refresh_voices(self):
        curr = self.cmb_voice.currentData()
        self.cmb_voice.clear()
        self.cmb_voice.addItem("Default Chatterbox Voice", "")
        profiles = self.voice_mgr.list_profiles()
        for p in profiles:
            self.cmb_voice.addItem(f"{p['name']} ({p.get('primary_language','').upper()})", p["id"])
        if curr:
            idx = self.cmb_voice.findData(curr)
            if idx >= 0:
                self.cmb_voice.setCurrentIndex(idx)
        elif profiles:
            self.cmb_voice.setCurrentIndex(1)

    def _update_speed_label(self, val):
        self.lbl_speed_val.setText(f"{val/100.0:.2f}x")
        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx]["speed"] = val / 100.0

    def _update_express_label(self, val):
        self.lbl_express_val.setText(f"{val/100.0:.2f}")
        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx]["exaggeration"] = val / 100.0

    def _on_tone_style_changed(self, idx):
        style_key = self.cmb_tone_style.currentData()
        if not style_key or style_key not in TONE_STYLES:
            return
        info = TONE_STYLES[style_key]
        self.slider_exaggeration.blockSignals(True)
        self.slider_exaggeration.setValue(int(info["exaggeration"] * 100))
        self.lbl_express_val.setText(f"{info['exaggeration']:.2f}")
        self.slider_exaggeration.blockSignals(False)

        self.slider_speed.blockSignals(True)
        self.slider_speed.setValue(int(info["speed"] * 100))
        self.lbl_speed_val.setText(f"{info['speed']:.2f}x")
        self.slider_speed.blockSignals(False)

        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx]["tone_style"] = style_key
            self.current_project.slides[self.current_slide_idx]["exaggeration"] = info["exaggeration"]
            self.current_project.slides[self.current_slide_idx]["speed"] = info["speed"]

    def _on_open_pptx(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PowerPoint Presentation",
            "",
            "PowerPoint Presentations (*.pptx)",
        )
        if not file_path:
            return

        self.lbl_pptx_file.setText(f"Loading {Path(file_path).name}...")
        self.extract_worker = PPTXExtractWorker(file_path, generate_thumbnails=True)
        self.extract_worker.finished.connect(lambda slides: self._on_pptx_loaded(file_path, slides))
        self.extract_worker.error.connect(lambda err: QMessageBox.critical(self, "Load Failed", err))
        self.extract_worker.start()

    def _on_pptx_loaded(self, pptx_path: str, slides: list[dict]):
        self.current_project = ProjectModel(
            name=Path(pptx_path).stem,
            pptx_path=pptx_path,
        )
        total = len(slides)
        # Automatically distribute tones across slides so no two slides share monotone delivery
        for i, s in enumerate(slides):
            if "tone_style" not in s or not s.get("tone_style"):
                content = s.get("notes", "") or s.get("body", "")
                h = detect_slide_tone_heuristic(content, i, total)
                s["tone_style"] = h["tone_style"]
                s["exaggeration"] = h["exaggeration"]
                s["speed"] = h["speed"]
                s["pause_ms"] = h["pause_ms"]
                s["tone_reason"] = h["reason"]

        self.current_project.slides = slides
        self.lbl_pptx_file.setText(f"Loaded: {Path(pptx_path).name}")
        self.lbl_slide_count.setText(f"{len(slides)} slides")
        self._refresh_slide_list()
        if slides:
            self.slide_list.setCurrentRow(0)

    def _refresh_slide_list(self):
        self.slide_list.clear()
        for idx, s in enumerate(self.current_project.slides):
            num = s.get("slide_number", idx + 1)
            title = s.get("title", f"Slide {num}")
            item = QListWidgetItem()

            # Status indicators
            status_en = "🇬🇧" if s.get("audio_en_path") else ""
            status_de = "🇩🇪" if s.get("audio_de_path") else ""
            status_vid = "🎬" if s.get("video_path") else ""

            # Tone badge
            tone = s.get("tone_style", "engaging")
            if tone == "energetic_hook":
                tone_badge = "[🚀 Hook]"
            elif tone == "deep_dive":
                tone_badge = "[🔬 Deep]"
            elif tone == "key_takeaway":
                tone_badge = "[💡 Takeaway]"
            else:
                tone_badge = "[🎙️ Live]"

            flags = " ".join(filter(None, [tone_badge, status_en, status_de, status_vid]))
            item.setText(f"{num}. {title}  {flags}".strip())

            # Thumbnail if available
            thumb = s.get("thumbnail_path")
            if thumb and Path(thumb).exists():
                item.setIcon(QIcon(thumb))

            self.slide_list.addItem(item)

    def _on_slide_selected(self, row: int):
        if row < 0 or row >= len(self.current_project.slides):
            self.current_slide_idx = -1
            return

        self.current_slide_idx = row
        slide = self.current_project.slides[row]

        self.lbl_current_slide_title.setText(f"Slide {slide.get('slide_number', row+1)}: {slide.get('title', '')}")
        self.txt_slide_body.setPlainText(slide.get("body_text", ""))
        self.txt_slide_notes.setPlainText(slide.get("notes", ""))

        # Set scripts
        self.txt_script_en.blockSignals(True)
        self.txt_script_en.setPlainText(slide.get("script_en", ""))
        self.txt_script_en.blockSignals(False)

        self.txt_script_de.blockSignals(True)
        self.txt_script_de.setPlainText(slide.get("script_de", ""))
        self.txt_script_de.blockSignals(False)

        # Video status
        vid = slide.get("video_path")
        if vid and Path(vid).exists():
            self.lbl_attached_video.setText(f"Attached: {Path(vid).name}")
            self.btn_embed_video.setEnabled(True)
        else:
            self.lbl_attached_video.setText("No MP4 attached to this slide")
            self.btn_embed_video.setEnabled(False)

        # Restore slide tone & pacing controls
        tone = slide.get("tone_style", "engaging")
        t_idx = self.cmb_tone_style.findData(tone)
        if t_idx >= 0:
            self.cmb_tone_style.blockSignals(True)
            self.cmb_tone_style.setCurrentIndex(t_idx)
            self.cmb_tone_style.blockSignals(False)

        sp = slide.get("speed", 1.0)
        self.slider_speed.blockSignals(True)
        self.slider_speed.setValue(int(sp * 100))
        self.lbl_speed_val.setText(f"{sp:.2f}x")
        self.slider_speed.blockSignals(False)

        ex = slide.get("exaggeration", 0.60)
        self.slider_exaggeration.blockSignals(True)
        self.slider_exaggeration.setValue(int(ex * 100))
        self.lbl_express_val.setText(f"{ex:.2f}")
        self.slider_exaggeration.blockSignals(False)

        reason = slide.get("tone_reason", "")
        self.lbl_tone_reason.setText(f"ℹ️ {reason}" if reason else "")

        # Load active audio
        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        audio_key = f"audio_{active_lang}_path"
        audio_path = slide.get(audio_key)
        if audio_path and Path(audio_path).exists():
            self.player_widget.load_audio(audio_path)
        else:
            self.player_widget.stop()

    def _on_script_en_changed(self):
        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx]["script_en"] = self.txt_script_en.toPlainText()

    def _on_script_de_changed(self):
        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx]["script_de"] = self.txt_script_de.toPlainText()

    def _copy_notes_to_script(self, lang: str):
        notes = self.txt_slide_notes.toPlainText().strip()
        if not notes:
            QMessageBox.information(self, "No Notes", "This slide has no PowerPoint speaker notes.")
            return

        if lang == "en":
            self.txt_script_en.setPlainText(notes)
            self.script_tabs.setCurrentIndex(0)
        else:
            self.txt_script_de.setPlainText(notes)
            self.script_tabs.setCurrentIndex(1)

    def _on_humanize_script(self):
        if self.current_slide_idx < 0:
            QMessageBox.information(self, "No Slide", "Please select a slide first.")
            return

        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        current_text = self.txt_script_en.toPlainText().strip() if active_lang == "en" else self.txt_script_de.toPlainText().strip()
        notes_text = self.txt_slide_notes.toPlainText().strip()
        body_text = self.txt_slide_body.toPlainText().strip()

        source_text = current_text or notes_text or body_text
        if not source_text:
            QMessageBox.warning(self, "Empty Source", "This slide has no script, notes, or body text to direct.")
            return

        tone_key = self.cmb_tone_style.currentData() or "engaging"

        self.btn_humanize_script.setEnabled(False)
        self.btn_humanize_script.setText("✨ Directing with Gemini...")
        self.lbl_slide_status.setText("Transforming into spoken narration via Gemini...")

        self.humanize_worker = HumanizeWorker(
            raw_text=source_text,
            language=active_lang,
            tone=tone_key,
        )
        self.humanize_worker.finished.connect(lambda result: self._on_humanize_finished(active_lang, result))
        self.humanize_worker.error.connect(self._on_humanize_error)
        self.humanize_worker.start()

    def _on_humanize_finished(self, lang: str, result_script: str):
        self.btn_humanize_script.setEnabled(True)
        self.btn_humanize_script.setText("✨ Direct Narration (Gemini)")
        self.lbl_slide_status.setText("Narration script ready!")

        if lang == "en":
            self.txt_script_en.setPlainText(result_script)
            self.script_tabs.setCurrentIndex(0)
            if self.current_slide_idx >= 0:
                self.current_project.slides[self.current_slide_idx]["script_en"] = result_script
        else:
            self.txt_script_de.setPlainText(result_script)
            self.script_tabs.setCurrentIndex(1)
            if self.current_slide_idx >= 0:
                self.current_project.slides[self.current_slide_idx]["script_de"] = result_script

    def _on_humanize_error(self, err: str):
        self.btn_humanize_script.setEnabled(True)
        self.btn_humanize_script.setText("✨ Direct Narration (Gemini)")
        self.lbl_slide_status.setText("Direction failed")
        QMessageBox.warning(self, "Gemini Script Director", f"Could not direct narration:\n{err}")

    def _on_auto_detect_current_slide(self):
        if self.current_slide_idx < 0:
            QMessageBox.information(self, "No Slide", "Please select a slide first.")
            return

        slide = self.current_project.slides[self.current_slide_idx]
        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        current_text = self.txt_script_en.toPlainText().strip() if active_lang == "en" else self.txt_script_de.toPlainText().strip()
        notes_text = self.txt_slide_notes.toPlainText().strip()
        body_text = self.txt_slide_body.toPlainText().strip()

        source_text = current_text or notes_text or body_text
        total = len(self.current_project.slides)

        self.btn_auto_tone.setEnabled(False)
        self.btn_auto_tone.setText("⏳")
        self.lbl_slide_status.setText("Auto-detecting optimal tone & prosody...")

        self.auto_slide_worker = AutoDirectSlideWorker(
            raw_text=source_text,
            slide_index=self.current_slide_idx,
            total_slides=total,
            language=active_lang,
        )
        self.auto_slide_worker.finished.connect(self._on_auto_detect_slide_finished)
        self.auto_slide_worker.error.connect(self._on_auto_detect_slide_error)
        self.auto_slide_worker.start()

    def _on_auto_detect_slide_finished(self, result: dict):
        self.btn_auto_tone.setEnabled(True)
        self.btn_auto_tone.setText("🪄 Auto")
        self.lbl_slide_status.setText("Tone & prosody auto-tuned!")

        if self.current_slide_idx < 0:
            return

        slide = self.current_project.slides[self.current_slide_idx]
        slide["tone_style"] = result["tone_style"]
        slide["exaggeration"] = result["exaggeration"]
        slide["speed"] = result["speed"]
        slide["pause_ms"] = result.get("pause_ms", 250)
        slide["tone_reason"] = result.get("reason", "")

        t_idx = self.cmb_tone_style.findData(result["tone_style"])
        if t_idx >= 0:
            self.cmb_tone_style.blockSignals(True)
            self.cmb_tone_style.setCurrentIndex(t_idx)
            self.cmb_tone_style.blockSignals(False)

        self.slider_exaggeration.setValue(int(result["exaggeration"] * 100))
        self.lbl_express_val.setText(f"{result['exaggeration']:.2f}")

        self.slider_speed.setValue(int(result["speed"] * 100))
        self.lbl_speed_val.setText(f"{result['speed']:.2f}x")

        self.lbl_tone_reason.setText(f"ℹ️ {result.get('reason', '')}")
        self._refresh_slide_list()

    def _on_auto_detect_slide_error(self, err: str):
        self.btn_auto_tone.setEnabled(True)
        self.btn_auto_tone.setText("🪄 Auto")
        self.lbl_slide_status.setText("Auto-tone failed")
        QMessageBox.warning(self, "Auto-Tone Error", f"Could not auto-detect tone:\n{err}")

    def _on_auto_direct_all(self):
        if not self.current_project.slides:
            QMessageBox.information(self, "No Slides", "Please load a PowerPoint presentation first.")
            return

        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        reply = QMessageBox.question(
            self,
            "Auto-Direct Entire Presentation",
            f"This will analyze all {len(self.current_project.slides)} slides with Gemini AI,\n"
            f"automatically assign varied tone styles (hooks, deep-dives, takeaways),\n"
            f"tune dynamic pitch ranges, and generate spoken narration for {active_lang.upper()}.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_auto_direct_all.setEnabled(False)
        self.btn_batch_generate_all.setEnabled(False)
        self.batch_prog_bar.setVisible(True)
        self.batch_prog_bar.setValue(0)
        self.lbl_batch_status.setText("Analyzing slides with Gemini...")

        self.auto_direct_worker = AutoDirectPresentationWorker(
            slides=self.current_project.slides,
            language=active_lang,
        )
        self.auto_direct_worker.progress.connect(self._on_auto_direct_all_progress)
        self.auto_direct_worker.finished.connect(self._on_auto_direct_all_finished)
        self.auto_direct_worker.error.connect(self._on_auto_direct_all_error)
        self.auto_direct_worker.start()

    def _on_auto_direct_all_progress(self, cur: int, total: int, msg: str):
        pct = int((cur / max(1, total)) * 100)
        self.batch_prog_bar.setValue(pct)
        self.lbl_batch_status.setText(msg)

    def _on_auto_direct_all_finished(self, updated_slides: list[dict]):
        self.btn_auto_direct_all.setEnabled(True)
        self.btn_batch_generate_all.setEnabled(True)
        self.batch_prog_bar.setVisible(False)
        self.lbl_batch_status.setText("✨ Presentation auto-directed successfully!")

        self.current_project.slides = updated_slides
        self._refresh_slide_list()
        if 0 <= self.current_slide_idx < len(updated_slides):
            self._on_slide_selected(self.current_slide_idx)
        QMessageBox.information(
            self,
            "Auto-Direction Complete",
            f"All {len(updated_slides)} slides have been analyzed and given distinct tone styles, pitch curves, and spoken scripts!",
        )

    def _on_check_storyline(self):
        if not self.current_project.slides:
            QMessageBox.information(self, "No Slides", "Please load a PowerPoint presentation first.")
            return

        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        self.btn_check_storyline.setEnabled(False)
        self.btn_batch_generate_all.setEnabled(False)
        self.batch_prog_bar.setVisible(True)
        self.batch_prog_bar.setValue(50)
        self.lbl_batch_status.setText("Analyzing deck narrative arc & storylines...")

        self.storyline_worker = StorylineAnalysisWorker(
            slides=self.current_project.slides,
            language=active_lang,
        )
        self.storyline_worker.finished.connect(self._on_storyline_finished)
        self.storyline_worker.error.connect(self._on_storyline_error)
        self.storyline_worker.start()

    def _on_storyline_finished(self, updated_slides: list[dict]):
        self.btn_check_storyline.setEnabled(True)
        self.btn_batch_generate_all.setEnabled(True)
        self.batch_prog_bar.setVisible(False)
        self.lbl_batch_status.setText("Storyline & tones balanced!")

        self.current_project.slides = updated_slides
        self._refresh_slide_list()
        if 0 <= self.current_slide_idx < len(updated_slides):
            self._on_slide_selected(self.current_slide_idx)

        # Build breakdown dialog
        lines = []
        for s in updated_slides[:10]:
            num = s.get("slide_number", 1)
            title = s.get("title", f"Slide {num}")
            reason = s.get("tone_reason", "")
            lines.append(f"• Slide {num} ({title}): {reason}")
        if len(updated_slides) > 10:
            lines.append(f"... and {len(updated_slides) - 10} more slides")

        summary = "\n".join(lines)
        QMessageBox.information(
            self,
            "Storyline Analysis Complete",
            f"Analyzed {len(updated_slides)} slides. Tone styles and dynamic pitch curves adjusted without changing your script text:\n\n"
            f"{summary}\n\n"
            "You can now synthesize audio and embed into PowerPoint!",
        )

    def _on_storyline_error(self, err: str):
        self.btn_check_storyline.setEnabled(True)
        self.btn_batch_generate_all.setEnabled(True)
        self.batch_prog_bar.setVisible(False)
        self.lbl_batch_status.setText("Storyline analysis failed")
        QMessageBox.warning(self, "Storyline Analysis Error", f"Could not analyze storyline:\n{err}")

    def _on_batch_generate_all_audios(self):
        if not self.current_project.slides:
            QMessageBox.information(self, "No Slides", "Please load a presentation first.")
            return

        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        script_key = "script_en" if active_lang == "en" else "script_de"
        slides_with_script = [s for s in self.current_project.slides if s.get(script_key, "").strip()]

        if not slides_with_script:
            QMessageBox.warning(
                self,
                "No Scripts Found",
                f"No slides have {active_lang.upper()} narration script yet.\n"
                "Tip: Click '🪄 Auto-Direct All Slides (AI)' first to generate scripts with optimal tones!",
            )
            return

        profile_id = self.cmb_voice.currentData()
        ref_audio = None
        if profile_id:
            p = self.voice_mgr.get_profile(profile_id)
            if p and "reference_audio" in p:
                ref_audio = p["reference_audio"]

        self.btn_auto_direct_all.setEnabled(False)
        self.btn_batch_generate_all.setEnabled(False)
        self.batch_prog_bar.setVisible(True)
        self.batch_prog_bar.setValue(0)
        self.lbl_batch_status.setText(f"Generating audio for {len(slides_with_script)} slides...")

        self.batch_tts_worker = BatchGenerateAudioWorker(
            slides=self.current_project.slides,
            language=active_lang,
            reference_audio_path=ref_audio,
        )
        self.batch_tts_worker.progress.connect(self._on_batch_tts_progress)
        self.batch_tts_worker.finished.connect(self._on_batch_tts_finished)
        self.batch_tts_worker.error.connect(self._on_batch_tts_error)
        self.batch_tts_worker.start()

    def _on_batch_tts_progress(self, cur: int, total: int, msg: str):
        pct = int((cur / max(1, total)) * 100)
        self.batch_prog_bar.setValue(pct)
        self.lbl_batch_status.setText(msg)

    def _on_batch_tts_finished(self, updated_slides: list[dict]):
        self.btn_auto_direct_all.setEnabled(True)
        self.btn_batch_generate_all.setEnabled(True)
        self.batch_prog_bar.setVisible(False)
        self.lbl_batch_status.setText("⚡ All slide audios synthesized!")

        self.current_project.slides = updated_slides
        self._refresh_slide_list()
        if 0 <= self.current_slide_idx < len(updated_slides):
            self._on_slide_selected(self.current_slide_idx)
        QMessageBox.information(
            self,
            "Batch Audio Ready",
            "Audio generated for all slides with their individual tone ranges!\nYou can now click 'Embed Audio' or 'Export Presentation'.",
        )

    def _on_batch_tts_error(self, err: str):
        self.btn_auto_direct_all.setEnabled(True)
        self.btn_batch_generate_all.setEnabled(True)
        self.batch_prog_bar.setVisible(False)
        self.lbl_batch_status.setText("Batch TTS failed")
        QMessageBox.warning(self, "Batch Audio Error", f"Synthesis error:\n{err}")

    def _on_generate_slide_audio(self):
        if self.current_slide_idx < 0:
            return

        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        script = self.txt_script_en.toPlainText().strip() if active_lang == "en" else self.txt_script_de.toPlainText().strip()

        if not script:
            QMessageBox.warning(self, "Empty Script", f"Please enter {active_lang.upper()} narration script for this slide.")
            return

        profile_id = self.cmb_voice.currentData()
        ref_audio = None
        if profile_id:
            p = self.voice_mgr.get_profile(profile_id)
            if p and "reference_audio" in p:
                ref_audio = p["reference_audio"]

        speed = self.slider_speed.value() / 100.0
        exaggeration = self.slider_exaggeration.value() / 100.0

        slide = self.current_project.slides[self.current_slide_idx] if (self.current_project and 0 <= self.current_slide_idx < len(self.current_project.slides)) else {}
        slide_pause_ms = slide.get("pause_ms", 250)
        slide_temperature = slide.get("temperature", 0.82)
        slide_cfg_weight = slide.get("cfg_weight", 0.35)
        slide_native_accent = slide.get("native_accent", False)

        self.btn_gen_slide_audio.setEnabled(False)
        self.slide_prog_bar.setVisible(True)
        self.slide_prog_bar.setValue(0)
        self.lbl_slide_status.setText("Synthesizing slide speech...")

        self.tts_worker = TTSWorker(
            text=script,
            language=active_lang,
            reference_audio_path=ref_audio,
            speed=speed,
            exaggeration=exaggeration,
            pause_duration_ms=slide_pause_ms,
            temperature=slide_temperature,
            cfg_weight=slide_cfg_weight,
            native_accent=slide_native_accent,
        )
        self.tts_worker.progress.connect(lambda cur, tot, msg: self.slide_prog_bar.setValue(int(cur / tot * 100)))
        self.tts_worker.finished.connect(lambda path: self._on_slide_audio_finished(active_lang, path))
        self.tts_worker.error.connect(self._on_slide_audio_error)
        self.tts_worker.start()

    def _on_slide_audio_finished(self, lang: str, wav_path: str):
        self.btn_gen_slide_audio.setEnabled(True)
        self.slide_prog_bar.setVisible(False)
        self.lbl_slide_status.setText("Slide audio ready!")

        if self.current_slide_idx >= 0:
            self.current_project.slides[self.current_slide_idx][f"audio_{lang}_path"] = wav_path
            self._refresh_slide_list()
            self.slide_list.setCurrentRow(self.current_slide_idx)

        self.player_widget.load_audio(wav_path)

    def _on_slide_audio_error(self, err: str):
        self.btn_gen_slide_audio.setEnabled(True)
        self.slide_prog_bar.setVisible(False)
        self.lbl_slide_status.setText("Generation error")
        QMessageBox.critical(self, "Generation Failed", err)

    def _on_embed_slide_audio_live(self):
        if self.current_slide_idx < 0:
            return

        slide_data = self.current_project.slides[self.current_slide_idx]
        active_lang = "en" if self.script_tabs.currentIndex() == 0 else "de"
        audio_path = slide_data.get(f"audio_{active_lang}_path")

        if not audio_path or not Path(audio_path).exists():
            QMessageBox.warning(self, "No Audio", "Generate audio for this slide first.")
            return

        pptx_path = self.current_project.pptx_path
        if not pptx_path or not Path(pptx_path).exists():
            QMessageBox.warning(self, "No Presentation", "Please open a presentation first.")
            return

        try:
            import win32com.client
            import time
            ppt = win32com.client.Dispatch("PowerPoint.Application")
            pres = ppt.Presentations.Open(pptx_path, ReadOnly=False, Untitled=False, WithWindow=True)
            service = PowerPointService()
            service.embed_audio_to_slide(pres, slide_data["slide_number"], audio_path, autoplay=True)
            pres.Save()
            time.sleep(0.3)
            try:
                pres.Close()
            except Exception:
                pass
            QMessageBox.information(self, "Success", f"Audio embedded into Slide {slide_data['slide_number']} with autoplay enabled!")
        except Exception as e:
            QMessageBox.critical(self, "Embedding Error", str(e))

    def _on_attach_video(self):
        if self.current_slide_idx < 0:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select MP4 Screen Recording",
            "",
            "MP4 Video (*.mp4 *.mkv *.mov)",
        )
        if file_path:
            self.current_project.slides[self.current_slide_idx]["video_path"] = file_path
            self.lbl_attached_video.setText(f"Attached: {Path(file_path).name}")
            self.btn_embed_video.setEnabled(True)
            self._refresh_slide_list()
            self.slide_list.setCurrentRow(self.current_slide_idx)

    def _on_embed_video_live(self):
        if self.current_slide_idx < 0:
            return

        slide_data = self.current_project.slides[self.current_slide_idx]
        video_path = slide_data.get("video_path")
        if not video_path or not Path(video_path).exists():
            return

        pptx_path = self.current_project.pptx_path
        try:
            import win32com.client
            import time
            ppt = win32com.client.Dispatch("PowerPoint.Application")
            pres = ppt.Presentations.Open(pptx_path, ReadOnly=False, Untitled=False, WithWindow=True)
            service = PowerPointService()
            service.embed_video_to_slide(pres, slide_data["slide_number"], video_path, autoplay=False)
            pres.Save()
            time.sleep(0.3)
            try:
                pres.Close()
            except Exception:
                pass
            QMessageBox.information(self, "Success", f"Video embedded into Slide {slide_data['slide_number']}!")
        except Exception as e:
            QMessageBox.critical(self, "Video Embedding Error", str(e))

    def _on_save_project(self):
        if not self.current_project.slides:
            QMessageBox.warning(self, "Empty Project", "No slides to save.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Voice Studio Project",
            "",
            "Voice Studio Projects (*.vsproj)",
        )
        if file_path:
            out = self.project_mgr.save_project(self.current_project, file_path)
            QMessageBox.information(self, "Project Saved", f"Saved: {Path(out).name}")

    def _on_load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Voice Studio Project",
            "",
            "Voice Studio Projects (*.vsproj)",
        )
        if file_path:
            try:
                self.current_project = self.project_mgr.load_project(file_path)
                self.lbl_pptx_file.setText(f"Project: {self.current_project.name}")
                self.lbl_slide_count.setText(f"{len(self.current_project.slides)} slides")
                self._refresh_slide_list()
                if self.current_project.slides:
                    self.slide_list.setCurrentRow(0)
            except Exception as e:
                QMessageBox.critical(self, "Load Failed", str(e))

    def _on_export_presentation(self, lang: str):
        if not self.current_project.pptx_path or not Path(self.current_project.pptx_path).exists():
            QMessageBox.warning(self, "No PPTX", "Please open a PowerPoint file first.")
            return

        audio_map = {}
        for s in self.current_project.slides:
            num = s.get("slide_number")
            aud = s.get(f"audio_{lang}_path")
            if aud and Path(aud).exists():
                audio_map[num] = aud

        if not audio_map:
            QMessageBox.warning(self, "No Audio Generated", f"No {lang.upper()} audio has been generated yet for any slides.")
            return

        video_map = {}
        for s in self.current_project.slides:
            num = s.get("slide_number")
            vid = s.get("video_path")
            if vid and Path(vid).exists():
                video_map[num] = vid

        stem = Path(self.current_project.pptx_path).stem
        default_out = str(EXPORTS_DIR / f"{stem}_{lang.upper()}_Narrated.pptx")
        dest_file, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {lang.upper()} Narrated PowerPoint",
            default_out,
            "PowerPoint Presentations (*.pptx)",
        )
        if not dest_file:
            return

        self.lbl_pptx_file.setText(f"Exporting {lang.upper()} presentation...")
        self.batch_worker = PPTXBatchExportWorker(
            source_pptx=self.current_project.pptx_path,
            output_pptx=dest_file,
            slide_audio_map=audio_map,
            slide_video_map=video_map,
        )
        self.batch_worker.progress.connect(lambda cur, tot, msg: self.lbl_pptx_file.setText(msg))
        self.batch_worker.finished.connect(lambda out: self._on_export_finished(out))
        self.batch_worker.error.connect(lambda err: QMessageBox.critical(self, "Export Failed", err))
        self.batch_worker.start()

    def _on_export_finished(self, out_file: str):
        self.lbl_pptx_file.setText(f"Exported: {Path(out_file).name}")
        QMessageBox.information(
            self,
            "Export Complete",
            f"Successfully created presentation:\n\n{out_file}\n\nAll slide audios configured to play automatically when slides transition!",
        )
