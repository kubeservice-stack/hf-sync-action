FROM python:3.11-slim

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

ENTRYPOINT ["python", "-m", "src.sync_engine"]
