#!/usr/bin/env bash
# Linux/macOS equivalent of setup_windows.ps1 (handy for testing off Windows).
# Clones auto_avsr, downloads the VSR base checkpoint and the demo clip.
#
# Create the env and install torch yourself first (pick the right CUDA/CPU build):
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install torch torchvision torchaudio          # or the cu121 index-url on CUDA
#   pip install -r requirements.txt
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$root/third_party" "$root/checkpoints" "$root/media" "$root/models"

auto_avsr="$root/third_party/auto_avsr"
if [ -f "$auto_avsr/lightning.py" ]; then
  echo "[setup] auto_avsr already present"
else
  echo "[setup] cloning auto_avsr..."
  git clone --depth 1 https://github.com/mpc001/auto_avsr.git "$auto_avsr"
fi

# VSR checkpoint. Default = best available (20.3% WER, 3291h training, ~1GB).
# All share the same "base" architecture, so any is a drop-in swap. Options:
#   vsr_trlrs3_base.pth              36.0% WER   12PNM5szUsk_CuaV1yB9dL_YWvSM1zvAd
#   vsr_trlrs3vox2_base.pth          24.6% WER   1shcWXUK2iauRhW9NbwCc25FjU1CoMm8i
#   vsr_trlrs2lrs3vox2avsp_base.pth  20.3% WER   1r1kx7l9sWnDOCnaFHIGvOtzuhFyFA88_
ckpt_name="vsr_trlrs2lrs3vox2avsp_base.pth"
ckpt_id="1r1kx7l9sWnDOCnaFHIGvOtzuhFyFA88_"
ckpt="$root/checkpoints/$ckpt_name"
if [ -f "$ckpt" ]; then
  echo "[setup] checkpoint already present"
else
  echo "[setup] downloading VSR checkpoint $ckpt_name (~1GB) via gdown..."
  gdown "$ckpt_id" -O "$ckpt"   # handles Google Drive large-file confirm token
fi

blaze="$root/models/blaze_face_short_range.tflite"
if [ -f "$blaze" ]; then
  echo "[setup] BlazeFace model already present"
else
  echo "[setup] downloading BlazeFace face-detector model..."
  curl -L "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite" -o "$blaze"
fi

demo="$root/media/demo.mp4"
if [ -f "$demo" ]; then
  echo "[setup] demo video already present"
else
  echo "[setup] downloading demo video..."
  curl -L "http://www.doc.ic.ac.uk/~pm4115/autoAVSR/autoavsr_demo_video.mp4" -o "$demo"
fi

echo
echo "[setup] done. Run the smoke test:"
echo "  python -m server.engine --video media/demo.mp4 --checkpoint checkpoints/$ckpt_name"
