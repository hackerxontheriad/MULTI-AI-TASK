FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium \
    G4F_MEDIA_DIR=/app/generated_images
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver ffmpeg flac ca-certificates fonts-liberation fonts-noto-color-emoji \
    libnss3 libatk-bridge2.0-0 libatk1.0-0 libgbm1 libasound2 libxshmfence1 libxdamage1 \
    libxrandr2 libxcomposite1 libxkbcommon0 libgtk-3-0 libdrm2 libu2f-udev libvulkan1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p generated_images generated_media && chmod -R 755 /app
EXPOSE 10000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
