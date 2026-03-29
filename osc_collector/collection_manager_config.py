"""Citește folderul osu! setat în Collection Manager (user.config)."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def _collection_manager_config_roots() -> list[Path]:
    """
    Rădăcini sub %LocalAppData% unde WinForms poate salva user.config.

    Versiunile vechi foloseau ``CollectionManager.App.Win``; proiectul curent
    publică ``CollectionManager.App.WinForms.exe`` — numele folderului pe disc
    poate diferi. Scanăm și orice subdirector LocalAppData care conține
    „CollectionManager” în nume (ex. ``Company_Product_Url_hash``).
    """
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    if not base.is_dir():
        return []
    roots: list[Path] = []
    for name in (
        "CollectionManager.App.Win",
        "CollectionManager.App.WinForms",
        "CollectionManagerApp",
    ):
        p = base / name
        if p.is_dir():
            roots.append(p)
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            if "collectionmanager" not in child.name.lower():
                continue
            if child not in roots:
                roots.append(child)
    except OSError:
        pass
    return roots


def iter_collection_manager_user_configs() -> list[Path]:
    """Toate user.config găsite, cele mai noi primele (mtime)."""
    seen: set[Path] = set()
    found: list[Path] = []
    for root in _collection_manager_config_roots():
        try:
            for p in root.rglob("user.config"):
                try:
                    key = p.resolve()
                except OSError:
                    key = p
                if key in seen:
                    continue
                seen.add(key)
                found.append(p)
        except OSError:
            continue
    try:
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        pass
    return found


def osu_location_from_user_config(config_path: Path) -> Path | None:
    """Extrage ``OsuLocation`` din JSON-ul ``StartupSettings``."""
    try:
        tree = ET.parse(config_path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()
    for setting in root.iter("setting"):
        if setting.get("name") != "StartupSettings":
            continue
        val_el = setting.find("value")
        if val_el is None or not (val_el.text or "").strip():
            return None
        try:
            data = json.loads(val_el.text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("OsuLocation") or data.get("osuLocation")
        if not raw or not isinstance(raw, str):
            return None
        p = Path(raw.strip())
        try:
            if p.is_dir():
                return p.resolve()
        except OSError:
            return None
    return None


def osu_location_from_collection_manager() -> Path | None:
    """
    Folderul de date osu! din setările Collection Manager (dacă există).

    Setările user-scoped WinForms stau sub ``%LocalAppData%`` în subfoldere care
    depind de versiunea CM (ex. ``CollectionManager.App.Win`` sau nume derivat
    din ``CollectionManager.App.WinForms``).
    """
    for cfg in iter_collection_manager_user_configs():
        loc = osu_location_from_user_config(cfg)
        if loc is not None:
            return loc
    return None
