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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url


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

    Handles:
      - bare integer / float seconds:   "1385"  -> "00:23:05"
      - ISO 8601:                        "PT23M5S" -> "00:23:05"
      - already HH:MM:SS or MM:SS       passed through after normalisation
    """
    if not raw:
        return ""
    raw = str(raw).strip()

    # ISO 8601  PT1H23M45S
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", raw, _re.IGNORECASE)
    if m and any(m.groups()):
        total_s = int(float(m.group(1) or 0)) * 3600 \
                + int(float(m.group(2) or 0)) * 60 \
                + int(float(m.group(3) or 0))
        h, rem = divmod(total_s, 3600)
        mn, s  = divmod(rem, 60)
        return f"{h:02d}:{mn:02d}:{s:02d}"

    # HH:MM:SS or MM:SS — already colon-delimited, just zero-pad
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

    # Bare seconds (integer or float)
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
        self.root.geometry("820x780")
        self.root.resizable(True, True)
        self.log_queue = queue.Queue()
        self._loguru_sink_id = None
        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self):
        # ── Target ────────────────────────────────────────────────────────────
        top = tk.LabelFrame(self.root, text="Target", padx=8, pady=6)
        top.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(top, text="Site:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.site_manager = get_site_manager()
        self.sites = self.site_manager.sites
        self.site_names = sorted([s.name for s in self.sites.values()])
        self.site_var = tk.StringVar()
        self.site_combo = ttk.Combobox(top, textvariable=self.site_var, values=self.site_names, width=30, state="readonly")
        self.site_combo.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        self.site_combo.bind("<<ComboboxSelected>>", self._on_site_selected)

        tk.Label(top, text="Mode:", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, width=20, state="readonly")
        self.mode_combo.grid(row=1, column=1, sticky="w", padx=6, pady=3)

        tk.Label(top, text="Query:", width=14, anchor="e").grid(row=2, column=0, sticky="e", pady=3)
        self.query_entry = tk.Entry(top, width=50)
        self.query_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=3)
        top.columnconfigure(1, weight=1)

        # ── Filters ───────────────────────────────────────────────────────────
        filters = tk.LabelFrame(self.root, text="Filters", padx=8, pady=6)
        filters.pack(fill="x", padx=10, pady=4)

        tk.Label(filters, text="After Date:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.after_entry = tk.Entry(filters, width=18)
        self.after_entry.grid(row=0, column=1, sticky="w", padx=6)
        tk.Label(filters, text="YYYY-MM  or  YYYY-MM-DD", fg="grey").grid(row=0, column=2, sticky="w")

        tk.Label(filters, text="Min Duration (min):", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=3)
        self.min_dur_entry = tk.Entry(filters, width=8)
        self.min_dur_entry.grid(row=1, column=1, sticky="w", padx=6)
        tk.Label(filters, text="e.g. 10  (skip videos shorter than this)", fg="grey").grid(row=1, column=2, sticky="w")

        tk.Label(filters, text="Start Page:", width=14, anchor="e").grid(row=2, column=0, sticky="e", pady=3)
        self.page_entry = tk.Entry(filters, width=8)
        self.page_entry.insert(0, "1")
        self.page_entry.grid(row=2, column=1, sticky="w", padx=6)
        tk.Label(filters, text="Begin scraping from this page number", fg="grey").grid(row=2, column=2, sticky="w")

        # ── Options ───────────────────────────────────────────────────────────
        opts = tk.LabelFrame(self.root, text="Options", padx=8, pady=4)
        opts.pack(fill="x", padx=10, pady=4)
        self.overwrite_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Overwrite existing files", variable=self.overwrite_var).grid(row=0, column=0, sticky="w", padx=10)
        self.renfo_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Regenerate .nfo files", variable=self.renfo_var).grid(row=0, column=1, sticky="w", padx=10)
        self.applystate_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Apply state (skip already seen)", variable=self.applystate_var).grid(row=0, column=2, sticky="w", padx=10)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=6)
        self.run_button = tk.Button(
            btn_frame, text="\u25b6  Start Scraping", command=self._start_scraping,
            bg="#2e7d32", fg="white", font=("Helvetica", 10, "bold"), padx=16, pady=4
        )
        self.run_button.pack(side="left", padx=8)
        tk.Button(btn_frame, text="Clear Log", command=self._clear_log,
                  bg="#555", fg="white", padx=10, pady=4).pack(side="left", padx=8)

        # ── Progress panel ────────────────────────────────────────────────────
        prog_frame = tk.LabelFrame(self.root, text="Progress", padx=8, pady=6)
        prog_frame.pack(fill="x", padx=10, pady=(2, 4))
        prog_frame.columnconfigure(1, weight=1)

        tk.Label(prog_frame, text="Current video:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=2)
        self.video_title_var = tk.StringVar(value="—")
        tk.Label(prog_frame, textvariable=self.video_title_var, anchor="w",
                 fg="#1a5276", font=("Helvetica", 9, "bold")).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)

        tk.Label(prog_frame, text="Date / Duration:", width=14, anchor="e").grid(row=1, column=0, sticky="e", pady=2)
        self.video_meta_var = tk.StringVar(value="—")
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

    # ── helpers ──────────────────────────────────────────────────────────────

    def _on_site_selected(self, event=None):
        site_name = self.site_var.get()
        site_obj  = next((s for s in self.sites.values() if s.name == site_name), None)
        if not site_obj: return
        modes = [m for m in site_obj.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes: self.mode_combo.current(0)

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
        self.video_title_var.set(title or "—")
        parts = []
        if date:     parts.append(f"\U0001f4c5 {date}")
        dur_fmt = _format_duration(duration)
        if dur_fmt:  parts.append(f"\u23f1 {dur_fmt}")
        self.video_meta_var.set("   ".join(parts) if parts else "—")
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

    # ── scraping ─────────────────────────────────────────────────────────────

    def _start_scraping(self):
        site_name = self.site_var.get()
        mode      = self.mode_var.get()
        query     = self.query_entry.get().strip()
        if not site_name: messagebox.showwarning("Input Error", "Please select a site.");  return
        if not mode:      messagebox.showwarning("Input Error", "Please select a mode.");  return
        if not query:     messagebox.showwarning("Input Error", "Please enter a query.");   return

        self.dl_bar["value"]     = 0
        self.dl_pct_var.set("")
        self.global_bar["value"] = 0
        self.global_pct_var.set("")
        self.video_title_var.set("—")
        self.video_meta_var.set("—")

        self.run_button.config(state="disabled")
        self.status_var.set("Scraping in progress...")
        self._install_loguru_sink()
        self._log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting: site={site_name}  mode={mode}  query={query}", "success")
        threading.Thread(target=self._run_task, args=(site_name, mode, query), daemon=True).start()

    def _run_task(self, site_name, mode, query):
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

            url_pattern     = mode_config.url_pattern
            ph_match        = _re.search(r'\{(\w+)\}', url_pattern)
            placeholder_key = ph_match.group(1) if ph_match else mode

            site_dict = site_obj.to_dict()

            constructed_url = construct_url(
                site_obj.base_url, url_pattern, site_dict,
                mode=mode, **{placeholder_key: query}
            )

            from loguru import logger as _logger
            _logger.debug(f"[GUI] Constructed URL for page 1: {constructed_url}")

            after_date   = self.after_entry.get().strip()   or None
            min_duration = self.min_dur_entry.get().strip() or None
            overwrite    = self.overwrite_var.get()
            re_nfo       = self.renfo_var.get()
            try:    start_page = int(self.page_entry.get().strip())
            except: start_page = 1

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
                )
                current_url = next_url
                if next_page: current_page = next_page
                if current_url:
                    _time.sleep(general_config.get('sleep', {}).get('between_pages', 3))

            self.log_queue.put(("log", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Finished successfully."))
            self.root.after(0, lambda: self.status_var.set("Finished!"))

        except Exception as exc:
            import traceback
            self.log_queue.put(("log", f"ERROR: {traceback.format_exc()}"))
            self.root.after(0, lambda s=str(exc): self.status_var.set(f"Error: {s}"))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self._remove_loguru_sink()
            self.root.after(0, lambda: self.run_button.config(state="normal"))


def launch_gui():
    root = tk.Tk()
    app  = SmutscrapeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
