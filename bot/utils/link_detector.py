"""Link detection, sanitization, and classification for supported media platforms."""

import re
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Platform specific regex patterns
PATTERNS = {
    "tiktok": re.compile(
        r"https?://(?:(?:[a-zA-Z0-9_-]+\.)?tiktok\.com|(?:v\.)?douyin\.com)/(?:(?:t/|vm/|vt/|@[^/\s?#]+/video/|@[^/\s?#]+/photo/|v/|share/video/)?[A-Za-z0-9_-]+|[^\s?#]+)",
        re.IGNORECASE
    ),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv|stories|share)/[A-Za-z0-9_-]+",
        re.IGNORECASE
    ),
    "youtube": re.compile(
        r"https?://(?:(?:www\.|m\.)?youtube\.com/(?:shorts/|watch\?|v/|embed/)|youtu\.be/)[A-Za-z0-9_-]+",
        re.IGNORECASE
    ),
    "twitter": re.compile(
        r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[^/\s?#]+/status/([0-9]+)",
        re.IGNORECASE
    ),
    "reddit": re.compile(
        r"https?://(?:(?:www\.)?reddit\.com/r/[^/\s?#]+/comments/([A-Za-z0-9_-]+)|(?:v|preview)\.redd\.it/([A-Za-z0-9_-]+)|redd\.it/([A-Za-z0-9_-]+))",
        re.IGNORECASE
    ),
    "facebook": re.compile(
        r"https?://(?:(?:www\.|m\.)?facebook\.com/(?:reel|watch|[^/\s?#]+/videos)/|fb\.watch/)([A-Za-z0-9._-]+)",
        re.IGNORECASE
    ),
}

# Generic URL pattern to find candidate links in text
URL_REGEX = re.compile(
    r"https?://[^\s<>\"'()]+",
    re.IGNORECASE
)

# Punctuation to trim from trailing ends of URLs
TRAILING_PUNCTUATION = ".,!?:;)\]>\"'~*^"

# Tracking query parameters to strip across platforms
TRACKING_PARAMS = {
    "_t", "_r", "is_from_webapp", "sender_device", "share_app_id", "source",
    "igsh", "igshid", "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "si", "feature", "s", "t", "ref", "ref_src"
}


def clean_url(raw_url: str) -> str:
    """Normalize and clean URL by removing trailing punctuation and tracking parameters."""
    if not raw_url:
        return ""

    url = raw_url.strip()
    # Strip common enclosing characters and trailing punctuation
    url = url.rstrip(TRAILING_PUNCTUATION)

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url

        netloc = parsed.netloc.lower()

        # YouTube specific URL cleaning: strip all tracking tokens, keep only v= for watch URLs
        if "youtube.com" in netloc or "youtu.be" in netloc:
            path = parsed.path
            if "/shorts/" in path:
                return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
            query_dict = parse_qs(parsed.query, keep_blank_values=True)
            if "v" in query_dict:
                return urlunparse((parsed.scheme, parsed.netloc, path, "", f"v={query_dict['v'][0]}", ""))
            return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

        # TikTok specific URL cleaning: strip dynamic share tracking params
        if "tiktok.com" in netloc or "douyin.com" in netloc:
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

        # Parse query parameters and remove tracking tokens for other platforms
        query_dict = parse_qs(parsed.query, keep_blank_values=True)
        filtered_query = {
            k: v for k, v in query_dict.items() if k.lower() not in TRACKING_PARAMS
        }

        # Re-encode query string
        new_query = urlencode(filtered_query, doseq=True)

        cleaned = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            ""  # drop fragment #
        ))
        return cleaned.rstrip("?")
    except Exception:
        return url


def extract_all_links(text: str = "", entities: Optional[List[Any]] = None) -> List[str]:
    """Extract and clean all candidate URLs from text and Telegram message entities."""
    found_urls = []

    # 1. Extract from Telegram MessageEntities if available
    if entities and text:
        for entity in entities:
            # Check for type string or enum
            etype = getattr(entity, "type", "")
            if etype == "url":
                offset = getattr(entity, "offset", 0)
                length = getattr(entity, "length", 0)
                url_text = text[offset:offset + length]
                if url_text:
                    found_urls.append(url_text)
            elif etype == "text_link":
                link_url = getattr(entity, "url", None)
                if link_url:
                    found_urls.append(link_url)

    # 2. Extract from raw regex search in text
    if text:
        matches = URL_REGEX.findall(text)
        found_urls.extend(matches)

    # Clean and deduplicate while maintaining order
    cleaned_urls = []
    seen = set()
    for raw in found_urls:
        cleaned = clean_url(raw)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            cleaned_urls.append(cleaned)

    return cleaned_urls


# Backward-compatible alias
extract_links = extract_all_links


def detect_platform(url: str) -> Optional[str]:
    """Detect platform name (instagram, tiktok, youtube, twitter, reddit, facebook) or None."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    # Domain fast-path checks
    if any(d in netloc for d in ("tiktok.com", "douyin.com")):
        return "tiktok"
    if "instagram.com" in netloc:
        return "instagram"
    if any(d in netloc for d in ("youtube.com", "youtu.be")):
        return "youtube"
    if any(d in netloc for d in ("twitter.com", "x.com")):
        return "twitter"
    if any(d in netloc for d in ("reddit.com", "redd.it")):
        return "reddit"
    if any(d in netloc for d in ("facebook.com", "fb.watch", "fb.com")):
        return "facebook"

    # Regex fallback checks
    for platform, pattern in PATTERNS.items():
        if pattern.search(url):
            return platform

    return None


def is_supported_url(url: str) -> bool:
    """Return True if URL matches any supported platform."""
    return detect_platform(url) is not None


def get_platform_display_name(platform: str) -> str:
    """Get pretty display name for platform."""
    display_names = {
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "youtube": "YouTube",
        "twitter": "X / Twitter",
        "reddit": "Reddit",
        "facebook": "Facebook",
    }
    return display_names.get(platform, "Media")
