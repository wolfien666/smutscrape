#!/usr/bin/env python3
"""
Browse & Pick Tab  —  Smutscrape

Self-contained module.  Attach to an existing ttk.Notebook with:

    from smutscrape.browse_tab import BrowseTab
    tab = BrowseTab(notebook, general_config, C, widget_factories)
    notebook.add(tab.frame, text="  📂  Browse & Pick  ")

Supported sites: xHamster, PornHub, YouPorn, XNXX, XVideos
"""

import os
import re
import io
import time
import queue
import threading
import datetime
import urllib.parse
import urllib.request
import subprocess
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from loguru import logger

# ---------------------------------------------------------------------------
# Site definitions  (search URL, thumb/title/duration/date CSS selectors)
# ---------------------------------------------------------------------------

SITES = {
    "xHamster": {
        "shortcode": "xh",
        "base": "https://xhamster.com",
        "search_url": "https://xhamster.com/search/{q}?page={page}",
        "search_url_p1": "https://xhamster.com/search/{q}",
        "use_selenium": True,
        "encoding": lambda s: s.replace(" ", "+"),
        # list-page card selectors
        "card":      "div.thumb-list__item.video-thumb",
        "thumb":     ("a.video-thumb__image-container img", "src"),
        "thumb_alt": ("a.video-thumb__image-container img", "data-src"),
        "url":       ("a.video-thumb__image-container", "href"),
        "title":     ("a.video-thumb-info__name", "title"),
        "duration":  ("div.thumb-image-container__duration", None),
        "date":      ("div.thumb-image-container__date, span.video-thumb-views__date", None),
    },
    "PornHub": {
        "shortcode": "ph",
        "base": "https://www.pornhub.com",
        "search_url": "https://www.pornhub.com/video/search?search={q}&page={page}",
        "search_url_p1": "https://www.pornhub.com/video/search?search={q}",
        "use_selenium": True,
        "encoding": lambda s: s.replace(" ", "+"),
        "card":      "li.pcVideoListItem",
        "thumb":     ("img.thumb, img[src*='phncdn']", "src"),
        "thumb_alt": ("img", "data-src"),
        "url":       ("a.linkVideoThumb", "href"),
        "title":     ("span.title a", "title"),
        "duration":  ("var.duration", None),
        "date":      ("var.added", None),
    },
    "YouPorn": {
        "shortcode": "yp",
        "base": "https://www.youporn.com",
        "search_url": "https://www.youporn.com/search/?query={q}&page={page}",
        "search_url_p1": "https://www.youporn.com/search/?query={q}",
        "use_selenium": True,
        "encoding": lambda s: urllib.parse.quote_plus(s),
        "card":      "li[class*='video'], div[class*='video-box'], article[class*='video']",
        "thumb":     ("img", "src"),
        "thumb_alt": ("img", "data-src"),
        "url":       ("a[href*='/watch/']", "href"),
        "title":     ("a[class*='title'],span[class*='title'],div[class*='title'],a[title]", "title"),
        "duration":  ("span[class*='duration'],div[class*='duration'],var[class*='duration']", None),
        "date":      ("time[datetime],span[class*='date']", "datetime"),
    },
    "XNXX": {
        "shortcode": "xn",
        "base": "https://www.xnxx.com",
        "search_url": "https://www.xnxx.com/search/{q}/{page_0}",
        "search_url_p1": "https://www.xnxx.com/search/{q}",
        "use_selenium": True,
        "encoding": lambda s: s.replace(" ", "+"),
        "page_offset": -1,   # XNXX page 2 => /1
        "card":      "div.thumb-under",
        "thumb":     ("img.thumb, img[src*='thumb']", "src"),
        "thumb_alt": ("img", "data-src"),
        "url":       ("a", "href"),
        "title":     ("a", "title"),
        "duration":  ("p.metadata", None),
        "date":      (None, None),
    },
    "XVideos": {
        "shortcode": "xv",
        "base": "https://www.xvideos.com",
        "search_url": "https://www.xvideos.com/?k={q}&p={page_0}",
        "search_url_p1": "https://www.xvideos.com/?k={q}",
        "use_selenium": True,
        "encoding": lambda s: s.replace(" ", "+"),
        "page_offset": -1,   # XVideos page 2 => p=1
        "card":      "div.thumb-under",
        "thumb":     ("img.thumb, img[src*='thumb']", "src"),
        "thumb_alt": ("img", "data-src"),
        "url":       ("a", "href"),
        "title":     ("a", "title"),
        "duration":  ("span.duration", None),
        "date":      (None, None),
    },
}

