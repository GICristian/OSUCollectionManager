"""Tests for mirror download helpers."""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

from osc_collector import download_maps as dm
from osc_collector.osu_site_download import OfficialDownloadGate, OsuOfficialThrottler


@pytest.mark.parametrize(
    "name, expected",
    [
        ("12345.osz", 12345),
        ("12345 Artist - Title.osz", 12345),
        ("notid rest.osz", None),
    ],
)
def test_parse_set_id_from_osz_name(name: str, expected: int | None, tmp_path: Path) -> None:
    p = tmp_path / name
    p.write_bytes(b"x")
    assert dm._parse_set_id_from_osz_name(p) == expected


def test_existing_valid_set_ids_detects_zip_header(tmp_path: Path) -> None:
    z = tmp_path / "999 Minimal.osz"
    z.write_bytes(b"PK\x03\x04" + b"\x00" * 600)
    assert dm.existing_valid_set_ids(tmp_path) == {999}


def test_beatmapset_download_url_with_placeholder() -> None:
    assert (
        dm.beatmapset_download_url("https://x.example/d/{id}", 42)
        == "https://x.example/d/42"
    )


def test_beatmapset_download_url_prefix_without_placeholder() -> None:
    assert dm.beatmapset_download_url("https://x.example/d/", 7) == "https://x.example/d/7"


def test_unique_beatmapset_ids_preserve_order() -> None:
    assert dm.unique_beatmapset_ids_preserve_order([1, 2, 1, 3, 2]) == [1, 2, 3]


def test_existing_valid_set_ids_ignores_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "888 Bad.osz"
    bad.write_bytes(b"<html>")
    assert dm.existing_valid_set_ids(tmp_path) == set()


def test_content_type_rejects_html_and_json() -> None:
    assert dm._content_type_is_not_osz("text/html; charset=utf-8") is True
    assert dm._content_type_is_not_osz("application/json") is True
    assert dm._content_type_is_not_osz("application/octet-stream") is False


def _http_status(code: int, url: str = "https://beatconnect.io/b/1") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(str(code), request=request, response=response)


def test_host_guard_cools_down_then_clears_on_success() -> None:
    guard = dm.MirrorHostGuard()
    template = "https://beatconnect.io/b/{id}"
    guard.note_failure(template, _http_status(429))
    assert guard.skip_reason(template) is not None
    guard.note_success(template)
    assert guard.skip_reason(template) is None


def test_host_guard_blocks_after_repeated_429() -> None:
    guard = dm.MirrorHostGuard()
    template = "https://beatconnect.io/b/{id}"
    error = _http_status(429)
    for _ in range(3):
        guard.note_failure(template, error)
    reason = guard.skip_reason(template)
    assert reason is not None
    assert "oprit" in reason


def test_host_guard_ignores_404() -> None:
    guard = dm.MirrorHostGuard()
    template = "https://osu.direct/d/{id}"
    guard.note_failure(template, _http_status(404, "https://osu.direct/d/1"))
    assert guard.skip_reason(template) is None


def test_host_guard_blocks_html_mirror_after_two_failures() -> None:
    guard = dm.MirrorHostGuard()
    template = "https://nerinyan.moe/d/{id}"
    error = ValueError("nu a returnat un .osz valid")
    guard.note_failure(template, error)
    assert guard.skip_reason(template) is None
    guard.note_failure(template, error)
    assert guard.skip_reason(template) is not None


def test_beatconnect_slot_is_single_flight() -> None:
    guard = dm.MirrorHostGuard()
    template = "https://beatconnect.io/b/{id}"
    guard.acquire(template)
    entered = threading.Event()

    def second() -> None:
        guard.acquire(template)
        entered.set()
        guard.release(template)

    worker = threading.Thread(target=second)
    worker.start()
    worker.join(0.2)
    assert entered.is_set() is False
    guard.release(template)
    worker.join(2)
    assert entered.is_set() is True


def test_fallback_tries_mirrors_before_official_account(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def fake(client, set_id, dest_dir, **kwargs):
        seen.append(kwargs.get("download_url") or kwargs.get("mirror_url_template") or "")
        if kwargs.get("download_url"):
            return dest_dir / "9.osz"
        raise ValueError("nu a returnat un .osz valid")

    monkeypatch.setattr(dm, "download_beatmapset", fake)
    out = dm.download_beatmapset_with_fallback(
        client=object(),
        set_id=9,
        dest_dir=tmp_path,
        mirror_templates=["https://mirror.example/d/{id}"],
        official_osu_cookie="osu_session=abc",
        official_throttler=OsuOfficialThrottler(per_minute=10, per_hour=100),
        official_gate=OfficialDownloadGate(),
    )
    assert out == tmp_path / "9.osz"
    assert seen[0] == "https://mirror.example/d/{id}"
    assert "osu.ppy.sh" in seen[1]


def test_official_429_stops_account_for_later_sets(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def fake(client, set_id, dest_dir, **kwargs):
        url = kwargs.get("download_url") or kwargs.get("mirror_url_template") or ""
        seen.append(url)
        if kwargs.get("download_url"):
            raise _http_status(429, kwargs["download_url"])
        raise ValueError("nu a returnat un .osz valid")

    monkeypatch.setattr(dm, "download_beatmapset", fake)
    gate = OfficialDownloadGate()
    stopped: list[str] = []
    throttler = OsuOfficialThrottler(per_minute=10, per_hour=100)
    kwargs = dict(
        client=object(),
        dest_dir=tmp_path,
        mirror_templates=["https://mirror.example/d/{id}"],
        official_osu_cookie="osu_session=abc",
        official_throttler=throttler,
        official_gate=gate,
        on_official_stopped=stopped.append,
    )
    with pytest.raises(dm.AllMirrorsFailed):
        dm.download_beatmapset_with_fallback(set_id=1, **kwargs)
    with pytest.raises(dm.AllMirrorsFailed):
        dm.download_beatmapset_with_fallback(set_id=2, **kwargs)
    official = [url for url in seen if "osu.ppy.sh" in url]
    assert len(official) == 1
    assert stopped
    assert gate.is_stopped() is True


def test_blocked_host_is_not_requested_again(tmp_path: Path, monkeypatch) -> None:
    template = "https://beatconnect.io/b/{id}"
    guard = dm.MirrorHostGuard()
    for _ in range(3):
        guard.note_failure(template, _http_status(429))
    seen: list[str] = []

    def fake(client, set_id, dest_dir, **kwargs):
        seen.append(kwargs.get("mirror_url_template") or "")
        raise ValueError("nu a returnat un .osz valid")

    monkeypatch.setattr(dm, "download_beatmapset", fake)
    with pytest.raises(dm.AllMirrorsFailed):
        dm.download_beatmapset_with_fallback(
            client=object(),
            set_id=3,
            dest_dir=tmp_path,
            mirror_templates=[template, "https://ok.example/d/{id}"],
            host_guard=guard,
        )
    assert seen == ["https://ok.example/d/{id}"]
