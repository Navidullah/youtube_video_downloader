# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile — YouTube Downloader API
#
# Stage 1: Python deps builder
# Stage 2: Runtime image with ffmpeg + Node.js + bgutil PO token server
#
# Why bgutil?
#   YouTube requires Proof-of-Origin (PO) tokens for web-client requests from
#   datacenter IPs. bgutil generates these tokens server-side using YouTube's
#   own JavaScript challenge, without cookies or manual login.
#   This is the same approach used by production YouTube download services.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Python builder ───────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Install system deps:
#   ffmpeg   — video/audio merging and MP3 conversion
#   curl     — used by Node.js setup script
#   nodejs   — runtime for bgutil PO token server
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install bgutil PO token provider globally
# This npm package starts a local HTTP server that generates YouTube PO tokens
# so yt-dlp can use the full WEB client without being bot-detected.
RUN npm install -g @imputnet/bgutil-yt-dlp-pot-provider 2>/dev/null; exit 0

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . .
RUN mkdir -p app/temp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "75"]
