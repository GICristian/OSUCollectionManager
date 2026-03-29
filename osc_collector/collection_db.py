"""Read and write osu! legacy collection.db (ppy wiki: Legacy database file structure)."""

from __future__ import annotations

import struct
from dataclasses import dataclass


DB_VERSION = 20150203


def _read_uleb128(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return value, pos


def _write_uleb128(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def read_osu_string(data: bytes, pos: int) -> tuple[str, int]:
    if pos >= len(data):
        return "", pos
    kind = data[pos]
    pos += 1
    if kind == 0:
        return "", pos
    if kind != 0x0B:
        raise ValueError(f"Invalid string prefix: 0x{kind:02x}")
    length, pos = _read_uleb128(data, pos)
    end = pos + length
    if end > len(data):
        raise ValueError("String length past end of buffer")
    s = data[pos:end].decode("utf-8", errors="replace")
    return s, end


def write_osu_string(s: str) -> bytes:
    if not s:
        return b"\x00"
    raw = s.encode("utf-8")
    return b"\x0b" + _write_uleb128(len(raw)) + raw


def read_int32_le(data: bytes, pos: int) -> tuple[int, int]:
    if pos + 4 > len(data):
        raise ValueError("Not enough data for int32")
    (v,) = struct.unpack_from("<I", data, pos)
    return int(v), pos + 4


def write_int32_le(v: int) -> bytes:
    return struct.pack("<I", v & 0xFFFFFFFF)


@dataclass
class OsuCollection:
    name: str
    md5_hashes: list[str]


def parse_collection_db(path: str) -> tuple[int, list[OsuCollection]]:
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    version, pos = read_int32_le(data, pos)
    count, pos = read_int32_le(data, pos)
    collections: list[OsuCollection] = []
    for _ in range(count):
        name, pos = read_osu_string(data, pos)
        n_maps, pos = read_int32_le(data, pos)
        hashes: list[str] = []
        for _ in range(n_maps):
            h, pos = read_osu_string(data, pos)
            hashes.append(h)
        collections.append(OsuCollection(name=name, md5_hashes=hashes))
    return version, collections


def build_collection_db(collections: list[OsuCollection], version: int = DB_VERSION) -> bytes:
    parts: list[bytes] = [
        write_int32_le(version),
        write_int32_le(len(collections)),
    ]
    for coll in collections:
        parts.append(write_osu_string(coll.name))
        parts.append(write_int32_le(len(coll.md5_hashes)))
        for h in coll.md5_hashes:
            parts.append(write_osu_string(h))
    return b"".join(parts)


def merge_collection(
    existing: list[OsuCollection],
    new_name: str,
    new_hashes: list[str],
    if_exists: str,
) -> list[OsuCollection]:
    """
    if_exists: 'append' = always add a new collection (rename if name taken);
               'merge' = union hashes into existing collection with same name;
               'replace' = drop same-named collection and add fresh one.
    """
    normalized = [h.lower() for h in new_hashes if h]
    names = {c.name for c in existing}

    if if_exists == "replace":
        rest = [c for c in existing if c.name != new_name]
        rest.append(OsuCollection(name=new_name, md5_hashes=normalized))
        return rest

    if if_exists == "merge" and new_name in names:
        out: list[OsuCollection] = []
        for c in existing:
            if c.name != new_name:
                out.append(c)
                continue
            merged = dict.fromkeys([h.lower() for h in c.md5_hashes] + normalized)
            out.append(OsuCollection(name=new_name, md5_hashes=list(merged.keys())))
        return out

    final_name = new_name
    if if_exists == "append" and new_name in names:
        suffix = 2
        while f"{new_name} ({suffix})" in names:
            suffix += 1
        final_name = f"{new_name} ({suffix})"

    return existing + [OsuCollection(name=final_name, md5_hashes=normalized)]
