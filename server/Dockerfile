FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# System tools that power several namespaces (OCR, media, pdf images, git).
# build-essential + cmake are a fallback so llama-cpp-python can compile from
# source if no prebuilt CPU wheel matches this platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        ffmpeg \
        poppler-utils \
        git \
        build-essential \
        cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --prefer-binary makes pip use the prebuilt CPU wheel (from the extra index in
# requirements.txt) when available, falling back to a source build otherwise.
RUN pip install --prefer-binary -r requirements.txt

COPY . .

# Writable workspace for tool runtime (HF Spaces run as a non-root user)
RUN mkdir -p /app/workspace && chmod -R 777 /app

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
