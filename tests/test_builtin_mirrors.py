"""Teste mirror-uri integrate (fără rețea)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from osc_collector.builtin_mirrors import (
    BUILTIN_MIRROR_TEMPLATES_ORDERED,
    beatmap_url_from_template,
    mirror_templates_for_job,
    rank_builtin_mirrors,
)


def test_beatmap_url_placeholder() -> None:
    assert beatmap_url_from_template("https://x/d/{id}", 9) == "https://x/d/9"


def test_beatmap_url_prefix() -> None:
    assert beatmap_url_from_template("https://x/d/", 3) == "https://x/d/3"


def test_rank_all_fail_preserves_order() -> None:
    with patch("osc_collector.builtin_mirrors.probe_mirror", return_value=False):
        ranked = rank_builtin_mirrors(MagicMock())
    assert len(ranked) == 4
    assert ranked[0] == "https://beatconnect.io/b/{id}"


def test_job_auto_uses_static_builtin_order() -> None:
    out = mirror_templates_for_job("auto", "", MagicMock())
    assert out == list(BUILTIN_MIRROR_TEMPLATES_ORDERED)


def test_job_custom_empty_uses_static_builtin_order() -> None:
    out = mirror_templates_for_job("custom", "  ", MagicMock())
    assert out == list(BUILTIN_MIRROR_TEMPLATES_ORDERED)


def test_job_catboy_single() -> None:
    client = MagicMock()
    with patch("osc_collector.builtin_mirrors.rank_builtin_mirrors"):
        out = mirror_templates_for_job("catboy", "", client)
    assert out == ["https://catboy.best/d/{id}"]


def test_job_beatconnect_single() -> None:
    client = MagicMock()
    with patch("osc_collector.builtin_mirrors.rank_builtin_mirrors"):
        out = mirror_templates_for_job("beatconnect", "", client)
    assert out == ["https://beatconnect.io/b/{id}"]


def test_job_custom_nonempty() -> None:
    client = MagicMock()
    out = mirror_templates_for_job("custom", "https://z/{id}", client)
    assert out == ["https://z/{id}"]
