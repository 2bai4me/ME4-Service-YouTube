# ME4-YouTube — Dockerfile (Template)
# Konform zum ME4 Container-Standard v1.0 (siehe OpenBrain)
#
# TODO: Vervollstaendigen, wenn der Service produktionsreif ist
# Aktuell ist das ein Template mit Platzhaltern.

FROM python:3.11-slim
WORKDIR /app

# System-Dependencies (Playwright + Chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
COPY requirements.txt . 2>/dev/null || echo "TODO: requirements.txt erstellen"
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
RUN pip install --no-cache-dir playwright yt-dlp fastapi uvicorn

# Playwright-Browser installieren
RUN playwright install chromium

# Source-Code
COPY . /app/

# Non-root user
RUN useradd -m -u 1001 me4 2>/dev/null || true \
    && mkdir -p /app/data /app/logs /home/me4/.cache \
    && chown -R me4:me4 /app /home/me4
USER me4

# ENV-Defaults
ENV PORT=8770 \
    SERVICE_ID=ME4-YOUTUBE \
    SERVICE_VERSION=1.0.0 \
    LOG_LEVEL=info

EXPOSE 8770 8771 8772

# Volumes
VOLUME ["/app/data", "/app/logs"]

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8770/health || exit 1

CMD ["python", "-m", "app.main"]
