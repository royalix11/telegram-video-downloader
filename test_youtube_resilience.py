"""Verification script for YouTube Shorts resilience, URL sanitization, and fallback cascade.

Tests the exact previously failing URL (https://youtube.com/shorts/QaBmK0Rs7cA?si=...)
to verify that:
1. Tracking queries (?si=...) are stripped before extraction.
2. The multi-tier client cascade resolves stream URLs without triggering bot challenges.
3. Media downloads, transcodes to streamable H.264/AAC, and verifies under the 49.5 MB limit.
"""

import asyncio
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
from bot.utils.link_detector import clean_url


async def test_youtube_shorts_resilience():
    print("=" * 70)
    print("🛡️ YouTube Shorts Resilience & Cascade Fallback Verification")
    print("=" * 70)

    raw_test_url = "https://youtube.com/shorts/QaBmK0Rs7cA?si=t4_xT5A4rN4Xbv_test"
    print(f"\n[Step 1] Testing URL Sanitization:")
    print(f"  • Input Raw URL:    {raw_test_url}")
    cleaned = clean_url(raw_test_url)
    print(f"  • Cleaned Endpoint: {cleaned}")
    assert "?si=" not in cleaned, "Tracking query ?si= was not stripped!"
    assert cleaned == "https://youtube.com/shorts/QaBmK0Rs7cA", f"Unexpected cleaned URL: {cleaned}"
    print("✅ Step 1 Passed: Tracking tokens stripped cleanly.")

    # Step 2: Test Extractor Tier 1 format options
    print(f"\n[Step 2] Testing Extractor Tier 1 Options:")
    extractor = ExtractorService()
    opts_tier1 = extractor._build_options(cleaned, tier=1)
    print(f"  • Format:       {opts_tier1['format']}")
    print(f"  • Format Sort:  {opts_tier1['format_sort']}")
    print(f"  • Extractor Args: {opts_tier1.get('extractor_args')}")
    assert opts_tier1["format"] == "bestvideo+bestaudio/best"
    assert "player_client" in opts_tier1["extractor_args"]["youtube"]
    print("✅ Step 2 Passed: Tier 1 options configured.")

    # Step 3: End-to-end Orchestrator execution
    print(f"\n[Step 3] Executing MediaOrchestrator Pipeline for {cleaned}:")
    orchestrator = MediaOrchestrator()

    def progress(text: str):
        clean_text = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        print(f"  -> {clean_text}")

    async with orchestrator.process_job(
        url=raw_test_url,
        platform_name="YouTube",
        progress_cb=progress
    ) as media:
        info = media.media_info
        print("\n" + "=" * 70)
        print("📊 Final Media Stream Verification:")
        print(f"  • Title:          {media.title}")
        print(f"  • Video Path:     {media.video_path}")
        print(f"  • Resolution:     {info.width} x {info.height}")
        print(f"  • Video Codec:    {info.video_codec}")
        print(f"  • Audio Codec:    {info.audio_codec}")
        print(f"  • Duration:       {info.duration:.1f}s")
        print(f"  • Final File Size: {format_bytes(media.final_size_bytes)}")
        print(f"  • Was Compressed: {media.was_compressed}")
        print("=" * 70)

        # Assertions
        assert media.video_path.is_file(), "Produced video file does not exist on disk!"
        assert media.video_path.stat().st_size > 0, "Produced video file is empty!"
        assert info.video_codec.lower() in ("h264", "avc1"), f"Invalid video codec: {info.video_codec}"
        assert info.audio_codec.lower() in ("aac", "mp4a"), f"Invalid audio codec: {info.audio_codec}"
        assert min(info.width, info.height) >= 720, "Video resolution was excessively degraded!"
        assert media.final_size_bytes <= 49.5 * 1024 * 1024, "File size exceeded Telegram limit!"

        print("\n" + "=" * 70)
        print("🎉 SUCCESS: YouTube Short downloaded, transcoded, and verified without errors!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_youtube_shorts_resilience())
