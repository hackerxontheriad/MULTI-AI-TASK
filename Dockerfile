FROM python:3.10-slim

WORKDIR /app

# Basic build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Automatically install all correct system dependencies for Playwright chromium
RUN playwright install-deps chromium
RUN playwright install chromium

COPY . .

EXPOSE 10000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
