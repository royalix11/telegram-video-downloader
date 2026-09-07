# 🚀 Telegram Multi-Platform Video Downloader Bot

An asynchronous, production-ready Telegram Bot built with Python 3.11, [aiogram 3.x](https://github.com/aiogram/aiogram), [yt-dlp](https://github.com/yt-dlp/yt-dlp), and [FFmpeg](https://ffmpeg.org/).

Downloads video streams in the highest possible quality from TikTok, Instagram Reels, YouTube Shorts, X/Twitter, Reddit, and Facebook, automatically remuxing and transcoding to Telegram-compatible H.264 / AAC MP4 containers with `+faststart` streaming optimization and 2-pass bitrate compression strictly adhering to Telegram's 50 MB Bot API ceiling.

---

## ✨ Features

- **Multi-Platform Interception:**
  - 🎵 **TikTok:** Full audio preservation (voiceovers + creator audio retained, isolated sound-library stripping prevented). Automatic shortlink redirection handling (`vm.tiktok.com`, `vt.tiktok.com`, `tiktok.com/t/`).
  - 📸 **Instagram:** Reels, video posts, stories, and share links (`instagram.com/reel/`, `/p/`).
  - 🔴 **YouTube Shorts & Videos:** Multi-tier client fallback cascade (`web`, `android`), original creator language track prioritization (MLA AI-dub stripping), tracking token cleaning (`?si=...`).
  - 🐦 **X (Twitter):** Media status links (`x.com`, `twitter.com`).
  - 🤖 **Reddit & Facebook:** Post video streams and reels.

- **High-Quality Media Pipeline:**
  - Extracts full 1080p vertical resolution (`format_sort` with bitrate, fps, and resolution prioritization).
  - Native FFmpeg remuxing with `-movflags +faststart` for instant playback buffering on mobile clients.
  - Generates high-definition video thumbnails and extracts duration/dimensions via `ffprobe`.
  - Automated 2-pass target bitrate compression for videos exceeding 49.5 MB.
  - Automatic temporary file cleanup with zero disk leakage.

- **Production-Ready & 24/7 Hosting:**
  - Fully containerized with `Dockerfile` and `docker-compose.yml` (multi-stage build, non-root user `appuser`, healthcheck).
  - Native Linux `systemd` unit configuration with automatic crash recovery (`Restart=always`).
  - Resilient upload timeouts (300s) preventing network aborts on large media payloads.

---

## 🛠️ Quick Start (Local Run)

### 1. Prerequisites
- Python 3.11+
- FFmpeg & FFprobe installed and accessible in your system `PATH`.

### 2. Setup & Installation
```bash
# Clone the repository
git clone <repository_url>
cd "Telegram Bot Downloader"

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` and insert your Telegram Bot Token:
```env
BOT_TOKEN="your_bot_token_from_botfather"
MAX_CONCURRENT_DOWNLOADS=3
MAX_FILE_SIZE_MB=49.5
TEMP_DIR="temp_downloads"
```

### 4. Run
```bash
python main.py
```

---

## 🐳 Running with Docker

```bash
# 1. Create .env file with your BOT_TOKEN
cp .env.example .env
nano .env

# 2. Build and start in background
docker compose up -d --build

# 3. View live logs
docker compose logs -f telegram-bot
```

---

## 🧪 Running Tests
```bash
python test_pipeline.py
python test_youtube_resilience.py
python test_tiktok_audio.py
```
