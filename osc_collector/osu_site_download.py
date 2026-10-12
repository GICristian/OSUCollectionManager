"""Descărcare .osz de pe osu.ppy.sh cu cookie de sesiune (ca Piotrekol Collection Manager)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Aceleași plafoane ca Collection Manager: peste ele osu poate restricționa
# temporar descărcările pe cont. Nu există un mod sigur „nelimitat”.
OFFICIAL_DOWNLOADS_PER_MINUTE = 3
OFFICIAL_DOWNLOADS_PER_HOUR = 170
OFFICIAL_MAX_IN_FLIGHT = 1


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
    """Limitează descărcările reușite pe minut și pe oră (aceleași plafoane ca CM)."""

    def __init__(
        self,
        per_minute: int = OFFICIAL_DOWNLOADS_PER_MINUTE,
        per_hour: int = OFFICIAL_DOWNLOADS_PER_HOUR,
        max_in_flight: int = OFFICIAL_MAX_IN_FLIGHT,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._per_minute = max(1, per_minute)
        self._per_hour = max(1, per_hour)
        self._max_in_flight = max(1, max_in_flight)
        self._completion_times: list[float] = []
        self._inflight = 0
        self._lock = threading.Lock()
        self._now = now_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    def _prune_hour(self, now: float) -> None:
        floor = now - 3600.0
        self._completion_times = [t for t in self._completion_times if t > floor]

    def wait_for_slot(self) -> None:
        """Rezervă un loc și așteaptă până e permis un GET oficial."""
        while True:
            with self._lock:
                now = self._now()
                self._prune_hour(now)
                minute_floor = now - 60.0
                in_minute = sum(1 for t in self._completion_times if t > minute_floor)
                hour_used = len(self._completion_times)
                minute_busy = in_minute + self._inflight >= self._per_minute
                hour_busy = hour_used + self._inflight >= self._per_hour
                if (
                    self._inflight < self._max_in_flight
                    and not minute_busy
                    and not hour_busy
                ):
                    self._inflight += 1
                    return
                sleep_s = 0.2
                if minute_busy:
                    in_win = [t for t in self._completion_times if t > minute_floor]
                    if in_win:
                        oldest = min(in_win)
                        sleep_s = max(0.05, (oldest + 60.0) - now)
                elif hour_busy and self._completion_times:
                    oldest = min(self._completion_times)
                    sleep_s = max(0.05, (oldest + 3600.0) - now)
            self._sleep(min(sleep_s, 30.0))

    def register_success(self) -> None:
        """Apelat după ce un .osz oficial a fost scris și validat."""
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            self._completion_times.append(self._now())

    def release_slot(self) -> None:
        """Eliberă locul rezervat când GET-ul nu s-a terminat cu un .osz valid."""
        with self._lock:
            self._inflight = max(0, self._inflight - 1)


class OfficialDownloadGate:
    """Oprește contul pentru restul job-ului după 401, 403 sau 429."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reason: str | None = None

    def is_stopped(self) -> bool:
        with self._lock:
            return self._reason is not None

    def stop(self, reason: str) -> str | None:
        """Returnează motivul doar la prima oprire, ca log-ul să apară o dată."""
        text = reason.strip() or "răspuns respins de osu.ppy.sh"
        with self._lock:
            if self._reason is not None:
                return None
            self._reason = text
            return text
