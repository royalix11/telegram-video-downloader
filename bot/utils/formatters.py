"""Formatters for data presentation, file sizes, and media attributes."""

import re


def format_bytes(size_bytes: int | float) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"


def format_duration(seconds: float | int | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_resolution(width: int | None, height: int | None) -> str:
    """Format width and height into display resolution (e.g. 1080p, 720p)."""
    if not width or not height:
        return "Auto"
    min_dim = min(width, height)
    return f"{min_dim}p ({width}x{height})"


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """Sanitize filename to be safe across Windows and Linux filesystems."""
    # Remove illegal characters: <>:"/\|?* and control characters
    cleaned = re.sub(r'[\<\>\:\"\/\\\|\?\*\x00-\x1f]', '', filename)
    # Strip whitespace and trailing periods
    cleaned = cleaned.strip().strip(".")
    if not cleaned:
        cleaned = "download"
    return cleaned[:max_length]
