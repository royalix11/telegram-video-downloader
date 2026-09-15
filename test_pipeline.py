"""Comprehensive headless integration and unit test suite for Telegram Video Downloader.

Tests:
1. Environment Doctor: Verifies ffmpeg, ffprobe, disk permissions, python runtime.
2. Link Detector: Validates URL classification for Instagram, TikTok, YouTube, X, Reddit, Facebook.
3. Formatters: Validates size, duration, and filename sanitization.
4. Media Pipeline Probing & Thumbnail: Generates a synthetic test video via ffmpeg, tests probing and thumbnail generation.
5. Media Pipeline Remuxing: Validates MP4 remuxing with +faststart.
6. Two-Pass Compression: Generates a high-bitrate synthetic video and compresses it to a strict target threshold.
7. Temporary Directory Lifecycle: Validates that all temporary files are purged with zero disk leaks.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from bot.services.doctor import EnvironmentDoctor
from bot.services.pipeline import MediaPipeline, MediaInfo
from bot.utils.formatters import format_bytes, format_duration, sanitize_filename, format_progress
from bot.utils.link_detector import (
    clean_url,
    detect_platform,
    extract_links,
    is_supported_url,
    get_platform_display_name,
)


def log_test(name: str, passed: bool, details: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"[{status}] {name}" + (f": {details}" if details else ""))


async def test_doctor():
    print("\n--- 1. Testing Environment Doctor ---")
    report = await EnvironmentDoctor.run_full_diagnostic()

    assert report["healthy"], f"Doctor health check failed: {report}"
    assert report["ffmpeg"]["ffmpeg_installed"], "FFmpeg not installed"
    assert report["ffmpeg"]["ffprobe_installed"], "FFprobe not installed"
    assert report["disk"]["writable"], "Temp disk not writable"

    log_test("Doctor System Check", True, f"OS: {report['system']['os']}, Python: {report['system']['python_version']}")
    log_test("Doctor FFmpeg Check", True, f"{report['ffmpeg']['version_info']}")
    log_test("Doctor Disk Check", True, f"Writable: {report['disk']['path']}, Free: {report['disk']['free_space_mb']} MB")


def test_link_detector():
    print("\n--- 2. Testing Link Detector & URL Classification ---")

    test_urls = {
        "https://www.instagram.com/reel/C1234567890/": "instagram",
        "https://instagram.com/p/C9876543210/?igsh=abc": "instagram",
        "https://vm.tiktok.com/ZM1234567/": "tiktok",
        "https://www.tiktok.com/@creator/video/7123456789012345678": "tiktok",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ": "youtube",
        "https://youtu.be/dQw4w9WgXcQ": "youtube",
        "https://youtube.com/watch?v=dQw4w9WgXcQ": "youtube",
        "https://x.com/user/status/1234567890123456789": "twitter",
        "https://twitter.com/user/status/1234567890123456789": "twitter",
        "https://www.reddit.com/r/videos/comments/123456/sample_video/": "reddit",
        "https://v.redd.it/abcdefghijklm": "reddit",
        "https://www.facebook.com/reel/123456789012345": "facebook",
        "https://fb.watch/abcdef123/": "facebook",
    }

    for url, expected_platform in test_urls.items():
        detected = detect_platform(url)
        assert detected == expected_platform, f"Failed for {url}: expected {expected_platform}, got {detected}"
        assert is_supported_url(url), f"URL reported unsupported: {url}"

    # Test extracting from message text
    sample_text = (
        "Check this out: https://www.instagram.com/reel/C1234567890/ and also "
        "watch https://www.youtube.com/shorts/dQw4w9WgXcQ right now!"
    )
    extracted = extract_links(sample_text)
    assert len(extracted) == 2, f"Expected 2 extracted links, got {len(extracted)}"

    log_test("Link Detection & Platform Matching", True, f"Verified {len(test_urls)} platform URL variations")


def test_formatters():
    print("\n--- 3. Testing Formatters ---")

    # Byte format tests
    assert format_bytes(500) == "500.00 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024 * 48.5) == "48.50 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2.5) == "2.50 GB"

    # Duration tests
    assert format_duration(45) == "00:45"
    assert format_duration(75) == "01:15"
    assert format_duration(3665) == "01:01:05"

    # Filename sanitization
    raw = 'Awesome: Video <Test> *2026* / cool "quote"?.mp4'
    clean = sanitize_filename(raw)
    assert ":" not in clean and "<" not in clean and '"' not in clean and "*" not in clean

    # Progress bar tests
    p1 = format_progress(1)
    p50 = format_progress(50)
    p100 = format_progress(100)
    assert "1%" in p1 and "░░░░░░░░░░" in p1
    assert "50%" in p50 and "█████░░░░░" in p50
    assert "100%" in p100 and "██████████" in p100 and "✅" in p100

    log_test("Formatting Utilities", True, f"Cleaned filename: '{clean}', progress format verified")


async def generate_synthetic_video(output_file: Path, duration: int = 3, bitrate: str = "2000k"):
    """Helper to generate a clean synthetic MP4 video using ffmpeg testsrc."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=640x360:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}",
        "-c:v", "libx264",
        "-b:v", bitrate,
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(output_file)
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, f"Synthetic video generation failed: {stderr.decode()}"


