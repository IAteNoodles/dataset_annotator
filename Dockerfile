FROM python:3.11-slim

WORKDIR /app

# Runtime deps for Pillow image processing
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY config /app/config
COPY frontend /app/frontend

RUN mkdir -p /app/data /app/dataset /app/exports /app/snapshots /app/crops

ENV DATASET_ANNOTATOR_CONFIG=/app/config/dataset_config.example.yaml
ENV DATASET_ANNOTATOR_DB=/app/data/annotator.db
ENV DATASET_ANNOTATOR_DATASET_PATH=/app/dataset

EXPOSE 8080

CMD ["python", "-m", "backend.cli", "serve", "--port", "8080"]