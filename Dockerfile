# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile — YouTube Downloader API with bgutil PO token server
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Python deps builder ──────────────────────────────────────────────
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


# ── Stage 2: bgutil server builder ────────────────────────────────────────────
FROM node:20-slim AS bgutil-builder

# Clone and compile the bgutil PO token server
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /bgutil

WORKDIR /bgutil/server
RUN npm ci && npx tsc && npm prune --production


# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Install ffmpeg + Node.js runtime (for bgutil server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy compiled bgutil server
COPY --from=bgutil-builder /bgutil/server /bgutil/server

# Copy application source
COPY . .
RUN mkdir -p app/temp

# Write start script with guaranteed Unix line endings
# Key fixes:
#   --port 4416  forces bgutil to 4416 regardless of PORT env var
#   ${PORT:-8000} lets uvicorn use Render's PORT (e.g. 10000) or 8000 locally
RUN printf '#!/bin/sh\n\
node /bgutil/server/build/main.js --port 4416 &\n\
echo "bgutil started on port 4416"\n\
sleep 4\n\
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 75\n\
' > /start.sh && chmod +x /start.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["/start.sh"]
