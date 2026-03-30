"""HTTP client for osu!Collector public API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

COLLECTION_API = "https://osucollector.com/api/collections/"
USER_AGENT = "OSC-CollectionManager/0.1 (+https://osucollector.com)"


@dataclass
class CollectionData:
    """Parsed collection from API v1."""

    id: int
    name: str
    description: str
    uploader_username: str
    beatmap_count: int
    md5_checksums: list[str] = field(default_factory=list)
    beatmapset_ids: list[int] = field(default_factory=list)


def parse_collection_id(text: str) -> int | None:
    """Extract numeric collection id from URL or raw id string."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    m = re.search(r"osucollector\.com/collections/(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"/collections/(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _flatten_checksums(beatmapsets: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for bms in beatmapsets:
        for bm in bms.get("beatmaps") or []:
            cs = bm.get("checksum")
            if isinstance(cs, str) and len(cs) == 32:
                out.append(cs.lower())
    return out


def _as_int_id(v: Any) -> int | None:
    if isinstance(v, int) and v > 0:
        return v
    if isinstance(v, str) and v.isdigit():
        n = int(v)
        return n if n > 0 else None
    return None


def _beatmapset_ids(beatmapsets: list[dict[str, Any]]) -> list[int]:
    """Extrage ID-uri unice de beatmapset (oglindă API osu! / osu!Collector)."""
    seen: set[int] = set()
    ordered: list[int] = []
    for bms in beatmapsets:
        if not isinstance(bms, dict):
            continue
        for key in ("id", "beatmapset_id", "beatmapsetId", "BeatmapsetId"):
            sid = _as_int_id(bms.get(key))
            if sid is not None and sid not in seen:
                seen.add(sid)
                ordered.append(sid)
                break
        for bm in bms.get("beatmaps") or []:
            if not isinstance(bm, dict):
                continue
            for key in ("beatmapset_id", "beatmapsetId", "beatmapset", "parent_id"):
                bid = _as_int_id(bm.get(key))
                if bid is not None and bid not in seen:
                    seen.add(bid)
                    ordered.append(bid)
                    break
    return ordered


def fetch_collection(client: httpx.Client, collection_id: int) -> CollectionData:
    """GET /api/collections/{id} (includes beatmapsets with per-difficulty checksums)."""
    from osc_collector.diagnostic_log import debug

    url = f"{COLLECTION_API}{collection_id}"
    debug(f"osuc API: GET {url}")
    try:
        r = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=120.0)
        debug(f"osuc API: status={r.status_code} bytes≈{len(r.content)}")
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        debug(f"osuc API: excepție la GET/JSON pentru id={collection_id}: {e!s}")
        raise

    beatmapsets = data.get("beatmapsets") or []
    md5s = _flatten_checksums(beatmapsets)
    set_ids = _beatmapset_ids(beatmapsets)
    uploader = data.get("uploader") or {}
    username = uploader.get("username") if isinstance(uploader, dict) else None

    debug(
        f"osuc API: parsat id={data.get('id')} beatmapsets={len(beatmapsets)} "
        f"md5_count={len(md5s)} set_ids={len(set_ids)}",
    )
    return CollectionData(
        id=int(data["id"]),
        name=str(data.get("name") or f"collection_{collection_id}"),
        description=str(data.get("description") or ""),
        uploader_username=str(username or "unknown"),
        beatmap_count=int(data.get("beatmapCount") or len(md5s)),
        md5_checksums=md5s,
        beatmapset_ids=set_ids,
    )
