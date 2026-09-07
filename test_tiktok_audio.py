"""Automated verification test ensuring TikTok videos preserve native mixed audio (voiceover + music)."""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from bot.services.extractor import ExtractorService, resolve_canonical_url
from bot.services.pipeline import MediaPipeline


async def test_tiktok_audio_preservation():
    print("=" * 70)
    print("🎵 Testing TikTok Audio Stream Preservation (No Music Overwrite)")
    print("=" * 70)

    extractor = ExtractorService()
    pipeline = MediaPipeline()
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

    # Test URL from user testing
    test_url = "https://www.tiktok.com/t/ZTUhdJsJc/"
    print(f"Testing URL: {test_url}")

    canonical_url = await resolve_canonical_url(test_url)
    print(f"Canonical URL: {canonical_url}")

    # 1. Verify format string configured for TikTok
    opts = extractor._build_options(canonical_url)
    print(f"Configured format string for TikTok: '{opts['format']}'")
    assert "+bestaudio" not in opts["format"], "CRITICAL: '+bestaudio' must not be in TikTok format string!"
    assert opts["format"] == "best[vcodec!=none][acodec!=none]/best"

    # 2. Download into temporary directory and inspect streams
    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        info = await extractor.download_media(test_url, work_dir)

        # Verify yt-dlp did not merge separate video and music streams
        requested_formats = info.get("requested_formats")
        assert requested_formats is None or len(requested_formats) == 1, (
            f"Expected single pre-muxed stream, but got requested_formats: {requested_formats}"
        )

        downloaded_files = list(work_dir.glob("*.mp4"))
        assert len(downloaded_files) > 0, "No MP4 file downloaded"
        video_file = downloaded_files[0]
        print(f"Downloaded video file: {video_file.name} ({video_file.stat().st_size / 1024 / 1024:.2f} MB)")

        # 3. Probe with ffprobe to verify audio track integrity
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_streams",
            "-of", "json",
            str(video_file)
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        assert proc.returncode == 0, f"ffprobe failed: {stderr.decode()}"

        data = json.loads(stdout.decode("utf-8"))
        streams = data.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        assert video_stream is not None, "Missing video stream"
        assert audio_stream is not None, "Missing audio stream"

        audio_codec = audio_stream.get("codec_name")
        sample_rate = audio_stream.get("sample_rate")
        channels = audio_stream.get("channels")
        audio_duration = float(audio_stream.get("duration") or video_stream.get("duration") or 0)
        video_duration = float(video_stream.get("duration") or 0)

        print("\nFFprobe Stream Inspection:")
        print(f"  • Video Stream: {video_stream.get('codec_name')} {video_stream.get('width')}x{video_stream.get('height')}")
        print(f"  • Audio Codec:  {audio_codec} (AAC native muxed track)")
        print(f"  • Sample Rate:  {sample_rate} Hz")
        print(f"  • Channels:     {channels} ({'Stereo' if channels == 2 else 'Mono'})")
        print(f"  • Duration:     {audio_duration:.2f}s (Video: {video_duration:.2f}s)")

        # The native TikTok audio stream is AAC (44.1kHz or 48kHz), NOT external MP3 music track
        assert audio_codec in ("aac", "mp4a"), f"Expected native AAC audio track, but got '{audio_codec}'!"
        assert channels in (1, 2), f"Invalid channel count: {channels}"
        assert abs(audio_duration - video_duration) < 1.0, "Audio and video durations desynchronized"

        print("\n✅ Verification PASSED: Native pre-muxed audio track (voiceover + music) preserved intact!")


def test_platform_format_differentiation():
    print("\n" + "=" * 70)
    print("📋 Testing Platform Format Differentiation")
    print("=" * 70)

    extractor = ExtractorService()

    tiktok_opts = extractor._build_options("https://www.tiktok.com/@user/video/123")
    assert tiktok_opts["format"] == "best[vcodec!=none][acodec!=none]/best"
    print("✅ TikTok format: 'best[vcodec!=none][acodec!=none]/best' (single pre-muxed stream)")

    yt_opts = extractor._build_options("https://www.youtube.com/watch?v=123")
    assert yt_opts["format"] == "bestvideo+bestaudio/best"
    assert yt_opts["format_sort"] == ["lang", "res", "fps", "codec:h264", "size", "br"]
    assert yt_opts["extractor_args"]["youtube"]["player_client"] == ["web", "default"]
    assert yt_opts["extractor_args"]["youtube"]["lang"] == ["en", "orig", "original"]
    print("✅ YouTube format: Resilient format string with language and quality sort [lang, res, fps, codec:h264, size, br]")

    ig_opts = extractor._build_options("https://www.instagram.com/reel/123")
    assert ig_opts["format"] == "bestvideo+bestaudio/best"
    assert ig_opts["format_sort"] == ["res", "fps", "codec", "size", "br"]
    print("✅ Instagram format: 'bestvideo+bestaudio/best' with full quality sort")


async def main():
    test_platform_format_differentiation()
    await test_tiktok_audio_preservation()
    print("\n" + "=" * 70)
    print("🎉 ALL AUDIO PRESERVATION TESTS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
