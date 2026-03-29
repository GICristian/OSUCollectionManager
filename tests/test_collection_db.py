"""Tests for legacy collection.db serialization."""

import tempfile
from pathlib import Path

from osc_collector.collection_db import (
    OsuCollection,
    build_collection_db,
    merge_collection,
    parse_collection_db,
    read_osu_string,
    write_osu_string,
)


def test_osu_string_roundtrip() -> None:
    for s in ["", "jump", "ășîț colecție", "a" * 500]:
        raw = write_osu_string(s)
        out, pos = read_osu_string(raw, 0)
        assert out == s
        assert pos == len(raw)


def test_parse_write_roundtrip() -> None:
    cols = [
        OsuCollection(
            name="Test",
            md5_hashes=["a" * 32, "b" * 32],
        ),
        OsuCollection(name="Empty", md5_hashes=[]),
    ]
    blob = build_collection_db(cols, version=20150203)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "collection.db"
        p.write_bytes(blob)
        ver, back = parse_collection_db(str(p))
    assert ver == 20150203
    assert len(back) == 2
    assert back[0].name == "Test"
    assert len(back[0].md5_hashes) == 2


def test_roundtrip_collection_names_like_osu_client_dropdown() -> None:
    """Titluri realiste (ex. colecții văzute în osu!lazer); formatul e collection.db (stable)."""
    names = [
        "300Pp Farm HD",
        "jumpy",
        "pp",
        "stream",
        "zaza",
    ]
    md5 = "a" * 32
    cols = [OsuCollection(name=n, md5_hashes=[md5]) for n in names]
    blob = build_collection_db(cols, version=20150203)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "collection.db"
        p.write_bytes(blob)
        ver, back = parse_collection_db(str(p))
    assert ver == 20150203
    assert [c.name for c in back] == names
    assert len(back) == 5


def test_merge_modes() -> None:
    base = [OsuCollection("A", ["11" * 16, "22" * 16])]
    m = merge_collection(base, "A", ["33" * 16], "merge")
    assert len(m) == 1
    assert len(m[0].md5_hashes) == 3

    r = merge_collection(base, "A", ["44" * 16], "replace")
    assert len(r) == 1
    assert len(r[0].md5_hashes) == 1

    ap = merge_collection(base, "A", ["55" * 16], "append")
    assert len(ap) == 2
    assert ap[1].name.startswith("A (")
