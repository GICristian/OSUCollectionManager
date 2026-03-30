"""Interfață principală OSC — sidebar, import, setări."""

from __future__ import annotations

import os
import queue
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import traceback
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from collections.abc import Callable
from pathlib import Path

import customtkinter as ctk
import httpx

from osc_collector.diagnostic_log import (
    debug as dbg,
    error as diag_error,
    info as diag_info,
    is_verbose,
    log_exception as diag_log_exception,
    log_session_start,
    set_verbose,
    verbose_from_environment,
    warning as diag_warning,
)
from osc_collector.collection_db import (
    build_collection_db,
    merge_collection,
    parse_collection_db,
)
from osc_collector.builtin_mirrors import mirror_templates_for_job
from osc_collector.mirror_net import (
    exclude_templates_for_failed_dns_hosts,
    mirror_dns_preflight,
    short_download_error_message,
)
from osc_collector.download_maps import (
    AllMirrorsFailed,
    DEFAULT_PARALLEL_DOWNLOADS,
    create_mirror_client,
    download_beatmapset_with_fallback,
    existing_valid_set_ids,
    thread_local_download_client,
    unique_beatmapset_ids_preserve_order,
)
from osc_collector.osu_site_download import normalize_osu_web_cookie
from osc_collector.lazer_realm_import import (
    import_collection as import_lazer_realm,
    realm_remove_beatmaps_from_collection,
)
from osc_collector.library_service import list_lazer_collections_detail, list_stable_collections
from osc_collector.osu_paths import (
    effective_lazer_realm_path,
    find_realm_files_under_osu,
    is_dir_writable,
    normalize_osu_data_dir,
    path_is_under_distribution_bundle,
    pick_best_realm_candidate,
    try_clear_readonly_windows,
)
from osc_collector.osuc_api import CollectionData, fetch_collection, parse_collection_id
from osc_collector.settings_dialog import SettingsDialog
from osc_collector.settings_store import AppSettings, load_settings, save_settings
from osc_collector.version import __version__
from osc_collector import ui_theme as T

try:
    from osc_collector._build_stamp import BUILD_STAMP
except ImportError:
    BUILD_STAMP = ""

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Limită rânduri Lazer în sidebar (fiecare rând = mai multe widget-uri CustomTkinter).
_LAZER_UI_ROW_CAP = 500


def _mirror_job_log_line(
    preset: str,
    chain_len: int,
    *,
    osu_official_cookie: bool = False,
) -> str:
    prefix = ""
    if osu_official_cookie:
        prefix = "Întâi osu.ppy.sh (cookie salvat), apoi "
    if preset == "auto":
        return (
            f"{prefix}mirror: automat — {chain_len} surse (ordonate după probă); "
            "la eșec trece la următoarea."
        )
    if preset == "custom":
        return f"{prefix}mirror: URL personalizat (o sursă)."
    return f"{prefix}mirror: {preset!r} (o sursă)."


def _theme_hex(color: tuple[str, str] | str) -> str:
    return color[0] if isinstance(color, tuple) else color


