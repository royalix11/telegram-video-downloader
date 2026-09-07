"""Base bot commands: /start, /help, /health."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.services.doctor import EnvironmentDoctor

router = Router(name="base_router")


@router.message(CommandStart())
async def handle_start(message: Message):
    """Handle /start command with onboarding overview."""
    text = (
        "👋 <b>Welcome to Fast Video Downloader Bot!</b>\n\n"
        "Send me a link from any of the following platforms and I will download, "
        "optimize, and deliver the video directly to your chat:\n\n"
        "• 📸 <b>Instagram</b> (Reels, Posts, Stories)\n"
        "• 🎵 <b>TikTok</b> (Videos & Audio)\n"
        "• 🔴 <b>YouTube</b> (Shorts & Standard Videos)\n"
        "• 🐦 <b>X / Twitter</b> (Clips & Posts)\n"
        "• 🤖 <b>Reddit</b> (Posts & v.redd.it)\n"
        "• 📘 <b>Facebook</b> (Reels & Watch)\n\n"
        "⚡ <i>Features: Instant in-app streaming (+faststart), automatic 2-pass compression under 50 MB, "
        "and high-resolution stream selection.</i>\n\n"
        "👉 <b>Just paste a link below to get started!</b>"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("help"))
async def handle_help(message: Message):
    """Handle /help command with usage information."""
    text = (
        "ℹ️ <b>How to use Fast Video Downloader Bot</b>\n\n"
        "1. Copy the link of the video you want from Instagram, TikTok, YouTube, X, Reddit, or Facebook.\n"
        "2. Paste the link into this chat.\n"
        "3. Wait a few seconds while the bot fetches and formats your video.\n\n"
        "💡 <b>Telegram Limits & Quality:</b>\n"
        "• Standard Telegram Bot API allows files up to <b>50 MB</b>.\n"
        "• If a downloaded video is larger than 50 MB, our pipeline automatically recalculates "
        "bitrates and executes high-efficiency 2-pass compression to fit strictly under the limit.\n"
        "• All videos are encoded in H.264/AAC with <code>+faststart</code> for immediate playback.\n\n"
        "🔧 <b>Diagnostics:</b> Send /health to inspect host status."
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("health"))
async def handle_health(message: Message):
    """Run environment doctor and report diagnostic health."""
    status_msg = await message.answer("🔄 <i>Running environment diagnostic check...</i>", parse_mode="HTML")
    report = await EnvironmentDoctor.run_full_diagnostic()

    sys_info = report["system"]
    ffmpeg = report["ffmpeg"]
    disk = report["disk"]
    net = report["network"]

    overall_icon = "✅" if report["healthy"] else "⚠️"
    ffmpeg_icon = "✅" if ffmpeg.get("ffmpeg_installed") and ffmpeg.get("supports_h264") else "❌"
    disk_icon = "✅" if disk.get("writable") else "❌"

    net_summary = []
    for cdn, info in net.items():
        icon = "🟢" if info.get("reachable") else "🔴"
        net_summary.append(f"{icon} {cdn}")

    text = (
        f"{overall_icon} <b>System Health Report</b>\n\n"
        f"<b>Host System:</b>\n"
        f"• OS: <code>{sys_info['os']} {sys_info['os_release']} ({sys_info['architecture']})</code>\n"
        f"• Python: <code>{sys_info['python_version']} (venv: {sys_info['in_venv']})</code>\n\n"
        f"<b>Media Pipeline:</b>\n"
        f"• FFmpeg: {ffmpeg_icon} <code>{ffmpeg.get('ffmpeg_path', 'Not found')}</code>\n"
        f"• H.264/AAC: {'Available' if ffmpeg.get('supports_h264') and ffmpeg.get('supports_aac') else 'Missing'}\n\n"
        f"<b>Disk & Storage:</b>\n"
        f"• Temp directory: {disk_icon} <code>{disk.get('path')}</code>\n"
        f"• Free Space: <code>{disk.get('free_space_mb', 0):,.1f} MB</code>\n\n"
        f"<b>CDN Reachability:</b>\n"
        + " | ".join(net_summary)
    )

    await status_msg.edit_text(text, parse_mode="HTML")
