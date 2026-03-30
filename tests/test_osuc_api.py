"""Parsare ID beatmapset din răspuns API (variante de câmp)."""

from __future__ import annotations

from osc_collector import osuc_api


def test_beatmapset_ids_top_level_id_int() -> None:
    bms = [{"id": 42, "beatmaps": []}]
    assert osuc_api._beatmapset_ids(bms) == [42]


def test_beatmapset_ids_string_id() -> None:
    bms = [{"id": "99", "beatmaps": []}]
    assert osuc_api._beatmapset_ids(bms) == [99]


def test_beatmapset_ids_from_beatmaps_nested() -> None:
    bms = [
        {
            "beatmaps": [
                {"checksum": "a" * 32, "beatmapset_id": 7},
                {"checksum": "b" * 32, "beatmapset_id": 7},
            ],
        },
    ]
    assert osuc_api._beatmapset_ids(bms) == [7]


def test_beatmapset_ids_camel_case_keys() -> None:
    bms = [{"beatmapsetId": 3, "beatmaps": []}]
    assert osuc_api._beatmapset_ids(bms) == [3]


def test_beatmapset_ids_dedup_order() -> None:
    bms = [
        {"id": 1, "beatmaps": [{"beatmapset_id": 1}]},
        {"id": 2, "beatmaps": []},
    ]
    assert osuc_api._beatmapset_ids(bms) == [1, 2]
