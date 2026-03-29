"""Teste citire OsuLocation din Collection Manager user.config."""

import json
import os
from pathlib import Path

import pytest

from osc_collector.collection_manager_config import (
    osu_location_from_collection_manager,
    osu_location_from_user_config,
)


def test_osu_location_from_user_config_parses_startup_settings(tmp_path: Path) -> None:
    osu = tmp_path / "my_osu_data"
    osu.mkdir()
    payload = json.dumps({"OsuLocation": str(osu)})
    cfg = tmp_path / "user.config"
    cfg.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <userSettings>
    <CollectionManager.App.Winforms.Properties.Settings>
      <setting name="StartupSettings" serializeAs="String">
        <value>{payload}</value>
      </setting>
    </CollectionManager.App.Winforms.Properties.Settings>
  </userSettings>
</configuration>
""",
        encoding="utf-8",
    )
    out = osu_location_from_user_config(cfg)
    assert out is not None
    assert out.resolve() == osu.resolve()


def test_osu_location_from_user_config_accepts_camel_case(tmp_path: Path) -> None:
    osu = tmp_path / "osu_data"
    osu.mkdir()
    payload = json.dumps({"osuLocation": str(osu)})
    cfg = tmp_path / "user.config"
    cfg.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <userSettings>
    <CollectionManager.App.Winforms.Properties.Settings>
      <setting name="StartupSettings" serializeAs="String">
        <value>{payload}</value>
      </setting>
    </CollectionManager.App.Winforms.Properties.Settings>
  </userSettings>
</configuration>
""",
        encoding="utf-8",
    )
    out = osu_location_from_user_config(cfg)
    assert out is not None
    assert out.resolve() == osu.resolve()


def test_osu_location_from_collection_manager_scans_localappdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cm_root = tmp_path / "CollectionManager.App.Win"
    nested = cm_root / "app_Path_xyz" / "1.0.0"
    nested.mkdir(parents=True)
    osu = tmp_path / "from_cm"
    osu.mkdir()
    payload = json.dumps({"OsuLocation": str(osu)})
    (nested / "user.config").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <userSettings>
    <CollectionManager.App.Winforms.Properties.Settings>
      <setting name="StartupSettings" serializeAs="String">
        <value>{payload}</value>
      </setting>
    </CollectionManager.App.Winforms.Properties.Settings>
  </userSettings>
</configuration>
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    found = osu_location_from_collection_manager()
    assert found is not None
    assert found.resolve() == osu.resolve()


def test_osu_location_scans_winforms_named_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exe-ul publicat e CollectionManager.App.WinForms — folderul poate purta acest nume."""
    cm_root = tmp_path / "CollectionManager.App.WinForms"
    nested = cm_root / "app_Url_deadbeef" / "1.0.0.0"
    nested.mkdir(parents=True)
    osu = tmp_path / "lazer_data"
    osu.mkdir()
    payload = json.dumps({"OsuLocation": str(osu)})
    (nested / "user.config").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <userSettings>
    <CollectionManager.App.Winforms.Properties.Settings>
      <setting name="StartupSettings" serializeAs="String">
        <value>{payload}</value>
      </setting>
    </CollectionManager.App.Winforms.Properties.Settings>
  </userSettings>
</configuration>
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    found = osu_location_from_collection_manager()
    assert found is not None
    assert found.resolve() == osu.resolve()