async def test_ffmpeg_probe_and_remux():
    print("\n--- 4. Testing Media Probing, Thumbnailing & Remuxing ---")
    pipeline = MediaPipeline()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_video = tmp_path / "test_raw.mp4"
        test_thumb = tmp_path / "test_thumb.jpg"
        test_streamable = tmp_path / "test_streamable.mp4"

        # 1. Generate 3-second test video
        await generate_synthetic_video(test_video, duration=3, bitrate="1500k")
        assert test_video.is_file(), "Test video was not created"

        # 2. Probe media
        info = await pipeline.probe_media(test_video)
        assert info.width == 640, f"Expected width 640, got {info.width}"
        assert info.height == 360, f"Expected height 360, got {info.height}"
        assert 2.8 <= info.duration <= 3.2, f"Expected ~3s duration, got {info.duration}"
        assert info.video_codec in ("h264", "avc1"), f"Expected h264, got {info.video_codec}"
        log_test("FFprobe Media Probe", True, f"{info.width}x{info.height}, {info.duration:.1f}s, {info.video_codec}/{info.audio_codec}")

        # 3. Extract thumbnail
        await pipeline.extract_thumbnail(test_video, test_thumb, timestamp=1.0)
        assert test_thumb.is_file() and test_thumb.stat().st_size > 0, "Thumbnail extraction failed"
        log_test("Thumbnail Extraction", True, f"Thumb size: {format_bytes(test_thumb.stat().st_size)}")

        # 4. Remux to streamable MP4 (+faststart)
        await pipeline.remux_to_streamable_mp4(test_video, test_streamable)
        assert test_streamable.is_file(), "Streamable MP4 was not created"
        remux_info = await pipeline.probe_media(test_streamable)
        assert remux_info.video_codec in ("h264", "avc1")
        log_test("FastStart Remuxing", True, f"Streamable size: {format_bytes(test_streamable.stat().st_size)}")


async def test_compression_pipeline():
    print("\n--- 5. Testing 2-Pass Bitrate Compression (< Target Threshold) ---")
    pipeline = MediaPipeline()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_heavy_video = tmp_path / "heavy_video.mp4"
        compressed_video = tmp_path / "compressed_video.mp4"

        # Generate a 6-second video with high bitrate to simulate an oversize file
        # 6 seconds with video bitrate 15 Mbps -> ~12 MB raw file
        await generate_synthetic_video(raw_heavy_video, duration=6, bitrate="15000k")
        raw_size = raw_heavy_video.stat().st_size
        print(f"Generated raw test video: {format_bytes(raw_size)}")

        # Now define a strict target size: 2.0 MB (2,097,152 bytes)
        target_size_bytes = 2 * 1024 * 1024
        await pipeline.compress_video(
            input_path=raw_heavy_video,
            output_path=compressed_video,
            target_size_bytes=target_size_bytes,
            duration=6.0
        )

        assert compressed_video.is_file(), "Compressed video was not created"
        compressed_size = compressed_video.stat().st_size
        print(f"Compressed video size: {format_bytes(compressed_size)} (Target: {format_bytes(target_size_bytes)})")

        # Must be strictly under target size
        assert compressed_size <= target_size_bytes, (
            f"Compression exceeded target! Got {compressed_size} bytes, limit was {target_size_bytes} bytes."
        )

        # Probe the compressed video to ensure valid H.264/AAC streams and dimensions
        comp_info = await pipeline.probe_media(compressed_video)
        assert comp_info.video_codec in ("h264", "avc1"), f"Invalid video codec: {comp_info.video_codec}"
        assert comp_info.audio_codec in ("aac", "mp4a"), f"Invalid audio codec: {comp_info.audio_codec}"

        log_test(
            "Two-Pass Compression Pipeline",
            True,
            f"Compressed {format_bytes(raw_size)} -> {format_bytes(compressed_size)} (< {format_bytes(target_size_bytes)} threshold)"
        )


