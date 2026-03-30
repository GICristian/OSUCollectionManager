"""Setări persistente OSC (JSON în %AppData%\\OSC\\)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from osc_collector.builtin_mirrors import ALL_MIRROR_PRESET_KEYS

DEFAULT_MIRROR_DOWNLOAD_TEMPLATE = "https://beatconnect.io/b/{id}"


@dataclass
class AppSettings:
    """Preferințe utilizator."""

    client: str
    download_dir: str
    realm_path: str
    stable_collection_db: str
    osu_data_dir: str
    developer_mode: bool
    diagnostic_verbose: bool = False
    mirror_download_template: str = ""
    mirror_preset: str = "auto"
    osu_web_cookie: str = ""

    def merged_paths(self, defaults: AppSettings) -> AppSettings:
        """String gol = folosește implicitul."""
        return AppSettings(
            client=self.client or defaults.client,
            download_dir=self.download_dir or defaults.download_dir,
            realm_path=self.realm_path or defaults.realm_path,
            stable_collection_db=self.stable_collection_db
            or defaults.stable_collection_db,
            osu_data_dir=self.osu_data_dir or defaults.osu_data_dir,
            developer_mode=self.developer_mode,
            diagnostic_verbose=self.diagnostic_verbose,
            mirror_download_template=self.mirror_download_template
            or defaults.mirror_download_template,
            mirror_preset=_normalize_mirror_preset(self.mirror_preset, defaults.mirror_preset),
            osu_web_cookie=self.osu_web_cookie or defaults.osu_web_cookie,
        )


def _normalize_mirror_preset(raw: str, fallback: str) -> str:
    p = (raw or "").strip().lower()
    if p in ALL_MIRROR_PRESET_KEYS:
        return p
    fb = (fallback or "auto").strip().lower()
    return fb if fb in ALL_MIRROR_PRESET_KEYS else "auto"


def settings_file_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / "OSC"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def default_settings() -> AppSettings:
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local"))
    from osc_collector.collection_manager_config import osu_location_from_collection_manager
    from osc_collector.osu_paths import (
        default_osu_data_dir,
        discover_lazer_realm_file,
        resolve_existing_lazer_realm,
    )

    cm_osu = osu_location_from_collection_manager()
    osu_data = cm_osu if cm_osu is not None else default_osu_data_dir()

    realm = resolve_existing_lazer_realm(osu_data)
    if realm is None:
        realm = discover_lazer_realm_file(osu_data)
    return AppSettings(
        client="Lazer",
        download_dir=str(home / "Downloads" / "osu_collector_maps"),
        realm_path=str(realm),
        stable_collection_db=str(local / "osu!" / "collection.db"),
        osu_data_dir=str(osu_data),
        developer_mode=False,
        diagnostic_verbose=False,
        mirror_download_template=DEFAULT_MIRROR_DOWNLOAD_TEMPLATE,
        mirror_preset="auto",
        osu_web_cookie="",
    )


def _sanitize_loaded_settings(
    merged: AppSettings,
    base: AppSettings,
) -> tuple[AppSettings, bool]:
    """
    Corectează căi care indică folderul aplicației / build în loc de date osu!.
    Persistă la încărcare dacă s-a schimbat ceva.
    """
    from osc_collector.collection_manager_config import osu_location_from_collection_manager
    from osc_collector.osu_paths import (
        is_dir_writable,
        looks_like_osu_data_dir,
        normalize_osu_data_dir,
        path_is_under_distribution_bundle,
    )

    changed = False
    out = merged
    norm_osu = normalize_osu_data_dir(Path(out.osu_data_dir))
    cm_osu = osu_location_from_collection_manager()
    if cm_osu is not None:
        try:
            use_cm = not norm_osu.is_dir()
            if norm_osu.is_dir() and not looks_like_osu_data_dir(norm_osu):
                use_cm = True
            if use_cm:
                norm_osu = cm_osu
        except OSError:
            norm_osu = cm_osu
    if str(norm_osu) != out.osu_data_dir.strip():
        out = replace(out, osu_data_dir=str(norm_osu))
        changed = True

    rp = out.realm_path.strip()
    if rp:
        try:
            hp = Path(rp).expanduser()
            if path_is_under_distribution_bundle(hp):
                out = replace(out, realm_path="")
                changed = True
            else:
                try:
                    rfile = hp.resolve()
                except OSError:
                    rfile = hp
                if rfile.is_file() and rfile.suffix.lower() == ".realm":
                    pass
                elif not rfile.is_file():
                    out = replace(out, realm_path="")
                    changed = True
        except OSError:
            out = replace(out, realm_path="")
            changed = True

    dd = out.download_dir.strip()
    if dd:
        try:
            dp = Path(dd).expanduser()
            try:
                dr = dp.resolve()
            except OSError:
                dr = dp
            if path_is_under_distribution_bundle(dr):
                out = replace(out, download_dir=base.download_dir)
                changed = True
            elif not is_dir_writable(dr):
                out = replace(out, download_dir=base.download_dir)
                changed = True
        except OSError:
            out = replace(out, download_dir=base.download_dir)
            changed = True

    return out, changed


def load_settings() -> AppSettings:
    path = settings_file_path()
    base = default_settings()
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        loaded = AppSettings(
            client=str(raw.get("client") or base.client),
            download_dir=str(raw.get("download_dir") or ""),
            realm_path=str(raw.get("realm_path") or ""),
            stable_collection_db=str(raw.get("stable_collection_db") or ""),
            osu_data_dir=str(raw.get("osu_data_dir") or ""),
            developer_mode=bool(raw.get("developer_mode", base.developer_mode)),
            diagnostic_verbose=bool(raw.get("diagnostic_verbose", base.diagnostic_verbose)),
            mirror_download_template=str(raw.get("mirror_download_template") or ""),
            mirror_preset=str(raw.get("mirror_preset") or "auto"),
            osu_web_cookie=str(raw.get("osu_web_cookie") or ""),
        )
        merged = loaded.merged_paths(base)
        fixed, changed = _sanitize_loaded_settings(merged, base)
        if changed:
            save_settings(fixed)
        return fixed
    except (json.JSONDecodeError, OSError, TypeError, KeyError):
        return base


def save_settings(s: AppSettings) -> None:
    path = settings_file_path()
    path.write_text(
        json.dumps(asdict(s), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    from osc_collector.diagnostic_log import debug

    debug(
        f"settings_store: salvat {path} client={s.client!r} "
        f"developer_mode={s.developer_mode} diagnostic_verbose={s.diagnostic_verbose}",
    )
