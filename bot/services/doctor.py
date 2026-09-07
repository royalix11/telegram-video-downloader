"""Host environment and dependency diagnostic service."""

import asyncio
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
import aiohttp


class EnvironmentDoctor:
    """Diagnoses host environment, binaries, permissions, and CDN network health."""

    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
            "in_venv": sys.prefix != sys.base_prefix,
            "executable": sys.executable,
        }

    @staticmethod
    async def check_ffmpeg() -> Dict[str, Any]:
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")

        result = {
            "ffmpeg_installed": ffmpeg_path is not None,
            "ffprobe_installed": ffprobe_path is not None,
            "ffmpeg_path": ffmpeg_path,
            "ffprobe_path": ffprobe_path,
            "version_info": None,
            "supports_h264": False,
            "supports_aac": False,
        }

        if ffmpeg_path:
            try:
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_path,
                    "-version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                version_str = stdout.decode("utf-8", errors="replace")
                result["version_info"] = version_str.splitlines()[0] if version_str else "Unknown"
                result["supports_h264"] = "enable-libx264" in version_str or "libx264" in version_str
                result["supports_aac"] = "aac" in version_str
            except Exception as e:
                result["error"] = str(e)

        return result

    @staticmethod
    def check_temp_disk(base_path: Path | None = None) -> Dict[str, Any]:
        target_dir = base_path or Path(tempfile.gettempdir())
        result = {
            "path": str(target_dir),
            "writable": False,
            "cleanup_verified": False,
            "free_space_mb": 0.0,
        }

        try:
            # Check free space
            total, used, free = shutil.disk_usage(str(target_dir))
            result["free_space_mb"] = round(free / (1024 * 1024), 2)

            # Test write, read, and delete
            with tempfile.TemporaryDirectory(dir=target_dir) as tmpdir:
                test_file = Path(tmpdir) / "doctor_check.tmp"
                test_file.write_text("antigravity-health-check", encoding="utf-8")
                content = test_file.read_text(encoding="utf-8")
                if content == "antigravity-health-check":
                    result["writable"] = True
            result["cleanup_verified"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    @staticmethod
    async def check_cdn_connectivity() -> Dict[str, Any]:
        endpoints = {
            "YouTube": "https://www.youtube.com",
            "TikTok": "https://www.tiktok.com",
            "Instagram": "https://www.instagram.com",
            "X": "https://x.com",
            "Reddit": "https://www.reddit.com",
            "Telegram": "https://api.telegram.org",
        }
        results = {}
        timeout = aiohttp.ClientTimeout(total=6)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for name, url in endpoints.items():
                try:
                    async with session.get(url, allow_redirects=True) as resp:
                        # Consider 200, 301, 302, 403, 405 as network reachable
                        results[name] = {
                            "reachable": resp.status in (200, 301, 302, 303, 307, 403, 405),
                            "status_code": resp.status
                        }
                except Exception as e:
                    results[name] = {
                        "reachable": False,
                        "error": str(e)
                    }
        return results

    @classmethod
    async def run_full_diagnostic(cls, base_temp_path: Path | None = None) -> Dict[str, Any]:
        sys_info = cls.get_system_info()
        ffmpeg_info = await cls.check_ffmpeg()
        disk_info = cls.check_temp_disk(base_temp_path)
        net_info = await cls.check_cdn_connectivity()

        all_healthy = (
            ffmpeg_info.get("ffmpeg_installed", False)
            and ffmpeg_info.get("ffprobe_installed", False)
            and disk_info.get("writable", False)
            and disk_info.get("cleanup_verified", False)
        )

        return {
            "healthy": all_healthy,
            "system": sys_info,
            "ffmpeg": ffmpeg_info,
            "disk": disk_info,
            "network": net_info,
        }


if __name__ == "__main__":
    async def main():
        report = await EnvironmentDoctor.run_full_diagnostic()
        import json
        print(json.dumps(report, indent=2))
    asyncio.run(main())