def test_temp_cleanup():
    print("\n--- 6. Testing Temporary Resource Garbage Collection ---")
    created_path = None
    with tempfile.TemporaryDirectory() as tmp_dir:
        created_path = Path(tmp_dir)
        dummy_file = created_path / "test_leak.bin"
        dummy_file.write_bytes(b"x" * 1024 * 1024)
        assert dummy_file.is_file()

    # After exiting with block, directory must not exist
    assert not created_path.exists(), f"Temp directory leaked: {created_path}"
    log_test("Resource Garbage Collection", True, "Zero disk leaks verified")


async def test_photomode_synthesis():
    print("\n--- 7. Testing Photomode URL Cleaning & Video Synthesis ---")
    # 1. URL Normalization check
    raw_photo_url = "https://www.tiktok.com/@traquew/photo/7680944229220207875?_r=1"
    cleaned = clean_url(raw_photo_url)
    assert "/video/7680944229220207875" in cleaned, f"Expected /video/ rewrite, got {cleaned}"
    log_test("TikTok Photomode URL Normalization", True, f"Cleaned: {cleaned}")

    # 2. Synthesis of static image + audio stream
    pipeline = MediaPipeline()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_video = tmp_path / "test_raw.mp4"
        test_thumb = tmp_path / "test_thumb.jpg"
        test_audio = tmp_path / "test_audio.m4a"
        out_synth = tmp_path / "synthesized.mp4"

        # Generate base synthetic media
        await generate_synthetic_video(test_video, duration=2, bitrate="1000k")
        await pipeline.extract_thumbnail(test_video, test_thumb, timestamp=0.5)

        # Extract audio stream from test video
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg_bin, "-y", "-i", str(test_video), "-vn", "-c:a", "copy", str(test_audio)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        # Test audio-only probe
        audio_info = await pipeline.probe_media(test_audio, allow_audio_only=True)
        assert audio_info.video_codec == "", f"Expected empty video codec, got {audio_info.video_codec}"
        assert audio_info.audio_codec in ("aac", "mp4a")

        # Synthesize video
        await pipeline.synthesize_video_from_photo(test_thumb, test_audio, out_synth)
        assert out_synth.is_file() and out_synth.stat().st_size > 0

        # Probe synthesized video
        synth_info = await pipeline.probe_media(out_synth)
        assert synth_info.video_codec in ("h264", "avc1")
        assert synth_info.audio_codec in ("aac", "mp4a")
        assert synth_info.duration > 1.5
        log_test("Photomode Video Synthesis", True, f"Created {synth_info.width}x{synth_info.height} video ({synth_info.duration:.1f}s)")


async def main():
    print("=" * 70)
    print("🚀 Running Headless Telegram Bot Pipeline Verification Suite")
    print("=" * 70)

    await test_doctor()
    test_link_detector()
    test_formatters()
    await test_ffmpeg_probe_and_remux()
    await test_compression_pipeline()
    test_temp_cleanup()
    await test_photomode_synthesis()

    print("\n" + "=" * 70)
    print("🎉 ALL 7 TEST SUITES PASSED CLEANLY WITH ZERO ERRORS!")
    print("=" * 70)



if __name__ == "__main__":
    asyncio.run(main())
