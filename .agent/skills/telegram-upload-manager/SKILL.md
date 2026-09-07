---
name: telegram-upload-manager
description: Asynchronous media dispatch via aiogram 3.x with interactive stage-by-stage status feedback, rate-limit handling, metadata attachment, and strict 50 MB Bot API payload enforcement.
---

# Telegram Upload Manager Skill

## Overview
This skill outlines patterns for handling asynchronous communication with users via Telegram Bot API (`aiogram` v3.x), providing reassuring real-time status transitions, validating payload limits, and ensuring streamable video uploads.

---

## 1. Interactive Lifecycle Messages
When processing heavy video downloads, users expect immediate feedback and clear progress. Avoid leaving users in the dark:

### Status Transitions:
1. **Receipt & Link Extraction:**
   `🔍 Analyzing link & querying media stream...`
2. **Download in Progress:**
   `⬇️ Downloading stream: <b>{title}</b> ({resolution})...`
3. **Processing & Optimization (or Compression):**
   - Standard: `⚙️ Optimizing container for instant streaming...`
   - Compressing: `📦 Original size ({orig_size_mb} MB) exceeds Telegram limit. Compressing to < 50 MB...`
4. **Uploading to Telegram:**
   `⬆️ Uploading video to Telegram ({final_size_mb} MB)...`
5. **Completion:**
   - Call `bot.send_video(...)`
   - Promptly `await status_message.delete()` to keep chat history tidy.

---

## 2. Telegram Bot API 50 MB Boundary Enforcement
Telegram's standard Bot API rejects file uploads $\ge 50$ MB with `TelegramBadRequest: File is too big`.

```python
MAX_UPLOAD_BYTES = int(49.5 * 1024 * 1024) # 51,904,512 bytes

def validate_upload_size(file_path: Path):
    size = file_path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            f"File size ({size / 1024 / 1024:.2f} MB) exceeds Telegram 49.5 MB bot limit."
        )
```

---

## 3. Streaming-Optimized `send_video` Dispatch
Always pass the complete probed metadata to `bot.send_video`. This tells Telegram clients the exact aspect ratio and allows instant streaming without downloading the entire file first:

```python
from aiogram.types import FSInputFile

await bot.send_video(
    chat_id=chat_id,
    video=FSInputFile(video_path),
    duration=int(media_info.duration),
    width=media_info.width,
    height=media_info.height,
    thumbnail=FSInputFile(thumb_path) if thumb_path.exists() else None,
    caption=f"🎬 <b>{caption}</b>\n\n🔗 <i>Downloaded via FastDownloaderBot</i>",
    parse_mode="HTML",
    supports_streaming=True
)
```

---

## 4. Concurrency Throttling with `asyncio.Semaphore`
Prevent system resource exhaustion (CPU spike from multiple simultaneous ffmpeg passes or network saturation):
```python
# In bot setup
download_semaphore = asyncio.Semaphore(config.max_concurrent_downloads)

# In handler
async with download_semaphore:
    await orchestrator.process_and_send(...)
```

---

## 5. Graceful Error Handling
Whenever an exception occurs:
1. Update the status message with a clear, user-friendly error explanation.
2. Avoid dumping raw Python stack traces into user chats.
3. Examples:
   - *Geo-restricted:* "❌ This video is unavailable in our server's region."
   - *Too long / Oversize:* "⚠️ Video duration is too long to compress under Telegram's 50 MB limit without severe degradation."
   - *Private:* "🔒 This post is private. Please provide credentials or public link."
