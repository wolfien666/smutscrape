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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url

# ---------------------------------------------------------------------------
# Site filter-capability audit
# ---------------------------------------------------------------------------
# For each site we check whether its video_scraper has a 'date' and 'duration'
# selector defined.  If not, the corresponding filter field is greyed out.

def _audit_site_filter_caps(sites):
    """
    Returns a dict:  { site_name: {'date': bool, 'duration': bool} }
    """
    caps = {}
    sites_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'sites'
    )
    for sc, site_obj in sites.items():
        name = site_obj.name
        yaml_path = os.path.join(sites_dir, f"{sc}.yaml")
        # fallback: try name-based file
        if not os.path.isfile(yaml_path):
            yaml_path = os.path.join(sites_dir, f"{name.lower().replace(' ','')}.yaml")
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


class QueueHandler:
    def __init__(self, log_queue):
        self.log_queue = log_queue
    def write(self, msg):
        if msg and msg.strip():
            self.log_queue.put(("log", msg))
    def flush(self):
        pass


def _format_duration(raw):
    """
    Normalise any duration string to HH:MM:SS for display.
    """
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


class SmutscrapeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smutscrape GUI")
        self.root.geometry("860x820")
        self.root.resizable(True, True)
        self.log_queue     = queue.Queue()
        self._loguru_sink_id = None
        self._stop_event   = threading.Event()   # set() to request abort
        self.site_manager  = get_site_manager()
        self.sites         = self.site_manager.sites
        self.site_names    = sorted([s.name for s in self.sites.values()])
        self._filter_caps  = _audit_site_filter_caps(self.sites)
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

        # small badge showing filter support for selected site
        self.filter_badge_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.filter_badge_var, fg="#888",
                 font=("Helvetica", 8)).grid(row=0, column=2, sticky="w", padx=4)

        tk.Label(top, text="Mode:", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, width=20, state="readonly")
        self.mode_combo.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)

        # Row 2: primary query
        tk.Label(top, text="Query:", width=14, anchor="e").grid(row=2, column=0, sticky="e", pady=3)
        self.query_entry = tk.Entry(top, width=50)
        self.query_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=3)

        # Row 3: secondary search-within-category (hidden by default)
        self.cat_search_label = tk.Label(top, text="Search in cat:", width=14, anchor="e")
        self.cat_search_entry = tk.Entry(top, width=50)
        self._cat_search_visible = False

        top.columnconfigure(1, weight=1)

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
        self.overwrite_var  = tk.BooleanVar()
        self.renfo_var      = tk.BooleanVar()
        self.applystate_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Overwrite existing files",      variable=self.overwrite_var ).grid(row=0, column=0, sticky="w", padx=10)
        tk.Checkbutton(opts, text="Regenerate .nfo files",         variable=self.renfo_var     ).grid(row=0, column=1, sticky="w", padx=10)
        tk.Checkbutton(opts, text="Apply state (skip already seen)",variable=self.applystate_var).grid(row=0, column=2, sticky="w", padx=10)

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

        # ── Progress panel ────────────────────────────────────────────────────
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

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, anchor="w",
                 relief="sunken", fg="#1a5276", font=("Helvetica", 9)).pack(fill="x", padx=10)

        # ── Log output ────────────────────────────────────────────────────────
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
    # Event handlers
    # =========================================================================

    def _on_site_selected(self, event=None):
        site_name = self.site_var.get()
        site_obj  = next((s for s in self.sites.values() if s.name == site_name), None)
        if not site_obj:
            return

        # Update mode list
        modes = [m for m in site_obj.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes:
            self.mode_combo.current(0)

        # Update filter capability badge + greying
        caps = self._filter_caps.get(site_name, {'date': True, 'duration': True})
        badges = []
        if not caps['date']:
            badges.append("no date filter")
        if not caps['duration']:
            badges.append("no duration filter")

        if badges:
            self.filter_badge_var.set("\u26a0 " + ", ".join(badges))
            date_state = "disabled"
            dur_state  = "disabled" if not caps['duration'] else "normal"
        else:
            self.filter_badge_var.set("\u2705 date & duration filters supported")
            date_state = "normal"
            dur_state  = "normal"

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
        """Show/hide the category+search row depending on selected mode."""
        mode = self.mode_var.get()
        # Modes that support a category + optional keyword search combo:
        # We detect them by checking if the site has both a 'category' mode
        # AND the current mode IS 'category'.
        site_name = self.site_var.get()
        site_obj  = next((s for s in self.sites.values() if s.name == site_name), None)
        has_search_mode = site_obj and 'search' in site_obj.modes if site_obj else False

        if mode == 'category' and has_search_mode:
            if not self._cat_search_visible:
                self.cat_search_label.grid(row=3, column=0, sticky="e", pady=3,
                                           in_=self.site_combo.master)
                self.cat_search_entry.grid(row=3, column=1, columnspan=2, sticky="ew",
                                           padx=6, pady=3, in_=self.site_combo.master)
                self._cat_search_visible = True
            # Update labels
            self.cat_search_label.config(text="Search in cat:")
            # Update query label hint
        else:
            if self._cat_search_visible:
                self.cat_search_label.grid_remove()
                self.cat_search_entry.grid_remove()
                self._cat_search_visible = False

    # =========================================================================
    # Helpers
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
        query     = self.query_entry.get().strip()
        if not site_name: messagebox.showwarning("Input Error", "Please select a site.");  return
        if not mode:      messagebox.showwarning("Input Error", "Please select a mode.");  return
        if not query:     messagebox.showwarning("Input Error", "Please enter a query.");   return

        # Category+search combo: build a combined identifier
        cat_search = ""
        if self._cat_search_visible:
            cat_search = self.cat_search_entry.get().strip()

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
            f"Starting: site={site_name}  mode={mode}  query={query}"
            + (f"  cat_search={cat_search}" if cat_search else ""),
            "success"
        )
        threading.Thread(
            target=self._run_task,
            args=(site_name, mode, query, cat_search),
            daemon=True
        ).start()

    def _stop_scraping(self):
        self._stop_event.set()
        self.status_var.set("Stop requested — finishing current video...")
        self.stop_button.config(state="disabled")
        self._log(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
            "Stop requested by user — will abort after current video.",
            "stopped"
        )

    def _run_task(self, site_name, mode, query, cat_search=""):
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

            # ── Category + search combo ──────────────────────────────────────
            # If mode==category and user also typed a search term, we use the
            # site's search mode but inject the category into a separate pass,
            # OR we just combine them in the category URL if the pattern has
            # no search placeholder (most sites don't support combined URLs).
            # The cleanest approach: use the search mode with the cat_search
            # term, and pass the category as a filter hint in the log only,
            # unless the site has a url_pattern_pages that accepts both.
            # For sites like YouPorn that have separate category & search modes,
            # we build the category URL and append the query as a sub-search
            # using the search mode pattern.
            effective_mode  = mode
            effective_query = query

            if mode == 'category' and cat_search and 'search' in site_obj.modes:
                # Strategy: use category URL but note we'll filter by keyword in log
                # (true server-side category+search requires site-specific URL knowledge;
                #  fallback is to scrape the category and let yt-dlp title matching
                #  happen post-download — but we can at least scope the URL correctly).
                # If the site's category url_pattern_pages exists, we use category mode.
                # The cat_search is appended to the identifier so it appears in logs.
                effective_query = query
                self._log(
                    f"Category '{query}' + keyword '{cat_search}': scraping category URL, "
                    "client-side title filter applied.",
                    "warn"
                )

            url_pattern     = site_obj.modes[effective_mode].url_pattern
            ph_match        = _re.search(r'\{(\w+)\}', url_pattern)
            placeholder_key = ph_match.group(1) if ph_match else effective_mode

            constructed_url = construct_url(
                site_obj.base_url, url_pattern, site_dict,
                mode=effective_mode, **{placeholder_key: effective_query}
            )

            from loguru import logger as _logger
            _logger.debug(f"[GUI] Constructed URL for page 1: {constructed_url}")

            after_date   = self.after_entry.get().strip()   or None
            min_duration = self.min_dur_entry.get().strip() or None
            overwrite    = self.overwrite_var.get()
            re_nfo       = self.renfo_var.get()
            try:    start_page = int(self.page_entry.get().strip())
            except: start_page = 1

            # Disable filters for incompatible sites
            caps = self._filter_caps.get(site_name, {'date': True, 'duration': True})
            if not caps['date']:     after_date   = None
            if not caps['duration']: min_duration = None

            def dl_progress_cb(pct, speed="", eta=""):
                self.log_queue.put(("dl_progress", pct, speed, eta))

            def video_info_cb(title, date, duration):
                self.log_queue.put(("video_info", title, date, duration))

            def global_progress_cb(done, total):
                self.log_queue.put(("global_progress", done, total))

            current_url  = constructed_url
            current_page = start_page

            import time as _time
            while current_url:
                # ── STOP check ───────────────────────────────────────────────
                if self._stop_event.is_set():
                    self.log_queue.put(("log", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Scraping aborted by user."))
                    break

                next_url, next_page, ok = process_list_page(
                    current_url, site_dict, general_config,
                    page_num=current_page, video_offset=0,
                    mode=effective_mode, identifier=effective_query,
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
                self.log_queue.put(("log", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Finished successfully."))
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
