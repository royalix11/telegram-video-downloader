"""Media message handler for intercepting, extracting, and delivering social videos."""

import asyncio
import html
import logging
import traceback
from typing import Optional

from aiogram import Bot, Router
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import FSInputFile, Message

from bot.config import settings
from bot.services.extractor import (
    ExtractorError,
    LoginRequiredError,
    VideoUnavailableError,
)
from bot.services.orchestrator import MediaOrchestrator, ProcessedMedia
from bot.services.pipeline import PipelineError, VideoTooLongError
from bot.utils.formatters import format_bytes, format_duration
from bot.utils.link_detector import (
    detect_platform,
    extract_all_links,
    get_platform_display_name,
    is_supported_url,
)

logger = logging.getLogger(__name__)

router = Router(name="media_router")

# Shared orchestrator and concurrency semaphore
orchestrator = MediaOrchestrator()
concurrency_semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)


@router.message()
async def handle_media_message(message: Message, bot: Bot):
    """Intercept incoming messages containing supported social media links or provide clear guidance."""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    # Extract all URLs using both Telegram entities and regex
    candidate_links = extract_all_links(text, entities)

    # If message contains no URLs at all, prompt the user
    if not candidate_links:
        await message.reply(
            "💡 <b>Send me a video link!</b>\n\n"
            "Paste a link from <b>Instagram, TikTok, YouTube Shorts, X / Twitter, Reddit, or Facebook</b> "
            "and I will download and send it to you.",
            parse_mode="HTML"
        )
        return

    # Filter to supported platforms
    supported_links = [link for link in candidate_links if is_supported_url(link)]

    # If URLs were found but none match supported platforms, inform user gracefully
    if not supported_links:
        await message.reply(
            "⚠️ <b>Unsupported Link:</b>\n"
            "This link does not appear to be from a supported platform.\n\n"
            "<b>Supported services:</b>\n"
            "• 📸 <b>Instagram</b> (Reels, Posts, Stories)\n"
            "• 🎵 <b>TikTok</b> (vm, vt, /t/, standard links)\n"
            "• 🔴 <b>YouTube</b> (Shorts, Clips, Videos)\n"
            "• 🐦 <b>X / Twitter</b> (Clips & Posts)\n"
            "• 🤖 <b>Reddit</b> (Posts & v.redd.it)\n"
            "• 📘 <b>Facebook</b> (Reels & Watch)\n\n"
            "Please paste a valid video link from one of these platforms!",
            parse_mode="HTML"
        )
        return

    # Process first valid link
    target_url = supported_links[0]
    platform_key = detect_platform(target_url) or "media"
    platform_name = get_platform_display_name(platform_key)

    logger.info(f"Processing incoming link [{platform_name}]: {target_url} from user {message.from_user.id if message.from_user else 'unknown'}")

    status_msg = await message.reply(
        f"⏳ <b>Queued:</b> Preparing {platform_name} download...",
        parse_mode="HTML"
    )

    last_text = ""

    async def update_status(new_text: str):
        nonlocal last_text
        if new_text != last_text:
            try:
                await status_msg.edit_text(new_text, parse_mode="HTML")
                last_text = new_text
            except Exception as e:
                logger.debug(f"Could not update status message: {e}")

    try:
        async with concurrency_semaphore:
            async with orchestrator.process_job(
                url=target_url,
                platform_name=platform_name,
                progress_cb=update_status
            ) as media:
                await update_status(
                    f"⬆️ <b>Uploading {platform_name} video to Telegram...</b>\n"
                    f"<i>Size: {format_bytes(media.final_size_bytes)}</i>"
                )

                # Format caption
                caption_title = html.escape(media.title[:120])
                duration_str = format_duration(media.media_info.duration)
                res_str = f"{media.media_info.width}x{media.media_info.height}"

                caption_lines = [
                    f"🎬 <b>{caption_title}</b>",
                    f"⏱ <b>Duration:</b> {duration_str} | <b>Resolution:</b> {res_str}",
                    f"📦 <b>Size:</b> {format_bytes(media.final_size_bytes)}",
                ]
                if media.was_compressed:
                    orig_mb = format_bytes(media.original_size_bytes)
                    caption_lines.append(f"⚡ <i>Compressed from {orig_mb} to fit Telegram limit</i>")
                caption_lines.append(f"\n🌐 <i>Via {platform_name} Downloader</i>")

                caption_text = "\n".join(caption_lines)

                # Send video payload
                video_input = FSInputFile(str(media.video_path))
                thumb_input = FSInputFile(str(media.thumbnail_path)) if media.thumbnail_path else None

                await bot.send_video(
                    chat_id=message.chat.id,
                    video=video_input,
                    duration=int(media.media_info.duration),
                    width=media.media_info.width,
                    height=media.media_info.height,
                    thumbnail=thumb_input,
                    caption=caption_text,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_to_message_id=message.message_id,
                    request_timeout=300
                )

        # Delete status message on success
        try:
            await status_msg.delete()
        except Exception:
            pass

    except LoginRequiredError:
        logger.warning(f"Login required for link: {target_url}")
        await update_status(
            f"🔒 <b>Authentication Required:</b> This {platform_name} post is private or login-restricted. "
            "A valid <code>cookies.txt</code> session is required to extract this media."
        )
    except VideoUnavailableError:
        logger.warning(f"Video unavailable: {target_url}")
        await update_status(
            f"❌ <b>Unavailable:</b> The {platform_name} video could not be found, has expired, "
            "or is geo-restricted."
        )
    except VideoTooLongError as e:
        logger.warning(f"Video too long: {e}")
        await update_status(
            f"⚠️ <b>Video Too Long:</b> {html.escape(str(e))}"
        )
    except PipelineError as e:
        logger.error(f"Pipeline error processing {target_url}:\n{traceback.format_exc()}")
        await update_status(
            f"⚠️ <b>Processing Error:</b> Failed to process video ({html.escape(str(e))})."
        )
    except TelegramNetworkError as e:
        logger.error(f"Telegram upload timeout / network error processing {target_url}:\n{traceback.format_exc()}")
        await update_status(
            f"⚠️ <b>Upload Network Timeout:</b> Video was downloaded and transcoded successfully, "
            "but sending the file payload to Telegram timed out. Please retry."
        )
    except Exception as e:
        logger.error(f"Unexpected error processing {target_url}:\n{traceback.format_exc()}")
        await update_status(
            f"❌ <b>Download Failed:</b> Could not process this {platform_name} video.\n"
            f"<i>Reason: {html.escape(str(e)[:150])}</i>"
        )
