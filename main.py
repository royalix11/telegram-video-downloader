"""Main entry point for Fast Video Downloader Telegram Bot."""

import asyncio
import logging
import os
import sys

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.handlers import base, media
from bot.services.doctor import EnvironmentDoctor

from collections import deque

class MemoryLogHandler(logging.Handler):
    """In-memory circular ring buffer for real-time log inspection and remote monitoring."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self.buffer = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            pass


log_buffer = MemoryLogHandler()
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log_buffer.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), log_buffer]
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

    # 4. Start health check web server (default port 8080 for Docker healthchecks)
    web_runner = None
    port_str = os.getenv("PORT", "8080")
    if port_str:
        try:
            port = int(port_str)
            app = web.Application()

            async def health_check(request):
                return web.json_response({
                    "status": "healthy",
                    "service": "Telegram Video Downloader Bot",
                    "bot_username": f"@{bot_user.username}",
                    "buffered_logs_count": len(log_buffer.buffer)
                })

            async def get_logs(request):
                limit_str = request.query.get("limit", "200")
                try:
                    limit = min(1000, max(1, int(limit_str)))
                except ValueError:
                    limit = 200
                level = request.query.get("level", "").upper()
                lines = list(log_buffer.buffer)
                if level:
                    lines = [line for line in lines if f"[{level}]" in line]
                return web.Response(text="\n".join(lines[-limit:]), content_type="text/plain; charset=utf-8")

            async def get_errors(request):
                lines = [
                    line for line in log_buffer.buffer
                    if "[ERROR]" in line or "[WARNING]" in line
                ]
                return web.Response(
                    text="\n".join(lines[-200:]) if lines else "No errors logged.",
                    content_type="text/plain; charset=utf-8"
                )

            app.router.add_get("/", health_check)
            app.router.add_get("/health", health_check)
            app.router.add_get("/logs", get_logs)
            app.router.add_get("/logs/errors", get_errors)
            web_runner = web.AppRunner(app)

            await web_runner.setup()
            site = web.TCPSite(web_runner, "0.0.0.0", port)
            await site.start()
            logger.info(f"Render health check web server active on http://0.0.0.0:{port}")
        except Exception as e:
            logger.warning(f"Could not bind health check server to port {port_str}: {e}")

    try:
        await dp.start_polling(bot)
    finally:
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process terminated.")
