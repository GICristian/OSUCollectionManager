"""Teste mirror_net (DNS helpers)."""

from __future__ import annotations

from osc_collector.mirror_net import (
    exclude_templates_for_failed_dns_hosts,
    hostnames_from_mirror_templates,
    is_likely_dns_or_resolve_failure,
    short_download_error_message,
    template_hostname,
)


def test_template_hostname() -> None:
    assert template_hostname("https://catboy.best/d/{id}") == "catboy.best"


def test_exclude_failed_dns_hosts() -> None:
    t = [
        "https://catboy.best/d/{id}",
        "https://api.chimu.moe/v1/download/{id}?n=1",
    ]
    out = exclude_templates_for_failed_dns_hosts(t, {"api.chimu.moe"})
    assert out == ["https://catboy.best/d/{id}"]


def test_hostnames_unique_order() -> None:
    h = hostnames_from_mirror_templates(
        [
            "https://catboy.best/d/{id}",
            "https://a.example/x/{id}",
            "https://catboy.best/other/{id}",
        ],
    )
    assert h == ["catboy.best", "a.example"]


def test_dns_failure_detection_message() -> None:
    assert is_likely_dns_or_resolve_failure(OSError("getaddrinfo failed")) is True


def test_dns_failure_detection_11001_in_text() -> None:
    assert is_likely_dns_or_resolve_failure(RuntimeError("[Errno 11001] getaddrinfo failed")) is True


def test_short_message_dns() -> None:
    s = short_download_error_message(OSError("getaddrinfo failed"))
    assert "DNS" in s
    assert "rezolvă" in s
