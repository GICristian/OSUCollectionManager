"""Verificări rețea pentru mirror-uri (DNS)."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


def hostnames_from_mirror_templates(templates: list[str]) -> list[str]:
    """Host-uri unice extrase din șabloane (ex. ``https://x/d/{id}`` → ``x``)."""
    order: list[str] = []
    seen: set[str] = set()
    for tmpl in templates:
        url = (tmpl or "").replace("{id}", "0")
        try:
            host = urlparse(url).hostname
        except Exception:
            host = None
        if not host or host in seen:
            continue
        seen.add(host)
        order.append(host)
    return order


def try_resolve_hostname(host: str) -> tuple[bool, str]:
    try:
        socket.getaddrinfo(
            host,
            443,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return True, ""
    except OSError as e:
        return False, str(e)


def template_hostname(tmpl: str) -> str | None:
    """Hostul dintr-un singur șablon URL."""
    hs = hostnames_from_mirror_templates([tmpl])
    return hs[0] if hs else None


def exclude_templates_for_failed_dns_hosts(
    templates: list[str],
    failed_hosts: set[str],
) -> list[str]:
    """Scoate șabloanele al căror host a eșuat la proba DNS (nu-i mai încerca la descărcare)."""
    out: list[str] = []
    for t in templates:
        h = template_hostname(t)
        if h is None or h not in failed_hosts:
            out.append(t)
    return out


def mirror_dns_preflight(
    mirror_templates: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """
    Returnează ``(eșecuri [(host, mesaj)], hosturi_ok)``.
    """
    hosts = hostnames_from_mirror_templates(mirror_templates)
    failures: list[tuple[str, str]] = []
    oks: list[str] = []
    for h in hosts:
        ok, err = try_resolve_hostname(h)
        if ok:
            oks.append(h)
        else:
            failures.append((h, err))
    return failures, oks


def is_likely_dns_or_resolve_failure(exc: BaseException, _depth: int = 0) -> bool:
    """True pentru getaddrinfo / Win 11001 / erori echivalente în lanțul de excepții."""
    if _depth > 10:
        return False
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 11001:
            return True
        if exc.errno == 11001:
            return True
    low = str(exc).lower()
    if "getaddrinfo" in low or "11001" in low or "name or service not known" in low:
        return True
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        if is_likely_dns_or_resolve_failure(cause, _depth + 1):
            return True
    ctx = exc.__context__
    if ctx is not None and ctx is not cause:
        if is_likely_dns_or_resolve_failure(ctx, _depth + 1):
            return True
    return False


def short_download_error_message(exc: BaseException) -> str:
    """Un rând pentru log UI când eșuează o descărcare."""
    if is_likely_dns_or_resolve_failure(exc):
        return (
            "DNS/rețea: nu se rezolvă numele serverului (getaddrinfo). "
            "Verifică internetul, DNS (ex. 8.8.8.8), VPN, fișierul hosts, firewall."
        )
    return str(exc)


def summarize_mirror_attempts_for_log(attempts: list[tuple[str, BaseException]]) -> str:
    """Rezumat pentru log UI: fiecare mirror încercat + eroarea (scurtă)."""
    segs: list[str] = []
    for tmpl, exc in attempts:
        host = template_hostname(tmpl) or tmpl[:44]
        segs.append(f"{host}: {short_download_error_message(exc)}")
    return " | ".join(segs)
