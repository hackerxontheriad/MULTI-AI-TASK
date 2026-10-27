# Small supported-API image. No bundled browser automation, password scraping or unofficial wrappers.
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=10000
WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install -r requirements.txt
COPY . .
RUN mkdir -p data generated_images generated_media uploaded_files \
 && chown -R app:app /app
USER app
ENV HOME=/home/app
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','10000'), timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --timeout-keep-alive 30 --no-access-log"]
