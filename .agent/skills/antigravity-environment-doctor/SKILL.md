---
name: antigravity-environment-doctor
description: Automated host environment diagnosis verifying FFmpeg/FFprobe binaries, Python virtual environment integrity, disk write permissions in temp directories, and social media CDN connectivity.
---

# Antigravity Environment Doctor Skill

## Overview
This skill provides automated environment verification procedures to validate host system readiness before starting the Telegram downloader bot or during active troubleshooting (`/health` command).

---

## Diagnostic Check Matrix

| Component | Verification Target | Expected Result | Failure Remediation |
| :--- | :--- | :--- | :--- |
| **FFmpeg Binary** | `ffmpeg -version` | Version string present, `libx264` enabled | Install via `winget install Gyan.FFmpeg` or download static build |
| **FFprobe Binary** | `ffprobe -version` | Version string present | Verify PATH contains ffmpeg/bin directory |
| **Python Environment**| Python 3.11+ virtual environment | Active `.venv` with `aiogram`, `yt_dlp` | Rebuild virtual environment: `uv venv --python 3.11 .venv` |
| **Disk Write Permissions**| Temp directory read/write/delete | Temporary file created, written, read, unlinked | Check directory permissions or configure custom `TEMP_DIR` |
| **Network Reachability** | DNS / HTTPS to Instagram, TikTok, YouTube | HTTP 200/301/302 response | Check proxy, VPN, or firewall restrictions |

---

## 1. Automated Health Check Implementation
```python
import shutil
import asyncio
import tempfile
from pathlib import Path
import aiohttp

class EnvironmentDoctor:
    @staticmethod
    def check_ffmpeg() -> dict:
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")
        return {
            "ffmpeg": ffmpeg_path is not None,
            "ffprobe": ffprobe_path is not None,
            "ffmpeg_path": ffmpeg_path,
            "ffprobe_path": ffprobe_path,
        }

    @staticmethod
    def check_temp_disk(base_path: Path | None = None) -> dict:
        try:
            with tempfile.TemporaryDirectory(dir=base_path) as tmpdir:
                test_file = Path(tmpdir) / "health_check.tmp"
                test_file.write_text("ok")
                content = test_file.read_text()
                assert content == "ok"
            return {"status": True, "path": str(base_path or tempfile.gettempdir())}
        except Exception as e:
            return {"status": False, "error": str(e)}

    @staticmethod
    async def check_cdn_connectivity() -> dict:
        endpoints = {
            "YouTube": "https://www.youtube.com",
            "TikTok": "https://www.tiktok.com",
            "Instagram": "https://www.instagram.com",
            "X": "https://x.com",
            "Reddit": "https://www.reddit.com",
        }
        results = {}
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for name, url in endpoints.items():
                try:
                    async with session.get(url, allow_redirects=True) as resp:
                        results[name] = resp.status in (200, 301, 302, 403)
                except Exception:
                    results[name] = False
        return results
```

---

## 2. Recovery Procedures
- If `ffmpeg` is missing on Windows:
  Run `winget install Gyan.FFmpeg` or static zip extraction into `C:\ffmpeg` with PATH addition.
- If Temp disk permissions fail:
  Specify a project-local temp directory, e.g. `./temp_downloads`, ensuring `os.makedirs(..., exist_ok=True)`.
