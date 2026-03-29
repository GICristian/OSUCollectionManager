"""Listează colecții din collection.db (stable) sau client.realm (lazer)."""

from __future__ import annotations

import json
from pathlib import Path

from osc_collector.collection_db import parse_collection_db
from osc_collector.diagnostic_log import debug as diag_debug
from osc_collector.diagnostic_log import error as diag_error
from osc_collector.diagnostic_log import info as diag_info
from osc_collector.diagnostic_log import truncate as diag_truncate
from osc_collector.diagnostic_log import warning as diag_warning
from osc_collector.osu_paths import (
    default_osu_data_dir,
    effective_lazer_realm_path,
    path_is_under_distribution_bundle,
)


def list_stable_collections(db_path: Path) -> list[dict[str, object]]:
    diag_debug(f"library: list_stable_collections db_path={db_path}")
    if not db_path.is_file():
        diag_debug("library: list_stable_collections fișier lipsă → []")
        return []
    try:
        _, cols = parse_collection_db(str(db_path))
    except (OSError, ValueError) as e:
        diag_debug(f"library: list_stable_collections parse error {e!s}")
        return []
    rows = [
        {
            "name": c.name,
            "beatmaps": len(c.md5_hashes),
            "source": "stable",
        }
        for c in cols
    ]
    diag_debug(f"library: list_stable_collections → {len(rows)} colecții")
    return rows


def list_lazer_collections(
    osu_data_dir: Path,
    realm_path_hint: str,
) -> tuple[list[dict[str, object]] | None, str]:
    from osc_collector.lazer_realm_import import realm_list_collections

    diag_debug(
        f"library: list_lazer_collections osu_data_dir={osu_data_dir} hint={realm_path_hint!r}",
    )
    eff = effective_lazer_realm_path(osu_data_dir, realm_path_hint)
    if eff is not None and path_is_under_distribution_bundle(eff):
        eff = effective_lazer_realm_path(default_osu_data_dir(), "")
    if eff is not None and path_is_under_distribution_bundle(eff):
        eff = None
    if eff is None:
        diag_warning(
            f"library list_lazer_collections: niciun .realm rezolvat sub {osu_data_dir}",
        )
        return None, (
            "Nu s-a găsit niciun .realm în folderul de date osu! "
            f"({osu_data_dir}). Setează folderul corect în Setări "
            "(de obicei %AppData%\\osu) și pornește osu!lazer o dată."
        )
    diag_info(f"library list_lazer_collections effective_realm={eff}")
    code, out, err = realm_list_collections(eff)
    if code != 0:
        diag_warning(
            f"library list_lazer_collections: realm={eff} exit_code={code} "
            f"detail={diag_truncate(err or out or '')}",
        )
        return None, (err or out or "Eroare listare Realm.").strip()
    text = (out or "").strip()
    if not text:
        return [], (err or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        diag_error(
            f"library list_lazer_collections JSON: {e}\n{diag_truncate(text, 2000)}",
        )
        return None, f"JSON invalid de la utilitar: {e}\n{text[:400]}"
    if not isinstance(data, list):
        diag_error("library list_lazer_collections: răspuns JSON nu e listă.")
        return None, "Răspuns neașteptat de la utilitar."
    for row in data:
        if isinstance(row, dict):
            row["source"] = "lazer"
    stderr_hint = (err or "").strip()
    if len(data) == 0 and stderr_hint:
        return data, stderr_hint
    return data, ""


def list_lazer_collections_detail(
    osu_data_dir: Path,
    realm_path_hint: str,
) -> tuple[list[dict[str, object]] | None, str]:
    """Citește colecții + beatmap-uri (rezolvate din tabelul Beatmap), ca în Collection Manager."""
    from osc_collector.lazer_realm_import import realm_list_detail

    diag_debug(
        f"library: list_lazer_collections_detail osu_data_dir={osu_data_dir} "
        f"hint={realm_path_hint!r}",
    )
    eff = effective_lazer_realm_path(osu_data_dir, realm_path_hint)
    if eff is not None and path_is_under_distribution_bundle(eff):
        eff = effective_lazer_realm_path(default_osu_data_dir(), "")
    if eff is not None and path_is_under_distribution_bundle(eff):
        eff = None
    if eff is None:
        diag_warning(
            f"library list_lazer_collections_detail: niciun .realm sub {osu_data_dir}",
        )
        return None, (
            "Nu s-a găsit niciun .realm în folderul de date osu! "
            f"({osu_data_dir}). Setează folderul corect în Setări "
            "(de obicei %AppData%\\osu) și pornește osu!lazer o dată."
        )
    diag_info(f"library list-detail effective_realm={eff}")
    code, out, err = realm_list_detail(eff)
    if code != 0:
        diag_warning(
            f"library list-detail: realm={eff} exit_code={code} "
            f"detail={diag_truncate(err or out or '')}",
        )
        return None, (err or out or "Eroare list-detail Realm.").strip()
    text = (out or "").strip()
    if not text:
        return [], (err or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        diag_error(
            f"library list-detail JSON: {e}\n{diag_truncate(text, 2000)}",
        )
        return None, f"JSON invalid de la utilitar: {e}\n{text[:400]}"
    cols = data.get("collections")
    if not isinstance(cols, list):
        diag_error("library list-detail: răspuns fără collections[] valid.")
        return None, "Răspuns list-detail neașteptat (lipsește collections)."
    out_rows: list[dict[str, object]] = []
    for row in cols:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row["source"] = "lazer"
        items = row.get("items")
        if not isinstance(items, list):
            row["items"] = []
        else:
            row["items"] = [x for x in items if isinstance(x, dict)]
        out_rows.append(row)
    stderr_hint = (err or "").strip()
    if len(out_rows) == 0 and stderr_hint:
        return out_rows, stderr_hint
    return out_rows, ""
