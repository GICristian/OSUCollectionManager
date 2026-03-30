"""Descărcare oficială osu.ppy.sh (cookie + throttle)."""

from __future__ import annotations

from osc_collector.osu_site_download import (
    OsuOfficialThrottler,
    normalize_osu_web_cookie,
    official_beatmapset_download_url,
    official_download_headers,
)


def test_normalize_cookie_strips_prefix() -> None:
    assert normalize_osu_web_cookie("  cookie:  a=b  ") == "a=b"
    assert normalize_osu_web_cookie("") == ""


def test_official_url_no_video() -> None:
    assert official_beatmapset_download_url(42) == "https://osu.ppy.sh/beatmapsets/42/download?noVideo=1"


def test_official_headers_merge() -> None:
    base = {"User-Agent": "UA", "Accept": "*/*"}
    h = official_download_headers(7, "x=1", base)
    assert h["Cookie"] == "x=1"
    assert h["Referer"] == "https://osu.ppy.sh/beatmapsets/7"
    assert h["User-Agent"] == "UA"


def test_throttler_first_slots_unblocked() -> None:
    thr = OsuOfficialThrottler(per_minute=3, per_hour=170)
    thr.wait_for_slot()
    thr.register_success()
    thr.wait_for_slot()
    thr.register_success()
