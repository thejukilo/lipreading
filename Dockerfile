# Headless GPU server image for the lipreading backend (RunPod / any CUDA host).
#
# The large, slow-changing assets — the auto_avsr checkout and the model
# checkpoints — are NOT baked in; they live on a mounted network volume so the
# image stays small and rebuilds stay fast:
#
#     /workspace/third_party/auto_avsr        (the auto_avsr repo)
#     /workspace/checkpoints/*.pth            (base + any language checkpoints)
#     /workspace/data                         (per-user media; persists)
#
# Build:  docker build -t lipreading-api .
# Run:    docker run --gpus all -p 8000:8000 \
#             -e SUPABASE_JWT_SECRET=... -e LIPREADING_DB_URL=postgresql+psycopg://... \
#             -v /path/to/volume:/workspace  lipreading-api

FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/workspace/.cache/huggingface \
    LIPREADING_AUTO_AVSR_DIR=/workspace/third_party/auto_avsr \
    LIPREADING_BASE_CHECKPOINT=/workspace/checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth \
    LIPREADING_DATA_DIR=/workspace/data \
    PORT=8000

# System libraries: ffmpeg (av/opencv decode), libGL/glib (opencv), git.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-cloud.txt .
RUN pip install -r requirements-cloud.txt

# Only the app code is baked in; assets come from the mounted volume.
COPY server/ ./server/

EXPOSE 8000
# One GPU, one process. The in-process training worker runs here too.
CMD ["sh", "-c", "uvicorn server.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
