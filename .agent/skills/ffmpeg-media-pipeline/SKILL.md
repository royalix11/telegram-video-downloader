---
name: ffmpeg-media-pipeline
description: Remuxing media streams into Telegram-compatible H.264/AAC MP4 containers with +faststart moov atom, video thumbnail generation, ffprobe media inspection, visually lossless CRF 18 transcoding, and 2-pass bitrate-constrained compression strictly under 49.5 MB.
---

# FFmpeg Media Pipeline Skill

## Overview
This skill governs the transcoding, remuxing, thumbnail extraction, metadata probing, and two-pass compression operations required to prepare downloaded video streams for in-app native playback within Telegram, strictly adhering to the 50 MB Bot API payload ceiling while enforcing maximum visual fidelity.

## Core Directives & Container Specifications
To ensure smooth inline playback without requiring external players:
1. **Container:** MP4 (`.mp4`)
2. **Video Codec:** H.264 (`libx264`)
3. **Pixel Format:** `yuv420p` (strictly required for iOS and older Android Telegram clients)
4. **Audio Codec:** AAC (`aac`) with stereo 2-channel 44.1kHz or 48kHz (bitrate: 192 kbps)
5. **Streaming Header:** FastStart (`-movflags +faststart`) to relocate the `moov` atom to the front of the file, allowing instant playback buffering before the entire file finishes downloading.

---

## 1. Metadata Probing (`ffprobe`)
Always inspect media characteristics before deciding whether to remux, compress, or stream directly.

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration,codec_name,bit_rate -show_entries format=duration,size,bit_rate -of json "input_file"
```

### Key Extracted Attributes:
- `duration`: Float seconds of total media playback.
- `width` & `height`: Dimensions for Telegram's player presentation. Passed directly to `send_video(width=w, height=h)` to prevent client-side downscaling.
- `video_codec`: Codec identifier (e.g., `h264`, `hevc`, `vp9`, `av01`).
- `size`: Total file size in bytes.

---

## 2. Transcoding Heuristics: Passthrough vs. Visually Lossless CRF 18

### Rule A: Bitstream Direct Passthrough (`-c copy`)
When video is already `h264`/`avc1` and audio is `aac`/`mp4a`:
**Never re-encode.** Directly copy the original bitstream to preserve 100% fidelity with zero CPU overhead:

```powershell
ffmpeg -y -i "input.mp4" -c copy -movflags +faststart "output.mp4"
```

### Rule B: Visually Lossless Transcoding (VP9 / AV1 / ProRes)
When video is VP9 or AV1 (standard for 1080p/4K YouTube Shorts and WebM streams):
Transcode to H.264 using high-fidelity parameters:

```powershell
ffmpeg -y -i "input.mp4" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart "output.mp4"
```

- `-crf 18`: Visually lossless encoding preserving edge sharpness, textures, and gradient smoothness.
- `-preset slow`: Produces maximum compression density per bit for high-definition playback.
- `-b:a 192k`: Studio-grade stereo audio track.

---

## 3. Two-Pass Compression Pipeline (< 49.5 MB Threshold)

Telegram Bot API strictly rejects payloads $\ge 50$ MB. The safety threshold is set at **49.5 MB (51,904,512 bytes)**.
**Only apply 2-pass compression if the visually lossless output actually exceeds 49.5 MB.**

### Bitrate Calculation Formula
Given duration $T$ in seconds:
1. Target total budget: $B_{total} = 48.0 \times 1024 \times 1024 \times 8 \text{ bits} \approx 402,653,184 \text{ bits}$
2. Total allowable bitrate: $R_{total} = \frac{B_{total}}{T} \text{ bps}$
3. Audio bitrate budget: $R_{audio} = 96,000 \text{ bps}$ (or $64,000 \text{ bps}$ for long media)
4. Video bitrate budget: $R_{video} = R_{total} - R_{audio} \text{ bps}$

### Two-Pass Execution Commands
```powershell
# Pass 1: Motion and complexity analysis
ffmpeg -y -i "input.mp4" -c:v libx264 -b:v $vbitrate -pass 1 -preset fast -an -f null NUL

# Pass 2: Final encode with +faststart
ffmpeg -y -i "input.mp4" -c:v libx264 -b:v $vbitrate -pass 2 -preset fast -c:a aac -b:a $abitrate -pix_fmt yuv420p -movflags +faststart "compressed.mp4"
```

---

## 4. Video Thumbnail Extraction
Generate a crisp video thumbnail at 15% or the 1-second mark:

```powershell
ffmpeg -y -ss 00:00:01 -i "input.mp4" -vframes 1 -vf "scale=320:-1" -q:v 3 "thumbnail.jpg"
```
