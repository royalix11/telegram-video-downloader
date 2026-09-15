"""FFmpeg and FFprobe media processing pipeline."""

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for media pipeline failures."""
    pass


class VideoTooLongError(PipelineError):
    """Raised when video duration is too long to compress under Telegram limits."""
    pass


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    video_codec: str
    audio_codec: Optional[str]
    bit_rate: Optional[int]
    file_size_bytes: int


class MediaPipeline:
    """Handles async media probing, remuxing, thumbnail generation, and 2-pass compression."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg = shutil.which(ffmpeg_bin) or ffmpeg_bin
        self.ffprobe = shutil.which(ffprobe_bin) or ffprobe_bin
        self.null_device = "NUL" if sys.platform == "win32" else "/dev/null"

    async def probe_media(self, file_path: Path, allow_audio_only: bool = False) -> MediaInfo:
        """Probe media file via ffprobe and return parsed MediaInfo."""
        if not file_path.is_file():
            raise FileNotFoundError(f"Media file not found: {file_path}")

        cmd = [
            self.ffprobe,
            "-v", "error",
            "-show_entries", "stream=width,height,duration,codec_name,codec_type,bit_rate",
            "-show_entries", "format=duration,size,bit_rate",
            "-of", "json",
            str(file_path)
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise PipelineError(f"ffprobe failed: {stderr.decode('utf-8', errors='replace')}")

        data = json.loads(stdout.decode("utf-8"))
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        if not video_stream:
            if not allow_audio_only:
                raise PipelineError("No video stream detected in probed media.")
            # Audio-only container (e.g. TikTok / IG photo post soundtrack)
            duration = float(
                fmt.get("duration")
                or (audio_stream.get("duration") if audio_stream else 0.0)
                or 0.0
            )
            file_size = int(fmt.get("size") or file_path.stat().st_size)
            bit_rate = int(fmt.get("bit_rate") or 0) if fmt.get("bit_rate") else None
            return MediaInfo(
                duration=duration,
                width=0,
                height=0,
                video_codec="",
                audio_codec=audio_stream.get("codec_name") if audio_stream else None,
                bit_rate=bit_rate,
                file_size_bytes=file_size,
            )

        duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        video_codec = str(video_stream.get("codec_name") or "unknown")
        audio_codec = audio_stream.get("codec_name") if audio_stream else None
        
        file_size = int(fmt.get("size") or file_path.stat().st_size)
        bit_rate = int(fmt.get("bit_rate") or 0) if fmt.get("bit_rate") else None

        return MediaInfo(
            duration=duration,
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            bit_rate=bit_rate,
            file_size_bytes=file_size,
        )

    async def synthesize_video_from_photo(
        self,
        photo_path: Path,
        audio_path: Path,
        output_path: Path
    ) -> Path:
        """Combine a photo and audio stream into a streamable H.264/AAC MP4 video with +faststart."""
        cmd = [
            self.ffmpeg,
            "-y",
            "-loop", "1",
            "-i", str(photo_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            raise PipelineError(f"Failed to synthesize video from photo: {err}")
        return output_path


    async def extract_thumbnail(
        self,
        video_path: Path,
        output_thumb_path: Path,
        timestamp: float = 1.0
    ) -> Path:
        """Extract a high quality JPEG thumbnail from video."""
        output_thumb_path.parent.mkdir(parents=True, exist_ok=True)
        # Format timestamp HH:MM:SS.xxx
        hours = int(timestamp // 3600)
        mins = int((timestamp % 3600) // 60)
        secs = timestamp % 60
        ts_str = f"{hours:02d}:{mins:02d}:{secs:06.3f}"

        cmd = [
            self.ffmpeg,
            "-y",
            "-ss", ts_str,
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=320:-1",
            "-q:v", "3",
            str(output_thumb_path)
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(f"Thumbnail extraction at {ts_str} failed, attempting 00:00:00: {stderr.decode('utf-8', errors='replace')}")
            # Fallback to start
            cmd[3] = "00:00:00.000"
            proc_retry = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc_retry.communicate()

        return output_thumb_path

    async def remux_to_streamable_mp4(self, input_path: Path, output_path: Path) -> Path:
        """Ensure stream is in a fast-streaming MP4 container with +faststart.
        Prioritizes instant stream-copying (0 re-encoding) whenever possible.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        info = await self.probe_media(input_path)

        vcodec = info.video_codec.lower()
        acodec = (info.audio_codec or "").lower()

        # Modern mobile Telegram clients support H.264, AVC1, HEVC/H.265, and HVC1 in MP4
        can_copy_video = vcodec in ("h264", "avc1", "hevc", "h265", "hvc1")
        can_copy_audio = info.audio_codec is None or acodec in ("aac", "mp4a", "mp3", "opus", "flac")

        if can_copy_video and can_copy_audio:
            logger.info(f"Instant stream-copy (0 re-encoding) with +faststart: {input_path.name}")
            cmd = [
                self.ffmpeg,
                "-y",
                "-i", str(input_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path)
            ]
        elif can_copy_video:
            logger.info(f"Fast video copy + quick audio AAC remux with +faststart: {input_path.name}")
            cmd = [
                self.ffmpeg,
                "-y",
                "-i", str(input_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path)
            ]
        else:
            logger.info(
                f"High-speed transcoding {info.video_codec}/{info.audio_codec} to H.264 (CRF 22, ultrafast): {input_path.name}"
            )
            audio_args = ["-c:a", "copy"] if can_copy_audio else ["-c:a", "aac", "-b:a", "128k"]
            cmd = [
                self.ffmpeg,
                "-y",
                "-threads", "0",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                *audio_args,
                "-movflags", "+faststart",
                str(output_path)
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise PipelineError(f"Remuxing failed: {stderr.decode('utf-8', errors='replace')}")

        return output_path

    async def compress_video(
        self,
        input_path: Path,
        output_path: Path,
        target_size_bytes: int = 51_000_000,
        duration: Optional[float] = None
    ) -> Path:
        """Execute two-pass H.264/AAC compression targeting <= target_size_bytes."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if duration is None or duration <= 0:
            info = await self.probe_media(input_path)
            duration = info.duration

        if duration <= 0:
            raise PipelineError("Invalid media duration for compression.")

        # Allocate 95% of target size to leave a 5% muxing/container overhead buffer
        budget_bytes = target_size_bytes * 0.95
        total_bitrate_bps = (budget_bytes * 8) / duration

        # Allocate audio bitrate (64k for long media, 96k or 128k for shorter)
        if total_bitrate_bps > 1_000_000:
            audio_bitrate_bps = 128_000
        elif total_bitrate_bps > 500_000:
            audio_bitrate_bps = 96_000
        else:
            audio_bitrate_bps = 64_000

        video_bitrate_bps = total_bitrate_bps - audio_bitrate_bps

        # Safety floor: below 120 kbps video becomes unwatchable
        if video_bitrate_bps < 120_000:
            raise VideoTooLongError(
                f"Video duration ({duration:.1f}s) is too long to compress under 50 MB with acceptable visual quality."
            )

        vbitrate_k = int(video_bitrate_bps / 1000)
        abitrate_k = int(audio_bitrate_bps / 1000)

        logger.info(
            f"Starting 2-pass compression: target {target_size_bytes/1024/1024:.1f}MB, "
            f"vbitrate={vbitrate_k}k, abitrate={abitrate_k}k, duration={duration:.1f}s"
        )

        passlog_prefix = str(output_path.parent / f"passlog_{output_path.stem}")

        try:
            # Pass 1
            cmd_pass1 = [
                self.ffmpeg,
                "-y",
                "-threads", "0",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-b:v", f"{vbitrate_k}k",
                "-pass", "1",
                "-passlogfile", passlog_prefix,
                "-preset", "veryfast",
                "-an",
                "-f", "null",
                self.null_device
            ]
            proc1 = await asyncio.create_subprocess_exec(
                *cmd_pass1,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr1 = await proc1.communicate()
            if proc1.returncode != 0:
                raise PipelineError(f"Compression Pass 1 failed: {stderr1.decode('utf-8', errors='replace')}")

            # Pass 2
            cmd_pass2 = [
                self.ffmpeg,
                "-y",
                "-threads", "0",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-b:v", f"{vbitrate_k}k",
                "-pass", "2",
                "-passlogfile", passlog_prefix,
                "-preset", "veryfast",
                "-c:a", "aac",
                "-b:a", f"{abitrate_k}k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path)
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_pass2,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr2 = await proc2.communicate()
            if proc2.returncode != 0:
                raise PipelineError(f"Compression Pass 2 failed: {stderr2.decode('utf-8', errors='replace')}")

        finally:
            # Clean up 2-pass log files
            for log_file in output_path.parent.glob(f"passlog_{output_path.stem}*"):
                try:
                    log_file.unlink(missing_ok=True)
                except Exception:
                    pass

        return output_path
