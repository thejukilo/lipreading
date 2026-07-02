"""Friendly desktop UI — set everything up and run, no terminal needed.

One window: a Setup panel (camera, mic-to-Meet, voice, push-to-talk key, mode),
a live webcam preview, the transcript with Speak / Discard / Edit, and a big
Start / Stop button. Settings are saved to ~/.lipreading/config.json.

Run:  python -m server.gui_app   (or double-click run.bat)
"""

from __future__ import annotations

import sys
import threading

from PySide6 import QtCore, QtGui, QtWidgets

from .devices import list_audio_outputs, list_cameras
from .hotkey import PushToTalkListener
from .session import LiveSession
from .settings import load_config, save_config

# Push-to-talk key: friendly label -> internal name.
PTT_KEYS = {
    "Right Ctrl": "ctrl_r", "Left Ctrl": "ctrl_l", "Right Alt": "alt_r",
    "Space": "space", "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10",
}
VOICES = {"Piper (natural, local)": "piper", "Windows voice (SAPI)": "sapi"}

STATE_BANNER = {
    LiveSession.IDLE: ("Ready — hold your push-to-talk key and mouth a sentence", "#2e7d32"),
    LiveSession.RECORDING: ("● Recording — mouth your sentence", "#c62828"),
    LiveSession.BUSY: ("… transcribing", "#f9a825"),
    LiveSession.REVIEW: ("Review the text below, then Speak or Discard", "#1565c0"),
    LiveSession.SPEAKING: ("♪ speaking into Meet", "#6a1b9a"),
}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Lipreading → Voice")
        self.cfg = load_config()
        self.session = LiveSession(self.cfg)
        self.ptt = PushToTalkListener(self.cfg.ptt_key, self._ptt_down, self._ptt_up)
        self._starting = False
        self._last_state = None

        self._build_ui()
        self._populate_devices()
        self._apply_cfg_to_widgets()
        self._set_running_ui(False)

        # Poll the session for preview + state (keeps all UI updates on this thread).
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

        try:
            self.ptt.start()
        except Exception as e:
            self._status(f"push-to-talk unavailable: {e}")

    # ---- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        # Left: setup panel
        setup = QtWidgets.QGroupBox("Setup")
        form = QtWidgets.QFormLayout(setup)
        self.camera_cb = QtWidgets.QComboBox()
        self.mic_cb = QtWidgets.QComboBox()
        self.monitor_chk = QtWidgets.QCheckBox("Hear it on my speakers (monitor)")
        self.monitor_cb = QtWidgets.QComboBox()
        self.voice_cb = QtWidgets.QComboBox()
        self.voice_cb.addItems(list(VOICES.keys()))
        self.key_cb = QtWidgets.QComboBox()
        self.key_cb.addItems(list(PTT_KEYS.keys()))
        self.auto_chk = QtWidgets.QCheckBox("Speak immediately (skip review)")
        self.refresh_btn = QtWidgets.QPushButton("Refresh devices")

        form.addRow("Camera:", self.camera_cb)
        form.addRow("Microphone to Meet:", self.mic_cb)
        form.addRow("", self.monitor_chk)
        form.addRow("Monitor speakers:", self.monitor_cb)
        form.addRow("Voice:", self.voice_cb)
        form.addRow("Push-to-talk key:", self.key_cb)
        form.addRow("", self.auto_chk)
        form.addRow("", self.refresh_btn)
        self.mic_hint = QtWidgets.QLabel()
        self.mic_hint.setWordWrap(True)
        self.mic_hint.setStyleSheet("color:#b71c1c;")
        form.addRow(self.mic_hint)
        setup.setMaximumWidth(360)

        # Right: preview + transcript + controls
        right = QtWidgets.QVBoxLayout()
        self.banner = QtWidgets.QLabel("Press Start")
        self.banner.setAlignment(QtCore.Qt.AlignCenter)
        self.banner.setStyleSheet("padding:6px; color:white; background:#555; border-radius:4px;")
        self.preview = QtWidgets.QLabel()
        self.preview.setFixedSize(640, 480)
        self.preview.setStyleSheet("background:#111;")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)

        self.transcript = QtWidgets.QLineEdit()
        self.transcript.setPlaceholderText("transcript will appear here…")
        self.speak_btn = QtWidgets.QPushButton("Speak ▶")
        self.discard_btn = QtWidgets.QPushButton("Discard")
        review_row = QtWidgets.QHBoxLayout()
        review_row.addWidget(self.transcript, 1)
        review_row.addWidget(self.speak_btn)
        review_row.addWidget(self.discard_btn)

        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.setMinimumHeight(40)
        self.talk_btn = QtWidgets.QPushButton("Hold to Talk")
        self.talk_btn.setMinimumHeight(40)
        ctrl_row = QtWidgets.QHBoxLayout()
        ctrl_row.addWidget(self.start_btn, 1)
        ctrl_row.addWidget(self.talk_btn, 1)

        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color:#555;")

        right.addWidget(self.banner)
        right.addWidget(self.preview)
        right.addLayout(review_row)
        right.addLayout(ctrl_row)
        right.addWidget(self.status)

        root.addWidget(setup)
        root.addLayout(right, 1)

        # Wiring
        self.refresh_btn.clicked.connect(self._populate_devices)
        self.start_btn.clicked.connect(self._toggle_start)
        self.talk_btn.pressed.connect(self._ptt_down)
        self.talk_btn.released.connect(self._ptt_up)
        self.speak_btn.clicked.connect(self._on_speak)
        self.discard_btn.clicked.connect(self.session.discard)
        self.monitor_chk.toggled.connect(lambda v: self.session.set_monitor(v))
        self.key_cb.currentTextChanged.connect(self._on_key_changed)

    # ---- device population + config <-> widgets ---------------------------

    def _populate_devices(self) -> None:
        self.camera_cb.clear()
        try:
            cams = list_cameras()
        except Exception as e:
            cams = []
            self._status(f"camera scan failed: {e}")
        if not cams:
            self.camera_cb.addItem("Camera 0", 0)
        for idx, label in cams:
            self.camera_cb.addItem(label, idx)

        try:
            outs = list_audio_outputs()
        except Exception as e:
            outs = []
            self._status(f"audio scan failed: {e}")
        self.mic_cb.clear()
        self.monitor_cb.clear()
        self.monitor_cb.addItem("System default", None)
        for idx, name in outs:
            self.mic_cb.addItem(name, name)
            self.monitor_cb.addItem(name, name)

        # Preselect the VB-Cable input for the Meet mic, and warn if absent.
        cable_row = next((i for i in range(self.mic_cb.count())
                          if "cable input" in self.mic_cb.itemText(i).lower()), -1)
        if cable_row >= 0:
            self.mic_cb.setCurrentIndex(cable_row)
            self.mic_hint.setText("")
        else:
            self.mic_hint.setText(
                "VB-Cable not found. Install it from vb-audio.com/Cable and reboot, "
                "then Refresh — Meet needs 'CABLE Output' as its mic."
            )

    def _apply_cfg_to_widgets(self) -> None:
        self._select_data(self.camera_cb, self.cfg.camera)
        if self.cfg.output_device is not None:
            self._select_text_contains(self.mic_cb, str(self.cfg.output_device))
        self.monitor_chk.setChecked(self.cfg.monitor_on)
        self._select_data(self.monitor_cb, self.cfg.monitor_device)
        self._select_key(self.voice_cb, VOICES, self.cfg.tts)
        self._select_key(self.key_cb, PTT_KEYS, self.cfg.ptt_key)
        self.auto_chk.setChecked(self.cfg.auto_speak)

    def _widgets_to_cfg(self) -> None:
        self.cfg.camera = self.camera_cb.currentData() if self.camera_cb.currentData() is not None else 0
        self.cfg.output_device = self.mic_cb.currentData()
        self.cfg.monitor_on = self.monitor_chk.isChecked()
        self.cfg.monitor_device = self.monitor_cb.currentData()
        self.cfg.tts = VOICES[self.voice_cb.currentText()]
        self.cfg.ptt_key = PTT_KEYS[self.key_cb.currentText()]
        self.cfg.auto_speak = self.auto_chk.isChecked()

    @staticmethod
    def _select_data(cb, data) -> None:
        for i in range(cb.count()):
            if cb.itemData(i) == data:
                cb.setCurrentIndex(i)
                return

    @staticmethod
    def _select_text_contains(cb, needle) -> None:
        needle = needle.lower()
        for i in range(cb.count()):
            if needle in cb.itemText(i).lower():
                cb.setCurrentIndex(i)
                return

    @staticmethod
    def _select_key(cb, mapping, value) -> None:
        for label, val in mapping.items():
            if val == value:
                cb.setCurrentText(label)
                return

    # ---- start / stop -----------------------------------------------------

    def _toggle_start(self) -> None:
        if self.session.is_running:
            self.session.stop()
            self._set_running_ui(False)
            self._status("stopped")
            return
        if self._starting:
            return
        self._widgets_to_cfg()
        save_config(self.cfg)
        self.session.cfg = self.cfg
        self._starting = True
        self.start_btn.setText("Starting…")
        self.start_btn.setEnabled(False)
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self) -> None:
        try:
            if not self.session.is_loaded:
                self.session.load()      # heavy: builds the model (first time only)
            else:
                self.session.reconfigure_audio()
            self.session.start()          # opens camera + capture thread
            self._start_error = None
        except Exception as e:
            self._start_error = str(e)
        finally:
            self._starting = False

    # ---- push-to-talk + review -------------------------------------------

    def _ptt_down(self) -> None:
        if self.session.is_running:
            self.session.start_recording()

    def _ptt_up(self) -> None:
        if self.session.is_running:
            self.session.stop_recording()

    def _on_speak(self) -> None:
        self.session.speak(self.transcript.text())

    def _on_key_changed(self, label: str) -> None:
        name = PTT_KEYS.get(label)
        if name:
            self.cfg.ptt_key = name
            try:
                self.ptt.set_key(name)
            except Exception as e:
                self._status(f"key change failed: {e}")

    # ---- periodic UI update ----------------------------------------------

    def _tick(self) -> None:
        if self._starting:
            return
        if getattr(self, "_start_error", None):
            self._status(f"! {self._start_error}")
            self._start_error = None
            self._set_running_ui(False)
        elif self.session.is_running and self.start_btn.text() != "Stop":
            self._set_running_ui(True)

        self._update_preview()
        self._update_state()
        if self.session.last_status:
            self.status.setText(self.session.last_status)

    def _update_preview(self) -> None:
        import cv2  # local: heavy import, only once running

        frame = self.session.latest_bgr
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(img).scaled(
            self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.preview.setPixmap(pix)

    def _update_state(self) -> None:
        st = self.session.state
        text, color = STATE_BANNER.get(st, ("", "#555"))
        if st == LiveSession.RECORDING:
            text = f"● Recording — {self.session.frame_count} frames"
        self.banner.setText(text)
        self.banner.setStyleSheet(
            f"padding:6px; color:white; background:{color}; border-radius:4px;"
        )
        # Transitions: populate the edit box when entering REVIEW.
        if st != self._last_state:
            if st == LiveSession.REVIEW:
                self.transcript.setText(self.session.pending_text)
            self._last_state = st
        review = st == LiveSession.REVIEW
        self.speak_btn.setEnabled(review or bool(self.transcript.text()))
        self.discard_btn.setEnabled(review)

    def _set_running_ui(self, running: bool) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Stop" if running else "Start")
        self.talk_btn.setEnabled(running)
        for w in (self.camera_cb, self.mic_cb, self.monitor_cb, self.voice_cb,
                  self.refresh_btn):
            w.setEnabled(not running)

    def _status(self, msg: str) -> None:
        self.status.setText(msg)

    def closeEvent(self, event) -> None:
        try:
            self.ptt.stop()
            self.session.shutdown()
        finally:
            super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(1040, 620)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
