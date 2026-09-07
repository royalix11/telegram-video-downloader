---
name: ytdlp-extractor-engine
description: Multi-platform media extraction via yt-dlp covering Instagram, TikTok, YouTube Shorts, X/Twitter, Reddit, and Facebook with format selection heuristics, cookies authentication, and anti-throttling options.
---

# yt-dlp Extractor Engine Skill

## Overview
This skill handles querying, inspecting, and extracting maximum-resolution media streams across modern social platforms (YouTube Shorts, Instagram, TikTok, X/Twitter, Reddit, Facebook) using `yt-dlp`. It runs non-blockingly inside Python's async event loop with automatic redirect pre-resolution, format sorting, and exponential backoff retries.

---

## 1. High-Fidelity Format Selection & Sorting Heuristics

### Vertical Short-Form Video Rules (YouTube Shorts, Reels, TikTok)
1. **Never restrict formats by `height<=1080`:**
   Vertical 9:16 content has an inverted aspect ratio ($1080 \times 1920$). Restricting by `height<=1080` forces vertical video into $720 \times 1280$ or $360 \times 640$.
2. **Do NOT filter out VP9 or AV1 codecs on YouTube:**
   YouTube only serves high-bitrate 1080p and 4K Shorts in VP9 (`vp09`) or AV1 (`av01`). Restricting by `ext=mp4` forces YouTube to serve low-resolution 360p H.264 fallbacks.
3. **Do NOT restrict YouTube player clients to `['android', 'web']`:**
   The Android player client skips high-definition video formats and caps playback to 360p or 720p. Let `yt-dlp` default to its modern visionOS, iOS, and Web clients.
4. **Dynamic Format Sorting Matrix:**
   ```python
   # For YouTube, Instagram, Facebook, Reddit, X:
   format_str = "bestvideo+bestaudio/best"
   format_sort = ["res", "fps", "codec", "size", "br"]

   # For TikTok & Douyin (Preserves creator voiceovers):
   format_str = "best[vcodec!=none][acodec!=none]/best"
   format_sort = ["res", "fps", "size", "br"]
   ```

---

## 2. Platform Specific Handlers & Anti-Bot Mitigations

### TikTok (Mobile & Web)
- **Audio Stream Preservation (Voiceover Protection):**
  - TikTok video streams (`h264_...`, `download`, etc.) are natively pre-muxed with both the creator's microphone voiceover and background music mixed into an AAC stream.
  - TikTok pages also expose an isolated `audio` stream pointing to the original background song in TikTok's sound library.
  - *Mandatory Rule:* For TikTok and Douyin, format MUST be:
    `format = "best[vcodec!=none][acodec!=none]/best"`
    Never append `+bestaudio` on TikTok streams.
- **Canonical HTTP Pre-Resolution:**
  - Follow HTTP 301/302 redirects with modern browser headers (`Referer: https://www.tiktok.com/`) and strip tracking parameters (`_t`, `_r`, `is_from_webapp`) from the final canonical URL before handing it off to `yt-dlp`.

### YouTube Shorts & Videos
- **URL Sanitization:**
  - Mobile share links append tracking tokens (e.g. `?si=t4_xT5A4rN4Xbv...`).
  - Always clean URLs before extraction by stripping all query parameters from `/shorts/` endpoints, preserving only `v=` for standard watch URLs.
- **Multi-Tier Fallback Cascade:**
  - YouTube frequently enables experiments (such as SABR-only streaming on mobile endpoints) or applies strict web challenges.
  - To ensure zero outright failures, wrap YouTube extraction in a 3-tier cascade:
    - **Tier 1 (High Quality DASH):**
      `format = "bestvideo+bestaudio/best"`
      `format_sort = ["lang", "res", "fps", "codec:h264", "size", "br"]`
      `extractor_args = {"youtube": {"player_client": ["web", "default"], "lang": ["en", "orig", "original"]}}`
    - **Tier 2 (Mobile Client Fallback):**
      If Tier 1 fails, fall back to:
      `extractor_args = {"youtube": {"player_client": ["android", "web"], "lang": ["en", "orig", "original"]}}`
    - **Tier 3 (Pre-muxed Stream Fallback):**
      If stream combination fails, fall back to:
      `format = "best/bestvideo*+bestaudio*"`
- **Multi-Language Audio (MLA) & Original Dialogue Prioritization:**
  - YouTube hosts foreign audio translations and AI dubs as separate audio streams.
  - Prioritizing `"lang"` in `format_sort` and passing `lang: ["en", "orig", "original"]` in `extractor_args` ensures the creator's original dialogue is prioritized without hard-filtering that could break single-track videos.
  - *Track Inspection:* Pre-inspect formats and log all tracks:
    `[Audio Detection] Found tracks: {track.get('format_note'): track.get('language') for track in audio_formats}`.


---

## 3. Resilient Retry Architecture
Wrap extraction and downloads in a 3-stage exponential backoff loop (`1.5s`, `3.0s`) with rotating `User-Agent` headers and `Referer` headers to mitigate transient CDN drops without surfacing errors to users.

```python
opts = {
    'format': format_str,
    'format_sort': format_sort,
    'merge_output_format': 'mp4',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'retries': 5,
    'extractor_retries': 5,
    'fragment_retries': 5,
    'socket_timeout': 15,
    'impersonate': ImpersonateTarget.from_str('chrome'),
    'http_headers': {
        'User-Agent': chosen_ua,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': referer,
    },
}
```
