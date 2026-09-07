"""Verification script testing YouTube Shorts Multi-Language Audio (MLA) original stream selection.

Verifies that YouTube Shorts originally spoken in English (or creator's native tongue)
download with the original audio track and NEVER select foreign/AI dubbed tracks (e.g. Hindi, Spanish).
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from bot.services.extractor import ExtractorService
from bot.services.orchestrator import MediaOrchestrator
from bot.utils.formatters import format_bytes


async def test_youtube_mla_selection():
    print("=" * 70)
    print("🎙️ YouTube Shorts Multi-Language Audio (MLA) Selection Verification")
    print("=" * 70)

    # 1. Test Format Configuration & Heuristics
    extractor = ExtractorService()
    test_url = "https://www.youtube.com/shorts/5mU6SRS2Bxo"
    opts = extractor._build_options(test_url)

    print("\n[Step 1] Inspecting Extractor Options for YouTube:")
    print(f"  • Format Selector: {opts['format']}")
    print(f"  • Format Sort:     {opts['format_sort']}")
    print(f"  • Extractor Args:  {opts.get('extractor_args')}")

    assert opts["format"] == "bestvideo+bestaudio/best", "Format must be resilient bestvideo+bestaudio/best!"
    assert opts["format_sort"][0] == "lang", "format_sort must prioritize 'lang' first!"
    assert "youtube" in opts.get("extractor_args", {}), "Missing youtube extractor_args!"
    assert "orig" in opts["extractor_args"]["youtube"]["lang"], "Missing 'orig' in extractor_args lang!"
    assert "player_client" in opts["extractor_args"]["youtube"], "Missing player_client in extractor_args!"
    print("✅ Step 1 Passed: Extractor options properly configure resilient format and language priority.")

    # 2. Test Format Metadata Pre-Inspection
    print("\n[Step 2] Querying Media Metadata & Inspecting Audio Tracks:")
    meta = await extractor.extract_metadata(test_url)
    formats = meta.get("formats", [])
    audio_formats = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
    print(f"  • Title: {meta.get('title')}")
    print(f"  • Total Audio Tracks Detected: {len(audio_formats)}")

    # Detect tracks with foreign dubs / non-original audio
    dubbed_tracks = [
        f for f in audio_formats
        if "dub" in str(f.get("format_note", "")).lower()
        or (f.get("language") and f.get("language") != "en")
        or (f.get("language_preference") is not None and f.get("language_preference") < 0)
    ]
    orig_tracks = [
        f for f in audio_formats
        if "original" in str(f.get("format_note", "")).lower()
        or "default" in str(f.get("format_note", "")).lower()
        or (f.get("language_preference") is not None and f.get("language_preference") >= 0)
    ]
    print(f"  • Dubbed / Foreign Audio Tracks: {len(dubbed_tracks)}")
    print(f"  • Original Audio Tracks:         {len(orig_tracks)}")
    assert len(dubbed_tracks) > 0, "Test short should have multi-language dubbed tracks!"
    assert len(orig_tracks) > 0, "Test short should have an original audio track!"
    print("✅ Step 2 Passed: Multi-language audio tracks and dubbed streams detected.")

    # 3. Process Download and Pipeline Execution
    print("\n[Step 3] Running MediaOrchestrator Pipeline:")
    orchestrator = MediaOrchestrator()

    def progress(text: str):
        clean_text = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        print(f"  -> {clean_text}")

    async with orchestrator.process_job(
        url=test_url,
        platform_name="YouTube",
        progress_cb=progress
    ) as media:
        info = media.media_info
        print("\n" + "=" * 70)
        print("📊 Final Media Stream Verification:")
        print(f"  • Title:          {media.title}")
        print(f"  • Resolution:     {info.width} x {info.height}")
        print(f"  • Video Codec:    {info.video_codec}")
        print(f"  • Audio Codec:    {info.audio_codec}")
        print(f"  • Duration:       {info.duration:.1f}s")
        print(f"  • Final File Size: {format_bytes(media.final_size_bytes)}")
        print("=" * 70)

        # 4. Probe Stream Metadata via FFprobe for Audio Language / Track Tags
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(media.video_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        probe_data = json.loads(stdout.decode("utf-8", errors="replace"))

        audio_streams = [s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"]
        assert len(audio_streams) >= 1, "No audio stream found in final media file!"
        target_audio = audio_streams[0]
        tags = target_audio.get("tags", {})
        lang_tag = tags.get("language", "").lower()
        title_tag = tags.get("title", "").lower()
        handler_tag = tags.get("handler_name", "").lower()

        print("\n[Step 4] FFprobe Audio Stream Tags:")
        print(f"  • Audio Stream Index: {target_audio.get('index')}")
        print(f"  • Codec Name:         {target_audio.get('codec_name')}")
        print(f"  • Language Tag:       '{lang_tag}'")
        print(f"  • Title Tag:          '{title_tag}'")
        print(f"  • Handler Name:       '{handler_tag}'")

        # Crucial assertion: Audio language must NOT be Hindi or another dubbed language
        assert lang_tag not in ("hin", "hi"), "CRITICAL FAILURE: Downloaded Hindi dubbed audio track!"
        assert "dub" not in title_tag, f"CRITICAL FAILURE: Downloaded dubbed audio track ('{title_tag}')!"
        if lang_tag:
            assert lang_tag in ("eng", "en", "und"), f"Unexpected language tag: {lang_tag}"

        # General assertions
        assert info.audio_codec.lower() in ("aac", "mp4a"), f"Invalid audio codec: {info.audio_codec}"
        assert min(info.width, info.height) >= 1080, "Video resolution was degraded!"
        assert media.final_size_bytes <= 49.5 * 1024 * 1024, "File size exceeded Telegram limit!"

        print("\n" + "=" * 70)
        print("🎉 SUCCESS: Original audio track was selected! Zero dubbed audio contamination.")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_youtube_mla_selection())
