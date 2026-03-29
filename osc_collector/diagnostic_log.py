"""Log diagnostic pe disc (append-only), thread-safe, pentru depanare când UI-ul nu arată eroarea."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_MAX_ROTATE_BYTES = 4 * 1024 * 1024
_MAX_CHUNK = 8000
_verbose: bool = False


def verbose_from_environment() -> bool:
    """Activează log DEBUG dacă ``OSC_DEBUG_LOG`` este 1/true/yes/on."""
    v = (os.environ.get("OSC_DEBUG_LOG") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def set_verbose(enabled: bool) -> None:
    """Pornește sau oprește liniile ``[DEBUG]`` (în plus față de INFO/WARN/ERROR)."""
    global _verbose
    _verbose = bool(enabled)


def is_verbose() -> bool:
    return _verbose


def debug(message: str) -> None:
    """Log detaliat; scris doar când verbose e activ (setări sau ``OSC_DEBUG_LOG``)."""
    if not _verbose:
        return
    log("DEBUG", message)


def log_path() -> Path:
    """Dev: rădăcina repo OSC. Frozen: folderul cu OSC.exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "OSC_diagnostic.log"
    return Path(__file__).resolve().parent.parent / "OSC_diagnostic.log"


def _maybe_rotate() -> None:
    path = log_path()
    try:
        if path.is_file() and path.stat().st_size > _MAX_ROTATE_BYTES:
            prev = path.with_suffix(".log.prev")
            try:
                if prev.is_file():
                    prev.unlink()
            except OSError:
                pass
            path.rename(prev)
    except OSError:
        pass


def truncate(text: str, max_len: int = _MAX_CHUNK) -> str:
    t = text.replace("\r\n", "\n").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 24] + "\n… [truncat diagnostic]"


def _write_line(line: str) -> None:
    with _LOCK:
        _maybe_rotate()
        try:
            p = log_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8", errors="replace") as f:
                f.write(line)
                if not line.endswith("\n"):
                    f.write("\n")
        except OSError:
            pass


def log(level: str, message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for raw in message.replace("\r\n", "\n").split("\n"):
        line = f"{ts} [{level}] {raw}"
        if len(line) > 4000:
            line = line[:3980] + "…"
        _write_line(line)


def info(message: str) -> None:
    log("INFO", message)


def warning(message: str) -> None:
    log("WARN", message)


def error(message: str) -> None:
    log("ERROR", message)


def log_exception(context: str, exc: BaseException | None = None) -> None:
    if exc is not None:
        error(f"{context}: {exc!s}")
    error(f"{context}\n{traceback.format_exc()}")


def log_session_start(version: str, frozen: bool, build_stamp: str) -> None:
    info(
        "=== OSC session start ===\n"
        f"version={version} frozen={frozen} build_stamp={build_stamp or '(none)'}\n"
        f"log_file={log_path()}\n"
        f"diagnostic_DEBUG_lines={'on' if _verbose else 'off'} "
        f"(Setări: log detaliat sau env OSC_DEBUG_LOG)",
    )


def log_realm_tool(argv: list[str], code: int, stdout: str, stderr: str) -> None:
    """Înregistrează fiecare apel la OscLazerRealmImport / dotnet run (fără a copia JSON-uri uriașe la succes)."""
    cmd = " ".join(str(a) for a in argv)
    if len(cmd) > 600:
        cmd = cmd[:580] + "…"
    out_l = len(stdout or "")
    err_l = len(stderr or "")
    info(f"realm_tool exit={code} cmd={cmd}\nstdout_bytes={out_l} stderr_bytes={err_l}")
    es = (stderr or "").strip()
    if es:
        info(f"realm_tool stderr:\n{truncate(stderr)}")
    if code != 0:
        os_ = (stdout or "").strip()
        if os_:
            info(f"realm_tool stdout (failure):\n{truncate(stdout)}")
    elif out_l > 200_000:
        info("realm_tool stdout: mare (>200k); omis din log la succes.")
    elif _verbose and out_l:
        debug(f"realm_tool stdout preview ({out_l} bytes):\n{truncate(stdout, 6000)}")
