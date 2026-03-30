"""Mirror-uri .osz integrate: probă, ordonare „cel mai bun primul”, fallback."""

from __future__ import annotations

import httpx

from osc_collector.mirror_http import mirror_request_headers

# Set vechi, mic, prezent pe majoritatea mirror-urilor (probabă reușită).
PROBE_BEATMAPSET_ID = 75

# (cheie_setări, etichetă UI scurtă, șablon URL cu {id})
# Beatconnect: GET direct returnează .osz (ZIP); catboy/nerinyan pot da 403 sau HTML SPA.
MIRROR_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("beatconnect", "Beatconnect", "https://beatconnect.io/b/{id}"),
    ("catboy", "catboy.best", "https://catboy.best/d/{id}"),
    ("nerinyan", "Nerinyan", "https://nerinyan.moe/d/{id}"),
    ("chimu", "Chimu", "https://api.chimu.moe/v1/download/{id}?n=1"),
)

BUILTIN_MIRROR_TEMPLATES_ORDERED: tuple[str, ...] = tuple(t for _, _, t in MIRROR_ENTRIES)

_PRESET_TO_TEMPLATE: dict[str, str] = {k: t for k, _, t in MIRROR_ENTRIES}

ALL_MIRROR_PRESET_KEYS: frozenset[str] = frozenset(
    {"auto", "custom", *_PRESET_TO_TEMPLATE.keys()},
)


def beatmap_url_from_template(template: str, set_id: int) -> str:
    t = template.strip()
    if "{id}" in t:
        return t.replace("{id}", str(set_id))
    return t.rstrip("/") + "/" + str(set_id)


def probe_mirror(client: httpx.Client, template: str, set_id: int = PROBE_BEATMAPSET_ID) -> bool:
    """True dacă primii octeți par a fi .osz (ZIP) sau răspuns HTTP util."""
    url = beatmap_url_from_template(template, set_id)
    try:
        with client.stream(
            "GET",
            url,
            headers=mirror_request_headers(url),
            timeout=httpx.Timeout(12.0, read=18.0),
            follow_redirects=True,
        ) as r:
            if r.status_code >= 400:
                return False
            head = b""
            for chunk in r.iter_bytes(8192):
                head += chunk
                if len(head) >= 12:
                    break
            if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
                return True
            s = head.lstrip()[:400]
            if s.startswith(b"{") and b"error" in s.lower():
                return False
            if s.startswith(b"<") or s.startswith(b"<!"):
                return False
            return len(head) >= 256
    except (httpx.HTTPError, OSError):
        return False


def rank_builtin_mirrors(client: httpx.Client) -> list[str]:
    """Mirror-uri care trec proba primele; restul la coadă (fallback)."""
    templates = [t for _, _, t in MIRROR_ENTRIES]
    ok_first: list[str] = []
    rest: list[str] = []
    for tmpl in templates:
        if probe_mirror(client, tmpl):
            ok_first.append(tmpl)
        else:
            rest.append(tmpl)
    return ok_first + rest


def mirror_templates_for_job(
    preset: str,
    custom_template: str,
    client: httpx.Client,
) -> list[str]:
    """
    Lista ordonată de șabloane folosită la descărcare (încercare pe rând).

    * auto — proba toate, reușitele primele
    * catboy / nerinyan / … — un singur mirror
    * custom — doar șablonul din setări; dacă e gol, revine la auto
    """
    p = (preset or "auto").strip().lower()
    if p == "custom":
        ct = (custom_template or "").strip()
        if ct:
            return [ct]
        return list(BUILTIN_MIRROR_TEMPLATES_ORDERED)
    if p == "auto":
        # Fără probă secvențială la start: economisește zeci de secunde; fallback pe rând oricum.
        return list(BUILTIN_MIRROR_TEMPLATES_ORDERED)
    single = _PRESET_TO_TEMPLATE.get(p)
    if single:
        return [single]
    return rank_builtin_mirrors(client)


def mirror_preset_labels() -> tuple[tuple[str, str], ...]:
    """(cheie, etichetă UI) pentru meniu."""
    rows: list[tuple[str, str]] = [("auto", "Automat (probă + fallback)")]
    for key, label, _ in MIRROR_ENTRIES:
        rows.append((key, label))
    rows.append(("custom", "URL personalizat…"))
    return tuple(rows)
