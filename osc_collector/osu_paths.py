"""Căi implicite pentru instalări osu! pe Windows."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def default_osu_data_dir() -> Path:
    """Folder implicit de date osu!lazer pe Windows (%AppData%\\osu)."""
    home = Path.home()
    roaming = Path(os.environ.get("APPDATA") or str(home / "AppData" / "Roaming"))
    return roaming / "osu"


def looks_like_osu_data_dir(path: Path) -> bool:
    """
    True dacă folderul pare a fi date osu! (stable sau lazer).

    Collection Manager verifică doar ``client.realm`` literal; lazer modern poate
    avea doar ``client_<N>.realm``. Aliniem OSC la ambele cazuri.
    """
    if not path.is_dir():
        return False
    try:
        if (path / "osu!.db").is_file():
            return True
        if (path / "collection.db").is_file():
            return True
        if (path / "client.realm").is_file():
            return True
        for candidate in path.glob("client_*.realm"):
            if candidate.is_file():
                return True
    except OSError:
        return False
    return False


def is_distribution_bundle_dir(d: Path) -> bool:
    """
    Folder tip ``dist/OSC`` după PyInstaller: ``_internal/`` + ``OSC.exe`` sau
    (frozen) același folder ca părintele executabilului (inclusiv exe redenumit).
    """
    try:
        if not d.is_dir():
            return False
    except OSError:
        return False
    if not (d / "_internal").is_dir():
        return False
    if (d / "OSC.exe").is_file():
        return True
    if getattr(sys, "frozen", False):
        try:
            return d.resolve() == Path(sys.executable).resolve().parent
        except OSError:
            return False
    return False


def frozen_install_dir() -> Path | None:
    """
    Folderul care conține OSC.exe (onedir / frozen).

    Orice ``.realm`` sau folder „osu!” **sub acest path** e greșit: nu sunt
    datele lazer. Nu cerem ``_internal`` — unele copii partiale ale pachetului
    tot au exe-ul acolo și altfel scăpam filtrarea.
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except OSError:
        return None


def path_is_under_or_equal(path: Path, ancestor: Path) -> bool:
    """True dacă ``path`` e același folder sau subfolder al ``ancestor``."""
    try:
        a = ancestor.resolve()
        p = path.resolve()
    except OSError:
        return False
    if p == a:
        return True
    try:
        p.relative_to(a)
        return True
    except ValueError:
        return False


def path_is_under_distribution_bundle(path: Path) -> bool:
    """True dacă ``path`` e în interiorul unui folder-bundle PyInstaller."""
    inst = frozen_install_dir()
    if inst is not None and path_is_under_or_equal(path, inst):
        return True
    try:
        p = path.resolve()
    except OSError:
        return False
    for parent in [p, *p.parents]:
        if is_distribution_bundle_dir(parent):
            return True
    return False


def normalize_osu_data_dir(osu_data_dir: Path) -> Path:
    """
    Înlocuiește căi greșite: folderul exe-ului (frozen) sau folderul build PyInstaller
    (``dist/OSC``) cu datele reale osu! din AppData.
    """
    root = Path(osu_data_dir)
    try:
        r = root.resolve()
    except OSError:
        return default_osu_data_dir()
    inst = frozen_install_dir()
    if inst is not None and path_is_under_or_equal(r, inst):
        return default_osu_data_dir()
    if is_distribution_bundle_dir(root):
        return default_osu_data_dir()
    return root

_CLIENT_VERSIONED = re.compile(r"^client_(\d+)\.realm$", re.IGNORECASE)


def discover_lazer_realm_file(osu_data_dir: Path) -> Path:
    """
    Returnează fișierul Realm folosit în practică de osu!lazer.

    Jocul pornește de la ``client.realm``, dar îl redenumește în
    ``client_<schema_version>.realm`` (ex. ``client_51.realm``). Colecțiile
    trebuie scrise în acel fișier, nu într-un ``client.realm`` vechi lăsat
    după migrare.
    """
    if not osu_data_dir.is_dir():
        return osu_data_dir / "client.realm"

    best_version = -1
    best: Path | None = None

    plain = osu_data_dir / "client.realm"
    if plain.is_file():
        best_version = 0
        best = plain

    for candidate in osu_data_dir.glob("client_*.realm"):
        match = _CLIENT_VERSIONED.fullmatch(candidate.name)
        if match is None:
            continue
        version = int(match.group(1))
        if version > best_version:
            best_version = version
            best = candidate

    return best if best is not None else osu_data_dir / "client.realm"


