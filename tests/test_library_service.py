"""Teste listare colecții: stable (collection.db) și lazer (JSON din utilitarul Realm)."""

import json
import sys
import tempfile
from pathlib import Path

from osc_collector.collection_db import OsuCollection, build_collection_db
from osc_collector.library_service import (
    list_lazer_collections,
    list_lazer_collections_detail,
    list_stable_collections,
)

# Nume ca în dropdown-ul de colecții osu!lazer (exemplu real din UI).
LAZER_UI_COLLECTION_NAMES = (
    "300Pp Farm HD",
    "jumpy",
    "pp",
    "stream",
    "zaza",
)


def test_list_lazer_collections_parses_realm_tool_json_like_ui(monkeypatch, tmp_path: Path) -> None:
    """Flux lazer: ce returnează OscLazerRealmImport list → aceleași nume ca în joc."""
    realm = tmp_path / "client_51.realm"
    realm.write_bytes(b"\0")

    payload = [
        {"name": LAZER_UI_COLLECTION_NAMES[0], "beatmaps": 42},
        {"name": LAZER_UI_COLLECTION_NAMES[1], "beatmaps": 7},
        {"name": LAZER_UI_COLLECTION_NAMES[2], "beatmaps": 100},
        {"name": LAZER_UI_COLLECTION_NAMES[3], "beatmaps": 3},
        {"name": LAZER_UI_COLLECTION_NAMES[4], "beatmaps": 1},
    ]

    def fake_realm_list(p: Path) -> tuple[int, str, str]:
        assert p.resolve() == realm.resolve()
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(
        "osc_collector.lazer_realm_import.realm_list_collections",
        fake_realm_list,
    )

    rows, err = list_lazer_collections(tmp_path, str(realm))
    assert err == ""
    assert rows is not None
    assert [str(r["name"]) for r in rows] == list(LAZER_UI_COLLECTION_NAMES)
    assert all(r["source"] == "lazer" for r in rows)
    assert rows[1]["beatmaps"] == 7


def test_list_lazer_drops_bundle_realm_even_if_file_exists(
    monkeypatch, tmp_path: Path
) -> None:
    """Nu apelăm utilitarul cu un .realm din folderul instalării frozen."""
    bundle = tmp_path / "OSC"
    bundle.mkdir()
    fake_exe = bundle / "OSC.exe"
    fake_exe.write_bytes(b"x")
    realm_bad = bundle / "client.realm"
    realm_bad.write_bytes(b"\0")
    real_osu = tmp_path / "appdata_osu"
    real_osu.mkdir()
    (real_osu / "client_1.realm").write_bytes(b"\0")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(
        "osc_collector.osu_paths.default_osu_data_dir",
        lambda: real_osu,
    )

    called: list[Path] = []

    def fake_realm_list(p: Path) -> tuple[int, str, str]:
        called.append(p.resolve())
        return 0, "[]", ""

    monkeypatch.setattr(
        "osc_collector.lazer_realm_import.realm_list_collections",
        fake_realm_list,
    )

    rows, err = list_lazer_collections(bundle, str(realm_bad))
    assert err == ""
    assert rows == []
    assert len(called) == 1
    assert called[0] == (real_osu / "client_1.realm").resolve()


def test_list_stable_collections_same_titles_roundtrip_in_collection_db() -> None:
    """Aceleași titluri pot exista și în collection.db (osu!stable); OSC citește ambele surse."""
    md5_one = "0" * 32
    cols = [
        OsuCollection(
            name=n,
            md5_hashes=[md5_one, "f" * 32] if n == "jumpy" else [md5_one],
        )
        for n in LAZER_UI_COLLECTION_NAMES
    ]
    blob = build_collection_db(cols)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "collection.db"
        path.write_bytes(blob)
        rows = list_stable_collections(path)

    assert len(rows) == len(LAZER_UI_COLLECTION_NAMES)
    by_name = {str(r["name"]): r for r in rows}
    for n in LAZER_UI_COLLECTION_NAMES:
        assert n in by_name
        assert by_name[n]["source"] == "stable"
    assert by_name["jumpy"]["beatmaps"] == 2
    assert by_name["pp"]["beatmaps"] == 1


def test_list_lazer_collections_detail_parses_collections_and_items(
    monkeypatch, tmp_path: Path
) -> None:
    realm = tmp_path / "client_51.realm"
    realm.write_bytes(b"\0")
    payload = {
        "collections": [
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "name": "TestCol",
                "beatmaps": 1,
                "items": [
                    {
                        "md5": "a" * 32,
                        "title": "Song",
                        "artist": "Artist",
                        "difficulty": "Hard",
                        "missing": False,
                    }
                ],
            }
        ]
    }

    def fake_detail(p: Path) -> tuple[int, str, str]:
        assert p.resolve() == realm.resolve()
        return 0, json.dumps(payload), ""

    monkeypatch.setattr(
        "osc_collector.lazer_realm_import.realm_list_detail",
        fake_detail,
    )

    rows, err = list_lazer_collections_detail(tmp_path, str(realm))
    assert err == ""
    assert rows is not None and len(rows) == 1
    assert rows[0]["name"] == "TestCol"
    assert rows[0]["source"] == "lazer"
    items = rows[0]["items"]
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["md5"] == "a" * 32
    assert items[0]["artist"] == "Artist"
