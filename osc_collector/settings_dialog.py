"""Fereastră modală Setări."""

from __future__ import annotations

import tkinter.filedialog as filedialog
from collections.abc import Callable

import customtkinter as ctk

from osc_collector.builtin_mirrors import mirror_preset_labels
from osc_collector.settings_store import AppSettings, save_settings
from osc_collector import ui_theme as T


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        settings: AppSettings,
        on_saved: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(master)
        self._on_saved = on_saved
        self._data = AppSettings(**settings.__dict__)

        self.title("Setări OSC")
        self.geometry("560x720")
        self.minsize(520, 600)
        self.configure(fg_color=T.BG_CARD)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Setări",
            font=T.FONT_HEAD,
            text_color=T.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=T.PAD, pady=(T.PAD, 8))

        ctk.CTkLabel(
            self,
            text="Client implicit la pornire (Lazer / Stable).",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=T.PAD, pady=(0, 4))

        self.client_seg = ctk.CTkSegmentedButton(
            self,
            values=["Lazer", "Stable"],
        )
        self.client_seg.grid(row=2, column=0, sticky="w", padx=T.PAD, pady=(0, 12))
        self.client_seg.set(self._data.client if self._data.client in ("Lazer", "Stable") else "Lazer")

        self._rows: list[tuple[str, ctk.CTkEntry]] = []
        r = 3
        for label, attr, browse_kind in [
            (
                "Folder date osu!lazer (ca în Collection Manager: OsuLocation)",
                "osu_data_dir",
                "dir",
            ),
            ("Fișier Realm (client_*.realm)", "realm_path", "realm"),
            ("collection.db (stable)", "stable_collection_db", "db"),
            ("Folder descărcări .osz", "download_dir", "dir"),
        ]:
            ctk.CTkLabel(self, text=label, font=T.FONT_SMALL, text_color=T.TEXT_MUTED).grid(
                row=r, column=0, sticky="w", padx=T.PAD, pady=(8, 0)
            )
            r += 1
            row_f = ctk.CTkFrame(self, fg_color="transparent")
            row_f.grid(row=r, column=0, sticky="ew", padx=T.PAD, pady=(4, 0))
            row_f.grid_columnconfigure(0, weight=1)
            ent = ctk.CTkEntry(row_f, height=36, fg_color=T.BG_INPUT, border_width=0)
            ent.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ent.insert(0, getattr(self._data, attr))

            def browse_cmd(
                entry: ctk.CTkEntry = ent,
                kind: str = browse_kind,
            ) -> None:
                if kind == "dir":
                    p = filedialog.askdirectory()
                elif kind == "realm":
                    p = filedialog.askopenfilename(
                        filetypes=[("Realm", "*.realm"), ("Toate", "*.*")],
                    )
                else:
                    p = filedialog.askopenfilename(
                        filetypes=[("collection.db", "*.db"), ("Toate", "*.*")],
                    )
                if p:
                    entry.delete(0, "end")
                    entry.insert(0, p)

            btn = ctk.CTkButton(row_f, text="…", width=40, command=browse_cmd)
            btn.grid(row=0, column=1)
            self._rows.append((attr, ent))
            r += 1

        ctk.CTkLabel(
            self,
            text=(
                "Cookie osu.ppy.sh (opțional) — ca în Collection Manager: autentificat pe "
                "site, copiază valoarea header-ului Cookie din DevTools (F12 → Rețea → "
                "un request la osu.ppy.sh). OSC încearcă mai întâi descărcarea oficială "
                "(?noVideo=1), apoi mirror-urile. Gol = doar mirror."
            ),
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=500,
            justify="left",
        ).grid(row=r, column=0, sticky="w", padx=T.PAD, pady=(12, 0))
        r += 1
        self._osu_cookie_box = ctk.CTkTextbox(
            self,
            height=72,
            fg_color=T.BG_INPUT,
            border_width=0,
            font=("Consolas", 12),
        )
        self._osu_cookie_box.grid(row=r, column=0, sticky="ew", padx=T.PAD, pady=(4, 0))
        if self._data.osu_web_cookie:
            self._osu_cookie_box.insert("1.0", self._data.osu_web_cookie)
        r += 1

        self._mirror_preset_rows = mirror_preset_labels()
        self._mirror_key_by_label = {lab: key for key, lab in self._mirror_preset_rows}
        self._mirror_label_by_key = {key: lab for key, lab in self._mirror_preset_rows}
        menu_labels = [lab for _key, lab in self._mirror_preset_rows]
        ctk.CTkLabel(
            self,
            text=(
                "Sursă .osz: „Automat” testează mirror-urile cunoscute și le folosește "
                "în ordinea celor care răspund; la eroare trece la următorul."
            ),
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=500,
            justify="left",
        ).grid(row=r, column=0, sticky="w", padx=T.PAD, pady=(12, 0))
        r += 1
        self.mirror_preset_menu = ctk.CTkOptionMenu(
            self,
            values=menu_labels,
            height=36,
            fg_color=T.BG_INPUT,
            button_color=T.BG_INPUT,
            button_hover_color=T.ACCENT,
            command=self._on_mirror_preset_ui_change,
        )
        self.mirror_preset_menu.grid(row=r, column=0, sticky="ew", padx=T.PAD, pady=(4, 0))
        cur_key = _normalize_mirror_preset_key(self._data.mirror_preset)
        self.mirror_preset_menu.set(self._mirror_label_by_key.get(cur_key, menu_labels[0]))
        r += 1
        ctk.CTkLabel(
            self,
            text="URL personalizat (doar dacă ai ales „URL personalizat…”) — folosește {id}:",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
            wraplength=500,
            justify="left",
        ).grid(row=r, column=0, sticky="w", padx=T.PAD, pady=(8, 0))
        r += 1
        self.mirror_template_entry = ctk.CTkEntry(
            self,
            height=36,
            fg_color=T.BG_INPUT,
            border_width=0,
        )
        self.mirror_template_entry.grid(row=r, column=0, sticky="ew", padx=T.PAD, pady=(4, 0))
        self.mirror_template_entry.insert(0, self._data.mirror_download_template)
        r += 1
        self._on_mirror_preset_ui_change(self.mirror_preset_menu.get())

        self.chk_diagnostic_verbose = ctk.CTkCheckBox(
            self,
            text="Log diagnostic detaliat (DEBUG în OSC_diagnostic.log)",
            font=T.FONT_SMALL,
            text_color=T.TEXT_MUTED,
        )
        self.chk_diagnostic_verbose.grid(row=r, column=0, sticky="w", padx=T.PAD, pady=(12, 4))
        if self._data.diagnostic_verbose:
            self.chk_diagnostic_verbose.select()
        r += 1

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=r, column=0, sticky="e", padx=T.PAD, pady=(T.PAD, T.PAD))
        ctk.CTkButton(
            btn_row,
            text="Anulează",
            width=100,
            fg_color="transparent",
            border_width=1,
            border_color=T.TEXT_MUTED,
            command=self.destroy,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text="Salvează",
            width=120,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            command=self._save,
        ).grid(row=0, column=1)

    def _on_mirror_preset_ui_change(self, choice: str) -> None:
        key = self._mirror_key_by_label.get(choice, "auto")
        if key == "custom":
            self.mirror_template_entry.configure(state="normal")
        else:
            self.mirror_template_entry.configure(state="disabled")

    def _save(self) -> None:
        self._data.client = self.client_seg.get()
        self._data.diagnostic_verbose = bool(self.chk_diagnostic_verbose.get())
        sel = self.mirror_preset_menu.get()
        self._data.mirror_preset = self._mirror_key_by_label.get(sel, "auto")
        self._data.mirror_download_template = self.mirror_template_entry.get().strip()
        self._data.osu_web_cookie = self._osu_cookie_box.get("1.0", "end").strip()
        for attr, ent in self._rows:
            setattr(self._data, attr, ent.get().strip())
        save_settings(self._data)
        self._on_saved(self._data)
        self.destroy()


def _normalize_mirror_preset_key(raw: str) -> str:
    p = (raw or "auto").strip().lower()
    valid = {key for key, _lab in mirror_preset_labels()}
    return p if p in valid else "auto"
