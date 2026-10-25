# syntax=docker/dockerfile:1
# Pinned to bookworm: package names (chromium, chromium-driver) are stable there.
FROM python:3.11-slim-bookworm

# INSTALL_BROWSER=1 installs Chromium for browser-based community (g4f) adapters.
#   Use INSTALL_BROWSER=0 + REQUIREMENTS_FILE=requirements-lite.txt for a small, fast image that
#   runs every official free-tier API route (recommended for 512 MB free hosts).
ARG INSTALL_BROWSER=1
ARG REQUIREMENTS_FILE=requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000 \
    G4F_MEDIA_DIR=/app/generated_images \
    BROWSER_NO_SANDBOX=auto

WORKDIR /app

# ca-certificates fixes "SSL: CERTIFICATE_VERIFY_FAILED" on slim images.
# chromium pulls in every shared library it needs; do not hand-list libs (names change between Debian releases).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl fonts-liberation \
 && if [ "$INSTALL_BROWSER" = "1" ]; then \
      apt-get install -y --no-install-recommends chromium chromium-driver; \
    fi \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-lite.txt ./
RUN python -m pip install --upgrade pip \
 && pip install -r "${REQUIREMENTS_FILE}"

COPY . .
# Wrapper adds --no-sandbox/--disable-dev-shm-usage/headless; only used when Chromium is installed.
RUN install -m 0755 scripts/chromium-safe /usr/local/bin/chromium-safe \
 && if [ "$INSTALL_BROWSER" != "1" ]; then rm -f /usr/local/bin/chromium-safe; fi \
 && useradd --create-home --uid 10001 app \
 && mkdir -p generated_images generated_media \
 && chown -R app:app /app

USER app
ENV HOME=/home/app

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','10000'), timeout=4)" || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --timeout-keep-alive 30"]
