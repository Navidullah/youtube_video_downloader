# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for YouTube Downloader API
#
# Stage 1 (builder):  install Python dependencies into a virtual env
# Stage 2 (runner):   copy only the venv + app code → smaller final image
#
# Why multi-stage?
#   Build tools (gcc, pip cache) are NOT needed at runtime.
#   Keeping them out of the final image reduces attack surface and image size.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (Docker layer caching: deps rebuild only when
# requirements.txt changes, not on every code change)
COPY requirements.txt .

# Create a virtual environment and install dependencies into it
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runner ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Install ffmpeg (required for video/audio merging)
# This is the most important system dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source code
COPY . .

# Create temp directory for downloads
RUN mkdir -p app/temp

# Create a non-root user for security
RUN groupadd --system appuser && useradd --system --gid appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose the port uvicorn will listen on
EXPOSE 8000

# Health check – Render and Docker will poll this
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Production start command
# --workers 1: single worker keeps memory manageable on Render free tier
# --timeout-keep-alive: matches Render's 75s idle timeout
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "75"]
