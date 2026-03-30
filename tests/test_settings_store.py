"""Teste setări JSON."""

from pathlib import Path

import pytest

from osc_collector.settings_store import AppSettings, load_settings, save_settings


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "osc_collector.settings_store.settings_file_path",
        lambda: tmp_path / "settings.json",
    )
    base = AppSettings(
        client="Lazer",
        download_dir=str(tmp_path / "dl"),
        realm_path=str(tmp_path / "c.realm"),
        stable_collection_db=str(tmp_path / "col.db"),
        osu_data_dir=str(tmp_path / "osu"),
        developer_mode=False,
        diagnostic_verbose=False,
        mirror_download_template="https://beatconnect.io/b/{id}",
        mirror_preset="auto",
        osu_web_cookie="",
    )
    monkeypatch.setattr("osc_collector.settings_store.default_settings", lambda: base)
    return tmp_path, base


def test_save_and_load_roundtrip(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    custom = AppSettings(
        client="Stable",
        download_dir=str(tmp_path / "x"),
        realm_path=str(tmp_path / "y.realm"),
        stable_collection_db=str(tmp_path / "z.db"),
        osu_data_dir=str(tmp_path / "osu"),
        developer_mode=True,
        diagnostic_verbose=True,
    )
    save_settings(custom)
    loaded = load_settings()
    assert loaded.client == "Stable"
    assert loaded.download_dir.endswith("x")
    assert Path(loaded.stable_collection_db).name == "z.db"
    assert loaded.developer_mode is True
    assert loaded.diagnostic_verbose is True


def test_mirror_template_roundtrip(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    custom = AppSettings(
        client=base.client,
        download_dir=base.download_dir,
        realm_path=base.realm_path,
        stable_collection_db=base.stable_collection_db,
        osu_data_dir=base.osu_data_dir,
        developer_mode=False,
        diagnostic_verbose=False,
        mirror_download_template="https://mirror.example/d/{id}",
        mirror_preset="custom",
    )
    save_settings(custom)
    loaded = load_settings()
    assert loaded.mirror_download_template == "https://mirror.example/d/{id}"
    assert loaded.mirror_preset == "custom"


def test_osu_web_cookie_roundtrip(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    custom = AppSettings(
        client=base.client,
        download_dir=base.download_dir,
        realm_path=base.realm_path,
        stable_collection_db=base.stable_collection_db,
        osu_data_dir=base.osu_data_dir,
        developer_mode=False,
        diagnostic_verbose=False,
        mirror_download_template=base.mirror_download_template,
        mirror_preset=base.mirror_preset,
        osu_web_cookie="osu_session=abc",
    )
    save_settings(custom)
    loaded = load_settings()
    assert loaded.osu_web_cookie == "osu_session=abc"


def test_mirror_preset_roundtrip(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    custom = AppSettings(
        client=base.client,
        download_dir=base.download_dir,
        realm_path=base.realm_path,
        stable_collection_db=base.stable_collection_db,
        osu_data_dir=base.osu_data_dir,
        developer_mode=False,
        diagnostic_verbose=False,
        mirror_download_template=base.mirror_download_template,
        mirror_preset="nerinyan",
    )
    save_settings(custom)
    loaded = load_settings()
    assert loaded.mirror_preset == "nerinyan"


def test_load_missing_file_uses_defaults(isolated_settings) -> None:
    _tmp, base = isolated_settings
    loaded = load_settings()
    assert loaded.client == base.client


def test_load_prefers_cm_osu_location_when_saved_dir_not_osu_like(
    isolated_settings, monkeypatch
) -> None:
    tmp_path, base = isolated_settings
    wrong = tmp_path / "random_empty"
    wrong.mkdir()
    real_osu = tmp_path / "real_osu"
    real_osu.mkdir()
    (real_osu / "client_1.realm").write_bytes(b"x")

    def fake_cm() -> Path:
        return real_osu

    monkeypatch.setattr(
        "osc_collector.collection_manager_config.osu_location_from_collection_manager",
        fake_cm,
    )
    bad = AppSettings(
        client="Lazer",
        download_dir=str(tmp_path / "dl"),
        realm_path="",
        stable_collection_db=str(tmp_path / "col.db"),
        osu_data_dir=str(wrong),
        developer_mode=False,
    )
    save_settings(bad)
    loaded = load_settings()
    assert Path(loaded.osu_data_dir).resolve() == real_osu.resolve()


def test_load_clears_realm_path_when_file_missing(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    osu = tmp_path / "osu"
    osu.mkdir()
    (osu / "client.realm").write_bytes(b"x")
    bad = AppSettings(
        client="Lazer",
        download_dir=str(tmp_path / "dl"),
        realm_path=str(tmp_path / "missing" / "nope.realm"),
        stable_collection_db=str(tmp_path / "col.db"),
        osu_data_dir=str(osu),
        developer_mode=False,
    )
    save_settings(bad)
    loaded = load_settings()
    assert loaded.realm_path == ""


def test_load_resets_download_dir_inside_distribution_bundle(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    fake_bundle = tmp_path / "dist" / "OSC"
    fake_bundle.mkdir(parents=True)
    (fake_bundle / "_internal").mkdir()
    (fake_bundle / "OSC.exe").write_bytes(b"x")
    maps = fake_bundle / "maps"
    maps.mkdir()
    bad = AppSettings(
        client="Lazer",
        download_dir=str(maps),
        realm_path="",
        stable_collection_db=str(tmp_path / "col.db"),
        osu_data_dir=str(tmp_path / "osu"),
        developer_mode=False,
    )
    save_settings(bad)
    loaded = load_settings()
    assert loaded.download_dir == base.download_dir


def test_load_sanitizes_pyinstaller_osu_data_dir(isolated_settings) -> None:
    tmp_path, base = isolated_settings
    fake_bundle = tmp_path / "dist" / "OSC"
    fake_bundle.mkdir(parents=True)
    (fake_bundle / "_internal").mkdir()
    (fake_bundle / "OSC.exe").write_bytes(b"x")
    bad = AppSettings(
        client="Lazer",
        download_dir=str(tmp_path / "dl"),
        realm_path="",
        stable_collection_db=str(tmp_path / "col.db"),
        osu_data_dir=str(fake_bundle),
        developer_mode=False,
    )
    save_settings(bad)
    from osc_collector.osu_paths import default_osu_data_dir

    loaded = load_settings()
    assert loaded.osu_data_dir == str(default_osu_data_dir())
