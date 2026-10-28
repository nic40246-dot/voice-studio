from pathlib import Path
from PySide6.QtCore import QTime, QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class AudioPlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_file = None
        self._init_player()
        self._init_ui()

    def _init_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.9)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # File label
        self.lbl_file = QLabel("No audio loaded")
        self.lbl_file.setStyleSheet("color: #94a3b8; font-size: 11px;")
        main_layout.addWidget(self.lbl_file)

        # Controls row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setFixedWidth(80)
        self.btn_play.setObjectName("primaryBtn")
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setFixedWidth(70)
        self.btn_stop.clicked.connect(self.stop)
        ctrl_layout.addWidget(self.btn_stop)

        # Position slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        ctrl_layout.addWidget(self.slider)

        # Time label
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("font-family: monospace; font-size: 11px; color: #cbd5e1;")
        ctrl_layout.addWidget(self.lbl_time)

        # Volume slider
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(90)
        self.vol_slider.setFixedWidth(70)
        self.vol_slider.setToolTip("Volume")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        ctrl_layout.addWidget(self.vol_slider)

        main_layout.addLayout(ctrl_layout)

    def load_audio(self, file_path: str | Path):
        file_path = Path(file_path)
        if not file_path.exists():
            return

        self.player.stop()
        self.current_file = str(file_path.resolve())
        self.lbl_file.setText(f"File: {file_path.name}")
        self.player.setSource(QUrl.fromLocalFile(self.current_file))
        self.btn_play.setEnabled(True)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.player.stop()

    def set_position(self, position):
        self.player.setPosition(position)

    def _on_volume_changed(self, val):
        self.audio_output.setVolume(val / 100.0)

    def _on_position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self._update_time_label(position, self.player.duration())

    def _on_duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self._update_time_label(self.player.position(), duration)

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ Pause")
        else:
            self.btn_play.setText("▶ Play")

    def _update_time_label(self, pos, dur):
        pos_t = QTime(0, 0, 0).addMSecs(pos).toString("mm:ss")
        dur_t = QTime(0, 0, 0).addMSecs(dur).toString("mm:ss")
        self.lbl_time.setText(f"{pos_t} / {dur_t}")
