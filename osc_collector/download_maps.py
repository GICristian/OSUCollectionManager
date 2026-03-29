"""Download beatmap sets (.osz) from a third-party mirror (same pattern as osu-collector-dl)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import httpx

MIRROR_BASE = "https://catboy.best/d/"
USER_AGENT = "OSC-CollectionManager/0.1"


def _safe_filename(name: str, set_id: int) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or str(set_id)
    if not name.lower().endswith(".osz"):
        name += ".osz"
    return f"{set_id} {name}"


def download_beatmapset(
    client: httpx.Client,
    set_id: int,
    dest_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
    skip_existing: bool = True,
) -> Path | None:
    """Stream GET mirror URL; filename from Content-Disposition when possible.

    Returns None if skip_existing and a file starting with ``f\"{set_id} \"`` exists.
    """
    from osc_collector.diagnostic_log import debug

    url = f"{MIRROR_BASE}{set_id}"
    debug(f"mirror: pregătire set_id={set_id} url={url} dest={dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    if skip_existing:
        prefix = f"{set_id} "
        for p in dest_dir.iterdir():
            if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() == ".osz":
                debug(f"mirror: sărit set_id={set_id} (există deja .osz cu prefix)")
                return None
    with client.stream(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=300.0,
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
            for chunk in r.iter_bytes(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if on_progress and total > 0:
                    on_progress(done, total)
    debug(f"mirror: scris set_id={set_id} → {out_path} bytes={done}")
    return out_path
