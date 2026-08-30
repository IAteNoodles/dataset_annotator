FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY config/ ./config/
COPY frontend/dist/ ./frontend/dist/

ENV DATASET_ANNOTATOR_CONFIG=/app/config/dataset_config.yaml
ENV DATASET_ANNOTATOR_DB=/app/data/annotator.db

RUN mkdir -p /app/data /app/snapshots /app/exports /app/plugins

EXPOSE 8080

CMD ["python", "-m", "backend.cli", "serve", "--port", "8080"]