def find_realm_files_under_osu(osu_data_dir: Path, max_depth: int = 8) -> list[Path]:
    """
    Caută *.realm sub folderul de date osu!, evitând arbori mari (beatmap-uri).

    Unele instalări sau versiuni pot plasa fișiere auxiliare lângă
    ``client.realm.management``; evităm ``files/`` și ``cache/``.
    """
    if not osu_data_dir.is_dir():
        return []
    out: list[Path] = []
    for path in osu_data_dir.rglob("*.realm"):
        try:
            rel = path.relative_to(osu_data_dir)
        except ValueError:
            continue
        lowered = {p.lower() for p in rel.parts}
        if "files" in lowered or "cache" in lowered or "_internal" in lowered:
            continue
        if len(rel.parts) > max_depth:
            continue
        out.append(path)
    return out


def pick_best_realm_candidate(paths: list[Path]) -> Path | None:
    """Alege client_<N>.realm cu N maxim, altfel primul path sortat după nume."""
    if not paths:
        return None
    best_ver = -1
    best: Path | None = None
    for p in paths:
        m = _CLIENT_VERSIONED.fullmatch(p.name)
        if m is not None:
            v = int(m.group(1))
            if v > best_ver:
                best_ver = v
                best = p
    if best is not None:
        return best
    plain = [p for p in paths if p.name.lower() == "client.realm"]
    if plain:
        return plain[0]
    return sorted(paths, key=lambda x: x.name.lower())[0]


def resolve_existing_lazer_realm(osu_data_dir: Path) -> Path | None:
    """Prima cale preferată care există pe disc, sau None."""
    primary = discover_lazer_realm_file(osu_data_dir)
    if primary.is_file():
        return primary
    found = find_realm_files_under_osu(osu_data_dir)
    return pick_best_realm_candidate(found)


def _realm_from_hint_and_scan(
    osu_data_dir: Path,
    realm_path_hint: str | Path,
) -> Path | None:
    """Caută după hint apoi sub ``osu_data_dir`` (deja normalizat)."""
    raw = Path(realm_path_hint).expanduser() if realm_path_hint else Path()
    if raw.is_absolute():
        if raw.is_file() and raw.suffix.lower() == ".realm":
            if not path_is_under_distribution_bundle(raw):
                return raw.resolve()
    else:
        rel = raw.as_posix().strip()
        if rel:
            cwd = Path.cwd()
            inst = frozen_install_dir()
            search_bases: list[Path] = [osu_data_dir]
            if inst is None or not path_is_under_or_equal(cwd, inst):
                search_bases.append(cwd)
            for base in search_bases:
                try:
                    cand = (base / raw).resolve()
                except OSError:
                    continue
                if cand.is_file() and cand.suffix.lower() == ".realm":
                    if not path_is_under_distribution_bundle(cand):
                        return cand

    if not osu_data_dir.is_dir():
        return None
    resolved = resolve_existing_lazer_realm(osu_data_dir)
    if resolved is not None:
        out = resolved.resolve()
        if not path_is_under_distribution_bundle(out):
            return out
    candidate = discover_lazer_realm_file(osu_data_dir)
    if candidate.is_file():
        out = candidate.resolve()
        if not path_is_under_distribution_bundle(out):
            return out
    return None


def effective_lazer_realm_path(
    osu_data_dir: Path,
    realm_path_hint: str | Path,
) -> Path | None:
    """
    Calea reală către client.realm / client_*.realm.

    Ignoră hint-uri / scanări sub folderul aplicației PyInstaller; folosește
    ``%AppData%\\osu`` dacă folderul de date din setări e greșit.
    """
    base = normalize_osu_data_dir(Path(osu_data_dir))
    eff = _realm_from_hint_and_scan(base, realm_path_hint)
    if eff is not None:
        return eff
    fallback = default_osu_data_dir()
    try:
        if base.resolve() == fallback.resolve():
            return None
    except OSError:
        pass
    return _realm_from_hint_and_scan(fallback, "")
