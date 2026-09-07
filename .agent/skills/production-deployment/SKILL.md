---
name: production-deployment
description: Continuous 24/7 cloud hosting, Docker containerization, systemd daemonization, and server maintenance for the Telegram Video Downloader Bot.
---

# Production Deployment & Continuous 24/7 Hosting Skill

## Overview
This skill guides the continuous 24/7 deployment and hosting of the asynchronous Telegram Video Downloader Bot across cloud servers (Linux VPS or Container PaaS). Because the bot executes real-time media extraction (`yt-dlp`), FFmpeg video transcoding (`libx264`, `aac`), and high-speed multi-megabyte uploads to the Telegram Bot API, proper containerization, compute sizing, and disk hygiene are essential.

---

## 1. Workload Analysis & Server Sizing Guidelines

### Resource Requirements
1. **CPU (Compute Bound during Transcoding):**
   - When extracting modern 1080p/4K vertical streams (AV1/VP9), FFmpeg performs visually lossless transcoding (`-c:v libx264 -crf 18 -preset slow`).
   - *Recommendation:* Dedicated or standard cloud cores (minimum 1 vCPU, ideally **2 vCPUs**). Avoid shared micro tiers with aggressive throttling caps (like AWS t2.micro or Google e2-micro), as CPU throttling extends transcode turnaround times.
2. **Memory (RAM):**
   - Idle footprint: ~70 MB RAM.
   - Peak footprint during concurrent 4K extraction, FFprobe stream probing, and Telegram upload: ~500 MB – 1 GB RAM.
   - *Recommendation:* Minimum **1 GB RAM** (with 1 GB swapfile), ideally **2 GB RAM**.
3. **Storage (Disk I/O & Capacity):**
   - High-bitrate 4K vertical Shorts can temporarily take 100–200 MB during downloading, remuxing, and compression.
   - Under concurrent requests (`MAX_CONCURRENT_DOWNLOADS=3`), peak scratch usage can reach 1–2 GB.
   - *Recommendation:* Minimum **20 GB NVMe/SSD** storage with automated cron/systemd directory pruning.

---

## 2. Server Options Comparison

| Hosting Option | Monthly Cost | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **Hetzner Cloud (CX22 / CAX11)** | ~€3.50 – €4.50 | Exceptional CPU performance, unmetered 20 TB traffic, NVMe SSD | Requires basic Linux terminal setup | **Top Pick for Value & Speed** |
| **DigitalOcean / Linode / Vultr** | $4.00 – $6.00 | Instant deployment, worldwide locations, user-friendly dashboard | Slightly higher cost per compute core | Excellent Alternative |
| **Oracle Cloud Always-Free** | **Free** ($0) | 4 Ampere ARM vCPUs + 24 GB RAM free forever | Lengthy signup verification; ARM64 architecture | **Best Free Tier** |
| **Railway / Koyeb / Render** | Free tier / $5+ | Zero-config Docker deployment directly from GitHub | Potential container sleep timeouts; transient disk constraints | Good for quick prototype |

---

## 3. Docker Container Deployment (Recommended)

Containerization guarantees that Python 3.11, the native `ffmpeg`/`ffprobe` binaries, and system libraries run identically without host dependency conflicts.

### Build and Launch
```bash
# 1. Clone repository to server
git clone <your-repo-url> /opt/telegram-bot
cd /opt/telegram-bot

# 2. Configure environment variables
cp .env.example .env
nano .env  # Add your BOT_TOKEN

# 3. Build and launch in detached background mode
docker compose up -d --build

# 4. Monitor real-time logs
docker compose logs -f telegram-bot
```

### Container Management Commands
```bash
# Check container status and healthcheck
docker compose ps

# View live stream output and download telemetry
docker compose logs -f --tail=100

# Restart bot after updating code or .env
docker compose restart telegram-bot

# Pull latest code and rebuild
git pull
docker compose up -d --build
```

---

## 4. Linux VPS Native Deployment (`systemd`)

For deployments directly on Ubuntu/Debian without Docker:

### One-Time Host Setup
```bash
# 1. Update packages and install prerequisites
sudo apt-get update && sudo apt-get install -y \
    python3 python3-pip python3-venv ffmpeg curl git ca-certificates

# 2. Clone repository to /opt/telegram-bot
sudo git clone <your-repo-url> /opt/telegram-bot
sudo chown -R $USER:$USER /opt/telegram-bot
cd /opt/telegram-bot

# 3. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Set your BOT_TOKEN and parameters
```

### Install and Enable `systemd` Service
```bash
# 1. Copy unit file template to systemd directory
sudo cp telegram-bot.service /etc/systemd/system/telegram-bot.service

# 2. Adjust User and WorkingDirectory if not using 'ubuntu'
sudo nano /etc/systemd/system/telegram-bot.service

# 3. Reload systemd daemon and start service immediately
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot

# 4. Inspect status
sudo systemctl status telegram-bot
```

### Logging and Service Control
```bash
# Follow live colored logs
sudo journalctl -u telegram-bot -f -o cat

# Restart service after code updates
sudo systemctl restart telegram-bot

# Stop or disable service
sudo systemctl stop telegram-bot
```

---

## 5. Server Disk Hygiene & Temp Pruning

Although `MediaOrchestrator` automatically cleans up temporary directories using Python's `TemporaryDirectory` context manager, unexpected process terminations (e.g. system reboots during transcode) can occasionally leave orphaned files in `temp_downloads/`.

### Automated Hourly Cron Cleanup
Add a simple cron job to prune any orphaned files in `temp_downloads/` older than 2 hours:
```bash
(crontab -l 2>/dev/null; echo "0 * * * * find /opt/telegram-bot/temp_downloads -type f -mmin +120 -delete") | crontab -
```

### Check Available Storage
```bash
df -h /
```
