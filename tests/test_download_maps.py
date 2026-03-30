"""Tests for mirror download helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from osc_collector import download_maps as dm


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
