"""Friendly desktop UI — set everything up and run, no terminal needed.

One window: a Setup panel (camera, mic-to-Meet, voice, push-to-talk key, mode),
a live webcam preview, the transcript with Speak / Discard / Edit, and a big
Start / Stop button. Settings are saved to ~/.lipreading/config.json.

Run:  python -m server.gui_app   (or double-click run.bat)
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .corrector import CLAUDE_MODELS, list_ollama_models
from .dataset import TrainingStore
from .devices import list_audio_outputs, list_cameras
from .hotkey import PushToTalkListener
from .session import LiveSession, SessionConfig
from .settings import load_config, save_config
from .voices import VoicesStore

BASE_CKPT = SessionConfig().checkpoint             # the shipped base model path
PERSONALIZED_CKPT = "checkpoints/personalized.pth"  # produced by fine-tuning
DUTCH_CKPT = "checkpoints/dutch/dutch_vsr.pth"       # produced by the Phase-3 Dutch run
_BROWSE = "__browse__"                               # sentinel for the "Browse…" item

# A short, phonetically varied passage for recording a clean voice reference.
RECORD_PASSAGE = (
    "The quick brown fox jumps over the lazy dog. I usually enjoy a good cup of "
    "coffee in the morning, and a short walk before I start my work. Please call "
    "me back when you get a chance — it should only take a few minutes."
)

# Push-to-talk key: friendly label -> internal name.
PTT_KEYS = {
    "Right Ctrl": "ctrl_r", "Left Ctrl": "ctrl_l", "Right Alt": "alt_r",
    "Space": "space", "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10",
}
CLONE_ENGINES = {"VoxCPM (recommended)": "voxcpm", "XTTS": "xtts"}
CLEANUP_BACKENDS = {"Off": "off", "Local LLM (Ollama)": "ollama", "Claude (cloud)": "anthropic"}

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
        self.voices = VoicesStore()
        self.dataset = TrainingStore()
        self.session = LiveSession(self.cfg)
        self._teach_recording = False
        self._training = False
        self._train_msg = None
        self._train_done = False
        self.ptt = PushToTalkListener(self.cfg.ptt_key, self._ptt_down, self._ptt_up)
        self._starting = False
        self._last_state = None

        self._pending_cameras = None   # set by the background camera scan
        self._scanning_cameras = False
        self._pending_cleanup_models = None   # set by the background Ollama probe

        self._build_ui()
        self._populate_audio()
        self._populate_cameras_default()   # fast; real scan runs in background
        self._populate_voices()
        self._populate_recog_models()
        self._apply_cfg_to_widgets()
        self._populate_cleanup_models(self.cfg.corrector)
        self._set_running_ui(False)
        self._start_camera_scan()

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
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        speak_tab = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(speak_tab)

        # Left: setup panel
        setup = QtWidgets.QGroupBox("Setup")
        form = QtWidgets.QFormLayout(setup)
        self.camera_cb = QtWidgets.QComboBox()
        self.vcam_chk = QtWidgets.QCheckBox("Show my camera in Google Meet (virtual camera)")
        self.vcam_chk.setToolTip(
            "Mirror the webcam to a virtual camera so Meet can see you while the app "
            "reads your lips. Needs OBS Studio installed (provides 'OBS Virtual "
            "Camera'); pick that as your camera in Meet.")
        self.recog_model_cb = QtWidgets.QComboBox()
        self.mic_cb = QtWidgets.QComboBox()
        self.monitor_chk = QtWidgets.QCheckBox("Hear it on my speakers (monitor)")
        self.monitor_cb = QtWidgets.QComboBox()
        self.voice_cb = QtWidgets.QComboBox()
        self.clone_btn = QtWidgets.QPushButton("＋ Clone")
        self.del_voice_btn = QtWidgets.QPushButton("Delete")
        voice_row = QtWidgets.QHBoxLayout()
        voice_row.addWidget(self.voice_cb, 1)
        voice_row.addWidget(self.clone_btn)
        voice_row.addWidget(self.del_voice_btn)
        voice_row_w = QtWidgets.QWidget()
        voice_row_w.setLayout(voice_row)
        self.clone_engine_cb = QtWidgets.QComboBox()
        self.clone_engine_cb.addItems(list(CLONE_ENGINES.keys()))

        # Cloned-voice quality/speed (VoxCPM inference steps): low = faster.
        self.quality_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.quality_slider.setMinimum(4)
        self.quality_slider.setMaximum(24)
        self.quality_slider.setSingleStep(1)
        self.quality_slider.setPageStep(2)
        self.quality_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.quality_slider.setTickInterval(4)
        self.quality_lbl = QtWidgets.QLabel("10")
        self.quality_lbl.setMinimumWidth(28)
        q_row = QtWidgets.QHBoxLayout()
        q_row.addWidget(QtWidgets.QLabel("Faster"))
        q_row.addWidget(self.quality_slider, 1)
        q_row.addWidget(QtWidgets.QLabel("Better"))
        q_row.addWidget(self.quality_lbl)
        quality_row_w = QtWidgets.QWidget()
        quality_row_w.setLayout(q_row)

        self.key_cb = QtWidgets.QComboBox()
        self.key_cb.addItems(list(PTT_KEYS.keys()))
        self.auto_chk = QtWidgets.QCheckBox("Speak immediately (skip review)")

        # LLM transcript cleanup
        self.cleanup_cb = QtWidgets.QComboBox()
        self.cleanup_cb.addItems(list(CLEANUP_BACKENDS.keys()))
        self.cleanup_model_cb = QtWidgets.QComboBox()
        self.cleanup_model_cb.setEditable(True)  # pick installed, or type your own
        self.cleanup_model_cb.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.cleanup_key_edit = QtWidgets.QLineEdit()
        self.cleanup_key_edit.setPlaceholderText("Claude API key (stored locally)")
        self.cleanup_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.cleanup_ctx_edit = QtWidgets.QPlainTextEdit()
        self.cleanup_ctx_edit.setPlaceholderText(
            "Names & terms you use, e.g.  Juan, 1:1, case load, team chat, handover")
        self.cleanup_ctx_edit.setMaximumHeight(56)

        self.refresh_btn = QtWidgets.QPushButton("Refresh devices")

        form.addRow("Camera:", self.camera_cb)
        form.addRow("", self.vcam_chk)
        form.addRow("Recognition model:", self.recog_model_cb)
        form.addRow("Microphone to Meet:", self.mic_cb)
        form.addRow("", self.monitor_chk)
        form.addRow("Monitor speakers:", self.monitor_cb)
        form.addRow("Voice:", voice_row_w)
        form.addRow("Cloning engine:", self.clone_engine_cb)
        form.addRow("Voice quality:", quality_row_w)
        form.addRow("Push-to-talk key:", self.key_cb)
        form.addRow("Text cleanup:", self.cleanup_cb)
        form.addRow("Cleanup model:", self.cleanup_model_cb)
        form.addRow("Claude API key:", self.cleanup_key_edit)
        form.addRow("Cleanup context:", self.cleanup_ctx_edit)
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
        self.add_train_btn = QtWidgets.QPushButton("＋ Add to training")
        self.add_train_btn.setToolTip(
            "Save this clip with the (corrected) text above to the Teach dataset")
        review_row = QtWidgets.QHBoxLayout()
        review_row.addWidget(self.transcript, 1)
        review_row.addWidget(self.speak_btn)
        review_row.addWidget(self.discard_btn)
        review_row.addWidget(self.add_train_btn)

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

        self.tabs.addTab(speak_tab, "Speak")
        self.tabs.addTab(self._build_teach_tab(), "Teach")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Wiring
        self.refresh_btn.clicked.connect(self._refresh_devices)
        self.start_btn.clicked.connect(self._toggle_start)
        self.talk_btn.pressed.connect(self._ptt_down)
        self.talk_btn.released.connect(self._ptt_up)
        self.speak_btn.clicked.connect(self._on_speak)
        self.discard_btn.clicked.connect(self.session.discard)
        self.add_train_btn.clicked.connect(self._on_add_training)
        self.monitor_chk.toggled.connect(lambda v: self.session.set_monitor(v))
        self.key_cb.currentTextChanged.connect(self._on_key_changed)
        self.clone_btn.clicked.connect(self._on_clone_voice)
        self.del_voice_btn.clicked.connect(self._on_delete_voice)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        self.cleanup_cb.currentTextChanged.connect(self._on_cleanup_backend_changed)
        self.recog_model_cb.currentIndexChanged.connect(self._on_recog_changed)

    # ---- device population + config <-> widgets ---------------------------

    def _refresh_devices(self) -> None:
        self._populate_audio()
        self._start_camera_scan()

    def _populate_cameras_default(self) -> None:
        """Fast, non-blocking: list indices 0-3 without opening the cameras.
        The real (validated) list arrives from the background scan; Start also
        validates the chosen camera anyway."""
        if self.camera_cb.count() == 0:
            for i in range(4):
                self.camera_cb.addItem(f"Camera {i}", i)

    def _start_camera_scan(self) -> None:
        """Probe cameras in a background thread (opening MSMF can block for
        seconds on Windows — must not freeze the UI)."""
        if self._scanning_cameras:
            return
        self._scanning_cameras = True
        self._status("scanning cameras…")

        def worker():
            try:
                cams = list_cameras()
            except Exception:
                cams = []
            self._pending_cameras = cams  # applied by _tick on the UI thread

        threading.Thread(target=worker, daemon=True).start()

    def _apply_camera_scan(self, cams) -> None:
        self._scanning_cameras = False
        keep = self.camera_cb.currentData()
        self.camera_cb.blockSignals(True)
        self.camera_cb.clear()
        if cams:
            for idx, label in cams:
                self.camera_cb.addItem(label, idx)
        else:
            for i in range(4):
                self.camera_cb.addItem(f"Camera {i}", i)
        self._select_data(self.camera_cb, keep if keep is not None else self.cfg.camera)
        self.camera_cb.blockSignals(False)
        self._status(f"found {len(cams)} camera(s)" if cams else
                     "no cameras detected — pick an index and press Start")

    def _populate_audio(self) -> None:
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

    def _populate_voices(self) -> None:
        """Voice dropdown = built-ins + cloned voices. itemData holds the voice id."""
        current = self.voice_cb.currentData() if self.voice_cb.count() else self.cfg.voice
        self.voice_cb.blockSignals(True)
        self.voice_cb.clear()
        self.voice_cb.addItem("Piper (natural, local)", "piper")
        self.voice_cb.addItem("Windows voice (SAPI)", "sapi")
        for v in self.voices.list_voices():
            self.voice_cb.addItem(f"🗣 {v['name']} (your voice)", f"clone:{v['slug']}")
        self._select_data(self.voice_cb, current)
        self.voice_cb.blockSignals(False)

    def _on_clone_voice(self) -> None:
        engine = CLONE_ENGINES[self.clone_engine_cb.currentText()]
        dlg = CloneVoiceDialog(self.voices, engine=engine, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_slug:
            self._populate_voices()
            self._select_data(self.voice_cb, f"clone:{dlg.result_slug}")
            self._status(f"voice '{dlg.result_name}' saved — it applies on next Start")

    def _on_delete_voice(self) -> None:
        vid = self.voice_cb.currentData()
        if not isinstance(vid, str) or not vid.startswith("clone:"):
            self._status("select one of your cloned voices to delete")
            return
        slug = vid.split(":", 1)[1]
        if QtWidgets.QMessageBox.question(
            self, "Delete voice", f"Delete the cloned voice '{slug}'?"
        ) == QtWidgets.QMessageBox.Yes:
            self.voices.delete(slug)
            self._populate_voices()
            self._status(f"deleted voice '{slug}'")

    def _apply_cfg_to_widgets(self) -> None:
        self._select_data(self.recog_model_cb, self.cfg.checkpoint)
        self._select_data(self.camera_cb, self.cfg.camera)
        self.vcam_chk.setChecked(self.cfg.virtual_cam)
        if self.cfg.output_device is not None:
            self._select_text_contains(self.mic_cb, str(self.cfg.output_device))
        self.monitor_chk.setChecked(self.cfg.monitor_on)
        self._select_data(self.monitor_cb, self.cfg.monitor_device)
        self._select_data(self.voice_cb, self.cfg.voice)
        self._select_key(self.clone_engine_cb, CLONE_ENGINES, self.cfg.clone_engine)
        self.quality_slider.setValue(self.cfg.clone_timesteps)
        self.quality_lbl.setText(str(self.cfg.clone_timesteps))
        self._select_key(self.key_cb, PTT_KEYS, self.cfg.ptt_key)
        self._select_key(self.cleanup_cb, CLEANUP_BACKENDS, self.cfg.corrector)
        self.cleanup_model_cb.setCurrentText(self.cfg.corrector_model)
        self.cleanup_key_edit.setText(self.cfg.corrector_api_key)
        self.cleanup_key_edit.setEnabled(self.cfg.corrector == "anthropic")
        self.cleanup_ctx_edit.setPlainText(self.cfg.corrector_context)
        self.auto_chk.setChecked(self.cfg.auto_speak)

    def _widgets_to_cfg(self) -> None:
        ckpt = self.recog_model_cb.currentData()
        self.cfg.checkpoint = ckpt if ckpt and ckpt != _BROWSE else BASE_CKPT
        self.cfg.camera = self.camera_cb.currentData() if self.camera_cb.currentData() is not None else 0
        self.cfg.virtual_cam = self.vcam_chk.isChecked()
        self.cfg.output_device = self.mic_cb.currentData()
        self.cfg.monitor_on = self.monitor_chk.isChecked()
        self.cfg.monitor_device = self.monitor_cb.currentData()
        self.cfg.voice = self.voice_cb.currentData() or "piper"
        self.cfg.clone_engine = CLONE_ENGINES[self.clone_engine_cb.currentText()]
        self.cfg.clone_timesteps = self.quality_slider.value()
        self.cfg.ptt_key = PTT_KEYS[self.key_cb.currentText()]
        self.cfg.corrector = CLEANUP_BACKENDS[self.cleanup_cb.currentText()]
        self.cfg.corrector_model = self.cleanup_model_cb.currentText().strip()
        self.cfg.corrector_api_key = self.cleanup_key_edit.text().strip()
        self.cfg.corrector_context = self.cleanup_ctx_edit.toPlainText().strip()
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
        # Ignore push-to-talk while on the Teach tab (it uses the same buffer).
        if self.session.is_running and self.tabs.currentIndex() == 0:
            self.session.start_recording()

    def _ptt_up(self) -> None:
        if self.session.is_running and self.tabs.currentIndex() == 0:
            self.session.stop_recording()

    def _on_speak(self) -> None:
        self.session.speak(self.transcript.text())

    def _on_add_training(self) -> None:
        """Save the just-transcribed clip with the (corrected) text as a training
        example — turns real mistakes into personalization data."""
        text = self.transcript.text().strip()
        frames = getattr(self.session, "last_frames", None)
        if not text:
            self._status("type the correct text first")
            return
        if frames is None or len(frames) == 0:
            self._status("no clip available to add")
            return
        try:
            self.dataset.add_clip(text, frames, created=time.time())
        except Exception as e:
            self._status(f"! {e}")
            return
        self._refresh_teach_list()
        self.add_train_btn.setText("✓ Added")
        self._status(f"added “{text}” to training")

    def _on_quality_changed(self, value: int) -> None:
        self.quality_lbl.setText(str(value))
        self.cfg.clone_timesteps = value
        # Apply live if a cloned voice is currently running (no restart needed).
        tts = getattr(self.session, "tts", None)
        if tts is not None and hasattr(tts, "inference_timesteps"):
            tts.inference_timesteps = value

    def _populate_recog_models(self) -> None:
        """Base always; Personalized / Dutch only if that checkpoint exists; plus a
        Browse… item to point at any .pth (e.g. an experimental base)."""
        keep = self.recog_model_cb.currentData() if self.recog_model_cb.count() else self.cfg.checkpoint
        self.recog_model_cb.blockSignals(True)
        self.recog_model_cb.clear()
        self.recog_model_cb.addItem("Base (shipped)", BASE_CKPT)
        if os.path.isfile(PERSONALIZED_CKPT):
            self.recog_model_cb.addItem("Personalized (yours)", PERSONALIZED_CKPT)
        if os.path.isfile(DUTCH_CKPT):
            self.recog_model_cb.addItem("Dutch (Phase 3)", DUTCH_CKPT)
        # If the saved config points at some other checkpoint, keep it visible.
        if keep and keep not in (BASE_CKPT, PERSONALIZED_CKPT, DUTCH_CKPT) and os.path.isfile(keep):
            self.recog_model_cb.addItem(f"Custom: {os.path.basename(keep)}", keep)
        self.recog_model_cb.addItem("Browse…", _BROWSE)
        self._select_data(self.recog_model_cb, keep)
        self.recog_model_cb.blockSignals(False)
        self._last_recog_data = self.recog_model_cb.currentData()

    def _on_recog_changed(self) -> None:
        """Handle the Browse… item: pick any .pth and add/select it."""
        if self.recog_model_cb.currentData() != _BROWSE:
            self._last_recog_data = self.recog_model_cb.currentData()
            return
        prev = getattr(self, "_last_recog_data", BASE_CKPT)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a recognition model (.pth)",
            os.path.dirname(DUTCH_CKPT), "Checkpoints (*.pth *.pt);;All files (*)")
        if not path:  # cancelled — revert to the previous selection
            self._select_data(self.recog_model_cb, prev)
            return
        # Insert (or reselect) the chosen checkpoint just before Browse….
        existing = self.recog_model_cb.findData(path)
        if existing == -1:
            self.recog_model_cb.blockSignals(True)
            self.recog_model_cb.insertItem(
                self.recog_model_cb.count() - 1, f"Custom: {os.path.basename(path)}", path)
            self.recog_model_cb.blockSignals(False)
        self._select_data(self.recog_model_cb, path)
        self._last_recog_data = path

    def _teach_train(self) -> None:
        if self._training:
            return
        n_clips, n_phrases = self.dataset.stats()
        if n_clips < 4:
            QtWidgets.QMessageBox.information(
                self, "Fine-tune",
                f"Only {n_clips} clip(s) so far. Record several phrases with a few "
                "reps each first (more and more varied = better).")
            return
        if self.session.is_running:
            QtWidgets.QMessageBox.information(
                self, "Fine-tune",
                "Turn the camera off first (Teach tab) so training has the full GPU.")
            return
        if QtWidgets.QMessageBox.question(
            self, "Fine-tune",
            f"Train a personalized model on {n_clips} clip(s) across {n_phrases} "
            "phrase(s)? This uses your GPU for a few minutes. The base model is "
            "kept; a separate 'Personalized' model is created."
        ) != QtWidgets.QMessageBox.Yes:
            return

        self._training = True
        self._train_done = False
        self._train_msg = "starting…"
        self.teach_train_btn.setEnabled(False)

        def worker():
            try:
                from .finetune import finetune
                finetune(
                    self.dataset, checkpoint_path=BASE_CKPT, out_path=PERSONALIZED_CKPT,
                    auto_avsr_dir=self.cfg.auto_avsr_dir, detector=self.cfg.detector,
                    device=self.cfg.device,
                    on_progress=lambda s: setattr(self, "_train_msg", s),
                )
                self._train_msg = ("✓ done — pick 'Personalized' as the Recognition "
                                   "model on the Speak tab, then Start")
                self._train_done = True
            except Exception as e:
                self._train_msg = f"! training failed: {e}"
            finally:
                self._training = False

        threading.Thread(target=worker, daemon=True).start()

    def _on_cleanup_backend_changed(self, label: str) -> None:
        backend = CLEANUP_BACKENDS.get(label, "off")
        self.cleanup_key_edit.setEnabled(backend == "anthropic")
        self._populate_cleanup_models(backend)

    def _populate_cleanup_models(self, backend: str) -> None:
        """Fill the model dropdown for the selected cleanup backend.

        Claude models are a fixed list; Ollama models are probed from the local
        server in the background (a down/absent Ollama must not freeze the UI).
        Keeps whatever the user has typed/selected.
        """
        keep = self.cleanup_model_cb.currentText().strip()
        self.cleanup_model_cb.blockSignals(True)
        self.cleanup_model_cb.clear()
        if backend == "anthropic":
            self.cleanup_model_cb.addItems(CLAUDE_MODELS)
        if keep:
            self.cleanup_model_cb.setCurrentText(keep)
        self.cleanup_model_cb.blockSignals(False)

        if backend == "ollama" and not self._pending_cleanup_models:
            host = self.cfg.corrector_ollama_host

            def worker():
                models = list_ollama_models(host)
                self._pending_cleanup_models = models or [""]  # sentinel: probe done

            threading.Thread(target=worker, daemon=True).start()

    def _apply_cleanup_models(self, models) -> None:
        keep = self.cleanup_model_cb.currentText().strip()
        self.cleanup_model_cb.blockSignals(True)
        self.cleanup_model_cb.clear()
        self.cleanup_model_cb.addItems([m for m in models if m])
        if keep:
            self.cleanup_model_cb.setCurrentText(keep)
        self.cleanup_model_cb.blockSignals(False)
        real = [m for m in models if m]
        self._status(f"found {len(real)} Ollama model(s)" if real else
                     "no Ollama models found — is Ollama running? (ollama pull llama3.1:8b)")

    def _on_key_changed(self, label: str) -> None:
        name = PTT_KEYS.get(label)
        if name:
            self.cfg.ptt_key = name
            try:
                self.ptt.set_key(name)
            except Exception as e:
                self._status(f"key change failed: {e}")

    # ---- Teaching tab -----------------------------------------------------

    def _build_teach_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        intro = QtWidgets.QLabel(
            "Teach the model your words. Type a word or short sentence, turn on "
            "the camera, and record yourself saying it a few times (more reps and "
            "more phrases = better). Fine-tuning on this data comes next."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        body = QtWidgets.QHBoxLayout()

        # Left: preview + record controls
        left = QtWidgets.QVBoxLayout()
        self.teach_preview = QtWidgets.QLabel()
        self.teach_preview.setFixedSize(480, 360)
        self.teach_preview.setStyleSheet("background:#111;")
        self.teach_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.teach_cam_btn = QtWidgets.QPushButton("Turn camera on")
        self.teach_cam_btn.clicked.connect(self._teach_toggle_camera)
        self.teach_phrase = QtWidgets.QLineEdit()
        self.teach_phrase.setPlaceholderText("Word or sentence to teach, e.g.  Juan")
        self.teach_record_btn = QtWidgets.QPushButton("● Record a rep")
        self.teach_record_btn.setCheckable(True)
        self.teach_record_btn.setEnabled(False)
        self.teach_record_btn.clicked.connect(self._teach_toggle_record)
        self.teach_status = QtWidgets.QLabel("")
        self.teach_status.setStyleSheet("color:#555;")
        left.addWidget(self.teach_preview)
        left.addWidget(self.teach_cam_btn)
        left.addWidget(QtWidgets.QLabel("Phrase:"))
        left.addWidget(self.teach_phrase)
        left.addWidget(self.teach_record_btn)
        left.addWidget(self.teach_status)

        # Right: collected items
        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel("Training set (recorded here + added from the Speak tab):"))
        self.teach_list = QtWidgets.QListWidget()
        self.teach_del_btn = QtWidgets.QPushButton("Delete selected phrase")
        self.teach_del_btn.clicked.connect(self._teach_delete)
        self.teach_total = QtWidgets.QLabel("")
        self.teach_open_btn = QtWidgets.QPushButton("Open clips folder")
        self.teach_open_btn.clicked.connect(self._teach_open_folder)
        self.teach_path_lbl = QtWidgets.QLabel(f"Saved in: {self.dataset.clips_dir}")
        self.teach_path_lbl.setStyleSheet("color:#888; font-size:11px;")
        self.teach_path_lbl.setWordWrap(True)
        right.addWidget(self.teach_list, 1)
        right.addWidget(self.teach_del_btn)
        right.addWidget(self.teach_total)
        right.addWidget(self.teach_open_btn)
        right.addWidget(self.teach_path_lbl)

        body.addLayout(left)
        body.addLayout(right, 1)
        lay.addLayout(body)

        self.teach_train_btn = QtWidgets.QPushButton("⚙ Fine-tune a personalized model")
        self.teach_train_btn.setToolTip(
            "Train a personalized copy of the model on your clips (uses your GPU). "
            "The base model is not changed.")
        self.teach_train_btn.clicked.connect(self._teach_train)
        lay.addWidget(self.teach_train_btn)
        self._refresh_teach_list()
        return w

    def _on_tab_changed(self, index: int) -> None:
        # Keep camera state reflected on the Teach button when you switch tabs.
        on = self.session.is_running
        self.teach_cam_btn.setText("Turn camera off" if on else "Turn camera on")
        self.teach_record_btn.setEnabled(on)

    def _teach_toggle_camera(self) -> None:
        if self.session.is_running:
            if self._teach_recording:
                self._teach_toggle_record()  # stop an in-progress rep first
            self.session.stop()
            self.teach_cam_btn.setText("Turn camera on")
            self.teach_record_btn.setEnabled(False)
            return
        try:
            self.session.start()  # camera only — no model load needed to record
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Camera", str(e))
            return
        self.teach_cam_btn.setText("Turn camera off")
        self.teach_record_btn.setEnabled(True)

    def _teach_toggle_record(self) -> None:
        if not self._teach_recording:
            if not self.teach_phrase.text().strip():
                self.teach_record_btn.setChecked(False)
                self.teach_status.setText("type a phrase first")
                return
            self._teach_recording = True
            self.session.clip_record_start()
            self.teach_record_btn.setText("■ Stop & save")
            self.teach_record_btn.setChecked(True)
        else:
            self._teach_recording = False
            frames = self.session.clip_record_stop()
            self.teach_record_btn.setText("● Record a rep")
            self.teach_record_btn.setChecked(False)
            phrase = self.teach_phrase.text().strip()
            try:
                self.dataset.add_clip(phrase, frames, created=time.time())
            except Exception as e:
                self.teach_status.setText(f"! {e}")
                return
            self.teach_status.setText(f"saved a rep of “{phrase}”")
            self._refresh_teach_list()

    def _refresh_teach_list(self) -> None:
        self.teach_list.clear()
        for g in self.dataset.items_grouped():
            self.teach_list.addItem(f"{g['phrase']}  —  {g['count']} rep(s)")
        n_clips, n_phrases = self.dataset.stats()
        self.teach_total.setText(f"{n_clips} clip(s) across {n_phrases} phrase(s)")

    def _teach_open_folder(self) -> None:
        import subprocess

        path = self.dataset.clips_dir
        os.makedirs(path, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606 (Windows-only)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.teach_status.setText(f"couldn't open folder: {e}")

    def _teach_delete(self) -> None:
        item = self.teach_list.currentItem()
        if item is None:
            return
        phrase = item.text().split("  —  ")[0]
        if QtWidgets.QMessageBox.question(
            self, "Delete", f"Delete all recordings of “{phrase}”?"
        ) == QtWidgets.QMessageBox.Yes:
            self.dataset.delete_phrase(phrase)
            self._refresh_teach_list()

    # ---- periodic UI update ----------------------------------------------

    def _tick(self) -> None:
        if self._pending_cameras is not None:   # background scan finished
            cams, self._pending_cameras = self._pending_cameras, None
            self._apply_camera_scan(cams)
        if self._pending_cleanup_models is not None:   # Ollama probe finished
            models, self._pending_cleanup_models = self._pending_cleanup_models, None
            self._apply_cleanup_models(models)
        if self._train_msg is not None:                # fine-tuning progress
            self.teach_status.setText(self._train_msg)
        if not self._training and not self.teach_train_btn.isEnabled():
            self.teach_train_btn.setEnabled(True)
        if self._train_done:                            # a personalized model appeared
            self._train_done = False
            self._populate_recog_models()

        # Always mirror progress to the UI — including during Start (model load
        # + voice warm-up), which is the slowest phase and needs feedback.
        if self.session.last_status:
            self.status.setText(self.session.last_status)

        if self._starting:
            self.banner.setText("⏳ Starting — " + (self.session.last_status or "please wait…"))
            self.banner.setStyleSheet(
                "padding:6px; color:white; background:#f9a825; border-radius:4px;"
            )
            return

        if getattr(self, "_start_error", None):
            err, self._start_error = self._start_error, None
            self._status(f"! {err}")
            self._set_running_ui(False)
            QtWidgets.QMessageBox.warning(self, "Could not start", err)
        elif self.session.is_running and self.session.is_loaded and self.start_btn.text() != "Stop":
            # Only flip the Speak UI to "running" when the model is loaded — the
            # Teaching tab can turn on the camera without loading the model.
            self._set_running_ui(True)

        self._update_preview()
        self._update_state()
        if self._teach_recording:
            self.teach_status.setText(f"● recording… {self.session.frame_count} frames")

    def _update_preview(self) -> None:
        import cv2  # local: heavy import, only once running

        frame = self.session.latest_bgr
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(img)
        self.preview.setPixmap(pixmap.scaled(
            self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.teach_preview.setPixmap(pixmap.scaled(
            self.teach_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

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
                self.add_train_btn.setText("＋ Add to training")  # reset label
            self._last_state = st
        review = st == LiveSession.REVIEW
        self.speak_btn.setEnabled(review or bool(self.transcript.text()))
        self.discard_btn.setEnabled(review)
        self.add_train_btn.setEnabled(review and getattr(self.session, "last_frames", None) is not None)

    def _set_running_ui(self, running: bool) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Stop" if running else "Start")
        self.talk_btn.setEnabled(running)
        for w in (self.camera_cb, self.recog_model_cb, self.mic_cb, self.monitor_cb, self.voice_cb,
                  self.clone_engine_cb, self.refresh_btn, self.clone_btn,
                  self.del_voice_btn, self.cleanup_cb, self.cleanup_model_cb,
                  self.cleanup_key_edit, self.cleanup_ctx_edit):
            w.setEnabled(not running)

    def _status(self, msg: str) -> None:
        self.status.setText(msg)

    def closeEvent(self, event) -> None:
        try:
            self.ptt.stop()
            self.session.shutdown()
        finally:
            super().closeEvent(event)


class CloneVoiceDialog(QtWidgets.QDialog):
    """Wizard: name a voice, record or upload a reference clip, preview, save."""

    def __init__(self, store: VoicesStore, engine: str = "voxcpm", parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self.setWindowTitle("Clone a voice")
        self.setMinimumWidth(460)
        self.result_slug = None
        self.result_name = ""
        self._source_wav = None      # path to the reference audio to save
        self._source_is_recording = False  # True -> we know the transcript (passage)
        self._recorder = None
        self._rec_timer = QtCore.QTimer(self)
        self._rec_timer.timeout.connect(self._update_rec_time)

        v = QtWidgets.QVBoxLayout(self)

        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("e.g. My voice")
        nrow = QtWidgets.QHBoxLayout()
        nrow.addWidget(QtWidgets.QLabel("Name:"))
        nrow.addWidget(self.name_edit, 1)
        v.addLayout(nrow)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._record_tab(), "Record")
        self.tabs.addTab(self._upload_tab(), "Upload a file")
        v.addWidget(self.tabs)

        self.preview_btn = QtWidgets.QPushButton("Preview voice (loads model, slow first time)")
        self.preview_btn.clicked.connect(self._on_preview)
        v.addWidget(self.preview_btn)

        self.info = QtWidgets.QLabel(
            "Tip: 15–30s of clear speech in a quiet room clones best. "
            "The XTTS model is non-commercial (personal use)."
        )
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#666; font-size:11px;")
        v.addWidget(self.info)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _record_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        passage = QtWidgets.QLabel("Read this aloud:\n\n" + RECORD_PASSAGE)
        passage.setWordWrap(True)
        passage.setStyleSheet("background:#f3f3f3; padding:8px; border-radius:4px;")
        self.rec_btn = QtWidgets.QPushButton("● Start recording")
        self.rec_btn.clicked.connect(self._toggle_record)
        self.rec_time = QtWidgets.QLabel("0.0s")
        self.rec_play_btn = QtWidgets.QPushButton("Play back")
        self.rec_play_btn.setEnabled(False)
        self.rec_play_btn.clicked.connect(self._play_recorded)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.rec_btn)
        row.addWidget(self.rec_time)
        row.addStretch(1)
        row.addWidget(self.rec_play_btn)
        lay.addWidget(passage)
        lay.addLayout(row)
        return w

    def _upload_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.file_lbl = QtWidgets.QLabel("No file chosen (WAV).")
        self.file_lbl.setWordWrap(True)
        btn = QtWidgets.QPushButton("Choose WAV file…")
        btn.clicked.connect(self._choose_file)
        lay.addWidget(btn)
        lay.addWidget(self.file_lbl)
        lay.addStretch(1)
        return w

    # ---- record ----------------------------------------------------------

    def _toggle_record(self) -> None:
        from .audio_in import Recorder

        if self._recorder is None:
            try:
                self._recorder = Recorder()
                self._recorder.start()
            except Exception as e:
                self._recorder = None
                QtWidgets.QMessageBox.warning(self, "Microphone", f"Could not start recording:\n{e}")
                return
            self.rec_btn.setText("■ Stop recording")
            self.rec_play_btn.setEnabled(False)
            self._rec_timer.start(100)
        else:
            self._rec_timer.stop()
            data = self._recorder.stop()
            self._recorder = None
            self.rec_btn.setText("● Start recording")
            path = os.path.join(tempfile.gettempdir(), f"voice_rec_{int(time.time())}.wav")
            try:
                import soundfile as sf

                sf.write(path, data, 22050, subtype="PCM_16")
                self._source_wav = path
                self._source_is_recording = True   # transcript == RECORD_PASSAGE
                self.rec_play_btn.setEnabled(True)
                self.rec_time.setText(f"{len(data) / 22050:.1f}s recorded")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Recording", f"Could not save recording:\n{e}")

    def _update_rec_time(self) -> None:
        if self._recorder is not None:
            self.rec_time.setText(f"{self._recorder.seconds:.1f}s")

    def _play_recorded(self) -> None:
        if self._source_wav:
            self._play(self._source_wav)

    # ---- upload ----------------------------------------------------------

    def _choose_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose reference audio", "", "Audio (*.wav)"
        )
        if path:
            self._source_wav = path
            self._source_is_recording = False   # unknown transcript
            self.file_lbl.setText(path)

    # ---- preview / save --------------------------------------------------

    def _current_source(self) -> str | None:
        # The active tab decides which source we use.
        return self._source_wav

    def _on_preview(self) -> None:
        src = self._current_source()
        if not src:
            QtWidgets.QMessageBox.information(self, "Preview", "Record or choose a clip first.")
            return
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("Synthesizing…")
        threading.Thread(target=self._preview_worker, args=(src,), daemon=True).start()

    def _preview_worker(self, src: str) -> None:
        try:
            from .audio_out import play_wav

            prompt_text = RECORD_PASSAGE if self._source_is_recording else None
            if self.engine == "xtts":
                from .tts import XttsTTS

                tts = XttsTTS(speaker_wav=src)
            else:
                from .tts import VoxCpmTTS

                tts = VoxCpmTTS(reference_wav=src, prompt_text=prompt_text)
            wav = tts.synthesize_to_wav("Hi, this is my cloned voice. How does it sound?")
            play_wav(wav, device=None, monitor=False)  # default speakers
            try:
                os.remove(wav)
            except OSError:
                pass
        except Exception as e:
            print(f"[clone] preview failed: {e}")
        finally:
            QtCore.QMetaObject.invokeMethod(self, "_preview_done", QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def _preview_done(self) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("Preview voice (loads model, slow first time)")

    def _play(self, wav: str) -> None:
        from .audio_out import play_wav

        try:
            play_wav(wav, device=None, monitor=False, blocking=False)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Playback", str(e))

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        src = self._current_source()
        if not name:
            QtWidgets.QMessageBox.information(self, "Save", "Give the voice a name.")
            return
        if not src:
            QtWidgets.QMessageBox.information(self, "Save", "Record or choose a reference clip first.")
            return
        prompt_text = RECORD_PASSAGE if self._source_is_recording else None
        try:
            slug = self.store.add_from_wav(name, src, created=time.time(),
                                           prompt_text=prompt_text)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Save", f"Could not save voice:\n{e}")
            return
        self.result_slug = slug
        self.result_name = name
        self.accept()

    def closeEvent(self, event) -> None:
        self._rec_timer.stop()
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.resize(1040, 620)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
