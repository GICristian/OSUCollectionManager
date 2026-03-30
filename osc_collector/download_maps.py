"""Download beatmap sets (.osz) from a third-party mirror (same pattern as osu-collector-dl)."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

import httpx

from osc_collector.mirror_http import mirror_request_headers
from osc_collector.mirror_net import summarize_mirror_attempts_for_log
from osc_collector.settings_store import DEFAULT_MIRROR_DOWNLOAD_TEMPLATE
from osc_collector.osu_site_download import (
    official_beatmapset_download_url,
    official_download_headers,
)


class AllMirrorsFailed(Exception):
    """Toate mirror-urile din lanț au eșuat; vezi ``attempts`` pentru detalii."""

    def __init__(self, attempts: list[tuple[str, BaseException]]):
        self.attempts = attempts
        super().__init__(summarize_mirror_attempts_for_log(attempts))

# Larger read buffer = fewer Python iterations and syscall overhead vs mirror.
READ_CHUNK_BYTES = 1024 * 1024

# Descărcări I/O-bound: multe fire paralele: keep-alive pe clientul per-thread.
# Dacă osu.ppy.sh răspunde 403, lanțul trece la mirror-uri fără throttling artificial.
DEFAULT_PARALLEL_DOWNLOADS = 10

_download_tls = threading.local()


def thread_local_download_client() -> httpx.Client:
    """Un ``httpx.Client`` reutilizabil pe fir (ThreadPool); păstrează conexiuni TCP."""
    c = getattr(_download_tls, "client", None)
    if c is not None and getattr(c, "is_closed", False):
        c = None
    if c is None:
        c = create_mirror_client()
        _download_tls.client = c
    return c


def unique_beatmapset_ids_preserve_order(ids: list[int]) -> list[int]:
    """Elimină duplicate consecutive din API fără a schimba ordinea."""
    seen: set[int] = set()
    out: list[int] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def beatmapset_download_url(template: str | None, set_id: int) -> str:
    """Construiește URL-ul GET pentru un beatmapset.

    Dacă șablonul conține ``{id}``, e înlocuit cu ID-ul. Altfel se tratează ca prefix
    care se termină cu ``/`` și li se concatenează ID-ul (ex. ``https://host/d/``).
    """
    t = (template or "").strip() or DEFAULT_MIRROR_DOWNLOAD_TEMPLATE
    if "{id}" in t:
        return t.replace("{id}", str(set_id))
    base = t.rstrip("/") + "/"
    return f"{base}{set_id}"


def _safe_filename(name: str, set_id: int) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or str(set_id)
    if not name.lower().endswith(".osz"):
        name += ".osz"
    return f"{set_id} {name}"


def _parse_set_id_from_osz_name(path: Path) -> int | None:
    if path.suffix.lower() != ".osz":
        return None
    stem = path.stem
    if stem.isdigit():
        return int(stem)
    part = stem.split(" ", 1)[0]
    if part.isdigit():
        return int(part)
    return None


def _osz_looks_valid(path: Path) -> bool:
    try:
        n = path.stat().st_size
    except OSError:
        return False
    if n < 512:
        return False
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return True
    if head.lstrip().startswith(b"<") or head.startswith(b"<!DOCTYPE") or head.startswith(b"<html"):
        return False
    return head.startswith(b"PK")


def existing_valid_set_ids(dest_dir: Path) -> set[int]:
    """One directory scan: beatmapset IDs that already have a valid .osz on disk."""
    out: set[int] = set()
    try:
        for p in dest_dir.iterdir():
            if not p.is_file():
                continue
            sid = _parse_set_id_from_osz_name(p)
            if sid is None:
                continue
            if _osz_looks_valid(p):
                out.add(sid)
    except OSError:
        pass
    return out


def mirror_client_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=45.0, read=300.0, write=120.0, pool=45.0)


def create_mirror_client() -> httpx.Client:
    """Client HTTP pentru un singur fir; folosește ``thread_local_download_client()`` în pool."""
    return httpx.Client(
        follow_redirects=True,
        timeout=mirror_client_timeout(),
        limits=httpx.Limits(max_keepalive_connections=48, max_connections=64),
    )


def download_beatmapset(
    client: httpx.Client,
    set_id: int,
    dest_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
    skip_existing: bool = True,
    existing_valid_ids: set[int] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    mirror_url_template: str | None = None,
    download_url: str | None = None,
    request_headers: dict[str, str] | None = None,
    pre_stream_hook: Callable[[], None] | None = None,
    after_valid_osz_hook: Callable[[], None] | None = None,
) -> Path | None:
    """Stream GET mirror URL; filename from Content-Disposition when possible.

    Returns None if skip_existing and a valid .osz for this set_id already exists.
    """
    from osc_collector.diagnostic_log import debug

    url = (download_url or "").strip() or beatmapset_download_url(
        mirror_url_template,
        set_id,
    )
    debug(f"mirror: pregătire set_id={set_id} url={url} dest={dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    if skip_existing:
        if existing_valid_ids is not None and set_id in existing_valid_ids:
            debug(f"mirror: sărit set_id={set_id} (cache existent)")
            return None
        prefix = f"{set_id} "
        for p in dest_dir.iterdir():
            if not p.is_file() or p.suffix.lower() != ".osz":
                continue
            if p.name.startswith(prefix) or p.name == f"{set_id}.osz":
                if _osz_looks_valid(p):
                    debug(f"mirror: sărit set_id={set_id} (există deja .osz valid)")
                    return None
    if should_cancel and should_cancel():
        return None

    if pre_stream_hook:
        pre_stream_hook()

    headers = (
        request_headers
        if request_headers is not None
        else mirror_request_headers(url)
    )

    with client.stream(
        "GET",
        url,
        headers=headers,
        timeout=mirror_client_timeout(),
        follow_redirects=True,
    ) as r:
        r.raise_for_status()
        fname = f"{set_id}.osz"
        cd = r.headers.get("content-disposition") or ""
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            fname = _safe_filename(m.group(1).strip(), set_id)
        out_path = dest_dir / fname
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=READ_CHUNK_BYTES):
                if should_cancel and should_cancel():
                    try:
                        f.flush()
                    except OSError:
                        pass
                    try:
                        out_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise InterruptedError("Descărcare anulată.")
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    if total > 0:
                        on_progress(done, total)
                    else:
                        on_progress(done, 0)
        resp_ct = (r.headers.get("content-type") or "").lower()
    if not _osz_looks_valid(out_path):
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(
            f"Mirror nu a returnat un .osz valid pentru set {set_id} "
            f"(primele octeți nu sunt ZIP). content-type={resp_ct!r}. "
            "Încearcă alt mirror sau verifică dacă set-ul există.",
        )
    if after_valid_osz_hook:
        after_valid_osz_hook()
    debug(f"mirror: scris set_id={set_id} → {out_path} bytes={done}")
    return out_path


def download_beatmapset_with_fallback(
    client: httpx.Client,
    set_id: int,
    dest_dir: Path,
    mirror_templates: list[str],
    on_progress: Callable[[int, int], None] | None = None,
    skip_existing: bool = True,
    existing_valid_ids: set[int] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    official_osu_cookie: str | None = None,
) -> Path | None:
    """Încearcă opțional osu.ppy.sh (cookie), apoi fiecare șablon mirror."""
    from osc_collector.diagnostic_log import debug

    chain = [t.strip() for t in mirror_templates if (t or "").strip()]
    if not chain:
        chain = [DEFAULT_MIRROR_DOWNLOAD_TEMPLATE]
    attempts: list[tuple[str, BaseException]] = []
    cookie = (official_osu_cookie or "").strip()
    if cookie:
        ou = official_beatmapset_download_url(set_id)
        base_h = mirror_request_headers(ou)
        ohdr = official_download_headers(set_id, cookie, base_h)
        try:
            debug(f"mirror: set_id={set_id} sursă=osu.ppy.sh (oficial, cookie)")
            return download_beatmapset(
                client,
                set_id,
                dest_dir,
                on_progress=on_progress,
                skip_existing=skip_existing,
                existing_valid_ids=existing_valid_ids,
                should_cancel=should_cancel,
                mirror_url_template=None,
                download_url=ou,
                request_headers=ohdr,
                pre_stream_hook=None,
                after_valid_osz_hook=None,
            )
        except InterruptedError:
            raise
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.RequestError) as e:
            attempts.append((ou, e))
            debug(f"mirror: set_id={set_id} eșuat HTTP/transport osu.ppy.sh: {e!s}")
        except (ValueError, OSError) as e:
            attempts.append((ou, e))
            debug(f"mirror: set_id={set_id} eșuat conținut osu.ppy.sh: {e!s}")
    for i, tmpl in enumerate(chain):
        try:
            debug(
                f"mirror: set_id={set_id} încercare {i + 1}/{len(chain)} "
                f"template={tmpl!r}",
            )
            return download_beatmapset(
                client,
                set_id,
                dest_dir,
                on_progress=on_progress,
                skip_existing=skip_existing,
                existing_valid_ids=existing_valid_ids,
                should_cancel=should_cancel,
                mirror_url_template=tmpl,
                download_url=None,
                request_headers=None,
                pre_stream_hook=None,
                after_valid_osz_hook=None,
            )
        except InterruptedError:
            raise
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.RequestError) as e:
            attempts.append((tmpl, e))
            debug(f"mirror: set_id={set_id} eșuat HTTP/transport pe {tmpl!r}: {e!s}")
        except (ValueError, OSError) as e:
            attempts.append((tmpl, e))
            debug(f"mirror: set_id={set_id} eșuat conținut/fișier pe {tmpl!r}: {e!s}")
    if attempts:
        raise AllMirrorsFailed(attempts)
    return None
