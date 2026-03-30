"""Headere pentru cereri mirror."""

from osc_collector.mirror_http import CHROME_LIKE_USER_AGENT, mirror_request_headers


def test_mirror_headers_referer_matches_origin() -> None:
    h = mirror_request_headers("https://beatconnect.io/b/123")
    assert h["Referer"] == "https://beatconnect.io/"
    assert "Chrome" in h["User-Agent"]
    assert h["User-Agent"] == CHROME_LIKE_USER_AGENT
