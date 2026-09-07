"""Async media stream and metadata extraction via yt-dlp with redirect resolution and resilient retries."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse
import aiohttp
import traceback
import yt_dlp

from bot.utils.link_detector import clean_url

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    HAS_IMPERSONATE = True
except ImportError:
    HAS_IMPERSONATE = False

logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """Base exception for extraction errors."""
    pass


class VideoUnavailableError(ExtractorError):
    """Video is private, deleted, or geo-restricted."""
    pass


class LoginRequiredError(ExtractorError):
    """Platform requires authentication/cookies."""
    pass


# Domains that frequently use 301/302 short link redirects
SHORT_LINK_DOMAINS = {
    "vm.tiktok.com",
    "vt.tiktok.com",
    "v.douyin.com",
    "fb.watch",
    "youtu.be",
    "v.redd.it",
    "redd.it",
}


async def resolve_canonical_url(url: str) -> str:
    """Resolve HTTP redirects for shortened or mobile share links and strip tracking tokens before invoking yt-dlp."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        # Check if URL is a known short-link scheme
        is_short = (
            netloc in SHORT_LINK_DOMAINS
            or ("tiktok.com" in netloc and (path.startswith("/t/") or path.startswith("/vm/") or path.startswith("/vt/")))
            or ("instagram.com" in netloc and "/share/" in path)
        )

        if not is_short:
            return clean_url(url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.tiktok.com/" if ("tiktok.com" in netloc or "douyin.com" in netloc) else "https://www.google.com/",
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                resolved = str(resp.url)
                if resolved and resolved.startswith("http"):
                    # Strip tracking parameters from the final redirected URL
                    cleaned_canonical = clean_url(resolved)
                    logger.info(f"Resolved short link '{url}' -> '{cleaned_canonical}'")
                    return cleaned_canonical
    except Exception as e:
        logger.debug(f"Redirect resolution skipped for {url}: {e}")

    return clean_url(url)


class ExtractorService:
    """Non-blocking extraction engine wrapping yt-dlp with browser impersonation and resilient retries."""

    def __init__(self, cookies_file: Optional[Path] = None):
        self.cookies_file = cookies_file

    def _build_options(
        self,
        target_url: str,
        output_template: Optional[str] = None,
        attempt: int = 1,
        tier: int = 1,
    ) -> Dict[str, Any]:
        parsed = urlparse(target_url)
        netloc = parsed.netloc.lower()

        referer = "https://www.google.com/"
        if "tiktok.com" in netloc or "douyin.com" in netloc:
            referer = "https://www.tiktok.com/"
        elif "instagram.com" in netloc:
            referer = "https://www.instagram.com/"
        elif "youtube.com" in netloc or "youtu.be" in netloc:
            referer = "https://www.youtube.com/"

        # User-Agent rotation if on subsequent retry attempts
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        ]
        chosen_ua = user_agents[(attempt - 1) % len(user_agents)]

        # Platform-aware format string and sorting heuristics:
        # 1. TikTok: Video is pre-muxed with voiceover + music. Never merge +bestaudio on TikTok!
        if "tiktok.com" in netloc or "douyin.com" in netloc:
            format_str = "best[vcodec!=none][acodec!=none]/best"
            format_sort = ["res", "fps", "size", "br"]
            extractor_args = {}
        # 2. YouTube Shorts & Videos (Multi-Tier Fallback Strategy):
        elif "youtube.com" in netloc or "youtu.be" in netloc:
            if tier == 1:
                # Tier 1 (High Quality DASH):
                # Uses resilient format string + format_sort, with web & default clients
                format_str = "bestvideo+bestaudio/best"
                format_sort = ["lang", "res", "fps", "codec:h264", "size", "br"]
                extractor_args = {
                    "youtube": {
                        "player_client": ["web", "default"],
                        "lang": ["en", "orig", "original"],
                    }
                }
            elif tier == 2:
                # Tier 2 (Android / Mobile Client Fallback):
                format_str = "bestvideo+bestaudio/best"
                format_sort = ["lang", "res", "fps", "codec:h264", "size", "br"]
                extractor_args = {
                    "youtube": {
                        "player_client": ["android", "web"],
                        "lang": ["en", "orig", "original"],
                    }
                }
            else:
                # Tier 3 (Pre-muxed Stream Fallback):
                format_str = "best/bestvideo*+bestaudio*"
                format_sort = ["res", "fps", "size", "br"]
                extractor_args = {}
        else:
            # Instagram, Twitter, Facebook, Reddit:
            # Select highest resolution available (including 1080x1920 vertical HD VP9/AV1).
            format_str = "bestvideo+bestaudio/best"
            format_sort = ["res", "fps", "codec", "size", "br"]
            extractor_args = {}

        opts: Dict[str, Any] = {
            "format": format_str,
            "format_sort": format_sort,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "extractor_retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 15,
            "windowsfilenames": True,
            "restrictfilenames": True,
            "http_headers": {
                "User-Agent": chosen_ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": referer,
            },
        }

        if extractor_args:
            opts["extractor_args"] = extractor_args

        # Apply browser impersonation if available via curl-cffi
        if HAS_IMPERSONATE:
            try:
                opts["impersonate"] = ImpersonateTarget.from_str("chrome")
            except Exception:
                pass

        if output_template:
            opts["outtmpl"] = output_template

        if self.cookies_file and self.cookies_file.is_file():
            opts["cookiefile"] = str(self.cookies_file)
            logger.info(f"Mounted cookies session from: {self.cookies_file}")

        return opts

    @staticmethod
    def _inspect_and_log_audio_tracks(info_dict: Dict[str, Any]) -> None:
        """Inspect and log multi-language audio streams, detecting dubs and original tracks."""
        formats = info_dict.get("formats") or []
        audio_formats = [
            f for f in formats
            if f.get("vcodec") == "none" and f.get("acodec") != "none"
        ]
        if not audio_formats:
            return

        unique_langs = {f.get("language") for f in audio_formats if f.get("language")}
        has_dubs = any("dub" in str(f.get("format_note", "")).lower() for f in audio_formats)

        if len(unique_langs) > 1 or has_dubs:
            track_map = {track.get("format_note"): track.get("language") for track in audio_formats}
            logger.info(f"[Audio Detection] Found tracks: {track_map}")

    async def extract_metadata(
        self,
        url: str,
        status_cb: Optional[Callable[[str], Any]] = None
    ) -> Dict[str, Any]:
        """Query metadata without downloading media, with exponential backoff retries."""
        canonical_url = await resolve_canonical_url(url)
        max_attempts = 3
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            opts = self._build_options(target_url=canonical_url, attempt=attempt)

            def _query():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info_dict = ydl.extract_info(canonical_url, download=False)
                    self._inspect_and_log_audio_tracks(info_dict)
                    return info_dict

            try:
                return await asyncio.to_thread(_query)
            except yt_dlp.utils.DownloadError as e:
                msg = str(e).lower()
                if "private" in msg or "login" in msg:
                    raise LoginRequiredError("Authentication or cookies required to access this media.")
                if "unavailable" in msg or "not found" in msg or "deleted" in msg:
                    raise VideoUnavailableError("Media is unavailable or has been deleted.")
                last_exception = e
            except Exception as e:
                last_exception = e

            if attempt < max_attempts:
                wait_sec = 1.5 * (2 ** (attempt - 1))
                logger.warning(
                    f"Metadata extraction attempt {attempt} failed for {canonical_url}: {last_exception}. "
                    f"Retrying in {wait_sec:.1f}s..."
                )
                if status_cb:
                    try:
                        res = status_cb(f"🔄 <i>Transient network glitch. Retrying (attempt {attempt + 1}/{max_attempts})...</i>")
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass
                await asyncio.sleep(wait_sec)
                # Re-resolve in case short-link redirected dynamically
                canonical_url = await resolve_canonical_url(url)

        raise ExtractorError(f"Extraction failed after {max_attempts} attempts: {last_exception}")

    async def download_media(
        self,
        url: str,
        output_dir: Path,
        status_cb: Optional[Callable[[str], Any]] = None
    ) -> Dict[str, Any]:
        """Download media into designated output directory with multi-tier fallback cascade."""
        canonical_url = await resolve_canonical_url(url)
        output_template = str(output_dir / "%(id)s.%(ext)s")
        parsed = urlparse(canonical_url)
        netloc = parsed.netloc.lower()
        is_youtube = "youtube.com" in netloc or "youtu.be" in netloc
        tiers = [1, 2, 3] if is_youtube else [1]
        last_exception = None

        for tier in tiers:
            max_attempts = 2 if is_youtube else 3
            for attempt in range(1, max_attempts + 1):
                opts = self._build_options(
                    target_url=canonical_url,
                    output_template=output_template,
                    attempt=attempt,
                    tier=tier
                )

                def _download():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info_dict = ydl.extract_info(canonical_url, download=False)
                        self._inspect_and_log_audio_tracks(info_dict)
                        proc = ydl.process_ie_result(info_dict, download=True)
                        if is_youtube and not proc.get("requested_formats") and not proc.get("url"):
                            raise yt_dlp.utils.DownloadError("No downloadable stream URLs resolved for selected client.")
                        return proc

                try:
                    info = await asyncio.to_thread(_download)
                    fmt_id = info.get("format_id", "unknown")
                    w = info.get("width") or "unknown"
                    h = info.get("height") or "unknown"
                    vc = info.get("vcodec", "unknown")
                    ac = info.get("acodec", "unknown")
                    logger.info(
                        f"[Extractor] URL: {canonical_url} | Platform: {netloc} | Tier: {tier} | "
                        f"Selected Format ID: {fmt_id} | Resolution: {w}x{h} | Codec: {vc}/{ac}"
                    )
                    rf = info.get("requested_formats") or []
                    for f in rf:
                        if f.get("vcodec") == "none":
                            logger.info(
                                f"[Audio Selection] Downloaded track: format_id={f.get('format_id')}, "
                                f"note='{f.get('format_note')}', lang='{f.get('language')}'"
                            )
                    return info
                except yt_dlp.utils.DownloadError as e:
                    msg = str(e).lower()
                    if "private" in msg or "login" in msg:
                        raise LoginRequiredError("Authentication or cookies required to access this media.")
                    if "unavailable" in msg or "not found" in msg or "deleted" in msg:
                        raise VideoUnavailableError("Media is unavailable or has been deleted.")
                    last_exception = e
                    logger.warning(
                        f"Download error at Tier {tier}, attempt {attempt} for {canonical_url}: {e}\n"
                        f"{traceback.format_exc()}"
                    )
                except Exception as e:
                    last_exception = e
                    logger.warning(
                        f"Unexpected error at Tier {tier}, attempt {attempt} for {canonical_url}: {e}\n"
                        f"{traceback.format_exc()}"
                    )

                if attempt < max_attempts:
                    wait_sec = 1.0 * attempt
                    logger.info(f"Retrying Tier {tier} attempt {attempt + 1} in {wait_sec:.1f}s...")
                    await asyncio.sleep(wait_sec)
                    canonical_url = await resolve_canonical_url(url)

            if tier < max(tiers):
                logger.warning(
                    f"Tier {tier} exhausted for {canonical_url}: {last_exception}. "
                    f"Escalating to Tier {tier + 1}..."
                )
                if status_cb:
                    try:
                        res = status_cb(f"🔄 <i>Switching to fallback player client (Tier {tier + 1})...</i>")
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass

        logger.error(f"Download failed after {len(tiers)} tier cascade for {canonical_url}:\n{traceback.format_exc()}")
        raise ExtractorError(f"Download failed after {len(tiers)} tier cascade: {last_exception}")
