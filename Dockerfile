FROM python:3.11-slim

LABEL maintainer="kubeservice-stack"
LABEL org.opencontainers.image.source="https://github.com/kubeservice-stack/hf-sync-action"
LABEL org.opencontainers.image.description="Bidirectional sync of AI models and datasets between HuggingFace and ModelScope"
LABEL org.opencontainers.image.licenses="Apache-2.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

RUN git lfs install

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
