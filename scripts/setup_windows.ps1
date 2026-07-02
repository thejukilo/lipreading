# Step 1 setup for Windows + NVIDIA CUDA.
#
# Prepares everything the smoke test needs:
#   1. clones auto_avsr into third_party/auto_avsr
#   2. downloads the English VSR base checkpoint (LRS3)
#   3. downloads the auto_avsr demo clip to transcribe
#
# It does NOT create the Python env or install torch — do that yourself so you
# control the CUDA version:
#
#   py -3.10 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
#   pip install -r requirements.txt
#
# Then run this script, then run the smoke test (see docs/step1-smoke-test.md).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$thirdParty = Join-Path $root "third_party"
$autoAvsr   = Join-Path $thirdParty "auto_avsr"
$ckptDir    = Join-Path $root "checkpoints"
$mediaDir   = Join-Path $root "media"
$modelDir   = Join-Path $root "models"

New-Item -ItemType Directory -Force -Path $thirdParty, $ckptDir, $mediaDir, $modelDir | Out-Null

if (Test-Path (Join-Path $autoAvsr "lightning.py")) {
    Write-Host "[setup] auto_avsr already present at $autoAvsr"
} else {
    Write-Host "[setup] cloning auto_avsr..."
    git clone --depth 1 https://github.com/mpc001/auto_avsr.git $autoAvsr
}

$ckpt = Join-Path $ckptDir "vsr_trlrs3_base.pth"
if (Test-Path $ckpt) {
    Write-Host "[setup] checkpoint already present at $ckpt"
} else {
    Write-Host "[setup] downloading VSR checkpoint (vsr_trlrs3_base.pth)..."
    Invoke-WebRequest -Uri "http://www.doc.ic.ac.uk/~pm4115/autoAVSR/vsr_trlrs3_base.pth" -OutFile $ckpt
}

$blaze = Join-Path $modelDir "blaze_face_short_range.tflite"
if (Test-Path $blaze) {
    Write-Host "[setup] BlazeFace model already present at $blaze"
} else {
    Write-Host "[setup] downloading BlazeFace face-detector model..."
    Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite" -OutFile $blaze
}

$demo = Join-Path $mediaDir "demo.mp4"
if (Test-Path $demo) {
    Write-Host "[setup] demo video already present at $demo"
} else {
    Write-Host "[setup] downloading demo video..."
    Invoke-WebRequest -Uri "http://www.doc.ic.ac.uk/~pm4115/autoAVSR/autoavsr_demo_video.mp4" -OutFile $demo
}

Write-Host ""
Write-Host "[setup] done. Run the smoke test:"
Write-Host "  python -m server.engine --video media\demo.mp4 --checkpoint checkpoints\vsr_trlrs3_base.pth"