def _lazer_items_in_library_only(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """Doar beatmap-uri rezolvate în Realm (fără ``missing``)."""
    out: list[dict[str, object]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if bool(it.get("missing")):
            continue
        md5 = str(it.get("md5", "")).lower()
        if len(md5) != 32:
            continue
        out.append(it)
    return out


def _main_window_title() -> str:
    label = f"OSC — osu!Collector v{__version__}"
    if getattr(sys, "frozen", False):
        if BUILD_STAMP:
            return f"{label} · build {BUILD_STAMP}"
        return f"{label} · exe"
    return f"{label} · dev"


class OscApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        set_verbose(self.settings.diagnostic_verbose or verbose_from_environment())
        self.title(_main_window_title())
        self.geometry("1360x800")
        self.minsize(1100, 700)
        self.configure(fg_color=T.BG_APP)

        self._loaded: CollectionData | None = None
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._sidebar_btns: list[ctk.CTkButton] = []
        self._lazer_expanded: set[str] = set()
        self._lazer_check_vars: dict[tuple[str, str], tk.BooleanVar] = {}
        self._lazer_last_collections: list[dict[str, object]] = []
        self._lazer_sidebar_generation = 0
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._initial_load_complete = False
        self._lazer_shift_anchor: dict[str, int] = {}

        log_session_start(__version__, getattr(sys, "frozen", False), BUILD_STAMP)
        dbg(
            "OscApp.__init__: "
            f"osu_data_dir={self.settings.osu_data_dir!r} realm_path={self.settings.realm_path!r} "
            f"stable_db={self.settings.stable_collection_db!r} "
            f"download_dir={self.settings.download_dir!r} client={self.settings.client!r} "
            f"developer_mode={self.settings.developer_mode} "
            f"diagnostic_verbose={self.settings.diagnostic_verbose}",
        )

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self._build_loading_overlay()
        self._show_import_view()
        self._enqueue_main(self._refresh_sidebar)
        self.after(0, self._poll_ui_queue)

    def _safe_progress_set(self, v: float) -> None:
        try:
            p = getattr(self, "progress", None)
            if p is not None and p.winfo_exists():
                p.set(min(1.0, max(0.0, v)))
        except tk.TclError:
            pass

    def _enqueue_main(self, fn: Callable[[], None]) -> None:
        """Rulează pe firul Tk; nu folosi self.after din thread-uri de fundal (Windows)."""
        if is_verbose():
            dbg(
                "UI enqueue → main thread: "
                f"{getattr(fn, '__name__', None) or type(fn).__name__}",
            )
        self._ui_queue.put(fn)

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    if is_verbose():
                        dbg(
                            "UI queue run: "
                            f"{getattr(fn, '__name__', None) or type(fn).__name__}",
                        )
                    fn()
                except Exception:
                    diag_log_exception("Callback UI (coadă principală Tk)")
        except queue.Empty:
            pass
        self.after(30, self._poll_ui_queue)

    def _build_loading_overlay(self) -> None:
        """Ecran de așteptare peste tot window-ul până la primul refresh sidebar reușit."""
        self._loading_overlay = ctk.CTkFrame(self, fg_color=T.BG_APP, corner_radius=0)
        self._loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        card = ctk.CTkFrame(
            self._loading_overlay,
            fg_color=T.BG_CARD,
            corner_radius=16,
            border_width=1,
            border_color=T.TEXT_MUTED,
        )
        card.place(relx=0.5, rely=0.42, anchor="center")
        pad = T.PAD
        ctk.CTkLabel(
            card,
            text="OSC",
            font=("Segoe UI Semibold", 32),
            text_color=T.TEXT,
        ).pack(padx=pad * 2, pady=(pad * 2, 6))
        ctk.CTkLabel(
            card,
            text="Se încarcă colecțiile și interfața…",
            font=T.FONT_BODY,
            text_color=T.TEXT_MUTED,
        ).pack(padx=pad * 2, pady=(0, pad))
        self._loading_progress = ctk.CTkProgressBar(
            card,
            width=340,
            height=14,
            mode="indeterminate",
            progress_color=T.ACCENT,
            fg_color=T.BG_INPUT,
        )
        self._loading_progress.pack(padx=pad * 2, pady=(0, pad * 2))
        self._loading_progress.start()
        ctk.CTkLabel(
            card,
            text="Poate dura câteva secunde (citire Realm / collection.db).",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).pack(padx=pad * 2, pady=(0, pad * 2))
        self._loading_overlay.lift()

    def _dismiss_loading_overlay(self) -> None:
        if self._initial_load_complete:
            return
        self._initial_load_complete = True
        try:
            if hasattr(self, "_loading_progress"):
                self._loading_progress.stop()
        except tk.TclError:
            pass
        try:
            if hasattr(self, "_loading_overlay"):
                self._loading_overlay.place_forget()
        except tk.TclError:
            pass

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=T.BG_SIDEBAR, corner_radius=0, height=64)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=(T.PAD, 0), pady=12)
        ctk.CTkLabel(
            left,
            text="OSC",
            font=T.FONT_TITLE,
            text_color=T.TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            left,
            text="osu!Collector → colecții & beatmap-uri",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).pack(anchor="w")

        self.chk_developer = ctk.CTkCheckBox(
            bar,
            text="Mod avansat (developer)",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            fg_color=T.BG_INPUT,
            hover_color=T.ACCENT,
            command=self._on_developer_mode_toggle,
        )
        self.chk_developer.grid(row=0, column=2, sticky="e", padx=(0, 4), pady=12)
        if self.settings.developer_mode:
            self.chk_developer.select()

        ctk.CTkButton(
            bar,
            text="Setări",
            width=100,
            height=36,
            fg_color=T.BG_INPUT,
            hover_color=T.ACCENT,
            command=self._open_settings,
        ).grid(row=0, column=3, sticky="e", padx=T.PAD, pady=12)

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=0, minsize=T.SIDEBAR_WIDTH)
        body.grid_columnconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(
            body,
            width=T.SIDEBAR_WIDTH,
            fg_color=T.BG_SIDEBAR,
            corner_radius=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_propagate(False)
        self.sidebar.configure(width=T.SIDEBAR_WIDTH)

        ctk.CTkLabel(
            self.sidebar,
            text="Colecțiile tale",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).pack(anchor="w", padx=T.PAD, pady=(T.PAD, 4))

        ctk.CTkButton(
            self.sidebar,
            text="+ Import nou",
            height=40,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            font=("Segoe UI Semibold", 14),
            command=self._show_import_view,
        ).pack(fill="x", padx=T.PAD_SM, pady=(0, 8))

        ctk.CTkButton(
            self.sidebar,
            text="Reîmprospătează lista",
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=T.TEXT_MUTED,
            font=T.FONT_SMALL,
            command=self._refresh_sidebar,
        ).pack(fill="x", padx=T.PAD_SM, pady=(0, 6))

        self.btn_load_lazer = ctk.CTkButton(
            self.sidebar,
            text="Încarcă din osu!lazer",
            height=34,
            fg_color=T.BG_INPUT,
            hover_color=T.ACCENT,
            border_width=1,
            border_color=T.ACCENT,
            font=("Segoe UI Semibold", 12),
            command=self._on_load_lazer_clicked,
        )
        self.btn_load_lazer.pack(fill="x", padx=T.PAD_SM, pady=(0, 12))

        self.sidebar_scroll = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=0,
        )
        self.sidebar_scroll.pack(fill="both", expand=True, padx=T.PAD_SM, pady=(0, T.PAD))

        self.main_area = ctk.CTkFrame(body, fg_color=T.BG_APP, corner_radius=0)
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        self.main_scroll = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent",
        )
        self.main_scroll.grid(row=0, column=0, sticky="nsew", padx=T.PAD, pady=T.PAD)

    def _clear_main(self) -> None:
        for w in self.main_scroll.winfo_children():
            w.destroy()

    def _show_import_view(self) -> None:
        dbg("UI: _show_import_view")
        self._clear_main()
        if self.settings.developer_mode:
            self._build_import_form(self.main_scroll)
        else:
            self._build_simple_wizard(self.main_scroll)

    def _on_developer_mode_toggle(self) -> None:
        dbg("UI: _on_developer_mode_toggle")
        self.settings.developer_mode = bool(self.chk_developer.get())
        save_settings(self.settings)
        self._show_import_view()

    def _build_import_form(self, parent: ctk.CTkScrollableFrame) -> None:
        self.simple_btn_download = None
        self.simple_btn_import = None
        card = ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        card.pack(fill="x", pady=(0, T.PAD))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="Import din osu!Collector",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 4))

        ctk.CTkLabel(
            card,
            text="Lipește URL-ul sau doar ID-ul numeric al colecției, apoi Încarcă.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 12))

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.grid(row=2, column=0, sticky="ew", padx=T.PAD, pady=(0, 8))
        row2.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            row2,
            height=42,
            placeholder_text="https://osucollector.com/collections/11791/… sau 11791",
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            row2,
            text="Încarcă",
            width=100,
            height=42,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            command=self._on_fetch,
        ).grid(row=0, column=1)

        self.status = ctk.CTkLabel(
            card,
            text="Gata.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        )
        self.status.grid(row=3, column=0, sticky="w", padx=T.PAD, pady=(0, 8))

        self.info_label = ctk.CTkLabel(
            card,
            text="",
            font=T.FONT_BODY,
            text_color=T.TEXT,
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.info_label.grid(row=4, column=0, sticky="ew", padx=T.PAD, pady=(0, 12))

        ctk.CTkLabel(
            card,
            text="Nume colecție în osu (opțional)",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=5, column=0, sticky="w", padx=T.PAD, pady=(0, 4))
        self.collection_name_entry = ctk.CTkEntry(
            card,
            height=38,
            placeholder_text="gol = numele de pe osu!Collector",
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.collection_name_entry.grid(row=6, column=0, sticky="ew", padx=T.PAD, pady=(0, 16))

        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=7, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts, text="Client țintă", font=T.FONT_SMALL, text_color=T.TEXT_MUTED).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self.client_target = ctk.CTkSegmentedButton(
            opts,
            values=["Lazer", "Stable"],
            command=self._on_client_change,
        )
        self.client_target.grid(row=0, column=1, sticky="w", pady=(0, 4))

        self.chk_download = ctk.CTkCheckBox(
            opts,
            text="Descarcă beatmap set-uri (.osz)",
            font=T.FONT_BODY,
        )
        self.chk_download.grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        self.chk_download.select()

        self.chk_db = ctk.CTkCheckBox(
            opts,
            text="Importă în baza de date (Realm / collection.db)",
            font=T.FONT_BODY,
        )
        self.chk_db.grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        self.chk_db.select()

        self.db_label = ctk.CTkLabel(opts, text="", font=T.FONT_SMALL, text_color=T.TEXT_MUTED)
        self.db_label.grid(row=3, column=0, sticky="nw", pady=(8, 4))
        path_row = ctk.CTkFrame(opts, fg_color="transparent")
        path_row.grid(row=3, column=1, sticky="ew", pady=(8, 4))
        path_row.grid_columnconfigure(0, weight=1)
        self.db_path = ctk.CTkEntry(path_row, height=36, fg_color=T.BG_INPUT, border_width=0)
        self.db_path.grid(row=0, column=0, sticky="ew", padx=(8, 4))
        ctk.CTkButton(path_row, text="Auto", width=44, command=self._on_auto_realm).grid(
            row=0, column=1, padx=(0, 4)
        )
        ctk.CTkButton(path_row, text="…", width=36, command=self._browse_db).grid(row=0, column=2)

        ctk.CTkLabel(opts, text="Dacă există deja", font=T.FONT_SMALL, text_color=T.TEXT_MUTED).grid(
            row=4, column=0, sticky="w", pady=(8, 4)
        )
        self.merge_mode = ctk.CTkSegmentedButton(
            opts,
            values=["Înlocuiește", "Unește", "Adaugă nouă"],
        )
        self.merge_mode.grid(row=4, column=1, sticky="w", padx=8, pady=(8, 4))
        self.merge_mode.set("Adaugă nouă")

        ctk.CTkLabel(opts, text="Folder .osz", font=T.FONT_SMALL, text_color=T.TEXT_MUTED).grid(
            row=5, column=0, sticky="w", pady=(8, 4)
        )
        dl_row = ctk.CTkFrame(opts, fg_color="transparent")
        dl_row.grid(row=5, column=1, sticky="ew", pady=(8, 4))
        dl_row.grid_columnconfigure(0, weight=1)
        self.dl_path = ctk.CTkEntry(dl_row, height=36, fg_color=T.BG_INPUT, border_width=0)
        self.dl_path.grid(row=0, column=0, sticky="ew", padx=(8, 4))
        ctk.CTkButton(dl_row, text="…", width=36, command=self._browse_dl).grid(row=0, column=1)

        self._sync_path_fields_from_settings()

        self.progress = ctk.CTkProgressBar(card, height=8, progress_color=T.ACCENT)
        self.progress.grid(row=8, column=0, sticky="ew", padx=T.PAD, pady=(8, 8))
        self.progress.set(0)

        act = ctk.CTkFrame(card, fg_color="transparent")
        act.grid(row=9, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))
        act.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            act,
            text="Rulează import",
            height=48,
            font=("Segoe UI Semibold", 15),
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            command=self._on_run,
        ).grid(row=0, column=1, padx=(8, 8))
        ctk.CTkButton(
            act,
            text="Anulează",
            height=48,
            width=100,
            fg_color="transparent",
            border_width=1,
            border_color=T.TEXT_MUTED,
            command=self._on_cancel,
        ).grid(row=0, column=2)

        self.log = ctk.CTkTextbox(
            card,
            height=200,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.log.grid(row=10, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))
        self._sync_load_lazer_button_label()

    def _build_simple_wizard(self, parent: ctk.CTkScrollableFrame) -> None:
        ctk.CTkLabel(
            parent,
            text="Ghid rapid — pași în ordine",
            font=("Segoe UI Semibold", 22),
            text_color=T.TEXT,
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            parent,
            text="Fiecare pas are propriul buton. Poți face pauză între descărcare și colecție.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 16))

        b1 = ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        b1.pack(fill="x", pady=(0, 12))
        b1.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            b1,
            text="1–2. Link și încărcare",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 4))
        ctk.CTkLabel(
            b1,
            text="Lipește linkul sau ID-ul colecției osu!Collector, apoi încarcă.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 8))
        row_u = ctk.CTkFrame(b1, fg_color="transparent")
        row_u.grid(row=2, column=0, sticky="ew", padx=T.PAD, pady=(0, 8))
        row_u.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            row_u,
            height=40,
            placeholder_text="URL sau ID (ex. 11791)",
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            row_u,
            text="Încarcă",
            width=100,
            height=40,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            command=self._on_fetch,
        ).grid(row=0, column=1)
        self.status = ctk.CTkLabel(
            b1,
            text="Începe de la pașii 1–2.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        )
        self.status.grid(row=3, column=0, sticky="w", padx=T.PAD, pady=(0, 4))
        self.info_label = ctk.CTkLabel(
            b1,
            text="",
            font=T.FONT_BODY,
            text_color=T.TEXT,
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.info_label.grid(row=4, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))

        self.progress = ctk.CTkProgressBar(parent, height=8, progress_color=T.ACCENT)
        self.progress.pack(fill="x", pady=(4, 8))
        self.progress.set(0)

        b3 = ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        b3.pack(fill="x", pady=(0, 12))
        b3.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            b3,
            text="3. Descarcă fișierele .osz",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 4))
        ctk.CTkLabel(
            b3,
            text="Rulează manual când ești gata. Fișierele merg în folderul de mai jos.",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 8))
        row_dl = ctk.CTkFrame(b3, fg_color="transparent")
        row_dl.grid(row=2, column=0, sticky="ew", padx=T.PAD, pady=(0, 8))
        row_dl.grid_columnconfigure(0, weight=1)
        self.dl_path = ctk.CTkEntry(row_dl, height=36, fg_color=T.BG_INPUT, border_width=0)
        self.dl_path.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(row_dl, text="…", width=36, command=self._browse_dl).grid(row=0, column=1)
        self.simple_btn_download = ctk.CTkButton(
            b3,
            text="Pornește descărcarea",
            height=44,
            font=("Segoe UI Semibold", 14),
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            state="disabled",
            command=self._simple_on_download,
        )
        self.simple_btn_download.grid(row=3, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))

        b4 = ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        b4.pack(fill="x", pady=(0, 12))
        b4.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            b4,
            text="4. Pune hărțile în osu!",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 4))
        ctk.CTkLabel(
            b4,
            text=(
                "Importă manual beatmap-urile în client: trage .osz în fereastra jocului "
                "sau folosește meniul de import. Apoi treci la pasul 5."
            ),
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 8))
        self.simple_btn_open_folder = ctk.CTkButton(
            b4,
            text="Deschide folderul cu .osz în Explorer",
            height=40,
            fg_color=T.BG_INPUT,
            hover_color=T.ACCENT,
            command=self._simple_open_osz_folder,
        )
        self.simple_btn_open_folder.grid(row=2, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))

        b5 = ctk.CTkFrame(parent, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        b5.pack(fill="x", pady=(0, 12))
        b5.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            b5,
            text="5. Colecția în osu",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 4))
        ctk.CTkLabel(
            b5,
            text=(
                "Salvează lista ca colecție (același set de hărți ca pe osu!Collector). "
                "Pe Lazer: închide jocul înainte. Căile Realm / collection.db sunt în Setări."
            ),
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 8))
        ctk.CTkLabel(
            b5,
            text="Nume colecție în joc",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=2, column=0, sticky="w", padx=T.PAD, pady=(0, 4))
        self.collection_name_entry = ctk.CTkEntry(
            b5,
            height=38,
            placeholder_text="Lasă gol pentru numele de pe osu!Collector",
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.collection_name_entry.grid(row=3, column=0, sticky="ew", padx=T.PAD, pady=(0, 12))
        ctk.CTkLabel(
            b5,
            text="Client",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=4, column=0, sticky="w", padx=T.PAD, pady=(0, 4))
        self.client_target = ctk.CTkSegmentedButton(
            b5,
            values=["Lazer", "Stable"],
            command=self._on_client_change,
        )
        self.client_target.grid(row=5, column=0, sticky="w", padx=T.PAD, pady=(0, 12))
        ctk.CTkLabel(
            b5,
            text="Dacă colecția există deja în osu",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=6, column=0, sticky="w", padx=T.PAD, pady=(0, 4))
        self.merge_mode = ctk.CTkSegmentedButton(
            b5,
            values=["Înlocuiește", "Unește", "Adaugă nouă"],
        )
        self.merge_mode.grid(row=7, column=0, sticky="w", padx=T.PAD, pady=(0, 12))
        self.merge_mode.set("Adaugă nouă")
        self.simple_btn_import = ctk.CTkButton(
            b5,
            text="Adaugă colecția în osu",
            height=48,
            font=("Segoe UI Semibold", 15),
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            state="disabled",
            command=self._simple_on_import_collection,
        )
        self.simple_btn_import.grid(row=8, column=0, sticky="ew", padx=T.PAD, pady=(0, T.PAD))

        row_cancel = ctk.CTkFrame(parent, fg_color="transparent")
        row_cancel.pack(fill="x")
        ctk.CTkButton(
            row_cancel,
            text="Anulează descărcarea",
            fg_color="transparent",
            border_width=1,
            border_color=T.TEXT_MUTED,
            command=self._on_cancel,
        ).pack(side="right")

        self.log = ctk.CTkTextbox(
            parent,
            height=140,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.log.pack(fill="x", pady=(8, 0))

        self.dl_path.insert(0, self.settings.download_dir)
        self.client_target.set(self.settings.client)
        self._on_client_change(self.settings.client)
        self._sync_load_lazer_button_label()

    def _sync_load_lazer_button_label(self) -> None:
        if not hasattr(self, "btn_load_lazer"):
            return
        try:
            if not int(self.btn_load_lazer.winfo_exists()):
                return
        except tk.TclError:
            return
        if self._effective_client() == "Lazer":
            self.btn_load_lazer.configure(
                text="Încarcă din osu!lazer",
                fg_color=T.BG_INPUT,
            )
        else:
            self.btn_load_lazer.configure(
                text="Încarcă colecții (alege Lazer jos)",
                fg_color=T.BG_CARD,
            )

    def _on_load_lazer_clicked(self) -> None:
        dbg("UI: _on_load_lazer_clicked")
        if self._effective_client() != "Lazer":
            messagebox.showinfo(
                "OSC",
                "Colecțiile din osu!lazer se încarcă doar când „Lazer” este selectat "
                "la Client (jos în ecran, la pasul 5 — sau în modul avansat).\n\n"
                "Acum este modul Stable (collection.db).",
            )
            return
        self._refresh_sidebar()

    def _sync_path_fields_from_settings(self) -> None:
        dbg("UI: _sync_path_fields_from_settings")
        self.dl_path.delete(0, "end")
        self.dl_path.insert(0, self.settings.download_dir)
        self.client_target.set(self.settings.client)
        self._on_client_change(self.settings.client)

    def _persist_paths(self) -> None:
        dbg("UI: _persist_paths")
        self.settings.client = self.client_target.get()
        self.settings.download_dir = self.dl_path.get().strip()
        if self.client_target.get() == "Lazer":
            self.settings.realm_path = self.db_path.get().strip()
        else:
            self.settings.stable_collection_db = self.db_path.get().strip()
        save_settings(self.settings)

    def _persist_simple_paths(self) -> None:
        dbg("UI: _persist_simple_paths")
        self.settings.client = self.client_target.get()
        self.settings.download_dir = self.dl_path.get().strip()
        save_settings(self.settings)

    def _open_settings(self) -> None:
        dbg("UI: _open_settings (dialog)")

        def on_saved(s: AppSettings) -> None:
            self.settings = s
            set_verbose(s.diagnostic_verbose or verbose_from_environment())
            dbg(
                "UI: setări salvate din dialog — "
                f"client={s.client!r} diagnostic_verbose={s.diagnostic_verbose} "
                f"osu_data_dir={s.osu_data_dir!r}",
            )
            self._sync_path_fields_from_settings()
            self._refresh_sidebar()

        SettingsDialog(self, self.settings, on_saved)

    def _on_client_change(self, value: str) -> None:
        dbg(f"UI: _on_client_change → {value!r}")
        self.settings.client = value
        if hasattr(self, "db_path") and self.db_path.winfo_exists():
            if value == "Lazer":
                self.db_label.configure(
                    text="Fișier Realm (client_*.realm):",
                )
                self.chk_db.configure(text="Importă în Realm (închide osu!lazer)")
                self.db_path.delete(0, "end")
                self.db_path.insert(0, self.settings.realm_path)
            else:
                self.db_label.configure(text="collection.db (osu!stable):")
                self.chk_db.configure(text="Scrie / actualizează collection.db")
                self.db_path.delete(0, "end")
                self.db_path.insert(0, self.settings.stable_collection_db)
        self._sync_load_lazer_button_label()
        self.after(60, self._refresh_sidebar)

    def _is_lazer(self) -> bool:
        return self.client_target.get() == "Lazer"

    def _effective_client(self) -> str:
        """Lazer / Stable: același lucru ca în UI (segment), nu doar setări nesincronizate."""
        ct = getattr(self, "client_target", None)
        if ct is not None:
            try:
                if int(ct.winfo_exists()):
                    return ct.get()
            except tk.TclError:
                pass
        return self.settings.client

    def _browse_db(self) -> None:
        dbg(f"UI: _browse_db (lazer={self._is_lazer()})")
        if self._is_lazer():
            p = filedialog.askopenfilename(
                filetypes=[("Realm", "*.realm"), ("Toate", "*.*")],
            )
        else:
            p = filedialog.asksaveasfilename(
                defaultextension=".db",
                filetypes=[("collection.db", "*.db")],
            )
        if p:
            self.db_path.delete(0, "end")
            self.db_path.insert(0, p)

    def _browse_dl(self) -> None:
        dbg("UI: _browse_dl")
        p = filedialog.askdirectory()
        if p:
            self.dl_path.delete(0, "end")
            self.dl_path.insert(0, p)
            self.settings.download_dir = p.strip()
            save_settings(self.settings)

    def _on_auto_realm(self) -> None:
        dbg("UI: _on_auto_realm")
        from osc_collector.collection_manager_config import osu_location_from_collection_manager

        cm = osu_location_from_collection_manager()
        if cm is not None and cm.is_dir():
            self.settings.osu_data_dir = str(cm)
            save_settings(self.settings)
        root = normalize_osu_data_dir(Path(self.settings.osu_data_dir))
        if str(root) != self.settings.osu_data_dir.strip():
            self.settings.osu_data_dir = str(root)
            save_settings(self.settings)
        if not root.is_dir():
            dbg(f"UI: _on_auto_realm folder inexistent {root}")
            messagebox.showerror("OSC", f"Folder inexistent:\n{root}\nSetează-l în Setări.")
            return
        found = find_realm_files_under_osu(root)
        if not found:
            dbg(f"UI: _on_auto_realm niciun .realm sub {root}")
            messagebox.showwarning(
                "OSC",
                f"Niciun .realm găsit sub:\n{root}\n\nPornește osu!lazer o dată sau verifică folderul în Setări.",
            )
            return
        best = pick_best_realm_candidate(found)
        if best:
            self.db_path.delete(0, "end")
            self.db_path.insert(0, str(best))
            self.settings.realm_path = str(best)
            save_settings(self.settings)
            dbg(f"UI: _on_auto_realm → realm ales {best}")

    def _sidebar_show_scrollable_log(self, title: str, body: str, *, height_px: int = 280) -> None:
        dbg(f"UI: _sidebar_show_scrollable_log title={title!r} body_len={len(body or '')}")
        # CTkTextbox în state=disabled folosește disabledforeground implicit — adesea invizibil pe fundal
        # închis. tk.Text cu fg == disabledforeground evită zona „fără text”.
        ctk.CTkLabel(
            self.sidebar_scroll,
            text=title,
            font=("Segoe UI Semibold", 12),
            text_color=T.TEXT,
        ).pack(anchor="w", pady=(0, 6))
        wrap = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        wrap.pack(fill="both", expand=True, pady=(0, 8))
        fg_t = _theme_hex(T.TEXT)
        bg_t = _theme_hex(T.BG_INPUT)
        border_t = _theme_hex(T.TEXT_MUTED)
        line_h = max(12, min(28, int(height_px / 18)))
        native = tk.Text(
            wrap,
            height=line_h,
            width=2,
            wrap="word",
            font=("Segoe UI", 10),
            bg=bg_t,
            fg=fg_t,
            insertbackground=fg_t,
            disabledforeground=fg_t,
            selectbackground=_theme_hex(T.ACCENT_MUTED),
            selectforeground=fg_t,
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=border_t,
            highlightcolor=border_t,
            padx=10,
            pady=10,
            undo=False,
        )
        native.pack(fill="both", expand=True)
        native.insert("1.0", (body or "").strip() or "(fără detalii)")
        native.configure(state="disabled")

    def _refresh_sidebar(self) -> None:
        for w in self.sidebar_scroll.winfo_children():
            w.destroy()
        self._sidebar_btns.clear()
        self._lazer_check_vars.clear()

        client = self._effective_client()
        diag_info(f"sidebar refresh: client={client}")
        dbg(
            f"UI: _refresh_sidebar client={client!r} osu_data_dir={self.settings.osu_data_dir!r} "
            f"realm_hint={self.settings.realm_path!r}",
        )

        if client == "Lazer":
            osu_root = normalize_osu_data_dir(Path(self.settings.osu_data_dir))
            if str(osu_root) != self.settings.osu_data_dir.strip():
                self.settings.osu_data_dir = str(osu_root)
                save_settings(self.settings)
            hint = self.settings.realm_path
            eff = effective_lazer_realm_path(osu_root, hint)
            if eff is not None:
                hint_p = Path(hint).expanduser()
                valid_hint = (
                    hint_p.is_file()
                    and hint_p.suffix.lower() == ".realm"
                    and not path_is_under_distribution_bundle(hint_p)
                )
                if not valid_hint and str(eff) != hint:
                    self.settings.realm_path = str(eff)
                    save_settings(self.settings)
                    if hasattr(self, "db_path") and self.db_path.winfo_exists():
                        self.db_path.delete(0, "end")
                        self.db_path.insert(0, str(eff))
            ctk.CTkLabel(
                self.sidebar_scroll,
                text=(
                    "Se citește baza osu!lazer (Realm)…\n"
                    "Colecții + beatmap-uri (ca în Collection Manager). "
                    "Poate dura câteva secunde."
                ),
                font=T.FONT_SMALL,
                text_color=T.TEXT_MUTED,
                justify="left",
            ).pack(anchor="w", pady=12)
            self.update_idletasks()

            self._lazer_sidebar_generation += 1
            load_gen = self._lazer_sidebar_generation
            realm_hint = self.settings.realm_path

            def work() -> None:
                dbg(
                    f"worker: sidebar list-detail gen={load_gen} osu_root={osu_root} "
                    f"realm_hint={realm_hint!r}",
                )
                rows_ok: list[dict[str, object]] | None = None
                err_ok = ""
                try:
                    rows_ok, err_ok = list_lazer_collections_detail(osu_root, realm_hint)
                    if rows_ok is None:
                        diag_warning(
                            "sidebar lazer: list-detail eșuat — "
                            f"{(err_ok or '')[:2000]}",
                        )
                    else:
                        diag_info(f"sidebar lazer: {len(rows_ok)} colecții citite")
                except Exception:
                    err_ok = traceback.format_exc()
                    rows_ok = None
                    diag_log_exception("sidebar lazer: excepție la list_lazer_collections_detail")

                def apply_result() -> None:
                    if load_gen != self._lazer_sidebar_generation:
                        return
                    self._populate_sidebar_lazer(osu_root, rows_ok, err_ok)
                    self._dismiss_loading_overlay()

                self._enqueue_main(apply_result)

            threading.Thread(target=work, daemon=True).start()
            return

        db_stable = Path(self.settings.stable_collection_db)
        dbg(f"UI: _refresh_sidebar stable listă din {db_stable}")
        rows = list_stable_collections(db_stable)
        diag_info(f"sidebar stable: db={db_stable} colecții={len(rows)}")

        wrap_side = max(320, T.SIDEBAR_WIDTH - 32)
        if not rows:
            db_p = Path(self.settings.stable_collection_db)
            ctk.CTkLabel(
                self.sidebar_scroll,
                text=(
                    "Nicio colecție în collection.db.\n\n"
                    f"Fișier:\n{db_p}\n\n"
                    "Importă din dreapta sau verifică calea în Setări. "
                    "Colecțiile din osu!lazer nu apar la modul Stable."
                ),
                font=T.FONT_SMALL,
                text_color=T.TEXT,
                justify="left",
                wraplength=wrap_side,
                ).pack(anchor="w", pady=8)
            self._dismiss_loading_overlay()
            return

        for row in sorted(rows, key=lambda r: str(r.get("name", "")).lower()):
            name = str(row.get("name", "?"))
            n = int(row.get("beatmaps", 0))
            btn = ctk.CTkButton(
                self.sidebar_scroll,
                text=f"{name}\n{n} beatmap-uri în colecție",
                anchor="w",
                height=56,
                corner_radius=8,
                fg_color=T.BG_INPUT,
                hover_color=T.ACCENT,
                font=("Segoe UI", 13),
                text_color=T.TEXT,
                command=lambda nm=name, bc=n: self._show_collection_detail(nm, bc),
            )
            btn.pack(fill="x", pady=4)
            self._sidebar_btns.append(btn)
        self._dismiss_loading_overlay()

    def _populate_sidebar_lazer(
        self,
        osu_root: Path,
        rows: list[dict[str, object]] | None,
        list_side_err: str,
    ) -> None:
        dbg(
            f"UI: _populate_sidebar_lazer rows_is_none={rows is None} "
            f"n={0 if rows is None else len(rows)} err_len={len(list_side_err or '')}",
        )
        for w in self.sidebar_scroll.winfo_children():
            w.destroy()
        self._sidebar_btns.clear()
        self._lazer_check_vars.clear()

        if rows is None:
            self._lazer_last_collections = []
            err_text = (list_side_err or "").strip() or "Eroare necunoscută."
            self._sidebar_show_scrollable_log(
                "Nu pot citi Realm (detalii):",
                err_text,
                height_px=280,
            )
            return

        wrap_side = max(320, T.SIDEBAR_WIDTH - 32)
        if not rows:
            self._lazer_last_collections = []
            eff = effective_lazer_realm_path(osu_root, self.settings.realm_path)
            realm_line = str(eff) if eff is not None else "(necunoscut)"
            hint_extra = ""
            if (list_side_err or "").strip():
                hint_extra = "\n\n---\n" + (list_side_err or "").strip()
            ctk.CTkLabel(
                self.sidebar_scroll,
                text=(
                    "0 colecții în acest Realm.\n\n"
                    f"Fișier:\n{realm_line}\n\n"
                    "Dacă ai colecții în osu!stable, alege „Stable” la Client "
                    "(jos) sau în Setări. Pe Lazer, folosește același folder de date "
                    "ca în joc (Setări → Conținut).\n\n"
                    "Apasă „Încarcă din osu!lazer” după ce ai creat colecții în joc."
                    + hint_extra
                ),
                font=T.FONT_SMALL,
                text_color=T.TEXT,
                justify="left",
                wraplength=wrap_side,
            ).pack(anchor="w", pady=8)
            return

        self._lazer_last_collections = [dict(r) for r in rows]
        # Collapsed implicit: evită mii de widget-uri (crash / îngheț la multe colecții).
        self._lazer_expanded = set()
        for row in sorted(rows, key=lambda r: str(r.get("name", "")).lower()):
            self._build_lazer_collection_sidebar_block(row)

    def _build_lazer_collection_sidebar_block(self, coll: dict[str, object]) -> None:
        cid = str(coll.get("id", "")).strip()
        name = str(coll.get("name", "?"))
        dbg(f"UI: _build_lazer_collection_sidebar_block name={name!r} id={cid!r}")
        items_raw = coll.get("items")
        items_all: list[dict[str, object]] = (
            [dict(x) for x in items_raw if isinstance(x, dict)]
            if isinstance(items_raw, list)
            else []
        )
        items = _lazer_items_in_library_only(items_all)
        count = len(items)

        outer = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
        outer.pack(fill="x", pady=(0, 6))

        body = ctk.CTkFrame(outer, fg_color="transparent")
        expanded = cid in self._lazer_expanded
        arrow = "▼" if expanded else "▶"
        hdr = ctk.CTkButton(
            outer,
            text=f"{arrow}  {name}  ({count})",
            anchor="w",
            height=40,
            corner_radius=8,
            fg_color=T.BG_INPUT,
            hover_color=T.ACCENT,
            font=("Segoe UI Semibold", 13),
            text_color=T.TEXT,
            command=lambda: self._toggle_lazer_collection(cid, name, count, body, hdr),
        )
        hdr.pack(fill="x")

        if expanded:
            body.pack(fill="x", padx=(10, 0), pady=(4, 0))
            self._fill_lazer_collection_items(body, cid, list(items))

    def _toggle_lazer_collection(
        self,
        cid: str,
        name: str,
        count: int,
        body: ctk.CTkFrame,
        hdr: ctk.CTkButton,
    ) -> None:
        will_expand = cid not in self._lazer_expanded
        dbg(f"UI: _toggle_lazer_collection expand={will_expand} name={name!r} cid={cid!r}")
        if cid in self._lazer_expanded:
            self._lazer_expanded.discard(cid)
            for w in body.winfo_children():
                w.destroy()
            body.pack_forget()
            hdr.configure(text=f"▶  {name}  ({count})")
        else:
            self._lazer_expanded.add(cid)
            coll = next(
                (r for r in self._lazer_last_collections if str(r.get("id", "")) == cid),
                None,
            )
            items_all: list[dict[str, object]] = []
            if coll:
                ir = coll.get("items")
                if isinstance(ir, list):
                    items_all = [dict(x) for x in ir if isinstance(x, dict)]
            items = _lazer_items_in_library_only(items_all)
            body.pack(fill="x", padx=(10, 0), pady=(4, 0))
            self._fill_lazer_collection_items(body, cid, items)
            hdr.configure(text=f"▼  {name}  ({len(items)})")

    def _lazer_row_select_click(
        self,
        event: tk.Event,
        cid: str,
        index: int,
        md5: str,
        items: list[dict[str, object]],
    ) -> None:
        """Clic: comută o singură bifă. Shift+clic: bifează intervalul față de ultimul clic fără Shift."""
        var = self._lazer_check_vars.get((cid, md5))
        if var is None:
            return
        st = int(getattr(event, "state", 0))
        shift = (st & 0x0001) != 0
        if shift:
            anchor = self._lazer_shift_anchor.get(cid)
            if anchor is None:
                self._lazer_shift_anchor[cid] = index
                var.set(True)
                return
            lo, hi = sorted([anchor, index])
            for j in range(lo, hi + 1):
                if j < 0 or j >= len(items):
                    continue
                m2 = str(items[j].get("md5", "")).lower()
                if len(m2) != 32:
                    continue
                v2 = self._lazer_check_vars.get((cid, m2))
                if v2 is not None:
                    v2.set(True)
            self._lazer_shift_anchor[cid] = index
        else:
            var.set(not var.get())
            self._lazer_shift_anchor[cid] = index

    def _fill_lazer_collection_items(
        self,
        body: ctk.CTkFrame,
        cid: str,
        items: list[dict[str, object]],
    ) -> None:
        items = _lazer_items_in_library_only(list(items))
        dbg(f"UI: _fill_lazer_collection_items cid={cid!r} items={len(items)}")
        self._lazer_shift_anchor.pop(cid, None)

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", pady=(4, 2))
        ctk.CTkButton(
            btns,
            text="Bifează tot",
            width=100,
            height=28,
            font=T.FONT_SMALL,
            fg_color=T.BG_INPUT,
            command=lambda: self._lazer_select_all(cid, items),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            btns,
            text="Debifează",
            width=90,
            height=28,
            font=T.FONT_SMALL,
            fg_color=T.BG_INPUT,
            command=lambda: self._lazer_select_none(cid, items),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns,
            text="Șterge bifate",
            width=120,
            height=28,
            font=T.FONT_SMALL,
            fg_color="#b91c1c",
            hover_color="#991b1b",
            command=lambda: self._lazer_remove_selected(cid, items),
        ).pack(side="left", padx=(12, 0))

        ctk.CTkLabel(
            body,
            text=(
                "Clic pe rând: bifează/debifează un map. Shift+clic: bifează toate rândurile "
                "între acesta și ultimul clic fără Shift (selecție multiplă)."
            ),
            font=("Segoe UI", 9),
            text_color=T.TEXT_MUTED,
            wraplength=max(280, T.SIDEBAR_WIDTH - 24),
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        content_body = ctk.CTkFrame(body, fg_color="transparent")
        content_body.pack(fill="x", expand=True)

        total_maps = len(items)
        if total_maps > _LAZER_UI_ROW_CAP:
            ctk.CTkLabel(
                content_body,
                text=(
                    f"Afișez primele {_LAZER_UI_ROW_CAP} din {total_maps} hărți "
                    "(limită performanță). „Bifează tot” se aplică doar la rândurile afișate."
                ),
                font=("Segoe UI", 9),
                text_color="#f59e0b",
                wraplength=max(280, T.SIDEBAR_WIDTH - 24),
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(0, 6))
            items = items[:_LAZER_UI_ROW_CAP]

        if not items:
            ctk.CTkLabel(
                content_body,
                text="Nicio hartă din colecție nu e în librărie (toate lipsesc din Realm).",
                font=T.FONT_SMALL,
                text_color=T.TEXT_MUTED,
                wraplength=max(280, T.SIDEBAR_WIDTH - 24),
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=8)
            return

        for i, it in enumerate(items):
            md5 = str(it.get("md5", "")).lower()
            if len(md5) != 32:
                continue
            title = str(it.get("title", "")).strip()
            artist = str(it.get("artist", "")).strip()
            diff = str(it.get("difficulty", "")).strip()
            rank_s = str(it.get("rank") or "").strip()
            pp_raw = it.get("pp")

            core = f"{artist} — {title}"
            if diff:
                core += f"  [{diff}]"
            main_color = T.TEXT

            rowf = ctk.CTkFrame(content_body, fg_color=T.BG_CARD, corner_radius=6)
            rowf.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=False)
            self._lazer_check_vars[(cid, md5)] = var
            ctk.CTkCheckBox(
                rowf,
                text="",
                variable=var,
                width=26,
                checkbox_width=18,
                checkbox_height=18,
            ).pack(side="left", padx=(6, 4), pady=4)

            core_lbl = ctk.CTkLabel(
                rowf,
                text=core,
                font=("Segoe UI", 11),
                text_color=main_color,
                anchor="w",
            )
            core_lbl.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=4)

            bind_click: list[tk.Misc] = [rowf, core_lbl]

            if rank_s and rank_s != "—":
                rlv = rank_s.upper()
                if "X" in rlv or "SS" in rlv:
                    rank_color = "#E0E0E0"
                elif "S" in rlv:
                    rank_color = "#FFD700"
                elif "A" in rlv:
                    rank_color = "#4FFFD5"
                elif "B" in rlv:
                    rank_color = "#4FC0FF"
                elif "C" in rlv:
                    rank_color = "#FF69B4"
                elif "D" in rlv:
                    rank_color = "#FF4500"
                else:
                    rank_color = T.TEXT_MUTED

                rank_lbl = ctk.CTkLabel(
                    rowf,
                    text=rank_s,
                    font=("Segoe UI Black", 14, "bold"),
                    text_color=rank_color,
                    anchor="e",
                    width=34,
                )
                rank_lbl.pack(side="right", padx=(4, 10), pady=4)
                bind_click.append(rank_lbl)

            if pp_raw is not None and isinstance(pp_raw, (int, float)):
                pp_lbl = ctk.CTkLabel(
                    rowf,
                    text=f"{float(pp_raw):g}pp",
                    font=("Segoe UI", 10),
                    text_color=T.TEXT_MUTED,
                    anchor="e",
                    width=52,
                )
                pp_lbl.pack(side="right", padx=(4, 4), pady=4)
                bind_click.append(pp_lbl)

            for w in bind_click:
                w.bind(
                    "<Button-1>",
                    lambda e, ii=i, mm=md5: self._lazer_row_select_click(e, cid, ii, mm, items),
                )

    def _lazer_select_all(self, cid: str, items: list[dict[str, object]]) -> None:
        for it in items:
            m = str(it.get("md5", "")).lower()
            v = self._lazer_check_vars.get((cid, m))
            if v is not None:
                v.set(True)

    def _lazer_select_none(self, cid: str, items: list[dict[str, object]]) -> None:
        for it in items:
            m = str(it.get("md5", "")).lower()
            v = self._lazer_check_vars.get((cid, m))
            if v is not None:
                v.set(False)

    def _lazer_remove_selected(self, cid: str, items: list[dict[str, object]]) -> None:
        md5s: list[str] = []
        for it in items:
            m = str(it.get("md5", "")).lower()
            if len(m) != 32:
                continue
            v = self._lazer_check_vars.get((cid, m))
            if v is not None and v.get():
                md5s.append(m)
        if not md5s:
            messagebox.showinfo("OSC", "Nu ai bifat niciun beatmap.")
            return
        if not messagebox.askyesno(
            "OSC",
            f"Elimin {len(md5s)} intrare/ări din această colecție în Realm?\n\n"
            "Închide osu!lazer înainte. Modificarea e vizibilă în joc după repornire.",
        ):
            dbg("UI: _lazer_remove_selected anulat de utilizator")
            return
        dbg(
            f"UI: _lazer_remove_selected confirmat colecție={cid!r} hash-uri={len(md5s)}",
        )
        osu_root = normalize_osu_data_dir(Path(self.settings.osu_data_dir))
        rp = effective_lazer_realm_path(osu_root, self.settings.realm_path)
        if rp is None:
            messagebox.showerror("OSC", "Nu găsesc fișierul .realm.")
            return

        def work() -> None:
            dbg(f"worker: realm_remove_beatmaps_from_collection realm={rp} n={len(md5s)}")
            code, msg = realm_remove_beatmaps_from_collection(rp, cid, md5s)
            if code != 0:
                diag_warning(
                    f"lazer remove beatmaps: exit={code} realm={rp} "
                    f"msg={(msg or '')[:1500]}",
                )
            else:
                diag_info(
                    f"lazer remove beatmaps: OK ({len(md5s)} hash-uri) colecție={cid!r}",
                )

            def done() -> None:
                if code != 0:
                    messagebox.showerror("OSC", msg or "Eroare la scriere Realm.")
                else:
                    messagebox.showinfo("OSC", msg or "Actualizat.")
                self._refresh_sidebar()

            self._enqueue_main(done)

        threading.Thread(target=work, daemon=True).start()

    def _show_collection_detail(self, name: str, beatmaps: int) -> None:
        dbg(f"UI: _show_collection_detail name={name!r} beatmaps={beatmaps}")
        self._clear_main()
        card = ctk.CTkFrame(self.main_scroll, fg_color=T.BG_CARD, corner_radius=T.CORNER)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            card,
            text=name,
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).pack(anchor="w", padx=T.PAD, pady=(T.PAD, 8))

        src = "osu!lazer (Realm)" if self.settings.client == "Lazer" else "osu!stable (collection.db)"
        ctk.CTkLabel(
            card,
            text=f"Sursă: {src}\n{beatmaps} beatmap-uri (difficulty-uri) în această colecție.\n"
            "În joc vei vedea doar hărțile deja importate în client.",
            font=T.FONT_BODY,
            text_color=T.TEXT_MUTED,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=T.PAD, pady=(0, T.PAD))

        ctk.CTkButton(
            card,
            text="← Înapoi la import",
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            command=self._show_import_view,
        ).pack(anchor="w", padx=T.PAD, pady=(0, T.PAD))

    def _effective_collection_name(self, data: CollectionData) -> str:
        raw = self.collection_name_entry.get().strip()
        return raw if raw else data.name

    def _merge_mode_key(self) -> str:
        label = self.merge_mode.get()
        if label == "Înlocuiește":
            return "replace"
        if label == "Unește":
            return "merge"
        return "append"

    def _log(self, line: str) -> None:
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def _on_fetch(self) -> None:
        dbg("UI: _on_fetch")
        raw = self.url_entry.get().strip()
        cid = parse_collection_id(raw)
        if cid is None:
            self.status.configure(text="ID invalid.", text_color="#ef4444")
            diag_warning(f"fetch: ID/URL invalid din câmp ({raw[:120]!r})")
            return
        diag_info(f"fetch: început colecție id={cid}")
        self.status.configure(text="Se încarcă…", text_color=T.TEXT_MUTED)
        self.progress.set(0.05)

        def work() -> None:
            dbg(f"worker: fetch_collection thread start id={cid}")
            try:
                with httpx.Client() as client:
                    data = fetch_collection(client, cid)
                dbg(f"worker: fetch_collection thread OK id={cid}")
                self._enqueue_main( lambda: self._on_fetch_done(data, None))
            except Exception as e:
                dbg(f"worker: fetch_collection thread EXC id={cid} err={e!s}")
                self._enqueue_main( lambda: self._on_fetch_done(None, e))

        threading.Thread(target=work, daemon=True).start()

    def _maybe_set_simple_actions(self, enabled: bool) -> None:
        dbg(f"UI: _maybe_set_simple_actions enabled={enabled}")
        st = "normal" if enabled else "disabled"
        dl = getattr(self, "simple_btn_download", None)
        if dl is not None and dl.winfo_exists():
            dl.configure(state=st)
        im = getattr(self, "simple_btn_import", None)
        if im is not None and im.winfo_exists():
            im.configure(state=st)

    def _on_fetch_done(self, data: CollectionData | None, err: Exception | None) -> None:
        dbg(f"UI: _on_fetch_done err={'yes' if err else 'no'}")
        self.progress.set(0)
        if err is not None:
            diag_error(f"fetch: eșuat API/osu!Collector — {err!s}")
            self.status.configure(text="Eroare API.", text_color="#ef4444")
            self._log(str(err))
            self._loaded = None
            self._maybe_set_simple_actions(False)
            return
        assert data is not None
        self._loaded = data
        diag_info(
            f"fetch: OK id={data.id} „{data.name}” — "
            f"{len(data.md5_checksums)} MD5, {len(data.beatmapset_ids)} set-uri",
        )
        self.collection_name_entry.delete(0, "end")
        self.collection_name_entry.insert(0, data.name)
        if getattr(self, "simple_btn_download", None) is not None:
            self.status.configure(
                text="Încărcat. Poți continua cu pasul 3.",
                text_color=T.ACCENT,
            )
        else:
            self.status.configure(text="Încărcat.", text_color=T.ACCENT)
        self.info_label.configure(
            text=(
                f"„{data.name}” (id {data.id}) — {len(data.md5_checksums)} difficultăți, "
                f"{len(data.beatmapset_ids)} set-uri — {data.uploader_username}"
            ),
        )
        self._log(
            f"Încărcat: {data.name} — {len(data.md5_checksums)} MD5, "
            f"{len(data.beatmapset_ids)} set-uri.",
        )
        self._maybe_set_simple_actions(True)

    def _simple_on_download(self) -> None:
        dbg("UI: _simple_on_download")
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("OSC", "O operație rulează deja.")
            return
        data = self._loaded
        if data is None:
            messagebox.showwarning("OSC", "Încarcă mai întâi colecția (pașii 1–2).")
            return
        self._persist_simple_paths()
        self._cancel.clear()
        self.status.configure(text="Descărc…", text_color=T.TEXT_MUTED)
        self._worker = threading.Thread(
            target=self._run_download_only_job,
            args=(data,),
            daemon=True,
        )
        self._worker.start()

    def _simple_open_osz_folder(self) -> None:
        dbg("UI: _simple_open_osz_folder")
        self._persist_simple_paths()
        p = Path(self.dl_path.get().strip())
        try:
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p.resolve()))
        except OSError as e:
            messagebox.showerror("OSC", f"Nu pot deschide folderul:\n{e}")

    def _simple_on_import_collection(self) -> None:
        dbg("UI: _simple_on_import_collection")
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("OSC", "O operație rulează deja.")
            return
        data = self._loaded
        if data is None:
            messagebox.showwarning("OSC", "Încarcă mai întâi colecția (pașii 1–2).")
            return
        self._persist_simple_paths()
        display_name = self._effective_collection_name(data)
        self._cancel.clear()
        self.status.configure(text="Scriu colecția…", text_color=T.TEXT_MUTED)
        self._worker = threading.Thread(
            target=self._run_import_only_job,
            args=(data, display_name, self._is_lazer()),
            daemon=True,
        )
        self._worker.start()

    def _on_run(self) -> None:
        dbg("UI: _on_run (import combinat mod avansat)")
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("OSC", "O operație rulează deja.")
            return
        data = self._loaded
        if data is None:
            messagebox.showwarning("OSC", "Încarcă mai întâi colecția (buton „Încarcă”).")
            return
        do_dl = bool(self.chk_download.get())
        do_db = bool(self.chk_db.get())
        if not do_dl and not do_db:
            messagebox.showwarning("OSC", "Bifează cel puțin descărcare sau import.")
            return

        self.settings.client = self.client_target.get()
        self._persist_paths()
        display_name = self._effective_collection_name(data)
        self._cancel.clear()
        self.status.configure(text="Lucrez…", text_color=T.TEXT_MUTED)
        dbg(
            f"UI: _on_run pornește worker do_dl={do_dl} do_db={do_db} "
            f"display_name={display_name!r} lazer={self._is_lazer()}",
        )
        self._worker = threading.Thread(
            target=self._run_job,
            args=(data, do_dl, do_db, display_name, self._is_lazer()),
            daemon=True,
        )
        self._worker.start()

    def _on_cancel(self) -> None:
        dbg("UI: _on_cancel (steag anulare)")
        self._cancel.set()
        self._log("Anulare…")

    def _phase_import_db(
        self,
        data: CollectionData,
        display_name: str,
        is_lazer: bool,
    ) -> bool:
        dbg(
            f"worker: _phase_import_db is_lazer={is_lazer} display_name={display_name!r} "
            f"md5_count={len(data.md5_checksums)}",
        )
        if is_lazer:
            self._enqueue_main( lambda: self._log("Import Realm…"))
            realm = effective_lazer_realm_path(
                Path(self.settings.osu_data_dir),
                self.settings.realm_path,
            )
            if realm is None:
                root = Path(self.settings.osu_data_dir)
                diag_error(
                    "import_db lazer: niciun .realm — "
                    f"osu_data_dir={root} realm_hint={self.settings.realm_path!r}",
                )
                self._enqueue_main(
                    lambda r=root: messagebox.showerror(
                        "OSC",
                        "Nu s-a găsit niciun .realm în folderul de date osu!:\n"
                        f"{r}\n\nSetează folderul în Setări (de obicei %AppData%\\osu) "
                        "sau folosește „Auto”.",
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
                )
                return False
            diag_info(
                f"import_db lazer: realm={realm} nume={display_name!r} "
                f"hash-uri={len(data.md5_checksums)} mod={self._merge_mode_key()!r}",
            )
            code, msg = import_lazer_realm(
                realm,
                display_name,
                data.md5_checksums,
                self._merge_mode_key(),
            )
            if code != 0:
                diag_warning(
                    f"import_db lazer: exit={code} mesaj={(msg or '')[:2000]}",
                )
                self._enqueue_main( lambda m=msg: self._log(m))
                self._enqueue_main(
                    lambda m=msg: messagebox.showerror(
                        "OSC — Realm",
                        (m or "Eroare")[:900],
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
                )
                return False
            diag_info("import_db lazer: terminat cu succes (exit 0).")
            self._enqueue_main( lambda m=msg: self._log(m or "OK."))
            return True

        self._enqueue_main( lambda: self._log("Scriu collection.db…"))
        if hasattr(self, "db_path") and self.db_path.winfo_exists():
            db_path = Path(self.db_path.get().strip())
        else:
            db_path = Path(self.settings.stable_collection_db)
        diag_info(
            f"import_db stable: collection.db={db_path} nume={display_name!r} "
            f"hash-uri={len(data.md5_checksums)}",
        )
        self._write_db(data, display_name, db_path)
        self._enqueue_main( lambda: self._log("collection.db salvat."))
        return True

    def _phase_download(self, data: CollectionData) -> str:
        try:
            dest_raw = (self.settings.download_dir or "").strip()
            if not dest_raw:
                self._enqueue_main(
                    lambda: messagebox.showerror(
                        "OSC",
                        "Folderul de descărcări e gol. Alege un folder la pasul 3 sau în Setări.",
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
                )
                return "error"
            dest = Path(dest_raw)
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self._enqueue_main(
                    lambda err=e: messagebox.showerror(
                        "OSC",
                        f"Nu pot crea folderul de descărcări:\n{dest}\n\n{err}",
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="Eroare folder.", text_color="#ef4444"),
                )
                return "error"
            if not is_dir_writable(dest):
                try_clear_readonly_windows(dest)
            if not is_dir_writable(dest):
                self._enqueue_main(
                    lambda d=str(dest.resolve()): messagebox.showerror(
                        "OSC — nu se poate scrie în folder",
                        "OSC nu poate salva .osz aici (folder read-only, permisiuni sau "
                        "protecție antivirus / Controlled folder access).\n\n"
                        "Aplicația nu setează singură read-only. În Explorer, la foldere, "
                        "bifa „Read-only\" nu înseamnă mereu că nu poți scrie — verifică "
                        "Proprietăți → Securitate → Modificare pentru contul tău.\n\n"
                        f"Folder încercat:\n{d}\n\n"
                        "Alege alt folder (ex. D:\\Downloads\\OSC) cu butonul … sau din Setări, "
                        "apoi încearcă din nou.",
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(
                        text="Folder descărcări necitibil.",
                        text_color="#ef4444",
                    ),
                )
                return "error"
            set_ids = unique_beatmapset_ids_preserve_order(list(data.beatmapset_ids))
            total = len(set_ids)
            dbg(f"worker: _phase_download dest={dest} total_sets={total} md5={len(data.md5_checksums)}")
            if total == 0:
                if len(data.md5_checksums) > 0:
                    msg = (
                        "API osu!Collector nu a furnizat ID-uri de beatmapset pentru această colecție, "
                        "deci mirror-ul nu poate descărca .osz.\n\n"
                        "Apasă din nou „Încarcă” la pașii 1–2. Dacă problema persistă, notează ID-ul colecției."
                    )
                    self._enqueue_main(
                        lambda: self._log(
                            "0 beatmapset IDs din API — descărcare oprită. Reîncarcă colecția.",
                        ),
                    )
                    self._enqueue_main(lambda: messagebox.showwarning("OSC — descărcare", msg))
                else:
                    self._enqueue_main(
                        lambda: messagebox.showwarning(
                            "OSC",
                            "Colecția nu conține beatmap-uri de descărcat.",
                        ),
                    )
                self._enqueue_main(
                    lambda: self.status.configure(text="Nimic de descărcat.", text_color=T.TEXT_MUTED),
                )
                return "error"
            self._enqueue_main(
                lambda: self._log(f"Descărcări: {total} set-uri → {dest.resolve()}"),
            )
            self._enqueue_main(lambda: self._safe_progress_set(0.0))
            saved_n = 0
            skip_n = 0
            err_n = 0
            prog_gate = [0.0]
            est_osz_bytes = 40 * 1024 * 1024
            existing_ids = existing_valid_set_ids(dest)
            osu_cookie = normalize_osu_web_cookie(self.settings.osu_web_cookie)
            parallel = min(DEFAULT_PARALLEL_DOWNLOADS, max(1, total))
            with create_mirror_client() as rank_client:
                mirror_chain = mirror_templates_for_job(
                    self.settings.mirror_preset,
                    self.settings.mirror_download_template,
                    rank_client,
                )
            dbg(
                f"worker: _phase_download parallel={parallel} "
                f"existing_cache={len(existing_ids)} set-uri "
                f"mirror_preset={self.settings.mirror_preset!r} chain_len={len(mirror_chain)}",
            )
            self._enqueue_main(
                lambda pl=self.settings.mirror_preset, n=len(mirror_chain), oc=bool(osu_cookie): self._log(
                    _mirror_job_log_line(pl, n, osu_official_cookie=oc),
                ),
            )
            dns_fail, dns_ok = mirror_dns_preflight(mirror_chain)
            failed_host_set = {h for h, _ in dns_fail}
            if dns_fail and not dns_ok:
                detail = "\n".join(f"  • {h}: {msg}" for h, msg in dns_fail)
                dns_body = (
                    "Calculatorul nu poate rezolva numele mirror-urilor (DNS → adresă IP). "
                    "OSC nu poate descărca nimic până rețeaua rezolvă aceste domenii.\n\n"
                    "Verifică:\n"
                    "• Internet (deschide un site în browser)\n"
                    "• DNS: în Windows, setează DNS 8.8.8.8 / 1.1.1.1 pe adaptorul activ\n"
                    "• VPN sau proxy — încearcă fără sau cu alt server DNS\n"
                    "• Fișierul hosts (C:\\Windows\\System32\\drivers\\etc\\hosts)\n"
                    "• Antivirus / firewall care blochează DNS\n\n"
                    "Proba OSC (socket.getaddrinfo, port 443):\n"
                    f"{detail}"
                )
                self._enqueue_main(
                    lambda b=dns_body: messagebox.showerror("OSC — eroare DNS / rețea", b),
                )
                self._enqueue_main(
                    lambda: self._log(
                        "Descărcare oprită: niciun mirror nu e rezolvabil prin DNS (vezi dialogul).",
                    ),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="DNS / rețea.", text_color="#ef4444"),
                )
                return "error"
            if dns_fail and dns_ok:
                bad = ", ".join(h for h, _ in dns_fail)
                self._enqueue_main(
                    lambda b=bad: self._log(
                        f"Notă: DNS eșuat pentru {b} — aceste mirror-uri sunt scoase din lanț "
                        f"(nu se mai încearcă la fiecare set).",
                    ),
                )
                mirror_chain = exclude_templates_for_failed_dns_hosts(
                    mirror_chain,
                    failed_host_set,
                )
                dbg(
                    f"worker: mirror chain după filtru DNS: "
                    f"{len(mirror_chain)} șabloane rămase",
                )
            if not mirror_chain:
                self._enqueue_main(
                    lambda: messagebox.showerror(
                        "OSC",
                        "Niciun mirror disponibil după filtrarea DNS. Verifică rețeaua.",
                    ),
                )
                self._enqueue_main(
                    lambda: self._log("Descărcare oprită: lanț mirror gol după DNS."),
                )
                return "error"
            prog_lock = threading.Lock()
            prog_state: dict = {
                "finished": 0,
                "bytes": 0,
                "last_by_sid": {},
            }

            def _progress_from_state() -> float:
                with prog_lock:
                    fin = prog_state["finished"]
                    b = prog_state["bytes"]
                cap = max(1, total * est_osz_bytes)
                from_bytes = min(0.99, b / cap)
                from_done = fin / max(1, total)
                if fin >= total:
                    return 1.0
                return min(0.99, max(from_done, from_bytes))

            def on_chunk(sid: int, done: int, full: int) -> None:
                with prog_lock:
                    prev = prog_state["last_by_sid"].get(sid, 0)
                    prog_state["bytes"] += max(0, done - prev)
                    prog_state["last_by_sid"][sid] = done
                fr = _progress_from_state()
                now = time.monotonic()
                should = (
                    (full > 0 and done >= full)
                    or fr >= 0.997
                    or (now - prog_gate[0]) >= 0.35
                )
                if should:
                    prog_gate[0] = now
                    self._enqueue_main(lambda frc=fr: self._safe_progress_set(frc))

            def download_job(sid: int) -> tuple[str, int, Path | None, BaseException | None]:
                if self._cancel.is_set():
                    return ("cancel", sid, None, None)
                try:
                    client = thread_local_download_client()
                    out = download_beatmapset_with_fallback(
                        client,
                        sid,
                        dest,
                        mirror_chain,
                        on_progress=lambda d, f, _s=sid: on_chunk(_s, d, f),
                        skip_existing=True,
                        existing_valid_ids=existing_ids,
                        should_cancel=self._cancel.is_set,
                        official_osu_cookie=osu_cookie or None,
                    )
                    return ("ok" if out else "skip", sid, out, None)
                except InterruptedError:
                    return ("cancel", sid, None, None)
                except Exception as e:
                    return ("err", sid, None, e)

            dbg(
                f"worker: _phase_download pool continuu max_workers={parallel} "
                f"client HTTP per fir (keep-alive)",
            )
            executor = ThreadPoolExecutor(max_workers=parallel)
            future_map = {executor.submit(download_job, sid): sid for sid in set_ids}
            user_cancelled = False
            try:
                for fut in as_completed(future_map):
                    if self._cancel.is_set():
                        user_cancelled = True
                        break
                    sid = future_map[fut]
                    try:
                        status, _sid, out, exc = fut.result()
                    except Exception as e:
                        status, out, exc = "err", None, e
                    with prog_lock:
                        prog_state["finished"] += 1
                        prog_state["last_by_sid"].pop(sid, None)
                    fr = _progress_from_state()
                    self._enqueue_main(lambda frc=fr: self._safe_progress_set(frc))
                    if status == "ok":
                        saved_n += 1
                        existing_ids.add(sid)
                        self._enqueue_main(
                            lambda s=sid: self._log(f"{s}: OK"),
                        )
                    elif status == "skip":
                        skip_n += 1
                        self._enqueue_main(
                            lambda s=sid: self._log(f"{s}: sărit (există deja)"),
                        )
                    elif status == "cancel":
                        self._enqueue_main(
                            lambda s=sid: self._log(f"{s}: anulat"),
                        )
                    else:
                        err_n += 1
                        err = exc or RuntimeError("necunoscut")
                        diag_warning(f"download beatmapset_id={sid}: {err!s}")
                        if isinstance(err, AllMirrorsFailed):
                            err_line = str(err)
                        else:
                            err_line = short_download_error_message(err)
                        self._enqueue_main(
                            lambda msg=err_line, s=sid: self._log(f"{s}: {msg}"),
                        )
            finally:
                executor.shutdown(
                    wait=not user_cancelled,
                    cancel_futures=user_cancelled,
                )
            if user_cancelled:
                dbg("worker: _phase_download anulat (steag)")
                return "cancel"
            self._enqueue_main(lambda: self._safe_progress_set(1.0))
            summ = f"Rezumat: noi={saved_n}, sărite={skip_n}, erori={err_n} → {dest}"
            dbg(f"worker: _phase_download {summ}")
            self._enqueue_main(lambda s=summ: self._log(s))
            if saved_n == 0 and err_n == 0 and skip_n > 0:
                self._enqueue_main(
                    lambda d=dest: self._log(
                        f"Toate {skip_n} set-uri erau deja în folder (sărite). Folder: {d}",
                    ),
                )
            elif saved_n == 0 and err_n > 0:
                self._enqueue_main(
                    lambda: self._log(
                        "Niciun .osz nou: verifică liniile cu erori mai sus (mirror / set lipsă).",
                    ),
                )
            dbg("worker: _phase_download terminat OK")
            return "ok"
        except Exception as e:
            diag_log_exception("_phase_download (fatal)")
            self._enqueue_main( lambda err=e: self._log(str(err)))
            self._enqueue_main(
                lambda err=e: messagebox.showerror("OSC", str(err)[:700]),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
            )
            return "error"

    def _run_download_only_job(self, data: CollectionData) -> None:
        dbg("worker: _run_download_only_job start")
        try:
            result = self._phase_download(data)
            if result == "cancel":
                dbg("worker: _run_download_only_job rezultat=cancel")
                self._enqueue_main(
                    lambda: messagebox.showwarning("OSC", "Descărcare oprită."),
                )
                self._enqueue_main(
                    lambda: self.status.configure(text="Oprit.", text_color=T.TEXT_MUTED),
                )
                return
            if result == "error":
                dbg("worker: _run_download_only_job rezultat=error")
                return
            dbg("worker: _run_download_only_job rezultat=ok")
            self._enqueue_main(
                lambda: messagebox.showinfo(
                    "OSC",
                    "Pas finalizat. Verifică log-ul de mai jos și folderul de descărcări.\n\n"
                    "Pasul 4: importă .osz în osu, apoi pasul 5 pentru colecție.",
                ),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Descărcare gata.", text_color=T.ACCENT),
            )
        except Exception as e:
            diag_log_exception("_run_download_only_job")
            self._enqueue_main( lambda err=e: self._log(str(err)))
            self._enqueue_main(
                lambda err=e: messagebox.showerror("OSC", str(err)[:700]),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
            )

    def _run_import_only_job(
        self,
        data: CollectionData,
        display_name: str,
        is_lazer: bool,
    ) -> None:
        dbg(
            f"worker: _run_import_only_job name={display_name!r} lazer={is_lazer}",
        )
        try:
            if not self._phase_import_db(data, display_name, is_lazer):
                dbg("worker: _run_import_only_job oprit (_phase_import_db False)")
                return
            self._enqueue_main(
                lambda dn=display_name: messagebox.showinfo(
                    "OSC — reușit",
                    f"Colecția „{dn}” a fost salvată în osu.",
                ),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Colecție salvată.", text_color=T.ACCENT),
            )
            self._enqueue_main(self._refresh_sidebar)
        except Exception as e:
            diag_log_exception("_run_import_only_job")
            self._enqueue_main( lambda err=e: self._log(str(err)))
            self._enqueue_main(
                lambda err=e: messagebox.showerror("OSC", str(err)[:700]),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
            )

    def _run_job(
        self,
        data: CollectionData,
        do_dl: bool,
        do_db: bool,
        display_name: str,
        is_lazer: bool,
    ) -> None:
        dbg(
            f"worker: _run_job start do_db={do_db} do_dl={do_dl} "
            f"name={display_name!r} lazer={is_lazer}",
        )
        try:
            if do_db:
                if not self._phase_import_db(data, display_name, is_lazer):
                    dbg("worker: _run_job stop după import DB eșuat")
                    return
            if do_dl:
                result = self._phase_download(data)
                if result == "cancel":
                    dbg("worker: _run_job descărcare cancel")
                    self._enqueue_main(
                        lambda: messagebox.showwarning("OSC", "Oprit (anulare)."),
                    )
                    self._enqueue_main(
                        lambda: self.status.configure(text="Oprit.", text_color=T.TEXT_MUTED),
                    )
                    return
                if result == "error":
                    dbg("worker: _run_job descărcare error")
                    return

            dbg("worker: _run_job finalizare succes (mesaj UI)")
            parts = []
            if do_db:
                parts.append(
                    f"„{display_name}” în "
                    + ("Realm" if is_lazer else "collection.db"),
                )
            if do_dl:
                parts.append("Folder .osz actualizat")
            body = "\n".join(parts)
            self._enqueue_main(
                lambda b=body: messagebox.showinfo(
                    "OSC — reușit",
                    b or "Gata.",
                ),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Terminat OK.", text_color=T.ACCENT),
            )
            self._enqueue_main(self._refresh_sidebar)
        except Exception as e:
            diag_log_exception("_run_job")
            self._enqueue_main( lambda err=e: self._log(str(err)))
            self._enqueue_main(
                lambda err=e: messagebox.showerror("OSC", str(err)[:700]),
            )
            self._enqueue_main(
                lambda: self.status.configure(text="Eroare.", text_color="#ef4444"),
            )

    def _write_db(
        self,
        data: CollectionData,
        collection_name: str,
        path_override: Path | None = None,
    ) -> None:
        path = path_override if path_override is not None else Path(self.db_path.get().strip())
        mode = self._merge_mode_key()
        dbg(
            f"worker: _write_db path={path} mode={mode!r} "
            f"collection_name={collection_name!r} new_md5_count={len(data.md5_checksums)}",
        )
        if path.is_file():
            version, collections = parse_collection_db(str(path))
        else:
            version, collections = 20150203, []
        merged = merge_collection(
            collections,
            collection_name,
            data.md5_checksums,
            mode,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(build_collection_db(merged, version=version))
        tmp.replace(path)


def run_app() -> None:
    app = OscApp()
    app.mainloop()
