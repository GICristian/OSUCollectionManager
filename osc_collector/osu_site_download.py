"""Descărcare .osz de pe osu.ppy.sh cu cookie de sesiune (ca Piotrekol Collection Manager)."""

from __future__ import annotations

import threading
import time


def normalize_osu_web_cookie(raw: str) -> str:
    """Valoare pentru header-ul Cookie; acceptă și text lipit cu prefix „Cookie:”."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.lower().startswith("cookie:"):
        s = s[7:].strip()
    return s


def official_beatmapset_download_url(set_id: int, no_video: bool = True) -> str:
    base = f"https://osu.ppy.sh/beatmapsets/{set_id}/download"
    return f"{base}?noVideo=1" if no_video else base


def official_download_headers(set_id: int, cookie_value: str, base_headers: dict[str, str]) -> dict[str, str]:
    """UA/Accept din mirror_http + Referer + Cookie pentru domeniul oficial."""
    out = dict(base_headers)
    out["Referer"] = f"https://osu.ppy.sh/beatmapsets/{set_id}"
    out["Cookie"] = cookie_value
    return out


class OsuOfficialThrottler:
    """Limitează descărcările reușite pe minut și pe oră (downloadSources.json din CM)."""

    def __init__(self, per_minute: int = 3, per_hour: int = 170) -> None:
        self._per_minute = max(1, per_minute)
        self._per_hour = max(1, per_hour)
        self._completion_times: list[float] = []
        self._lock = threading.Lock()

    def _prune_hour(self, now: float) -> None:
        floor = now - 3600.0
        self._completion_times = [t for t in self._completion_times if t > floor]

    def wait_for_slot(self) -> None:
        """Așteaptă până e permisă o nouă descărcare (înainte de GET)."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune_hour(now)
                minute_floor = now - 60.0
                in_minute = sum(1 for t in self._completion_times if t > minute_floor)
                if in_minute < self._per_minute and len(self._completion_times) < self._per_hour:
                    return
                sleep_s = 1.0
                if in_minute >= self._per_minute:
                    in_win = [t for t in self._completion_times if t > minute_floor]
                    if in_win:
                        oldest = min(in_win)
                        sleep_s = max(0.05, (oldest + 60.0) - now)
                elif len(self._completion_times) >= self._per_hour:
                    oldest = min(self._completion_times)
                    sleep_s = max(0.05, (oldest + 3600.0) - now)
            time.sleep(min(sleep_s, 120.0))

    def register_success(self) -> None:
        """Apelat după ce un .osz oficial a fost scris și validat."""
        with self._lock:
            self._completion_times.append(time.monotonic())
