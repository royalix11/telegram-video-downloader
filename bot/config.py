"""Application configuration using Pydantic Settings."""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    bot_token: str = ""
    max_concurrent_downloads: int = 3
    max_file_size_mb: float = 49.5
    temp_dir: Optional[str] = None
    cookies_file: Optional[str] = "cookies.txt"
    request_timeout: int = 600

    @property
    def clean_bot_token(self) -> str:
        """Sanitize bot token by stripping quotes, angle brackets, and whitespace."""
        return self.bot_token.strip().strip("<>\"'").strip()

    @property
    def max_file_size_bytes(self) -> int:
        """Calculate max allowable file size in bytes for Telegram Bot API."""
        return int(self.max_file_size_mb * 1024 * 1024)

    @property
    def resolved_cookies_path(self) -> Optional[Path]:
        """Return Path to cookies.txt if it exists."""
        if self.cookies_file:
            path = Path(self.cookies_file)
            if path.is_file():
                return path.resolve()
        return None

    @property
    def resolved_temp_dir(self) -> Optional[Path]:
        """Return Path to custom temp directory if configured."""
        if self.temp_dir:
            p = Path(self.temp_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p.resolve()
        return None


settings = Settings()
