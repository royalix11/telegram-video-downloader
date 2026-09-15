"""End-to-end media download, transcoding, and optimization orchestrator."""

import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

import aiohttp

from bot.config import settings
from bot.services.extractor import ExtractorService
from bot.services.pipeline import MediaInfo, MediaPipeline, PipelineError
from bot.utils.formatters import format_bytes, sanitize_filename

logger = logging.getLogger(__name__)


async def _download_photo_asset(photo_url: str, dest: Path) -> bool:
    """Download a remote photo asset to local destination for video synthesis."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(photo_url) as resp:
                if resp.status == 200:
                    dest.write_bytes(await resp.read())
                    return True
    except Exception as e:
        logger.warning(f"Could not download photo asset from {photo_url}: {e}")
    return False


@dataclass
class ProcessedMedia:
    video_path: Path
    thumbnail_path: Optional[Path]
    media_info: MediaInfo
    title: str
    platform: str
    original_size_bytes: int
    final_size_bytes: int
    was_compressed: bool


class MediaOrchestrator:
    """Coordinates download, probing, transcoding/compression, and cleanup."""

    def __init__(
        self,
        extractor: Optional[ExtractorService] = None,
        pipeline: Optional[MediaPipeline] = None
    ):
        self.extractor = extractor or ExtractorService(cookies_file=settings.resolved_cookies_path)
        self.pipeline = pipeline or MediaPipeline()

    @asynccontextmanager
    async def process_job(
        self,
        url: str,
        platform_name: str = "media",
        progress_cb: Optional[Callable[[str], asyncio.Future | None]] = None
    ) -> AsyncIterator[ProcessedMedia]:
        """Safely execute the full download and transcode workflow in an isolated temp directory."""
        async def notify(val: int | float | str):
            if progress_cb:
                try:
                    res = progress_cb(val)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.debug(f"Progress callback notification error: {e}")

        base_tmp = settings.resolved_temp_dir
        with tempfile.TemporaryDirectory(dir=base_tmp, ignore_cleanup_errors=True) as tmp_dir_str:
            work_dir = Path(tmp_dir_str)
            logger.info(f"Initialized job directory: {work_dir}")

            await notify(10)

            # 1. Download media stream via yt-dlp with backoff retries
            download_info = await self.extractor.download_media(url, work_dir, status_cb=notify)
            title = download_info.get("title") or "Video"
            clean_title = sanitize_filename(title)

            # Locate downloaded file in work_dir
            downloaded_files = [
                f for f in work_dir.glob("*")
                if f.is_file() and not f.name.endswith(".part") and not f.name.endswith(".ytdl")
            ]
            if not downloaded_files:
                raise PipelineError("No media file was produced during download.")

            # Pick largest file if multiple were produced
            downloaded_file = max(downloaded_files, key=lambda f: f.stat().st_size)
            orig_size = downloaded_file.stat().st_size
            logger.info(f"Downloaded media: {downloaded_file.name} ({format_bytes(orig_size)})")

            # 2. Probe initial media characteristics
            await notify(76)
            info = await self.pipeline.probe_media(downloaded_file, allow_audio_only=True)
            thumb_path = None

            # If media is audio-only (e.g. TikTok / Instagram photo mode / slideshow)
            if not info.video_codec:
                logger.info(f"Audio-only media detected for '{clean_title}'. Looking for photomode assets...")
                photo_url = download_info.get("thumbnail")
                if not photo_url and download_info.get("thumbnails"):
                    thumbs = download_info.get("thumbnails")
                    if isinstance(thumbs, list) and thumbs:
                        photo_url = thumbs[-1].get("url")

                if photo_url:
                    photo_file = work_dir / "photo.jpg"
                    downloaded_photo = await _download_photo_asset(photo_url, photo_file)
                    if downloaded_photo and photo_file.is_file():
                        await notify(80)
                        synthesized_file = work_dir / f"{clean_title}_photovideo.mp4"
                        try:
                            await self.pipeline.synthesize_video_from_photo(
                                photo_path=photo_file,
                                audio_path=downloaded_file,
                                output_path=synthesized_file
                            )
                            downloaded_file = synthesized_file
                            thumb_path = photo_file
                            info = await self.pipeline.probe_media(downloaded_file)
                            logger.info(f"Synthesized photo video: {info.width}x{info.height}, {info.duration:.1f}s")
                        except Exception as e:
                            logger.warning(f"Failed to synthesize photo video: {e}")

                if not info.video_codec:
                    raise PipelineError("No video stream found and could not construct video from photo post.")

            logger.info(
                f"[Initial Probe] {clean_title} | Resolution: {info.width}x{info.height} | "
                f"Codec: {info.video_codec}/{info.audio_codec} | Duration: {info.duration:.1f}s | Size: {format_bytes(orig_size)}"
            )

            final_video_path = downloaded_file
            was_compressed = False

            # 3. Visually Lossless Transcoding / FastStart Container Optimization
            await notify(82)
            streamable_file = work_dir / f"{clean_title}_streamable.mp4"
            try:
                await self.pipeline.remux_to_streamable_mp4(downloaded_file, streamable_file)
                final_video_path = streamable_file
                info = await self.pipeline.probe_media(final_video_path)
            except Exception as e:
                logger.warning(f"Fast remux failed, falling back to original: {e}")
                final_video_path = downloaded_file

            # 4. Enforce Telegram 49.5 MB limit only if final file is oversize
            final_size = final_video_path.stat().st_size
            if final_size > settings.max_file_size_bytes:
                await notify(86)
                compressed_file = work_dir / f"{clean_title}_compressed.mp4"
                await self.pipeline.compress_video(
                    input_path=final_video_path,
                    output_path=compressed_file,
                    target_size_bytes=settings.max_file_size_bytes,
                    duration=info.duration
                )
                final_video_path = compressed_file
                was_compressed = True
                info = await self.pipeline.probe_media(final_video_path)
                final_size = final_video_path.stat().st_size

            # 5. Extract thumbnail for instant player preview (if not already set from photo)
            await notify(90)
            if not thumb_path or not thumb_path.is_file():
                thumb_path = work_dir / "thumb.jpg"
                thumb_ts = min(1.0, info.duration / 2.0) if info.duration > 0 else 0.5
                try:
                    await self.pipeline.extract_thumbnail(final_video_path, thumb_path, timestamp=thumb_ts)
                except Exception as e:
                    logger.warning(f"Could not generate thumbnail: {e}")
                    thumb_path = None


            logger.info(
                f"[Final Media] {clean_title} | Resolution: {info.width}x{info.height} | "
                f"Codec: {info.video_codec}/{info.audio_codec} | Final Size: {format_bytes(final_size)}"
            )

            processed = ProcessedMedia(
                video_path=final_video_path,
                thumbnail_path=thumb_path if thumb_path and thumb_path.is_file() else None,
                media_info=info,
                title=title,
                platform=platform_name,
                original_size_bytes=orig_size,
                final_size_bytes=final_size,
                was_compressed=was_compressed
            )

            try:
                yield processed
            finally:
                logger.info(f"Cleaning up temporary work directory: {work_dir}")
                # Temp directory auto-deleted by tempfile.TemporaryDirectory context manager
