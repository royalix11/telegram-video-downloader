"""Benchmark test verifying YouTube Shorts full resolution (1080x1920+) and visually lossless H.264/AAC output."""

import asyncio
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from bot.services.orchestrator import MediaOrchestrator
from bot.utils.formatters import format_bytes


async def benchmark_youtube_shorts_quality():
    print("=" * 70)
    print("🎬 YouTube Shorts Full Resolution & Visual Quality Benchmark")
    print("=" * 70)

    orchestrator = MediaOrchestrator()
    test_shorts_url = "https://youtube.com/shorts/wvVEKI2GpY4"

    print(f"Testing YouTube Short: {test_shorts_url}")
    print("Executing download, format sorting, and visually lossless transcoding...")

    def progress(text):
        # Print clean status line
        clean_text = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        print(f"  -> {clean_text}")

    async with orchestrator.process_job(
        url=test_shorts_url,
        platform_name="YouTube",
        progress_cb=progress
    ) as media:
        info = media.media_info
        print("\n" + "=" * 70)
        print("📊 Final Probed Media Stream Attributes:")
        print(f"  • Title:          {media.title}")
        print(f"  • Resolution:     {info.width} x {info.height}")
        print(f"  • Video Codec:    {info.video_codec}")
        print(f"  • Audio Codec:    {info.audio_codec}")
        print(f"  • Duration:       {info.duration:.1f}s")
        print(f"  • Final File Size: {format_bytes(media.final_size_bytes)}")
        print(f"  • Was Compressed: {media.was_compressed}")
        print("=" * 70)

        # Assertions
        # 1. Height must be vertical full HD (>= 1920) or width >= 1080
        min_dim = min(info.width, info.height)
        max_dim = max(info.width, info.height)
        print(f"Checking dimensions: min={min_dim} (expected >= 1080), max={max_dim} (expected >= 1920)")
        assert min_dim >= 1080, f"Resolution was degraded! Min dimension was {min_dim}, expected >= 1080"
        assert max_dim >= 1920, f"Resolution was degraded! Max dimension was {max_dim}, expected >= 1920"

        # 2. Codecs must be native Telegram streamable (H.264 / AAC)
        assert info.video_codec.lower() in ("h264", "avc1"), f"Invalid video codec: {info.video_codec}"
        assert info.audio_codec.lower() in ("aac", "mp4a"), f"Invalid audio codec: {info.audio_codec}"

        # 3. File size strictly under Telegram 49.5 MB ceiling
        assert media.final_size_bytes <= 49.5 * 1024 * 1024, "File size exceeded 49.5 MB threshold!"

        print("✅ ALL QUALITY BENCHMARKS PASSED! Full 1080x1920+ vertical clarity achieved.")


if __name__ == "__main__":
    asyncio.run(benchmark_youtube_shorts_quality())
