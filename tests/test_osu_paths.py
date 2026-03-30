"""Teste pentru detectarea fișierului Realm al osu!lazer."""

import sys
import tempfile
from pathlib import Path

from osc_collector.osu_paths import (
    default_osu_data_dir,
    discover_lazer_realm_file,
    effective_lazer_realm_path,
    find_realm_files_under_osu,
    is_dir_writable,
    is_distribution_bundle_dir,
    looks_like_osu_data_dir,
    normalize_osu_data_dir,
    pick_best_realm_candidate,
    resolve_existing_lazer_realm,
)


def test_looks_like_osu_data_dir_versioned_realm_only() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client_51.realm").write_bytes(b"x")
        assert looks_like_osu_data_dir(root) is True


def test_looks_like_osu_data_dir_empty_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        assert looks_like_osu_data_dir(Path(d)) is False


def test_is_dir_writable_creates_and_probe() -> None:
    with tempfile.TemporaryDirectory() as d:
        sub = Path(d) / "nested" / "dl"
        assert is_dir_writable(sub) is True


def test_discover_prefers_highest_versioned_realm() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client.realm").write_bytes(b"x")
        (root / "client_40.realm").write_bytes(b"x")
        (root / "client_51.realm").write_bytes(b"x")
        assert discover_lazer_realm_file(root).name.lower() == "client_51.realm"


def test_discover_plain_when_only_plain() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client.realm").write_bytes(b"x")
        assert discover_lazer_realm_file(root).name.lower() == "client.realm"


def test_discover_missing_dir_returns_default_name() -> None:
    root = Path("/nonexistent/osu/path/that/does/not/exist")
    p = discover_lazer_realm_file(root)
    assert p.name == "client.realm"


def test_find_realm_skips_files_subtree() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client_9.realm").write_bytes(b"x")
        deep = root / "files" / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "noise.realm").write_bytes(b"x")
        found = find_realm_files_under_osu(root)
        assert len(found) == 1


def test_find_realm_skips_internal_subtree() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client_1.realm").write_bytes(b"x")
        internal = root / "_internal"
        internal.mkdir()
        (internal / "noise.realm").write_bytes(b"x")
        found = find_realm_files_under_osu(root)
        assert len(found) == 1


def test_resolve_finds_nested_realm() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        sub = root / "client.realm.management"
        sub.mkdir()
        (sub / "client_12.realm").write_bytes(b"x")
        assert resolve_existing_lazer_realm(root) is not None


def test_pick_best_prefers_highest_version() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client_1.realm").write_bytes(b"x")
        (root / "client_99.realm").write_bytes(b"x")
        paths = find_realm_files_under_osu(root)
        assert pick_best_realm_candidate(paths).name.lower() == "client_99.realm"


def test_effective_ignores_bad_hint_uses_osu_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "client_42.realm").write_bytes(b"x")
        bogus = Path(d) / "not_osu"
        bogus.mkdir()
        eff = effective_lazer_realm_path(root, str(bogus))
        assert eff is not None
        assert eff.name.lower() == "client_42.realm"


def test_effective_accepts_valid_absolute_realm() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        realm = root / "client_7.realm"
        realm.write_bytes(b"x")
        eff = effective_lazer_realm_path(root, str(realm))
        assert eff == realm.resolve()


def test_normalize_identity_when_not_frozen() -> None:
    p = Path(tempfile.gettempdir()) / "some_osu"
    assert normalize_osu_data_dir(p) == p


def test_is_distribution_bundle_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "OSC"
        root.mkdir()
        assert is_distribution_bundle_dir(root) is False
        (root / "_internal").mkdir()
        assert is_distribution_bundle_dir(root) is False
        (root / "OSC.exe").write_bytes(b"x")
        assert is_distribution_bundle_dir(root) is True


def test_normalize_replaces_pyinstaller_dist_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "dist" / "OSC"
        root.mkdir(parents=True)
        (root / "_internal").mkdir()
        (root / "OSC.exe").write_bytes(b"x")
        assert normalize_osu_data_dir(root) == default_osu_data_dir()


def test_effective_falls_back_when_bundle_has_no_realm(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as d:
        bundle = Path(d) / "OSC"
        bundle.mkdir()
        (bundle / "_internal").mkdir()
        (bundle / "OSC.exe").write_bytes(b"x")
        real_osu = Path(d) / "real_osu"
        real_osu.mkdir()
        (real_osu / "client_3.realm").write_bytes(b"x")
        monkeypatch.setattr(
            "osc_collector.osu_paths.default_osu_data_dir",
            lambda: real_osu,
        )
        eff = effective_lazer_realm_path(bundle, str(bundle / "nope.realm"))
        assert eff is not None
        assert eff.name.lower() == "client_3.realm"


def test_normalize_replaces_exe_folder_when_frozen(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as d:
        exe_dir = Path(d) / "dist" / "OSC"
        exe_dir.mkdir(parents=True)
        fake_exe = exe_dir / "OSC.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        assert normalize_osu_data_dir(exe_dir) == default_osu_data_dir()


def test_normalize_any_path_under_frozen_exe_dir_even_without_internal(
    monkeypatch,
) -> None:
    """Fără folder _internal, tot arborele de sub exe trebuie respins ca date osu."""
    with tempfile.TemporaryDirectory() as d:
        exe_dir = Path(d) / "dist" / "Osc"
        exe_dir.mkdir(parents=True)
        fake_exe = exe_dir / "OSC.exe"
        fake_exe.write_bytes(b"")
        (exe_dir / "client.realm").write_bytes(b"x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        assert normalize_osu_data_dir(exe_dir) == default_osu_data_dir()
        assert normalize_osu_data_dir(exe_dir / "client.realm") == default_osu_data_dir()
