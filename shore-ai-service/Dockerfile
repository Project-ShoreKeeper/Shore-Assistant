# syntax=docker/dockerfile:1.6
FROM nvidia/cuda:12.9.0-runtime-ubuntu24.04

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3-pip espeak-ng git make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml Makefile ./
COPY proto ./proto
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/pip \
    python3.12 -m pip install --break-system-packages \
      torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
      --index-url https://download.pytorch.org/whl/cu129

RUN --mount=type=cache,target=/root/.cache/pip \
    python3.12 -m pip install --break-system-packages -e .[dev]

# ── OmniParser v2 (pinned) + weights ──
# TODO: pin to a real microsoft/OmniParser master commit at deploy time (verify weights layout icon_detect/model.pt + icon_caption_florence/)
ARG OMNIPARSER_REF=<PIN_A_COMMIT_SHA>
RUN git clone https://github.com/microsoft/OmniParser.git /opt/OmniParser \
    && cd /opt/OmniParser && git checkout ${OMNIPARSER_REF}

RUN --mount=type=cache,target=/root/.cache/huggingface \
    python3.12 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    "microsoft/OmniParser-v2.0",
    local_dir="/opt/OmniParser/weights",
    allow_patterns=["icon_detect/*", "icon_caption_florence/*"],
)
PY

ENV OMNIPARSER_ROOT=/opt/OmniParser
ENV PYTHONPATH=/opt/OmniParser:${PYTHONPATH}

RUN make PYTHON=python3.12 proto

EXPOSE 9200
CMD ["python3.12", "-m", "shore_ai.server"]
