#!/usr/bin/env python3
"""
GUI Module for Smutscrape  —  Dark mode edition
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import sys
import os
import re as _re
import queue
import datetime
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url
from smutscrape.config_editor import ConfigEditor

_SITES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'sites'
)

# ===========================================================================
# Colour palette
# ===========================================================================

C = dict(
    bg          = "#0d0d0d",
    panel       = "#141414",
    panel2      = "#1c1c1c",
    border      = "#2a2a2a",
    fg          = "#39ff14",
    fg_dim      = "#1f8c0b",
    fg_disabled = "#3a3a3a",
    accent      = "#00e5ff",
    accent2     = "#7fff00",
    entry_bg    = "#0a1a0a",
    entry_dis   = "#1a1a1a",
    btn_start   = "#1a5c1a",
    btn_stop    = "#3d0000",
    btn_clear   = "#2a2a2a",
    btn_cfg     = "#1a3a5c",
    cb_select   = "#1f3d1f",
    prog_trough = "#1a1a1a",
    prog_bar    = "#39ff14",
    log_bg      = "#050f05",
    log_fg      = "#39ff14",
    log_filter  = "#00e5ff",
    log_success = "#7fff00",
    log_error   = "#ff3333",
    log_warn    = "#ff8c00",
    log_stopped = "#ff6600",
    log_info    = "#39ff14",
)


# ===========================================================================
# Site filter-capability audit
# ===========================================================================

def _audit_site_filter_caps(sites):
    caps = {}
    for sc, site_obj in sites.items():
        name = site_obj.name
        yaml_path = os.path.join(_SITES_DIR, f"{sc}.yaml")
        if not os.path.isfile(yaml_path):
            yaml_path = os.path.join(_SITES_DIR, f"{name.lower().replace(' ','')}.yaml")
        has_date = has_dur = False
        try:
            with open(yaml_path) as fh:
                data = yaml.safe_load(fh)
            vs = data.get('scrapers', {}).get('video_scraper', {})
            ls = data.get('scrapers', {}).get('list_scraper', {}).get('video_item', {}).get('fields', {})
            has_date = bool(vs.get('date') or ls.get('date'))
            has_dur  = bool(vs.get('duration') or ls.get('duration'))
        except Exception:
            pass
        caps[name] = {'date': has_date, 'duration': has_dur}
    return caps


# ===========================================================================
# Category database loader
# ===========================================================================

def _load_category_db():
    cat_file = os.path.join(_SITES_DIR, 'categories.yaml')
    try:
        with open(cat_file) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


# ===========================================================================
# Misc helpers
# ===========================================================================

class QueueHandler:
    def __init__(self, log_queue):
        self.log_queue = log_queue
    def write(self, msg):
        if msg and msg.strip():
            self.log_queue.put(("log", msg))
    def flush(self):
        pass


def _format_duration(raw):
    if not raw:
        return ""
    raw = str(raw).strip()
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", raw, _re.IGNORECASE)
    if m and any(m.groups()):
        total_s = int(float(m.group(1) or 0))*3600 \
                + int(float(m.group(2) or 0))*60 \
                + int(float(m.group(3) or 0))
        h, rem = divmod(total_s, 3600); mn, s = divmod(rem, 60)
        return f"{h:02d}:{mn:02d}:{s:02d}"
    if ":" in raw:
        parts = raw.split(":")
        try:
            parts = [int(p) for p in parts]
            if len(parts) == 2: return f"00:{parts[0]:02d}:{parts[1]:02d}"
            if len(parts) == 3: return f"{parts[0]:02d}:{parts[1]:02d}:{parts[2]:02d}"
        except ValueError:
            return raw
    try:
        total_s = int(float(raw)); h, rem = divmod(total_s, 3600); mn, s = divmod(rem, 60)
        return f"{h:02d}:{mn:02d}:{s:02d}"
    except ValueError:
        return raw


def _get_after_date(yyyy, mm, dd):
    y = yyyy.strip(); mo = mm.strip(); d = dd.strip()
    if not y: return None
    if mo:
        if d: return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        return f"{y}-{mo.zfill(2)}"
    return y


# ===========================================================================
# TTK dark theme
# ===========================================================================

def _apply_dark_ttk(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".",
        background=C["panel"], foreground=C["fg"],
        fieldbackground=C["entry_bg"], bordercolor=C["border"],
        troughcolor=C["prog_trough"],
        selectbackground=C["cb_select"], selectforeground=C["fg"],
        insertcolor=C["fg"], font=("Courier", 9),
    )
    style.configure("TCombobox",
        fieldbackground=C["entry_bg"], background=C["panel2"],
        foreground=C["fg"], arrowcolor=C["fg"],
        selectbackground=C["cb_select"], selectforeground=C["fg"],
        bordercolor=C["border"],
    )
    style.map("TCombobox",
        fieldbackground=[("readonly", C["entry_bg"])],
        foreground=[("readonly", C["fg"])],
        selectbackground=[("readonly", C["cb_select"])],
    )
    root.option_add("*TCombobox*Listbox.background",       C["panel2"])
    root.option_add("*TCombobox*Listbox.foreground",       C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["cb_select"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["accent"])
    style.configure("green.Horizontal.TProgressbar",
        troughcolor=C["prog_trough"], background=C["prog_bar"],
        bordercolor=C["border"], lightcolor=C["prog_bar"], darkcolor=C["prog_bar"],
    )
    style.configure("TScrollbar",
        background=C["panel2"], troughcolor=C["bg"],
        arrowcolor=C["fg_dim"], bordercolor=C["border"],
    )
    style.map("TScrollbar", background=[("active", C["cb_select"])])
    style.configure("TLabelframe",
        background=C["panel"], bordercolor=C["border"],
    )
    style.configure("TLabelframe.Label",
        background=C["panel"], foreground=C["accent"],
        font=("Courier", 9, "bold"),
    )


# ===========================================================================
# Main GUI
# ===========================================================================

class SmutscrapeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smutscrape")
        self.root.geometry("960x860")
        self.root.resizable(True, True)
        self.root.configure(bg=C["bg"])
        _apply_dark_ttk(root)

        self.log_queue       = queue.Queue()
        self._loguru_sink_id = None
        self._stop_event     = threading.Event()
        self.site_manager    = get_site_manager()
        self.sites           = self.site_manager.sites
        self.site_names      = sorted([s.name for s in self.sites.values()])
        self._filter_caps    = _audit_site_filter_caps(self.sites)
        self._cat_db         = _load_category_db()
        self._cat_vars       = {}
        self._log_visible    = True
        self._cfg_win        = None   # keep reference to avoid garbage-collection

        self._build_ui()
        self._bind_mousewheel()
        self._poll_log_queue()

    # -------------------------------------------------------------------------
    # Widget factories
    # -------------------------------------------------------------------------

    def _lf(self, parent, text, borderless=False, **kw):
        bd = 0 if borderless else 1
        ht = 0 if borderless else 1
        return tk.LabelFrame(
            parent, text=text,
            bg=C["panel"], fg=C["accent"],
            font=("Courier", 9, "bold"),
            bd=bd, relief="flat",
            highlightbackground=C["border"],
            highlightthickness=ht,
            padx=kw.pop("padx", 8),
            pady=kw.pop("pady", 6),
            **kw
        )

    def _label(self, parent, text="", textvariable=None, fg=None, font=None, **kw):
        kwargs = dict(bg=C["panel"], fg=fg or C["fg"], font=font or ("Courier", 9))
        if textvariable: kwargs["textvariable"] = textvariable
        else:            kwargs["text"]          = text
        kwargs.update(kw)
        return tk.Label(parent, **kwargs)

    def _entry(self, parent, width=18, **kw):
        return tk.Entry(
            parent, width=width,
            bg=C["entry_bg"], fg=C["fg"],
            insertbackground=C["fg"],
            disabledbackground=C["entry_dis"],
            disabledforeground=C["fg_disabled"],
            relief="flat", bd=1,
            highlightbackground=C["border"],
            highlightthickness=1,
            font=("Courier", 9),
            **kw
        )

    def _button(self, parent, text, command, bg, fg="#ffffff", state="normal", **kw):
        return tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
            disabledforeground=C["fg_disabled"],
            relief="flat", bd=0,
            font=("Courier", 9, "bold"),
            cursor="hand2", state=state, **kw
        )

    def _checkbutton(self, parent, text, variable, bg=None, **kw):
        bg = bg or C["panel"]
        return tk.Checkbutton(
            parent, text=text, variable=variable,
            bg=bg, fg=C["fg"],
            activebackground=C["cb_select"], activeforeground=C["accent"],
            selectcolor=C["bg"],
            font=("Courier", 9),
            bd=0, relief="flat",
            **kw
        )

    # -------------------------------------------------------------------------
    # Configure window launcher
    # -------------------------------------------------------------------------

    def _open_config_editor(self):
        """Open the config editor as a modal Toplevel. Only one at a time."""
        if self._cfg_win is not None:
            try:
                self._cfg_win.lift()
                self._cfg_win.focus_set()
                return
            except tk.TclError:
                self._cfg_win = None
        self._cfg_win = ConfigEditor(self.root)
        self._cfg_win.protocol("WM_DELETE_WINDOW",
                               self._on_cfg_close)

    def _on_cfg_close(self):
        if self._cfg_win:
            self._cfg_win.destroy()
        self._cfg_win = None

    # -------------------------------------------------------------------------
    # Smart mousewheel routing
    # -------------------------------------------------------------------------

    def _bind_mousewheel(self):
        """
        Route mousewheel events to exactly one target:
          1. If event.widget is a bare string (Tk internal path, e.g. Combobox
             dropdown Listbox) — treat as native, do nothing.
          2. If widget (or any ancestor) is a Combobox/Listbox/Text — let Tk
             handle it natively.
          3. Else if widget is inside _cat_canvas — scroll _cat_canvas only.
          4. Else scroll _main_canvas, BUT only when content overflows viewport.
        """
        _NATIVE_SCROLL = {"TCombobox", "Combobox", "Listbox", "Text", "ScrolledText"}

        def _is_native(w):
            while w:
                if isinstance(w, str):
                    return True
                try:
                    if w.winfo_class() in _NATIVE_SCROLL:
                        return True
                    w = w.master
                except AttributeError:
                    break
            return False

        def _is_in_cat_canvas(w):
            while w:
                if isinstance(w, str):
                    break
                if w is self._cat_canvas:
                    return True
                try:
                    w = w.master
                except AttributeError:
                    break
            return False

        def _main_can_scroll():
            return self._inner.winfo_reqheight() > self._main_canvas.winfo_height()

        def _on_wheel(event):
            widget = event.widget
            delta  = -1 if (event.num == 5 or getattr(event, 'delta', 1) < 0) else 1
            if _is_native(widget):
                return
            if _is_in_cat_canvas(widget):
                self._cat_canvas.yview_scroll(-delta, "units")
                return
            if _main_can_scroll():
                self._main_canvas.yview_scroll(-delta, "units")

        self.root.bind_all("<MouseWheel>", _on_wheel)
        self.root.bind_all("<Button-4>",   _on_wheel)
        self.root.bind_all("<Button-5>",   _on_wheel)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self):
        self._main_canvas = tk.Canvas(self.root, bg=C["bg"],
                                      highlightthickness=0, bd=0)
        self._main_vsb    = ttk.Scrollbar(self.root, orient="vertical",
                                          command=self._main_canvas.yview)
        self._main_canvas.configure(yscrollcommand=self._main_vsb.set)
        self._main_vsb.pack(side="right", fill="y")
        self._main_canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._main_canvas, bg=C["bg"])
        self._inner_id = self._main_canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._main_canvas.bind("<Configure>", self._on_canvas_configure)

        # ── Title bar ────────────────────────────────────────────────────────
        title_bar = tk.Frame(self._inner, bg=C["panel"])
        title_bar.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(title_bar, text="\u2593\u2592\u2591  S M U T S C R A P E  \u2591\u2592\u2593",
                 bg=C["panel"], fg=C["fg"], font=("Courier", 13, "bold")
                 ).pack(side="left")
        tk.Label(title_bar, text="dark reaper edition",
                 bg=C["panel"], fg=C["fg_dim"], font=("Courier", 8)
                 ).pack(side="left", padx=10)
        # ─── Configure button lives in the title bar, far right ───
        self._button(
            title_bar, "\u2699  Configure",
            self._open_config_editor,
            bg=C["btn_cfg"], fg=C["accent"],
            padx=12, pady=3
        ).pack(side="right", padx=4)
        tk.Frame(self._inner, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(0, 6))

        # ── TARGET ───────────────────────────────────────────────────────────
        top = self._lf(self._inner, "  TARGET ")
        top.pack(fill="x", padx=10, pady=(0, 4))

        self._label(top, "Site:", width=16, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.site_var   = tk.StringVar()
        self.site_combo = ttk.Combobox(top, textvariable=self.site_var,
                                       values=self.site_names, width=30, state="readonly")
        self.site_combo.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        self.site_combo.bind("<<ComboboxSelected>>", self._on_site_selected)

        self.filter_badge_var = tk.StringVar(value="")
        self._label(top, textvariable=self.filter_badge_var,
                    fg=C["fg_dim"], font=("Courier", 8)
                    ).grid(row=0, column=2, sticky="w", padx=4)

        self._label(top, "Mode:", width=16, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.mode_var   = tk.StringVar()
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, width=20, state="readonly")
        self.mode_combo.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)

        self.query_label_var = tk.StringVar(value="Query:")
        self._label(top, textvariable=self.query_label_var,
                    width=16, anchor="e").grid(row=2, column=0, sticky="e", pady=3)
        self.query_entry = self._entry(top, width=52)
        self.query_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=3)
        top.columnconfigure(1, weight=1)

        # ── CATEGORIES ────────────────────────────────────────────────────────
        self.cat_frame = self._lf(
            self._inner,
            "  CATEGORIES  (check one or more \u2014 each scraped in sequence)",
            borderless=True, padx=6, pady=4
        )
        self._cat_canvas = tk.Canvas(self.cat_frame, height=140,
                                     bg=C["panel2"], highlightthickness=0)
        self._cat_scrollbar = ttk.Scrollbar(self.cat_frame, orient="vertical",
                                            command=self._cat_canvas.yview)
        self._cat_inner_frame = tk.Frame(self._cat_canvas, bg=C["panel2"])
        self._cat_inner_id = self._cat_canvas.create_window(
            (0, 0), window=self._cat_inner_frame, anchor="nw"
        )
        self._cat_inner_frame.bind(
            "<Configure>",
            lambda e: self._cat_canvas.configure(
                scrollregion=self._cat_canvas.bbox("all")
            )
        )
        self._cat_canvas.configure(yscrollcommand=self._cat_scrollbar.set)
        self._cat_canvas.pack(side="left", fill="both", expand=True)
        self._cat_scrollbar.pack(side="right", fill="y")

        btn_cat = tk.Frame(self.cat_frame, bg=C["panel"])
        btn_cat.pack(fill="x", pady=(4, 0))
        self._button(btn_cat, "Select All", self._cat_select_all,
                     bg=C["btn_start"], padx=10, pady=3).pack(side="left", padx=4)
        self._button(btn_cat, "Clear All", self._cat_clear_all,
                     bg=C["btn_clear"], padx=10, pady=3).pack(side="left", padx=4)
        self._label(btn_cat, "\u2190 leave all unchecked to use the Query field",
                    fg=C["fg_dim"], font=("Courier", 8)
                    ).pack(side="left", padx=10)

        # ── FILTERS ──────────────────────────────────────────────────────────
        filters = self._lf(self._inner, "  FILTERS ")
        filters.pack(fill="x", padx=10, pady=4)

        self._label(filters, "After Date:", width=20, anchor="e").grid(
            row=0, column=0, sticky="e", pady=3)
        date_row = tk.Frame(filters, bg=C["panel"])
        date_row.grid(row=0, column=1, sticky="w", padx=6)
        self.date_yyyy = self._entry(date_row, width=6)
        self.date_yyyy.pack(side="left")
        self._label(date_row, "YYYY", fg=C["fg_dim"], font=("Courier", 7),
                    bg=C["panel"]).pack(side="left", padx=(2, 8))
        self.date_mm = self._entry(date_row, width=4)
        self.date_mm.pack(side="left")
        self._label(date_row, "MM", fg=C["fg_dim"], font=("Courier", 7),
                    bg=C["panel"]).pack(side="left", padx=(2, 8))
        self.date_dd = self._entry(date_row, width=4)
        self.date_dd.pack(side="left")
        self._label(date_row, "DD", fg=C["fg_dim"], font=("Courier", 7),
                    bg=C["panel"]).pack(side="left", padx=(2, 0))
        self.after_hint = self._label(
            filters, "all optional \u2014 fill only YYYY for year filter", fg=C["fg_dim"]
        )
        self.after_hint.grid(row=0, column=2, sticky="w", padx=6)

        self._label(filters, "Min Duration (min):", width=20, anchor="e").grid(
            row=1, column=0, sticky="e", pady=3)
        self.min_dur_entry = self._entry(filters, width=8)
        self.min_dur_entry.grid(row=1, column=1, sticky="w", padx=6)
        self.dur_hint = self._label(
            filters, "e.g. 10  (skip videos shorter than this)", fg=C["fg_dim"]
        )
        self.dur_hint.grid(row=1, column=2, sticky="w")

        self._label(filters, "Start Page:", width=20, anchor="e").grid(
            row=2, column=0, sticky="e", pady=3)
        self.page_entry = self._entry(filters, width=8)
        self.page_entry.insert(0, "1")
        self.page_entry.grid(row=2, column=1, sticky="w", padx=6)
        self._label(filters, "Begin scraping from this page",
                    fg=C["fg_dim"]).grid(row=2, column=2, sticky="w")

        # ── OPTIONS ───────────────────────────────────────────────────────────
        opts = self._lf(self._inner, "  OPTIONS ", borderless=True, pady=4)
        opts.pack(fill="x", padx=10, pady=4)
        self.overwrite_var  = tk.BooleanVar()
        self.renfo_var      = tk.BooleanVar()
        self.applystate_var = tk.BooleanVar()
        self._checkbutton(opts, "Overwrite existing files",
                          self.overwrite_var).grid(row=0, column=0, sticky="w", padx=10)
        self._checkbutton(opts, "Regenerate .nfo files",
                          self.renfo_var).grid(row=0, column=1, sticky="w", padx=10)
        self._checkbutton(opts, "Apply state (skip already seen)",
                          self.applystate_var).grid(row=0, column=2, sticky="w", padx=10)

        # ── BUTTONS ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self._inner, bg=C["bg"])
        btn_frame.pack(pady=6)

        self.run_button = self._button(
            btn_frame, "\u25b6  Start Scraping", self._start_scraping,
            bg=C["btn_start"], fg=C["fg"], padx=18, pady=6
        )
        self.run_button.pack(side="left", padx=8)

        self.stop_button = self._button(
            btn_frame, "\u23f9  STOP", self._stop_scraping,
            bg=C["btn_stop"], fg="#ff4444", padx=18, pady=6, state="disabled"
        )
        self.stop_button.pack(side="left", padx=8)

        self._button(
            btn_frame, "\u232b  Clear Log", self._clear_log,
            bg=C["btn_clear"], fg=C["fg_dim"], padx=14, pady=6
        ).pack(side="left", padx=8)

        self.log_toggle_btn = self._button(
            btn_frame, "\u25bc  Hide Log", self._toggle_log,
            bg=C["btn_clear"], fg=C["accent"], padx=14, pady=6
        )
        self.log_toggle_btn.pack(side="left", padx=8)

        # ── PROGRESS ────────────────────────────────────────────────────────
        prog = self._lf(self._inner, "  PROGRESS ")
        prog.pack(fill="x", padx=10, pady=(2, 4))
        prog.columnconfigure(1, weight=1)

        self._label(prog, "Current video:", width=16, anchor="e").grid(
            row=0, column=0, sticky="e", pady=2)
        self.video_title_var = tk.StringVar(value="\u2014")
        self._label(prog, textvariable=self.video_title_var, anchor="w",
                    fg=C["accent"], font=("Courier", 9, "bold")
                    ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)

        self._label(prog, "Date / Duration:", width=16, anchor="e").grid(
            row=1, column=0, sticky="e", pady=2)
        self.video_meta_var = tk.StringVar(value="\u2014")
        self._label(prog, textvariable=self.video_meta_var, anchor="w",
                    fg=C["fg_dim"]
                    ).grid(row=1, column=1, columnspan=3, sticky="ew", padx=4)

        self._label(prog, "Download:", width=16, anchor="e").grid(
            row=2, column=0, sticky="e", pady=2)
        self.dl_bar = ttk.Progressbar(prog, orient="horizontal", length=400,
                                      mode="determinate", maximum=100,
                                      style="green.Horizontal.TProgressbar")
        self.dl_bar.grid(row=2, column=1, sticky="ew", padx=4)
        self.dl_pct_var = tk.StringVar(value="")
        self._label(prog, textvariable=self.dl_pct_var, width=20, anchor="w",
                    fg=C["fg"], font=("Courier", 9)
                    ).grid(row=2, column=2, sticky="w", padx=4)

        self._label(prog, "Query progress:", width=16, anchor="e").grid(
            row=3, column=0, sticky="e", pady=2)
        self.global_bar = ttk.Progressbar(prog, orient="horizontal", length=400,
                                          mode="determinate", maximum=100,
                                          style="green.Horizontal.TProgressbar")
        self.global_bar.grid(row=3, column=1, sticky="ew", padx=4)
        self.global_pct_var = tk.StringVar(value="")
        self._label(prog, textvariable=self.global_pct_var, width=20, anchor="w",
                    fg=C["fg"], font=("Courier", 9)
                    ).grid(row=3, column=2, sticky="w", padx=4)

        # ── STATUS BAR ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self._inner, textvariable=self.status_var,
                 anchor="w", relief="flat",
                 bg=C["panel2"], fg=C["accent"],
                 font=("Courier", 9), padx=8
                 ).pack(fill="x", padx=10, pady=(0, 2))

        # ── LOG ───────────────────────────────────────────────────────────────
        self.log_outer = tk.Frame(self._inner, bg=C["bg"])
        self.log_outer.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        log_lf = self._lf(self.log_outer, "  LOG ", padx=4, pady=4)
        log_lf.pack(fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_lf, state="disabled", wrap="word",
            bg=C["log_bg"], fg=C["log_fg"],
            insertbackground=C["fg"],
            selectbackground=C["cb_select"],
            font=("Courier", 9), height=14,
            relief="flat", bd=0,
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("filter",  foreground=C["log_filter"])
        self.log_text.tag_config("success", foreground=C["log_success"])
        self.log_text.tag_config("error",   foreground=C["log_error"])
        self.log_text.tag_config("warn",    foreground=C["log_warn"])
        self.log_text.tag_config("stopped", foreground=C["log_stopped"])
        self.log_text.tag_config("info",    foreground=C["log_info"])

    # -------------------------------------------------------------------------
    # Main canvas resize helpers
    # -------------------------------------------------------------------------

    def _on_inner_configure(self, event):
        bbox = self._main_canvas.bbox("all")
        if bbox:
            self._main_canvas.configure(scrollregion=(0, 0, bbox[2], bbox[3]))

    def _on_canvas_configure(self, event):
        self._main_canvas.itemconfig(self._inner_id, width=event.width)
        self.root.after(10, self._reset_scroll_if_fits)

    def _reset_scroll_if_fits(self):
        if self._inner.winfo_reqheight() <= self._main_canvas.winfo_height():
            self._main_canvas.yview_moveto(0)

    # -------------------------------------------------------------------------
    # Log toggle
    # -------------------------------------------------------------------------

    def _toggle_log(self):
        if self._log_visible:
            self.log_outer.pack_forget()
            self.log_toggle_btn.config(text="\u25b2  Show Log")
            self._log_visible = False
        else:
            self.log_outer.pack(fill="both", expand=True, padx=10, pady=(2, 10))
            self.log_toggle_btn.config(text="\u25bc  Hide Log")
            self._log_visible = True

    # =========================================================================
    # Category panel helpers
    # =========================================================================

    def _get_shortcode_for_site(self, site_name):
        for sc, site_obj in self.sites.items():
            if site_obj.name == site_name:
                return sc
        return None

    def _refresh_cat_panel(self, slugs):
        for w in self._cat_inner_frame.winfo_children():
            w.destroy()
        self._cat_vars = {}
        if not slugs:
            self.cat_frame.pack_forget()
            return
        cols = 4
        for idx, slug in enumerate(sorted(slugs)):
            var = tk.BooleanVar(value=False)
            self._cat_vars[slug] = var
            label = slug.replace('-', ' ').title()
            self._checkbutton(
                self._cat_inner_frame, label, var, bg=C["panel2"], anchor="w", padx=4
            ).grid(row=idx // cols, column=idx % cols, sticky="w", padx=4, pady=1)
        slaves = self._inner.pack_slaves()
        target = None
        for w in slaves:
            if hasattr(w, '_is_filters'):
                target = w
                break
        if target:
            self.cat_frame.pack(fill="x", padx=10, pady=4, before=target)
        else:
            self.cat_frame.pack(fill="x", padx=10, pady=4)

    def _cat_select_all(self):
        for v in self._cat_vars.values(): v.set(True)

    def _cat_clear_all(self):
        for v in self._cat_vars.values(): v.set(False)

    def _get_checked_categories(self):
        return [slug for slug, var in sorted(self._cat_vars.items()) if var.get()]

    # =========================================================================
    # Event handlers
    # =========================================================================

    def _on_site_selected(self, event=None):
        site_name = self.site_var.get()
        site_obj  = next((s for s in self.sites.values() if s.name == site_name), None)
        if not site_obj: return
        modes = [m for m in site_obj.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes: self.mode_combo.current(0)

        caps = self._filter_caps.get(site_name, {'date': True, 'duration': True})
        badges = []
        if not caps['date']:     badges.append("no date filter")
        if not caps['duration']: badges.append("no duration filter")
        self.filter_badge_var.set(
            ("\u26a0 " + ", ".join(badges)) if badges else "\u2714 date & duration supported"
        )

        date_state = "normal" if caps['date'] else "disabled"
        date_bg    = C["entry_bg"] if caps['date'] else C["entry_dis"]
        hint_fg    = C["fg_dim"]   if caps['date'] else C["fg_disabled"]
        hint_txt   = "all optional \u2014 fill only YYYY for year filter" \
                     if caps['date'] else "not available for this site"
        for e in (self.date_yyyy, self.date_mm, self.date_dd):
            e.config(state=date_state, bg=date_bg)
        self.after_hint.config(fg=hint_fg, text=hint_txt)

        if not caps['duration']:
            self.min_dur_entry.config(state="disabled", bg=C["entry_dis"])
            self.dur_hint.config(fg=C["fg_disabled"], text="not available for this site")
        else:
            self.min_dur_entry.config(state="normal", bg=C["entry_bg"])
            self.dur_hint.config(fg=C["fg_dim"], text="e.g. 10  (skip shorter than this)")

        self._on_mode_selected()

    def _on_mode_selected(self, event=None):
        mode      = self.mode_var.get()
        site_name = self.site_var.get()
        sc        = self._get_shortcode_for_site(site_name)
        slugs     = self._cat_db.get(sc, {}).get(mode, []) if sc and mode else []
        if mode in ('category', 'tag'):
            self.query_label_var.set("Keyword (opt):" if slugs else "Category:")
        else:
            self.query_label_var.set("Query:")
        self._refresh_cat_panel(slugs)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _log(self, msg, tag=None):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag or "info")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _set_dl_progress(self, pct, speed="", eta=""):
        self.dl_bar["value"] = pct
        label = f"{pct:.1f}%"
        if speed: label += f"  {speed}"
        if eta:   label += f"  ETA {eta}"
        self.dl_pct_var.set(label)

    def _set_global_progress(self, done, total):
        pct = (done / total * 100) if total else 0
        self.global_bar["value"] = pct
        self.global_pct_var.set(f"{done} / {total}  ({pct:.0f}%)")

    def _set_video_info(self, title, date, duration):
        self.video_title_var.set(title or "\u2014")
        parts = []
        if date: parts.append(f"\U0001f4c5 {date}")
        dur_fmt = _format_duration(duration)
        if dur_fmt: parts.append(f"\u23f1 {dur_fmt}")
        self.video_meta_var.set("   ".join(parts) if parts else "\u2014")
        self.dl_bar["value"] = 0
        self.dl_pct_var.set("")

    def _poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    msg = item[1]
                    low = msg.lower()
                    if   "[filter]" in low or "skip" in low:     tag = "filter"
                    elif "success"  in low or "finished" in low: tag = "success"
                    elif "stopped"  in low or "abort"    in low: tag = "stopped"
                    elif "error"    in low or "failed"   in low: tag = "error"
                    elif "warn"     in low:                       tag = "warn"
                    else:                                         tag = "info"
                    self._log(msg.rstrip(), tag)
                elif kind == "dl_progress":
                    _, pct, speed, eta = item
                    self._set_dl_progress(pct, speed, eta)
                elif kind == "global_progress":
                    _, done, total = item
                    self._set_global_progress(done, total)
                elif kind == "video_info":
                    _, title, date, duration = item
                    self._set_video_info(title, date, duration)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _install_loguru_sink(self):
        from loguru import logger
        import re as _re2
        ansi = _re2.compile(r'\x1b\[[0-9;]*m')
        def _sink(message):
            self.log_queue.put(("log", ansi.sub('', str(message)).rstrip()))
        if self._loguru_sink_id is not None:
            try: logger.remove(self._loguru_sink_id)
            except Exception: pass
        self._loguru_sink_id = logger.add(
            _sink, format="{time:HH:mm:ss} | {level:<7} | {message}",
            level="DEBUG", colorize=False
        )

    def _remove_loguru_sink(self):
        if self._loguru_sink_id is not None:
            try:
                from loguru import logger
                logger.remove(self._loguru_sink_id)
            except Exception: pass
            self._loguru_sink_id = None

    # =========================================================================
    # Scraping control
    # =========================================================================

    def _start_scraping(self):
        site_name = self.site_var.get()
        mode      = self.mode_var.get()
        if not site_name: messagebox.showwarning("Input Error", "Please select a site.");  return
        if not mode:      messagebox.showwarning("Input Error", "Please select a mode.");  return

        checked_cats = self._get_checked_categories()
        free_query   = self.query_entry.get().strip()
        if checked_cats:
            targets = checked_cats
        elif free_query:
            targets = [free_query]
        else:
            messagebox.showwarning("Input Error",
                "Please enter a query  OR  check at least one category.")
            return

        self.dl_bar["value"] = self.global_bar["value"] = 0
        self.dl_pct_var.set(""); self.global_pct_var.set("")
        self.video_title_var.set("\u2014"); self.video_meta_var.set("\u2014")
        self._stop_event.clear()
        self.run_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Scraping in progress...")
        self._install_loguru_sink()
        self._log(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
            f"Starting: site={site_name}  mode={mode}  targets={targets}",
            "success"
        )
        threading.Thread(target=self._run_task,
                         args=(site_name, mode, targets), daemon=True).start()

    def _stop_scraping(self):
        self._stop_event.set()
        self.status_var.set("Stop requested \u2014 finishing current video...")
        self.stop_button.config(state="disabled")
        self._log(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
            "Stop requested by user \u2014 will abort after current video.",
            "stopped"
        )

    def _run_task(self, site_name, mode, targets):
        handler = QueueHandler(self.log_queue)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = handler
        try:
            site_obj = next((s for s in self.sites.values() if s.name == site_name), None)
            if not site_obj: raise ValueError(f"Site '{site_name}' not found.")

            general_config = load_configuration('general')
            state_set      = get_session_manager().processed_urls \
                             if self.applystate_var.get() else set()
            mode_config    = site_obj.modes.get(mode)
            if not mode_config: raise ValueError(f"Mode '{mode}' not found.")

            site_dict    = site_obj.to_dict()
            after_date   = _get_after_date(
                self.date_yyyy.get(), self.date_mm.get(), self.date_dd.get()
            )
            min_duration = self.min_dur_entry.get().strip() or None
            overwrite    = self.overwrite_var.get()
            re_nfo       = self.renfo_var.get()
            try:    start_page = int(self.page_entry.get().strip())
            except: start_page = 1

            caps = self._filter_caps.get(site_name, {'date': True, 'duration': True})
            if not caps['date']:     after_date   = None
            if not caps['duration']: min_duration = None

            def dl_progress_cb(pct, speed="", eta=""):
                self.log_queue.put(("dl_progress", pct, speed, eta))
            def video_info_cb(title, date, duration):
                self.log_queue.put(("video_info", title, date, duration))
            def global_progress_cb(done, total):
                self.log_queue.put(("global_progress", done, total))

            import time as _time

            for target_idx, query in enumerate(targets):
                if self._stop_event.is_set(): break
                self.log_queue.put(("log",
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                    f"\u2500\u2500\u2500 category {target_idx+1}/{len(targets)}: '{query}' \u2500\u2500\u2500"
                ))
                self.root.after(0, lambda q=query: self.status_var.set(
                    f"Scraping '{q}'  ({target_idx+1}/{len(targets)})..."
                ))

                url_pattern     = mode_config.url_pattern
                ph_match        = _re.search(r'\{(\w+)\}', url_pattern)
                placeholder_key = ph_match.group(1) if ph_match else mode
                constructed_url = construct_url(
                    site_obj.base_url, url_pattern, site_dict,
                    mode=mode, **{placeholder_key: query}
                )
                from loguru import logger as _logger
                _logger.debug(f"[GUI] URL: {constructed_url}")

                current_url  = constructed_url
                current_page = start_page
                while current_url:
                    if self._stop_event.is_set(): break
                    next_url, next_page, ok = process_list_page(
                        current_url, site_dict, general_config,
                        page_num=current_page, video_offset=0,
                        mode=mode, identifier=query,
                        overwrite=overwrite,
                        headers=general_config.get('headers', {}),
                        new_nfo=re_nfo,
                        apply_state=self.applystate_var.get(),
                        state_set=state_set,
                        after_date=after_date,
                        min_duration=min_duration,
                        dl_progress_cb=dl_progress_cb,
                        video_info_cb=video_info_cb,
                        global_progress_cb=global_progress_cb,
                        stop_event=self._stop_event,
                    )
                    current_url = next_url
                    if next_page: current_page = next_page
                    if current_url and not self._stop_event.is_set():
                        _time.sleep(
                            general_config.get('sleep', {}).get('between_pages', 3)
                        )

            if not self._stop_event.is_set():
                self.log_queue.put(("log",
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                    "\u2714 Finished successfully."))
                self.root.after(0, lambda: self.status_var.set("\u2714 Finished!"))
            else:
                self.root.after(0, lambda: self.status_var.set("\u23f9 Stopped by user."))

        except Exception as exc:
            import traceback
            self.log_queue.put(("log", f"ERROR: {traceback.format_exc()}"))
            self.root.after(0, lambda s=str(exc): self.status_var.set(f"\u2718 Error: {s}"))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self._remove_loguru_sink()
            self.root.after(0, lambda: self.run_button.config(state="normal"))
            self.root.after(0, lambda: self.stop_button.config(state="disabled"))


def launch_gui():
    root = tk.Tk()
    app  = SmutscrapeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
