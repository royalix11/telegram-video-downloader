"""Headless resilience test looping through TikTok shortlinks to verify 0% failure rate."""

import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from bot.services.extractor import ExtractorService, resolve_canonical_url

# Real live TikTok links from user testing
TIKTOK_LINKS = [
    "https://www.tiktok.com/t/ZTUhdJsJc/",
    "https://www.tiktok.com/t/ZTUhddBey/",
    "https://www.tiktok.com/t/ZTUhe7EhE/",
    "https://www.tiktok.com/t/ZTUhdJsJc/",
    "https://www.tiktok.com/t/ZTUhe7EhE/",
    "https://www.tiktok.com/t/ZTUhddBey/",
]


async def run_resilience_test():
    print("=" * 70)
    print("🧪 Running TikTok Sequential Shortlink Resilience Test")
    print("=" * 70)

    extractor = ExtractorService()
    success_count = 0
    total_count = len(TIKTOK_LINKS)

    for idx, link in enumerate(TIKTOK_LINKS, start=1):
        print(f"\n[{idx}/{total_count}] Testing: {link}")

        # 1. Test canonical resolution & cleaning
        resolved = await resolve_canonical_url(link)
        print(f"  -> Canonical target: {resolved}")
        assert "/video/" in resolved or "tiktok.com" in resolved

        # 2. Test metadata/download extraction with retry wrapper
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)

            status_updates = []
            def on_status(msg):
                status_updates.append(msg)
                print(f"     [Status Update]: {msg}")

            try:
                info = await extractor.download_media(link, work_dir, status_cb=on_status)
                title = info.get("title") or "Unknown"
                downloaded_files = list(work_dir.glob("*.mp4"))
                assert len(downloaded_files) > 0, "No mp4 file downloaded"
                file_size = downloaded_files[0].stat().st_size
                print(f"  ✅ SUCCESS: '{title[:40]}' ({file_size / 1024 / 1024:.2f} MB)")
                success_count += 1
            except Exception as e:
                print(f"  ❌ FAILED: {e}")

        # Short pause between sequential downloads to respect edge rate limits
        await asyncio.sleep(1.0)

    print("\n" + "=" * 70)
    failure_rate = ((total_count - success_count) / total_count) * 100
    print(f"Test Summary: {success_count}/{total_count} succeeded. Failure Rate: {failure_rate:.1f}%")
    print("=" * 70)

    assert success_count == total_count, f"Expected 100% success rate, got {success_count}/{total_count}"
    print("🎉 ALL RESILIENCE TESTS PASSED WITH 0% FAILURE RATE!")


if __name__ == "__main__":
    asyncio.run(run_resilience_test())
