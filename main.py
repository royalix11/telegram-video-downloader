"""Main entry point for Fast Video Downloader Telegram Bot."""

import asyncio
import logging
import sys

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.handlers import base, media
from bot.services.doctor import EnvironmentDoctor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")


async def main():
    logger.info("Initializing Telegram Video Downloader Bot...")

    # 1. Run environment health check
    health_report = await EnvironmentDoctor.run_full_diagnostic(settings.resolved_temp_dir)
    logger.info(f"System: {health_report['system']['os']} {health_report['system']['architecture']} (Python {health_report['system']['python_version']})")
    
    ffmpeg_ok = health_report["ffmpeg"].get("ffmpeg_installed", False)
    ffprobe_ok = health_report["ffmpeg"].get("ffprobe_installed", False)
    if not (ffmpeg_ok and ffprobe_ok):
        logger.error("CRITICAL: FFmpeg and/or FFprobe not found on PATH. Media processing will fail.")
        sys.exit(1)
    logger.info("FFmpeg & FFprobe verified and ready.")

    disk_ok = health_report["disk"].get("writable", False)
    if not disk_ok:
        logger.error("CRITICAL: Temp directory is not writable. Aborting.")
        sys.exit(1)
    logger.info(f"Temp directory verified: {health_report['disk']['path']} ({health_report['disk']['free_space_mb']} MB free)")

    if settings.resolved_cookies_path:
        logger.info(f"Using cookies file: {settings.resolved_cookies_path}")
    else:
        logger.info("No cookies.txt file detected. Public links only.")

    # 2. Verify Bot Token
    token = settings.clean_bot_token
    if not token or token == "123456789:ABCdefGHIjklMNOpqrsTUVwxyz":
        logger.warning(
            "\n" + "=" * 70 + "\n"
            "⚠️  BOT_TOKEN is not configured or is using default template!\n"
            "Please create a .env file or set the BOT_TOKEN environment variable:\n"
            "  BOT_TOKEN=your_telegram_bot_token_from_botfather\n"
            "=" * 70
        )
        sys.exit(1)

    # 3. Setup Bot and Dispatcher
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Register handlers
    dp.include_router(base.router)
    dp.include_router(media.router)

    # Clear pending updates
    await bot.delete_webhook(drop_pending_updates=True)

    bot_user = await bot.get_me()
    logger.info(f"Bot started successfully as @{bot_user.username} (ID: {bot_user.id})")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process terminated.")
