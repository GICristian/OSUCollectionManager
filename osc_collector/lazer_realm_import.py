"""Rulează OscLazerRealmImport (C# / .NET): import colecții sau listare JSON."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from osc_collector.diagnostic_log import debug as diag_debug
from osc_collector.diagnostic_log import log_realm_tool, warning as diag_warning


def _application_dir() -> Path:
    """Rădăcina aplicației: folderul cu OSC.exe (frozen) sau repo OSC (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _tool_project_dir() -> Path:
    return _application_dir() / "tools" / "OscLazerRealmImport"


def _find_built_exe() -> Path | None:
    side = _application_dir() / "OscLazerRealmImport.exe"
    if side.is_file():
        return side
    base = _tool_project_dir() / "bin"
    if not base.is_dir():
        return None
    for exe in base.rglob("OscLazerRealmImport.exe"):
        if exe.is_file():
            return exe
    return None


def _can_run_tool() -> bool:
    if getattr(sys, "frozen", False):
        return _find_built_exe() is not None
    tool_dir = _tool_project_dir()
    csproj = tool_dir / "OscLazerRealmImport.csproj"
    return _find_built_exe() is not None or (
        csproj.is_file() and _which_dotnet() is not None
    )


def _which_dotnet() -> str | None:
    return shutil.which("dotnet")


def _run_tool(argv: list[str]) -> tuple[int, str, str]:
    """
    argv: argumente după numele executabilului (ex. [\"list\", \"path.realm\"]).
    Returnează (cod, stdout, stderr).
    """
    tool_dir = _tool_project_dir()
    csproj = tool_dir / "OscLazerRealmImport.csproj"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    exe = _find_built_exe()
    dotnet = _which_dotnet()
    diag_debug(
        f"lazer_realm_import._run_tool: argv={argv!r} built_exe={exe} dotnet={dotnet is not None}",
    )

    run_kw: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "creationflags": flags,
    }
    if exe is not None:
        cmd = [str(exe), *argv]
        r = subprocess.run(cmd, cwd=str(exe.parent), **run_kw)
        log_realm_tool(cmd, r.returncode, r.stdout or "", r.stderr or "")
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    if getattr(sys, "frozen", False):
        msg = (
            "Lipsește OscLazerRealmImport.exe (și fișierele din dotnet publish) lângă "
            "OSC.exe. Rulează build_exe.ps1 din nou — se copiază tot folderul publish-out."
        )
        diag_warning(f"realm_tool not run (frozen): {msg}")
        return (127, "", msg)
    if csproj.is_file() and dotnet is not None:
        cmd = [
            dotnet,
            "run",
            "-c",
            "Release",
            "--project",
            str(csproj),
            "--",
            *argv,
        ]
        r = subprocess.run(cmd, cwd=str(tool_dir), **run_kw)
        log_realm_tool(cmd, r.returncode, r.stdout or "", r.stderr or "")
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    msg = (
        "Lipsește OscLazerRealmImport.exe lângă OSC.exe (sau tools/… + dotnet). "
        "Rulează build_exe.ps1 sau dotnet publish."
    )
    diag_warning(f"realm_tool not run: {msg}")
    return (127, "", msg)


def realm_list_collections(realm_path: Path) -> tuple[int, str, str]:
    """Apel ``list`` → JSON pe stdout."""
    from osc_collector.osu_paths import path_is_under_distribution_bundle

    rp = realm_path.resolve()
    if path_is_under_distribution_bundle(rp):
        diag_warning(
            "realm list blocked: .realm sub pachetul aplicației — "
            f"{rp}",
        )
        return (
            1,
            "",
            "Calea Realm nu poate fi în folderul aplicației (lângă OSC.exe). "
            "În Setări pune folderul osu!lazer: %AppData%\\osu (sau Roaming\\osu).",
        )
    return _run_tool(["list", str(rp)])


def realm_list_detail(realm_path: Path) -> tuple[int, str, str]:
    """Apel ``list-detail`` → JSON cu ``collections`` și ``items`` (beatmap-uri)."""
    from osc_collector.osu_paths import path_is_under_distribution_bundle

    rp = realm_path.resolve()
    if path_is_under_distribution_bundle(rp):
        diag_warning(
            "realm list-detail blocked: .realm sub pachetul aplicației — "
            f"{rp}",
        )
        return (
            1,
            "",
            "Calea Realm nu poate fi în folderul aplicației (lângă OSC.exe). "
            "În Setări pune folderul osu!lazer: %AppData%\\osu (sau Roaming\\osu).",
        )
    return _run_tool(["list-detail", str(rp)])


def realm_remove_beatmaps_from_collection(
    realm_path: Path,
    collection_id: str,
    md5_hashes: list[str],
) -> tuple[int, str]:
    """Elimină hash-urile din colecția dată (GUID). Închide osu!lazer înainte."""
    if not _can_run_tool():
        diag_warning("realm remove-beatmaps: utilitar indisponibil (exe/dotnet).")
        return (
            127,
            "Lipsește OscLazerRealmImport.exe sau proiectul C# + dotnet.",
        )
    from osc_collector.osu_paths import path_is_under_distribution_bundle

    if path_is_under_distribution_bundle(realm_path.resolve()):
        diag_warning(
            "realm remove-beatmaps blocked: sub pachetul aplicației — "
            f"{realm_path.resolve()}",
        )
        return (
            1,
            "Calea Realm nu poate fi în folderul aplicației. Setări: folder osu!lazer.",
        )
    lines = "\n".join(h.lower().strip() for h in md5_hashes if h and len(h.strip()) == 32) + "\n"
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(lines)
        tmp.close()
        hf = Path(tmp.name)
        code, out, err = _run_tool(
            [
                "remove-beatmaps",
                str(realm_path.resolve()),
                collection_id.strip(),
                str(hf),
            ]
        )
        if code != 0:
            diag_warning(
                f"realm remove-beatmaps exit={code} collection_id={collection_id.strip()!r}",
            )
        combined = "\n".join(x for x in (out, err) if x).strip()
        return code, combined
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def import_collection(
    realm_path: Path,
    collection_name: str,
    md5_hashes: list[str],
    mode: str,
) -> tuple[int, str]:
    """Import în Realm; returnează (cod, stdout+stderr pentru log)."""
    if not _can_run_tool():
        diag_warning("realm import: utilitar indisponibil (exe/dotnet).")
        return (
            127,
            "Lipsește OscLazerRealmImport.exe sau proiectul C# + dotnet. "
            "Vezi readme/build_exe.ps1.",
        )

    from osc_collector.osu_paths import path_is_under_distribution_bundle

    if path_is_under_distribution_bundle(realm_path.resolve()):
        diag_warning(
            "realm import blocked: sub pachetul aplicației — "
            f"{realm_path.resolve()}",
        )
        return (
            1,
            "Calea Realm nu poate fi în folderul aplicației. Setări: folder "
            "osu!lazer = %AppData%\\osu.",
        )

    lines = "\n".join(h.lower() for h in md5_hashes if h) + "\n"
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    )
    try:
        tmp.write(lines)
        tmp.close()
        hash_file = Path(tmp.name)
        code, out, err = _run_tool(
            [
                str(realm_path.resolve()),
                mode,
                collection_name,
                str(hash_file),
            ]
        )
        if code != 0:
            diag_warning(
                f"realm import exit={code} mode={mode!r} name={collection_name!r}",
            )
        combined = "\n".join(x for x in (out, err) if x).strip()
        return code, combined
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