THUMB_W = 200
THUMB_H = 120
CARD_W   = 210
CARD_H   = 185   # thumb + title + meta
COLS     = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_search_url(site_cfg: dict, query: str, page: int) -> str:
    enc   = site_cfg["encoding"](query)
    off   = site_cfg.get("page_offset", 0)
    p0    = max(0, page + off)
    if page == 1:
        tpl = site_cfg["search_url_p1"]
        return tpl.replace("{q}", enc)
    tpl = site_cfg["search_url"]
    return tpl.replace("{q}", enc).replace("{page}", str(page)).replace("{page_0}", str(p0))


def _sel_first(soup, selector: Optional[str], attr: Optional[str]) -> str:
    if not selector:
        return ""
    try:
        el = soup.select_one(selector)
        if el is None:
            return ""
        if attr:
            return (el.get(attr) or "").strip()
        return el.get_text(" ", strip=True)
    except Exception:
        return ""


def _scrape_cards(soup, site_name: str) -> list:
    """
    Returns list of dicts: {url, title, duration, date, thumb_url}
    """
    cfg   = SITES[site_name]
    base  = cfg["base"]
    cards = soup.select(cfg["card"])
    results = []
    for card in cards:
        url = _sel_first(card, cfg["url"][0], cfg["url"][1])
        if not url:
            continue
        if url.startswith("/"):
            url = base + url
        title = _sel_first(card, cfg["title"][0], cfg["title"][1])
        if not title:
            # fallback: text of link
            a = card.select_one("a")
            title = a.get_text(strip=True) if a else url
        title = title[:80]

        duration = _sel_first(card, cfg["duration"][0], cfg["duration"][1])
        date     = _sel_first(card, cfg["date"][0],     cfg["date"][1])

        # thumb: try primary attribute, then fallback
        thumb_url = _sel_first(card, cfg["thumb"][0],     cfg["thumb"][1])
        if not thumb_url:
            thumb_url = _sel_first(card, cfg["thumb_alt"][0], cfg["thumb_alt"][1])

        results.append(dict(
            url=url, title=title,
            duration=duration.strip(), date=date.strip(),
            thumb_url=thumb_url,
        ))
    return results


def _fetch_thumb_bytes(url: str, timeout: int = 8) -> Optional[bytes]:
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _duration_passes(duration_str: str, min_min: Optional[float]) -> bool:
    """True if duration_str >= min_min minutes (or no filter / no data)."""
    if min_min is None or min_min <= 0:
        return True
    if not duration_str:
        return True   # can't tell — let it through
    # formats: "12:34", "1:02:34", "12 min", "734"  (seconds)
    s = duration_str.strip()
    m = re.match(r'(\d+):(\d{2}):(\d{2})', s)
    if m:
        mins = int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/60
        return mins >= min_min
    m = re.match(r'(\d+):(\d{2})', s)
    if m:
        mins = int(m.group(1)) + int(m.group(2))/60
        return mins >= min_min
    m = re.match(r'(\d+)', s)
    if m:
        val = float(m.group(1))
        # if it looks like raw seconds (>300) treat as seconds
        mins = val/60 if val > 300 else val
        return mins >= min_min
    return True


def _date_passes(date_str: str, after: Optional[datetime.date]) -> bool:
    """True if date_str >= after (or no filter / can't parse)."""
    if after is None:
        return True
    if not date_str:
        return True
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d",
                "%Y%m%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.datetime.strptime(date_str[:20], fmt).date()
            return d >= after
        except ValueError:
            continue
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d >= after
        except ValueError:
            pass
    return True


# ---------------------------------------------------------------------------
# BrowseTab
# ---------------------------------------------------------------------------

