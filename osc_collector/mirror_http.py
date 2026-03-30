"""Headere HTTP pentru cereri către mirror-uri .osz (multe resping clienți minimali)."""

from __future__ import annotations

from urllib.parse import urlparse

CHROME_LIKE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def mirror_request_headers(download_url: str) -> dict[str, str]:
    """User-Agent + Referer + Accept ca un browser; unele mirror-uri dau 403 fără ele."""
    parsed = urlparse(download_url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    return {
        "User-Agent": CHROME_LIKE_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": origin,
    }
