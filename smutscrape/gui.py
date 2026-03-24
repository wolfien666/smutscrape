#!/usr/bin/env python3
"""
GUI Module for Smutscrape
A functional Tkinter-based GUI for scraping with all filters.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import sys
import os
import queue
import datetime

# Ensure the parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url


class QueueHandler:
    """Redirect stdout/stderr to a tkinter Text widget via a thread-safe queue."""
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, msg):
        if msg and msg.strip():
            self.log_queue.put(msg)

    def flush(self):
        pass


class SmutscrapeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smutscrape GUI")
        self.root.geometry("750x640")
        self.root.resizable(True, True)
        self.log_queue = queue.Queue()
        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self):
        # ── Top frame: site + mode + query ──────────────────────────────────
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

        # ── Filters frame ────────────────────────────────────────────────────
        filters = tk.LabelFrame(self.root, text="Filters", padx=8, pady=6)
        filters.pack(fill="x", padx=10, pady=4)

        tk.Label(filters, text="After Date:", width=14, anchor="e").grid(row=0, column=0, sticky="e", pady=3)
        self.after_entry = tk.Entry(filters, width=18)
        self.after_entry.insert(0, "")
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

        # ── Options frame ────────────────────────────────────────────────────
        opts = tk.LabelFrame(self.root, text="Options", padx=8, pady=4)
        opts.pack(fill="x", padx=10, pady=4)

        self.overwrite_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Overwrite existing files", variable=self.overwrite_var).grid(row=0, column=0, sticky="w", padx=10)

        self.renfo_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Regenerate .nfo files", variable=self.renfo_var).grid(row=0, column=1, sticky="w", padx=10)

        self.applystate_var = tk.BooleanVar()
        tk.Checkbutton(opts, text="Apply state (skip already seen)", variable=self.applystate_var).grid(row=0, column=2, sticky="w", padx=10)

        # ── Run / Stop buttons ───────────────────────────────────────────────
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=6)
        self.run_button = tk.Button(
            btn_frame, text="▶  Start Scraping", command=self._start_scraping,
            bg="#2e7d32", fg="white", font=("Helvetica", 10, "bold"), padx=16, pady=4
        )
        self.run_button.pack(side="left", padx=8)
        self.clear_button = tk.Button(
            btn_frame, text="Clear Log", command=self._clear_log,
            bg="#555", fg="white", padx=10, pady=4
        )
        self.clear_button.pack(side="left", padx=8)

        # ── Status bar ───────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Label(self.root, textvariable=self.status_var, anchor="w",
                              relief="sunken", fg="#1a5276", font=("Helvetica", 9))
        status_bar.pack(fill="x", padx=10)

        # ── Log output ───────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(self.root, text="Log Output", padx=4, pady=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, state="disabled", wrap="word",
            bg="#1e1e1e", fg="#d4d4d4", font=("Courier", 9),
            height=12
        )
        self.log_text.pack(fill="both", expand=True)
        # Colour tags
        self.log_text.tag_config("filter", foreground="#5dade2")
        self.log_text.tag_config("success", foreground="#58d68d")
        self.log_text.tag_config("error", foreground="#ec7063")
        self.log_text.tag_config("warn", foreground="#f39c12")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _on_site_selected(self, event=None):
        site_name = self.site_var.get()
        site_obj = next((s for s in self.sites.values() if s.name == site_name), None)
        if not site_obj:
            return
        modes = [m for m in site_obj.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes:
            self.mode_combo.current(0)

    def _log(self, msg, tag=None):
        """Append a line to the log widget (must be called from main thread)."""
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag or "")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _poll_log_queue(self):
        """Check the queue for new log messages every 150 ms."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                # Choose colour tag based on keywords
                low = msg.lower()
                if "[filter]" in low or "skip" in low:
                    tag = "filter"
                elif "success" in low or "finished" in low:
                    tag = "success"
                elif "error" in low or "failed" in low:
                    tag = "error"
                elif "warn" in low:
                    tag = "warn"
                else:
                    tag = None
                self._log(msg.rstrip(), tag)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_log_queue)

    # ── scraping ─────────────────────────────────────────────────────────────

    def _start_scraping(self):
        site_name = self.site_var.get()
        mode = self.mode_var.get()
        query = self.query_entry.get().strip()

        if not site_name:
            messagebox.showwarning("Input Error", "Please select a site.")
            return
        if not mode:
            messagebox.showwarning("Input Error", "Please select a mode.")
            return
        if not query:
            messagebox.showwarning("Input Error", "Please enter a query / identifier.")
            return

        self.run_button.config(state="disabled")
        self.status_var.set("Scraping in progress...")
        self._log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting: site={site_name}  mode={mode}  query={query}", "success")

        t = threading.Thread(
            target=self._run_task,
            args=(site_name, mode, query),
            daemon=True
        )
        t.start()

    def _run_task(self, site_name, mode, query):
        # Redirect stdout/stderr into the log queue for this thread
        handler = QueueHandler(self.log_queue)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = handler
        sys.stderr = handler

        try:
            site_obj = next((s for s in self.sites.values() if s.name == site_name), None)
            if not site_obj:
                raise ValueError(f"Site '{site_name}' not found.")

            general_config = load_configuration('general')
            state_set = get_session_manager().processed_urls if self.applystate_var.get() else set()

            mode_config = site_obj.modes.get(mode)
            if not mode_config:
                raise ValueError(f"Mode '{mode}' not found for site '{site_name}'.")

            # mode_config is a ModeConfig dataclass — use attribute access
            url_pattern = mode_config.url_pattern
            constructed_url = construct_url(
                site_obj.base_url,
                url_pattern,
                site_obj.to_dict(),
                mode=mode,
                **{mode: query}
            )

            after_date = self.after_entry.get().strip() or None
            min_duration = self.min_dur_entry.get().strip() or None
            overwrite = self.overwrite_var.get()
            re_nfo = self.renfo_var.get()

            try:
                start_page = int(self.page_entry.get().strip())
            except (ValueError, AttributeError):
                start_page = 1

            current_url = constructed_url
            current_page = start_page

            import time as _time
            while current_url:
                next_url, next_page, ok = process_list_page(
                    current_url,
                    site_obj.to_dict(),
                    general_config,
                    page_num=current_page,
                    video_offset=0,
                    mode=mode,
                    identifier=query,
                    overwrite=overwrite,
                    headers=general_config.get('headers', {}),
                    new_nfo=re_nfo,
                    apply_state=self.applystate_var.get(),
                    state_set=state_set,
                    after_date=after_date,
                    min_duration=min_duration
                )
                current_url = next_url
                if next_page:
                    current_page = next_page
                if current_url:
                    sleep_s = general_config.get('sleep', {}).get('between_pages', 3)
                    _time.sleep(sleep_s)

            self.log_queue.put(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Finished successfully.")
            self.root.after(0, lambda: self.status_var.set("Finished!"))

        except Exception as exc:
            import traceback
            err_msg = traceback.format_exc()
            self.log_queue.put(f"ERROR: {err_msg}")
            self.root.after(0, lambda: self.status_var.set(f"Error: {exc}"))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.root.after(0, lambda: self.run_button.config(state="normal"))


def launch_gui():
    root = tk.Tk()
    app = SmutscrapeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
