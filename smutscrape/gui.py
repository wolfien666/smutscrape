#!/usr/bin/env python3
"""
GUI Module for Smutscrape
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
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url

_SITES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'sites'
)

# ---------------------------------------------------------------------------
# Site filter-capability audit
# ---------------------------------------------------------------------------

def _audit_site_filter_caps(sites):
    caps = {}
    for sc, site_obj in sites.items():
        name = site_obj.name
        yaml_path = os.path.join(_SITES_DIR, f"{sc}.yaml")
        if not os.path.isfile(yaml_path):
            yaml_path = os.path.join(_SITES_DIR, f"{name.lower().replace(' ','')}.yaml")
        has_date = False
        has_dur  = False
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


# ---------------------------------------------------------------------------
# Category database loader
# ---------------------------------------------------------------------------

def _load_category_db():
    """
    Returns dict: { shortcode: { mode_name: [slug, ...] } }
    Loaded from sites/categories.yaml.
    """
    cat_file = os.path.join(_SITES_DIR, 'categories.yaml')
    try:
        with open(cat_file) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        total_s = int(float(m.group(1) or 0)) * 3600 \
                + int(float(m.group(2) or 0)) * 60 \
                + int(float(m.group(3) or 0))
        h, rem = divmod(total_s, 3600)
        mn, s  = divmod(rem, 60)
        return f"{h:02d}:{mn:02d}:{s:02d}"
    if ":" in raw:
        parts = raw.split(":")
        try:
            parts = [int(p) for p in parts]
            if len(parts) == 2:
                return f"00:{parts[0]:02d}:{parts[1]:02d}"
            if len(parts) == 3:
                return f"{parts[0]:02d}:{parts[1]:02d}:{parts[2]:02d}"
        except ValueError:
            return raw
    try:
        total_s = int(float(raw))
        h, rem  = divmod(total_s, 3600)
        mn, s   = divmod(rem, 60)
        return f"{h:02d}:{mn:02d}:{s:02d}"
    except ValueError:
        return raw


# ---------------------------------------------------------------------------
# Main GUI class
# ---------------------------------------------------------------------------

class SmutscrapeGUI:
    def __init__(self, root):
        self.root          = root
        self.root.title("Smutscrape GUI")
        self.root.geometry("900x900")
        self.root.resizable(True, True)
        self.log_queue       = queue.Queue()
        self._loguru_sink_id = None
        self._stop_event     = threading.Event()
        self.site_manager    = get_site_manager()
        self.sites           = self.site_manager.sites
        self.site_names      = sorted([s.name for s in self.sites.values()])
        self._filter_caps    = _audit_site_filter_caps(self.sites)
        self._cat_db         = _load_category_db()   # { shortcode: {mode: [slug]} }
        self._cat_vars       = {}    # { slug: BooleanVar }  for current checkbox panel
        self._build_ui()
        self._poll_log_queue()

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_ui(self):
        # ── Target ────────────────────────────────────────────────────────────
        top = tk.LabelFrame(self.root, text="Target", padx=8, pady=6)
        top.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(top, text="Site:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.site_var = tk.StringVar()
        self.site_combo = ttk.Combobox(
            top, textvariable=self.site_var, values=self.site_names, width=30, state="readonly"
        )
        self.site_combo.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        self.site_combo.bind("<<ComboboxSelected>>", self._on_site_selected)

        self.filter_badge_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.filter_badge_var, fg="#888",
                 font=("Helvetica", 8)).grid(row=0, column=2, sticky="w", padx=4)

        tk.Label(top, text="Mode:", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, width=20, state="readonly")
        self.mode_combo.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)

        # Query row — label changes depending on mode
        self.query_label_var = tk.StringVar(value="Query:")
        tk.Label(top, textvariable=self.query_label_var, width=14, anchor="e").grid(
            row=2, column=0, sticky="e", pady=3
        )
        self.query_entry = tk.Entry(top, width=50)
        self.query_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=3)
        top.columnconfigure(1, weight=1)

        # ── Category picker (hidden until a mode with categories is selected) ──
        self.cat_frame = tk.LabelFrame(
            self.root, text="Categories  (check one or more — each will be scraped in order)",
            padx=6, pady=6
        )
        # cat_frame is packed/unpacked dynamically by _refresh_cat_panel
        # Inner scrollable canvas for the checkboxes
        self._cat_canvas      = tk.Canvas(self.cat_frame, height=130, bg="#f8f8f8",
                                          highlightthickness=0)
        self._cat_scrollbar   = ttk.Scrollbar(self.cat_frame, orient="vertical",
                                              command=self._cat_canvas.yview)
        self._cat_inner_frame = tk.Frame(self._cat_canvas, bg="#f8f8f8")
        self._cat_inner_id    = self._cat_canvas.create_window(
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

        # Buttons row inside cat_frame: Select All / Clear All
        btn_cat = tk.Frame(self.cat_frame)
        btn_cat.pack(fill="x", pady=(4, 0))
        tk.Button(btn_cat, text="Select All", command=self._cat_select_all,
                  bg="#1a5276", fg="white", padx=8, pady=2,
                  font=("Helvetica", 8)).pack(side="left", padx=4)
        tk.Button(btn_cat, text="Clear All", command=self._cat_clear_all,
                  bg="#555", fg="white", padx=8, pady=2,
                  font=("Helvetica", 8)).pack(side="left", padx=4)
        tk.Label(btn_cat,
                 text="Tip: leaving all unchecked falls back to the Query field above",
                 fg="#888", font=("Helvetica", 8)).pack(side="left", padx=10)

        # ── Filters ───────────────────────────────────────────────────────────
        filters = tk.LabelFrame(self.root, text="Filters", padx=8, pady=6)
        filters.pack(fill="x", padx=10, pady=4)

        tk.Label(filters, text="After Date:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.after_entry = tk.Entry(filters, width=18)
        self.after_entry.grid(row=0, column=1, sticky="w", padx=6)
        self.after_hint = tk.Label(filters, text="YYYY-MM  or  YYYY-MM-DD", fg="grey")
        self.after_hint.grid(row=0, column=2, sticky="w")

        tk.Label(filters, text="Min Duration (min):", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.min_dur_entry = tk.Entry(filters, width=8)
        self.min_dur_entry.grid(row=1, column=1, sticky="w", padx=6)
        self.dur_hint = tk.Label(filters, text="e.g. 10  (skip videos shorter than this)", fg="grey")
        self.dur_hint.grid(row=1, column=2, sticky="w")

        tk.Label(filters, text="Start Page:", width=14, anchor="e").grid(row=2, column=0, sticky="e", pady=3)
        self.page_entry = tk.Entry(filters, width=8)
        self.page_entry.insert(0, "1")
        self.page_entry.grid(row=2, column=1, sticky="w", padx=6)
        tk.Label(filters, text="Begin scraping from this page number", fg="grey").grid(row=2, column=2, sticky="w")

        # ── Options ───────────────────────────────────────────────────────────
        opts = tk.LabelFrame(self.root, text="Options", padx=8, pady=4)
        opts.pack(fill="x", padx=10, pady=4)
        self.overwrite_var   = tk.BooleanVar()
        self.renfo_var       = tk.BooleanVar()
        self.applystate_var  = tk.BooleanVar()
        tk.Checkbutton(opts, text="Overwrite existing files",       variable=self.overwrite_var ).grid(row=0, column=0, sticky="w", padx=10)
        tk.Checkbutton(opts, text="Regenerate .nfo files",          variable=self.renfo_var     ).grid(row=0, column=1, sticky="w", padx=10)
        tk.Checkbutton(opts, text="Apply state (skip already seen)", variable=self.applystate_var).grid(row=0, column=2, sticky="w", padx=10)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=6)
        self.run_button = tk.Button(
            btn_frame, text="\u25b6  Start Scraping", command=self._start_scraping,
            bg="#2e7d32", fg="white", font=("Helvetica", 10, "bold"), padx=16, pady=4
        )
        self.run_button.pack(side="left", padx=8)
        self.stop_button = tk.Button(
            btn_frame, text="\u23f9  Stop", command=self._stop_scraping,
            bg="#c0392b", fg="white", font=("Helvetica", 10, "bold"), padx=16, pady=4,
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=8)
        tk.Button(
            btn_frame, text="Clear Log", command=self._clear_log,
            bg="#555", fg="white", padx=10, pady=4
        ).pack(side="left", padx=8)

        # ── Progress ───────────────────────────────────────────────────────────
        prog_frame = tk.LabelFrame(self.root, text="Progress", padx=8, pady=6)
        prog_frame.pack(fill="x", padx=10, pady=(2, 4))
        prog_frame.columnconfigure(1, weight=1)

        tk.Label(prog_frame, text="Current video:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=2)
        self.video_title_var = tk.StringVar(value="\u2014")
        tk.Label(prog_frame, textvariable=self.video_title_var, anchor="w",
                 fg="#1a5276", font=("Helvetica", 9, "bold")).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)

        tk.Label(prog_frame, text="Date / Duration:", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=2)
        self.video_meta_var = tk.StringVar(value="\u2014")
        tk.Label(prog_frame, textvariable=self.video_meta_var, anchor="w",
                 fg="#555", font=("Helvetica", 9)).grid(row=1, column=1, columnspan=3, sticky="ew", padx=4)

        tk.Label(prog_frame, text="Download:", width=14, anchor="e").grid(row=2, column=0, sticky="e", pady=2)
        self.dl_bar = ttk.Progressbar(prog_frame, orient="horizontal", length=400, mode="determinate", maximum=100)
        self.dl_bar.grid(row=2, column=1, sticky="ew", padx=4)
        self.dl_pct_var = tk.StringVar(value="")
        tk.Label(prog_frame, textvariable=self.dl_pct_var, width=18, anchor="w",
                 font=("Courier", 9)).grid(row=2, column=2, sticky="w", padx=4)

        tk.Label(prog_frame, text="Query progress:", width=14, anchor="e").grid(row=3, column=0, sticky="e", pady=2)
        self.global_bar = ttk.Progressbar(prog_frame, orient="horizontal", length=400, mode="determinate", maximum=100)
        self.global_bar.grid(row=3, column=1, sticky="ew", padx=4)
        self.global_pct_var = tk.StringVar(value="")
        tk.Label(prog_frame, textvariable=self.global_pct_var, width=18, anchor="w",
                 font=("Courier", 9)).grid(row=3, column=2, sticky="w", padx=4)

        # ── Status bar ─────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, anchor="w",
                 relief="sunken", fg="#1a5276", font=("Helvetica", 9)).pack(fill="x", padx=10)

        # ── Log output ─────────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(self.root, text="Log Output", padx=4, pady=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, state="disabled", wrap="word",
            bg="#1e1e1e", fg="#d4d4d4", font=("Courier", 9), height=12
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("filter",  foreground="#5dade2")
        self.log_text.tag_config("success", foreground="#58d68d")
        self.log_text.tag_config("error",   foreground="#ec7063")
        self.log_text.tag_config("warn",    foreground="#f39c12")
        self.log_text.tag_config("stopped", foreground="#e67e22")

    # =========================================================================
    # Category panel helpers
    # =========================================================================

    def _get_shortcode_for_site(self, site_name):
        for sc, site_obj in self.sites.items():
            if site_obj.name == site_name:
                return sc
        return None

    def _refresh_cat_panel(self, slugs):
        """Rebuild the checkbox grid inside _cat_inner_frame."""
        # Destroy old checkboxes
        for w in self._cat_inner_frame.winfo_children():
            w.destroy()
        self._cat_vars = {}

        if not slugs:
            self.cat_frame.pack_forget()
            return

        # Build a 4-column grid of checkboxes, sorted alphabetically
        cols = 4
        for idx, slug in enumerate(sorted(slugs)):
            var = tk.BooleanVar(value=False)
            self._cat_vars[slug] = var
            label = slug.replace('-', ' ').title()
            cb = tk.Checkbutton(
                self._cat_inner_frame, text=label, variable=var,
                bg="#f8f8f8", anchor="w", padx=4
            )
            cb.grid(row=idx // cols, column=idx % cols, sticky="w", padx=4, pady=1)

        # Show the panel (insert it between Target and Filters)
        self.cat_frame.pack(fill="x", padx=10, pady=4,
                            before=self.root.pack_slaves()[1])  # after Target frame

    def _cat_select_all(self):
        for var in self._cat_vars.values():
            var.set(True)

    def _cat_clear_all(self):
        for var in self._cat_vars.values():
            var.set(False)

    def _get_checked_categories(self):
        """Return list of checked slugs (preserving alphabetical order)."""
        return [slug for slug, var in sorted(self._cat_vars.items()) if var.get()]

    # =========================================================================
    # Event handlers
    # =========================================================================

    def _on_site_selected(self, event=None):
        site_name = self.site_var.get()
        site_obj  = next((s for s in self.sites.values() if s.name == site_name), None)
        if not site_obj:
            return

        modes = [m for m in site_obj.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes:
            self.mode_combo.current(0)

        caps = self._filter_caps.get(site_name, {'date': True, 'duration': True})
        badges = []
        if not caps['date']:     badges.append("no date filter")
        if not caps['duration']: badges.append("no duration filter")
        if badges:
            self.filter_badge_var.set("\u26a0 " + ", ".join(badges))
        else:
            self.filter_badge_var.set("\u2705 date & duration filters supported")

        if not caps['date']:
            self.after_entry.config(state="disabled", bg="#e0e0e0")
            self.after_hint.config(fg="#aaa", text="not available for this site")
        else:
            self.after_entry.config(state="normal", bg="white")
            self.after_hint.config(fg="grey", text="YYYY-MM  or  YYYY-MM-DD")

        if not caps['duration']:
            self.min_dur_entry.config(state="disabled", bg="#e0e0e0")
            self.dur_hint.config(fg="#aaa", text="not available for this site")
        else:
            self.min_dur_entry.config(state="normal", bg="white")
            self.dur_hint.config(fg="grey", text="e.g. 10  (skip videos shorter than this)")

        self._on_mode_selected()

    def _on_mode_selected(self, event=None):
        mode      = self.mode_var.get()
        site_name = self.site_var.get()
        sc        = self._get_shortcode_for_site(site_name)

        # Look up categories for this site + mode
        slugs = []
        if sc and mode:
            slugs = self._cat_db.get(sc, {}).get(mode, [])

        # Update query label
        if mode in ('category', 'tag'):
            if slugs:
                self.query_label_var.set("Keyword (opt):")
            else:
                self.query_label_var.set("Category:")
        else:
            self.query_label_var.set("Query:")

        self._refresh_cat_panel(slugs)

    # =========================================================================
    # General helpers
    # =========================================================================

    def _log(self, msg, tag=None):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag or "")
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
        if date:    parts.append(f"\U0001f4c5 {date}")
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
                    if   "[filter]" in low or "skip" in low: tag = "filter"
                    elif "success"  in low or "finished" in low: tag = "success"
                    elif "stopped"  in low or "abort"    in low: tag = "stopped"
                    elif "error"    in low or "failed"   in low: tag = "error"
                    elif "warn"     in low:                       tag = "warn"
                    else:                                         tag = None
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

        # Determine the list of targets to run:
        # Either the checked categories, OR the free-text query field.
        checked_cats = self._get_checked_categories()
        free_query   = self.query_entry.get().strip()

        if checked_cats:
            targets = checked_cats   # run one scrape per checked category
        elif free_query:
            targets = [free_query]
        else:
            messagebox.showwarning("Input Error",
                "Please enter a query  OR  check at least one category.")
            return

        self.dl_bar["value"]     = 0
        self.dl_pct_var.set("")
        self.global_bar["value"] = 0
        self.global_pct_var.set("")
        self.video_title_var.set("\u2014")
        self.video_meta_var.set("\u2014")

        self._stop_event.clear()
        self.run_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Scraping in progress...")
        self._install_loguru_sink()
        self._log(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
            f"Starting: site={site_name}  mode={mode}  "
            f"targets={targets}",
            "success"
        )
        threading.Thread(
            target=self._run_task,
            args=(site_name, mode, targets),
            daemon=True
        ).start()

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
        """
        targets is a list of strings (category slugs or a single query).
        We iterate through them in order, honouring the stop event between each.
        """
        handler = QueueHandler(self.log_queue)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = handler

        try:
            site_obj = next((s for s in self.sites.values() if s.name == site_name), None)
            if not site_obj:
                raise ValueError(f"Site '{site_name}' not found.")

            general_config = load_configuration('general')
            state_set      = get_session_manager().processed_urls if self.applystate_var.get() else set()
            mode_config    = site_obj.modes.get(mode)
            if not mode_config:
                raise ValueError(f"Mode '{mode}' not found for site '{site_name}'.")

            site_dict = site_obj.to_dict()

            after_date   = self.after_entry.get().strip()   or None
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
                if self._stop_event.is_set():
                    break

                self.log_queue.put(("log",
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                    f"--- Category {target_idx+1}/{len(targets)}: '{query}' ---"
                ))
                self.root.after(0, lambda q=query: self.status_var.set(
                    f"Scraping '{q}' ({target_idx+1}/{len(targets)})..."
                ))

                url_pattern     = mode_config.url_pattern
                ph_match        = _re.search(r'\{(\w+)\}', url_pattern)
                placeholder_key = ph_match.group(1) if ph_match else mode

                constructed_url = construct_url(
                    site_obj.base_url, url_pattern, site_dict,
                    mode=mode, **{placeholder_key: query}
                )

                from loguru import logger as _logger
                _logger.debug(f"[GUI] Constructed URL for page 1: {constructed_url}")

                current_url  = constructed_url
                current_page = start_page

                while current_url:
                    if self._stop_event.is_set():
                        break

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
                        _time.sleep(general_config.get('sleep', {}).get('between_pages', 3))

            if not self._stop_event.is_set():
                self.log_queue.put(("log",
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Finished successfully."))
                self.root.after(0, lambda: self.status_var.set("Finished!"))
            else:
                self.root.after(0, lambda: self.status_var.set("Stopped by user."))

        except Exception as exc:
            import traceback
            self.log_queue.put(("log", f"ERROR: {traceback.format_exc()}"))
            self.root.after(0, lambda s=str(exc): self.status_var.set(f"Error: {s}"))
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
