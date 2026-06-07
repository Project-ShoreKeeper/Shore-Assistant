FROM nvidia/cuda:12.9.0-runtime-ubuntu24.04

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3-pip espeak-ng git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml Makefile ./
COPY proto ./proto
COPY src ./src

RUN python3.12 -m pip install --break-system-packages \
      torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
      --index-url https://download.pytorch.org/whl/cu129
RUN python3.12 -m pip install --break-system-packages -e .[dev]
RUN make proto

EXPOSE 9200
CMD ["python3.12", "-m", "shore_ai.server"]
