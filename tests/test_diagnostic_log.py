"""Teste pentru utilitarul de log diagnostic."""

from __future__ import annotations

from pathlib import Path

import pytest

from osc_collector import diagnostic_log as dl


def test_truncate_short_unchanged() -> None:
    assert dl.truncate("hello", max_len=100) == "hello"


def test_truncate_long_has_marker() -> None:
    s = "x" * 100
    out = dl.truncate(s, max_len=40)
    assert "truncat diagnostic" in out
    assert len(out) < len(s)


def test_log_path_is_absolute() -> None:
    p = dl.log_path()
    assert p.is_absolute()
    assert p.name == "OSC_diagnostic.log"
    assert isinstance(p, Path)


def test_debug_skipped_when_not_verbose(tmp_path, monkeypatch) -> None:
    logf = tmp_path / "OSC_diagnostic.log"
    monkeypatch.setattr(dl, "log_path", lambda: logf)
    dl.set_verbose(False)
    dl.debug("secret-detail")
    assert not logf.is_file()


def test_debug_written_when_verbose(tmp_path, monkeypatch) -> None:
    logf = tmp_path / "OSC_diagnostic.log"
    monkeypatch.setattr(dl, "log_path", lambda: logf)
    dl.set_verbose(True)
    dl.debug("visible-detail")
    text = logf.read_text(encoding="utf-8")
    assert "DEBUG" in text
    assert "visible-detail" in text
    dl.set_verbose(False)


@pytest.mark.parametrize(
    "val",
    ["1", "true", "yes", "on", "TRUE", " On "],
)
def test_verbose_from_environment(monkeypatch, val) -> None:
    monkeypatch.setenv("OSC_DEBUG_LOG", val)
    assert dl.verbose_from_environment() is True


def test_verbose_from_environment_off(monkeypatch) -> None:
    monkeypatch.setenv("OSC_DEBUG_LOG", "0")
    assert dl.verbose_from_environment() is False