class BrowseTab:
    """
    A self-contained "Browse & Pick" notebook tab.

    Parameters
    ----------
    notebook      : ttk.Notebook  — parent notebook widget
    get_general_config : callable  — returns current general_config dict
    get_driver    : callable  — returns (or creates) the Selenium driver
    C             : dict  — colour palette from gui.py
    mk            : dict  — widget factory callables from gui.py
                   keys: label, entry, button, checkbutton, lf
    """

    def __init__(self, notebook, get_general_config, get_driver, C, mk):
        self._notebook          = notebook
        self._get_general_config = get_general_config
        self._get_driver        = get_driver
        self.C                  = C
        self._mk                = mk

        self.frame = tk.Frame(notebook, bg=C["bg"])

        # state
        self._results: list          = []          # current page results
        self._selected: dict         = {}          # url -> BooleanVar
        self._thumb_images: dict     = {}          # url -> ImageTk.PhotoImage
        self._card_frames: dict      = {}          # url -> Frame  (for highlight)
        self._page                   = 1
        self._current_query          = ""
        self._current_site           = ""
        self._loading                = False
        self._dl_queue: queue.Queue  = queue.Queue()
        self._stop_dl                = threading.Event()
        self._dl_thread: Optional[threading.Thread] = None

        self._build()
        self._poll_dl_queue()

    # ------------------------------------------------------------------ build

    def _build(self):
        C  = self.C
        mk = self._mk
        outer = self.frame

        # ── Search bar ───────────────────────────────────────────────────────
        bar = tk.Frame(outer, bg=C["panel"], pady=6)
        bar.pack(fill="x", padx=10, pady=(8, 4))

        mk["label"](bar, "Site:").pack(side="left", padx=(6, 2))
        self._site_var = tk.StringVar(value="xHamster")
        self._site_cb  = ttk.Combobox(
            bar, textvariable=self._site_var,
            values=list(SITES.keys()), width=12, state="readonly"
        )
        self._site_cb.pack(side="left", padx=(0, 10))

        mk["label"](bar, "Search:").pack(side="left", padx=(0, 2))
        self._search_entry = mk["entry"](bar, width=28)
        self._search_entry.pack(side="left", padx=(0, 8))
        self._search_entry.bind("<Return>", lambda e: self._do_search())

        mk["label"](bar, "After date:").pack(side="left", padx=(0, 2))
        self._date_entry = mk["entry"](bar, width=10)
        self._date_entry.insert(0, "")
        self._date_entry.pack(side="left", padx=(0, 4))
        mk["label"](bar, "YYYY-MM-DD", fg=C["fg_dim"], font=("Courier", 7)).pack(side="left", padx=(0, 10))

        mk["label"](bar, "Min dur (min):").pack(side="left", padx=(0, 2))
        self._dur_entry = mk["entry"](bar, width=5)
        self._dur_entry.pack(side="left", padx=(0, 10))

        self._search_btn = mk["button"](
            bar, "\u2315  Search", self._do_search,
            bg=C["btn_start"], fg=C["fg"], padx=12, pady=4
        )
        self._search_btn.pack(side="left", padx=4)

        # ── Pagination row ────────────────────────────────────────────────────
        nav = tk.Frame(outer, bg=C["panel2"], pady=3)
        nav.pack(fill="x", padx=10)

        self._prev_btn = mk["button"](
            nav, "\u25c0 Prev", self._prev_page,
            bg=C["btn_clear"], fg=C["accent"], padx=10, pady=2, state="disabled"
        )
        self._prev_btn.pack(side="left", padx=4)

        self._page_var = tk.StringVar(value="Page 1")
        mk["label"](nav, textvariable=self._page_var, fg=C["accent"]).pack(side="left", padx=8)

        self._next_btn = mk["button"](
            nav, "Next \u25b6", self._next_page,
            bg=C["btn_clear"], fg=C["accent"], padx=10, pady=2, state="disabled"
        )
        self._next_btn.pack(side="left", padx=4)

        self._sel_all_btn = mk["button"](
            nav, "\u2611 Select All", self._select_all,
            bg=C["btn_clear"], fg=C["fg_dim"], padx=10, pady=2
        )
        self._sel_all_btn.pack(side="left", padx=(20, 4))

        self._sel_none_btn = mk["button"](
            nav, "\u2610 None", self._select_none,
            bg=C["btn_clear"], fg=C["fg_dim"], padx=10, pady=2
        )
        self._sel_none_btn.pack(side="left", padx=4)

        self._status_var = tk.StringVar(value="Enter a search term and press Search.")
        mk["label"](nav, textvariable=self._status_var, fg=C["fg_dim"],
                    font=("Courier", 8)).pack(side="right", padx=10)

        # ── Thumbnail grid (scrollable canvas) ───────────────────────────────
        grid_outer = tk.Frame(outer, bg=C["bg"])
        grid_outer.pack(fill="both", expand=True, padx=10, pady=4)

        self._canvas = tk.Canvas(grid_outer, bg=C["bg"],
                                 highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(grid_outer, orient="vertical",
                            command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._grid_frame = tk.Frame(self._canvas, bg=C["bg"])
        self._grid_win   = self._canvas.create_window(
            (0, 0), window=self._grid_frame, anchor="nw"
        )
        self._grid_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")
            )
        )
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(
                              self._grid_win, width=e.width))

        # Mousewheel on grid
        def _wheel(event):
            delta = -1 if (event.num == 5 or getattr(event, 'delta', 1) < 0) else 1
            self._canvas.yview_scroll(-delta, "units")
        self._canvas.bind_all("<MouseWheel>", _wheel)
        self._canvas.bind_all("<Button-4>",   _wheel)
        self._canvas.bind_all("<Button-5>",   _wheel)

        # ── Download queue bar ────────────────────────────────────────────────
        dl_bar = tk.Frame(outer, bg=C["panel"], pady=6)
        dl_bar.pack(fill="x", padx=10, pady=(4, 8))

        self._sel_count_var = tk.StringVar(value="0 selected")
        mk["label"](dl_bar, textvariable=self._sel_count_var,
                    fg=C["accent"], font=("Courier", 9, "bold")
                    ).pack(side="left", padx=8)

        self._dl_btn = mk["button"](
            dl_bar, "\u2b07  Download Selected", self._download_selected,
            bg=C["btn_start"], fg=C["fg"], padx=16, pady=5, state="disabled"
        )
        self._dl_btn.pack(side="left", padx=8)

        self._stop_dl_btn = mk["button"](
            dl_bar, "\u23f9  Stop", self._stop_downloads,
            bg=C["btn_stop"], fg="#ff4444", padx=12, pady=5, state="disabled"
        )
        self._stop_dl_btn.pack(side="left", padx=4)

        self._dl_progress_var = tk.StringVar(value="")
        mk["label"](dl_bar, textvariable=self._dl_progress_var,
                    fg=C["fg_dim"], font=("Courier", 8)
                    ).pack(side="left", padx=10)

    # ---------------------------------------------------------------- search

    def _do_search(self, page: int = 1):
        query = self._search_entry.get().strip()
        if not query:
            messagebox.showwarning("Browse & Pick", "Please enter a search term.")
            return
        if self._loading:
            return

        self._current_query = query
        self._current_site  = self._site_var.get()
        self._page          = page
        self._clear_grid()
        self._set_status(f"Loading page {page}\u2026")
        self._search_btn.config(state="disabled")
        self._prev_btn.config(state="disabled")
        self._next_btn.config(state="disabled")
        self._loading = True

        threading.Thread(
            target=self._load_page_thread,
            args=(self._current_site, query, page),
            daemon=True
        ).start()

    def _load_page_thread(self, site_name: str, query: str, page: int):
        try:
            from smutscrape.config import get_selenium_driver as _gsd
        except ImportError:
            _gsd = None

        site_cfg = SITES[site_name]
        url      = _build_search_url(site_cfg, query, page)
        logger.debug(f"[BROWSE] Fetching: {url}")

        soup = None
        try:
            driver = self._get_driver()
            if driver:
                driver.get(url)
                time.sleep(3.5)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(driver.page_source, "html.parser")
        except Exception as exc:
            logger.warning(f"[BROWSE] Selenium fetch failed: {exc}")

        if soup is None:
            self.frame.after(0, lambda: self._finish_load(
                [], "Fetch failed \u2014 is Chrome/Selenium running?"
            ))
            return

        all_cards = _scrape_cards(soup, site_name)

        # Apply client-side filters
        after    = self._parse_after_date()
        min_dur  = self._parse_min_dur()
        filtered = [
            c for c in all_cards
            if _date_passes(c["date"], after)
            and _duration_passes(c["duration"], min_dur)
        ]

        self.frame.after(0, lambda: self._finish_load(
            filtered,
            f"Page {page}  \u2022  {len(filtered)}/{len(all_cards)} cards"
            + (f"  (filtered {len(all_cards)-len(filtered)})"
               if len(all_cards) != len(filtered) else "")
        ))

    def _finish_load(self, results: list, status: str):
        self._results  = results
        self._selected = {r["url"]: tk.BooleanVar(value=False) for r in results}
        self._thumb_images = {}
        self._card_frames  = {}
        self._loading = False
        self._page_var.set(f"Page {self._page}")
        self._set_status(status)
        self._search_btn.config(state="normal")
        self._prev_btn.config(state="normal" if self._page > 1 else "disabled")
        self._next_btn.config(state="normal" if results else "disabled")
        self._render_grid()
        self._update_sel_count()

    # ------------------------------------------------------------------ grid

    def _clear_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._thumb_images = {}
        self._card_frames  = {}

    def _render_grid(self):
        self._clear_grid()
        C = self.C
        for idx, item in enumerate(self._results):
            row = idx // COLS
            col = idx % COLS
            self._build_card(self._grid_frame, item, row, col)

        # Kick off async thumbnail loading
        threading.Thread(
            target=self._load_thumbs_thread,
            args=(list(self._results),),
            daemon=True
        ).start()

    def _build_card(self, parent, item: dict, row: int, col: int):
        C   = self.C
        url = item["url"]
        var = self._selected[url]

        card = tk.Frame(
            parent, bg=C["panel2"],
            width=CARD_W, height=CARD_H,
            highlightthickness=2,
            highlightbackground=C["border"],
        )
        card.grid(row=row, column=col, padx=4, pady=4, sticky="nw")
        card.grid_propagate(False)
        self._card_frames[url] = card

        # Placeholder thumb canvas
        thumb_canvas = tk.Canvas(
            card, width=THUMB_W, height=THUMB_H,
            bg=C["bg"], highlightthickness=0
        )
        thumb_canvas.place(x=5, y=5)
        thumb_canvas.create_text(
            THUMB_W//2, THUMB_H//2,
            text="loading\u2026", fill=C["fg_dim"],
            font=("Courier", 8)
        )
        # Store canvas reference for later update
        card._thumb_canvas = thumb_canvas
        card._thumb_img_ref = None

        # Title
        title_lbl = tk.Label(
            card, text=item["title"][:38],
            bg=C["panel2"], fg=C["fg"],
            font=("Courier", 8), anchor="w",
            wraplength=CARD_W - 10
        )
        title_lbl.place(x=5, y=THUMB_H + 8)

        # Duration + date meta
        meta_parts = []
        if item["duration"]: meta_parts.append(f"\u23f1 {item['duration']}")
        if item["date"]:     meta_parts.append(f"\U0001f4c5 {item['date'][:10]}")
        meta_lbl = tk.Label(
            card, text="  ".join(meta_parts),
            bg=C["panel2"], fg=C["fg_dim"],
            font=("Courier", 7), anchor="w"
        )
        meta_lbl.place(x=5, y=THUMB_H + 24)

        # Checkbox overlay in top-right of thumb
        def _toggle(u=url, v=var, c=card):
            v.set(not v.get())
            self._refresh_card_highlight(u)
            self._update_sel_count()

        chk = tk.Checkbutton(
            card, variable=var,
            bg=C["panel2"],
            activebackground=C["cb_select"],
            selectcolor=C["bg"],
            bd=0, relief="flat",
            command=lambda u=url, v=var, c=card: (
                self._refresh_card_highlight(u),
                self._update_sel_count()
            )
        )
        chk.place(x=THUMB_W - 14, y=THUMB_H + 6)

        # Click anywhere on thumb to toggle
        for widget in (thumb_canvas, title_lbl):
            widget.bind("<Button-1>", lambda e, u=url: self._toggle_url(u))

    def _load_thumbs_thread(self, results: list):
        for item in results:
            url   = item["url"]
            t_url = item["thumb_url"]
            if not t_url:
                continue
            data = _fetch_thumb_bytes(t_url)
            if data and PIL_AVAILABLE:
                try:
                    img = Image.open(io.BytesIO(data))
                    img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.frame.after(
                        0,
                        lambda u=url, ph=photo: self._set_thumb(u, ph)
                    )
                except Exception:
                    pass

    def _set_thumb(self, url: str, photo):
        self._thumb_images[url] = photo   # keep a reference!
        card = self._card_frames.get(url)
        if not card:
            return
        tc = card._thumb_canvas
        tc.delete("all")
        tc.create_image(0, 0, anchor="nw", image=photo)

    def _refresh_card_highlight(self, url: str):
        card = self._card_frames.get(url)
        if card is None:
            return
        selected = self._selected[url].get()
        card.config(
            highlightbackground=self.C["accent"] if selected else self.C["border"]
        )

    # -------------------------------------------------------- selection helpers

    def _toggle_url(self, url: str):
        var = self._selected.get(url)
        if var:
            var.set(not var.get())
            self._refresh_card_highlight(url)
            self._update_sel_count()

    def _select_all(self):
        for url, var in self._selected.items():
            var.set(True)
            self._refresh_card_highlight(url)
        self._update_sel_count()

    def _select_none(self):
        for url, var in self._selected.items():
            var.set(False)
            self._refresh_card_highlight(url)
        self._update_sel_count()

    def _update_sel_count(self):
        n = sum(1 for v in self._selected.values() if v.get())
        self._sel_count_var.set(f"{n} selected")
        self._dl_btn.config(state="normal" if n > 0 else "disabled")

    # ------------------------------------------------------------ pagination

    def _prev_page(self):
        if self._page > 1 and not self._loading:
            self._do_search(self._page - 1)

    def _next_page(self):
        if not self._loading:
            self._do_search(self._page + 1)

    # --------------------------------------------------------------- download

    def _download_selected(self):
        urls = [url for url, var in self._selected.items() if var.get()]
        if not urls:
            return
        self._stop_dl.clear()
        self._dl_btn.config(state="disabled")
        self._stop_dl_btn.config(state="normal")
        self._dl_progress_var.set(f"Queuing {len(urls)} video(s)\u2026")

        gc = self._get_general_config()
        site_name = self._current_site
        shortcode = SITES[site_name]["shortcode"]

        self._dl_thread = threading.Thread(
            target=self._dl_worker,
            args=(urls, gc, shortcode),
            daemon=True
        )
        self._dl_thread.start()

    def _stop_downloads(self):
        self._stop_dl.set()
        self._dl_progress_var.set("Stop requested\u2026")
        self._stop_dl_btn.config(state="disabled")

    def _dl_worker(self, urls: list, general_config: dict, shortcode: str):
        from smutscrape.core import resolve_download_dir
        out_dir  = resolve_download_dir(general_config)
        site_dir = os.path.join(out_dir, shortcode)
        os.makedirs(site_dir, exist_ok=True)
        out_tpl  = os.path.join(site_dir, "%(title)s [%(id)s].%(ext)s")

        cookies = general_config.get("cookies_file", "")
        if cookies:
            cookies = os.path.expanduser(cookies)

        total = len(urls)
        for idx, url in enumerate(urls, 1):
            if self._stop_dl.is_set():
                self._dl_queue.put(("status", "Stopped."))
                break

            self._dl_queue.put(("status",
                f"Downloading {idx}/{total}: {url.split('/')[-1][:50]}"
            ))

            cmd = [
                "yt-dlp",
                "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--no-warnings",
                "--output", out_tpl,
            ]
            if cookies and os.path.isfile(cookies):
                cmd += ["--cookies", cookies]
            cmd.append(url)

            logger.info(f"[BROWSE-DL] {url}")
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600
                )
                if proc.returncode == 0:
                    logger.success(f"[BROWSE-DL] OK: {url}")
                    self._dl_queue.put(("done_one", url))
                else:
                    logger.error(
                        f"[BROWSE-DL] Failed rc={proc.returncode}: "
                        f"{proc.stderr.strip()[:200]}"
                    )
            except subprocess.TimeoutExpired:
                logger.error(f"[BROWSE-DL] Timeout: {url}")
            except Exception as exc:
                logger.error(f"[BROWSE-DL] Error: {exc}")

        self._dl_queue.put(("finished", total))

    def _poll_dl_queue(self):
        try:
            while True:
                msg = self._dl_queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self._dl_progress_var.set(msg[1])
                elif kind == "done_one":
                    url = msg[1]
                    # Mark card as done (green border)
                    card = self._card_frames.get(url)
                    if card:
                        card.config(highlightbackground="#39ff14")
                elif kind == "finished":
                    self._dl_progress_var.set(
                        f"\u2714 Done  ({msg[1]} video(s) processed)"
                    )
                    self._dl_btn.config(state="normal")
                    self._stop_dl_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.frame.after(200, self._poll_dl_queue)

    # ----------------------------------------------------------------- helpers

    def _set_status(self, text: str):
        self._status_var.set(text)

    def _parse_after_date(self) -> Optional[datetime.date]:
        s = self._date_entry.get().strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_min_dur(self) -> Optional[float]:
        s = self._dur_entry.get().strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
