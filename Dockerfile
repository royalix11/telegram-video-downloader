# Production Dockerfile for Telegram Video Downloader Bot
# Incorporates Python 3.11, system FFmpeg, curl-cffi support, and non-root security.

FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (FFmpeg, FFprobe, and ca-certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root dedicated application user
RUN useradd -m -u 1000 -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appuser . .

# Ensure temporary directory exists and has appropriate permissions
RUN mkdir -p /app/temp_downloads \
    && chown -R appuser:appuser /app/temp_downloads

# Switch to non-root user
USER appuser

# Health check ensuring python and bot environment are responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import aiogram, yt_dlp; print('Healthy')" || exit 1

# Launch the asynchronous Telegram polling service
CMD ["python", "main.py"]
