#!/usr/bin/env python3
"""
Config Editor — Toplevel window for editing config.yaml
All sections from example-config.yaml are surfaced as GUI widgets.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import copy
import yaml

# ---------------------------------------------------------------------------
# Locate config.yaml  (same logic as cli.py: project root, then ~/.config)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def _find_config_path():
    """Return the path that *should* be read/written.
    Priority: project-root/config.yaml  >  ~/.config/smutscrape/config.yaml
    If neither exists, defaults to project-root/config.yaml.
    """
    local = os.path.join(_PROJECT_ROOT, 'config.yaml')
    if os.path.isfile(local):
        return local
    xdg = os.path.join(
        os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')),
        'smutscrape', 'config.yaml'
    )
    if os.path.isfile(xdg):
        return xdg
    return local   # fall back to project root even if not yet created


# ---------------------------------------------------------------------------
# Colour palette (reuse from gui.py — kept in sync manually)
# ---------------------------------------------------------------------------

C = dict(
    bg          = "#0d0d0d",
    panel       = "#141414",
    panel2      = "#1c1c1c",
    panel3      = "#101010",
    border      = "#2a2a2a",
    fg          = "#39ff14",
    fg_dim      = "#1f8c0b",
    fg_disabled = "#3a3a3a",
    accent      = "#00e5ff",
    accent2     = "#7fff00",
    entry_bg    = "#0a1a0a",
    entry_dis   = "#1a1a1a",
    btn_save    = "#1a5c1a",
    btn_cancel  = "#2a2a2a",
    btn_add     = "#1a3a5c",
    btn_del     = "#3d0000",
    cb_select   = "#1f3d1f",
    sep         = "#2a2a2a",
)


# ---------------------------------------------------------------------------
# Tiny widget helpers
# ---------------------------------------------------------------------------

def _lbl(parent, text, fg=None, font=None, **kw):
    return tk.Label(parent, text=text,
                    bg=C['panel'], fg=fg or C['fg'],
                    font=font or ('Courier', 9), **kw)


def _entry(parent, width=30, **kw):
    return tk.Entry(parent, width=width,
                    bg=C['entry_bg'], fg=C['fg'],
                    insertbackground=C['fg'],
                    relief='flat', bd=1,
                    highlightbackground=C['border'],
                    highlightthickness=1,
                    font=('Courier', 9), **kw)


def _btn(parent, text, cmd, bg, fg='#ffffff', **kw):
    return tk.Button(parent, text=text, command=cmd,
                     bg=bg, fg=fg,
                     activebackground=bg, activeforeground=fg,
                     relief='flat', bd=0,
                     font=('Courier', 9, 'bold'),
                     cursor='hand2', **kw)


def _section_header(parent, text):
    f = tk.Frame(parent, bg=C['panel'])
    f.pack(fill='x', pady=(10, 2))
    tk.Label(f, text=f'  {text}',
             bg=C['panel'], fg=C['accent'],
             font=('Courier', 10, 'bold')).pack(side='left')
    tk.Frame(f, bg=C['border'], height=1).pack(side='left', fill='x', expand=True, padx=6)


def _hint(parent, text):
    tk.Label(parent, text=text,
             bg=C['panel'], fg=C['fg_dim'],
             font=('Courier', 8), anchor='w').pack(fill='x', padx=4)


# ---------------------------------------------------------------------------
# Row widget used for list-type sections (ignored words, case overrides, etc.)
# ---------------------------------------------------------------------------

class _ListEditor(tk.Frame):
    """Editable list of single-value string entries with Add / Delete buttons."""

    def __init__(self, parent, items=None, placeholder='value', **kw):
        super().__init__(parent, bg=C['panel'], **kw)
        self._placeholder = placeholder
        self._rows = []

        self._canvas = tk.Canvas(self, bg=C['panel'],
                                 highlightthickness=0, height=130)
        self._vsb = ttk.Scrollbar(self, orient='vertical',
                                  command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)

        self._inner = tk.Frame(self._canvas, bg=C['panel'])
        self._win_id = self._canvas.create_window((0, 0), window=self._inner,
                                                   anchor='nw')
        self._inner.bind('<Configure>', self._on_inner_conf)
        self._canvas.bind('<Configure>',
                          lambda e: self._canvas.itemconfig(self._win_id,
                                                             width=e.width))
        # bottom Add button
        add_bar = tk.Frame(self, bg=C['panel'])
        add_bar.pack(fill='x', pady=(2, 0))
        _btn(add_bar, '+ Add', self._add_row, bg=C['btn_add'],
             padx=8, pady=2).pack(side='left', padx=4)

        for item in (items or []):
            self._add_row(value=str(item))

    def _on_inner_conf(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))

    def _add_row(self, value=''):
        row = tk.Frame(self._inner, bg=C['panel'])
        row.pack(fill='x', pady=1, padx=2)
        e = _entry(row, width=40)
        e.insert(0, value)
        e.pack(side='left', padx=(0, 4))
        _btn(row, '✕', lambda r=row: self._del_row(r),
             bg=C['btn_del'], fg='#ff6666', padx=6, pady=1).pack(side='left')
        self._rows.append((row, e))

    def _del_row(self, row_frame):
        self._rows = [(r, e) for r, e in self._rows if r is not row_frame]
        row_frame.destroy()
        self._on_inner_conf()

    def get_values(self):
        return [e.get().strip() for _, e in self._rows if e.get().strip()]


# ---------------------------------------------------------------------------
# Main config editor window
# ---------------------------------------------------------------------------

class ConfigEditor(tk.Toplevel):

    def __init__(self, parent):
        super().__init__(parent)
        self.title('⚙  Smutscrape — Config Editor')
        self.geometry('780x780')
        self.resizable(True, True)
        self.configure(bg=C['bg'])
        self.transient(parent)
        self.grab_set()

        self._config_path = _find_config_path()
        self._cfg = {}          # raw loaded dict
        self._widgets = {}      # keyed by setting path

        self._apply_style()
        self._build()
        self._load()

    # ------------------------------------------------------------------
    # TTK style
    # ------------------------------------------------------------------

    def _apply_style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.',
            background=C['panel'], foreground=C['fg'],
            fieldbackground=C['entry_bg'], bordercolor=C['border'],
            selectbackground=C['cb_select'], selectforeground=C['fg'],
            insertcolor=C['fg'], font=('Courier', 9),
        )
        style.configure('TNotebook',
            background=C['bg'], bordercolor=C['border'],
            tabmargins=[2, 2, 0, 0],
        )
        style.configure('TNotebook.Tab',
            background=C['panel2'], foreground=C['fg_dim'],
            font=('Courier', 9, 'bold'), padding=[10, 4],
            bordercolor=C['border'],
        )
        style.map('TNotebook.Tab',
            background=[('selected', C['panel']), ('active', C['cb_select'])],
            foreground=[('selected', C['accent']), ('active', C['fg'])],
        )
        style.configure('TScrollbar',
            background=C['panel2'], troughcolor=C['bg'],
            arrowcolor=C['fg_dim'], bordercolor=C['border'],
        )

    # ------------------------------------------------------------------
    # Build skeleton
    # ------------------------------------------------------------------

    def _build(self):
        # title
        hdr = tk.Frame(self, bg=C['bg'])
        hdr.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(hdr, text='░▒▓  CONFIG EDITOR  ▓▒░',
                 bg=C['bg'], fg=C['fg'],
                 font=('Courier', 12, 'bold')).pack(side='left')
        self._path_lbl = tk.Label(hdr, text='',
                                   bg=C['bg'], fg=C['fg_dim'],
                                   font=('Courier', 8))
        self._path_lbl.pack(side='left', padx=12)
        tk.Frame(self, bg=C['border'], height=1).pack(fill='x', padx=10)

        # notebook tabs
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill='both', expand=True, padx=8, pady=6)

        self._tab_dl       = self._make_tab('💾 Downloads')
        self._tab_filters  = self._make_tab('🚫 Filters')
        self._tab_timing   = self._make_tab('⏱ Timing')
        self._tab_naming   = self._make_tab('📝 Naming')
        self._tab_selenium = self._make_tab('🌐 Selenium')
        self._tab_vpn      = self._make_tab('🔒 VPN')
        self._tab_api      = self._make_tab('🔌 API Server')
        self._tab_http     = self._make_tab('📡 HTTP')
        self._tab_case     = self._make_tab('🔡 Case')
        self._tab_fonts    = self._make_tab('🔤 Fonts')

        self._build_tab_downloads(self._tab_dl)
        self._build_tab_filters(self._tab_filters)
        self._build_tab_timing(self._tab_timing)
        self._build_tab_naming(self._tab_naming)
        self._build_tab_selenium(self._tab_selenium)
        self._build_tab_vpn(self._tab_vpn)
        self._build_tab_api(self._tab_api)
        self._build_tab_http(self._tab_http)
        self._build_tab_case(self._tab_case)
        self._build_tab_fonts(self._tab_fonts)

        # bottom bar
        sep = tk.Frame(self, bg=C['border'], height=1)
        sep.pack(fill='x', padx=8)
        bar = tk.Frame(self, bg=C['bg'])
        bar.pack(fill='x', padx=10, pady=6)
        _btn(bar, '💾  Save', self._save, bg=C['btn_save'],
             fg=C['fg'], padx=18, pady=6).pack(side='left', padx=6)
        _btn(bar, '✕  Cancel', self.destroy, bg=C['btn_cancel'],
             fg='#aaaaaa', padx=14, pady=6).pack(side='left', padx=4)
        self._status = tk.Label(bar, text='', bg=C['bg'],
                                 fg=C['accent'], font=('Courier', 9))
        self._status.pack(side='left', padx=14)

    # ------------------------------------------------------------------
    # Tab factory helpers
    # ------------------------------------------------------------------

    def _make_tab(self, label):
        """Create a scrollable tab frame and add it to the notebook."""
        outer = tk.Frame(self._nb, bg=C['panel'])
        self._nb.add(outer, text=label)

        canvas = tk.Canvas(outer, bg=C['panel'], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        inner = tk.Frame(canvas, bg=C['panel'])
        win = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>',
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e, c=canvas, w=win: c.itemconfig(w, width=e.width))

        # bind mousewheel for this tab canvas
        def _wheel(event, c=canvas):
            if isinstance(event.widget, str):
                return
            delta = -1 if (event.num == 5 or getattr(event, 'delta', 1) < 0) else 1
            c.yview_scroll(-delta, 'units')
        canvas.bind('<MouseWheel>', _wheel)
        canvas.bind('<Button-4>', _wheel)
        canvas.bind('<Button-5>', _wheel)

        return inner   # caller packs widgets into `inner`

    def _row(self, parent, label, hint=None):
        """Return a (label_frame, value_frame) tuple for a settings row."""
        f = tk.Frame(parent, bg=C['panel'])
        f.pack(fill='x', padx=8, pady=2)
        tk.Label(f, text=label, width=26, anchor='e',
                 bg=C['panel'], fg=C['fg'],
                 font=('Courier', 9)).pack(side='left', padx=(0, 6))
        vf = tk.Frame(f, bg=C['panel'])
        vf.pack(side='left', fill='x', expand=True)
        if hint:
            tk.Label(f, text=hint, bg=C['panel'], fg=C['fg_dim'],
                     font=('Courier', 8)).pack(side='left', padx=6)
        return vf

    def _field(self, parent, label, key, hint=None, width=40):
        """One-line text entry bound to self._widgets[key]."""
        vf = self._row(parent, label, hint)
        var = tk.StringVar()
        e = _entry(vf, width=width, textvariable=var)
        e.pack(side='left')
        self._widgets[key] = var
        return var

    def _check(self, parent, label, key, hint=None):
        """Checkbutton bound to self._widgets[key]."""
        vf = self._row(parent, label, hint)
        var = tk.BooleanVar()
        tk.Checkbutton(vf, variable=var,
                       bg=C['panel'], fg=C['fg'],
                       activebackground=C['cb_select'],
                       selectcolor=C['bg'],
                       bd=0, relief='flat').pack(side='left')
        self._widgets[key] = var
        return var

    def _path_field(self, parent, label, key, hint=None):
        """Path entry with Browse button."""
        vf = self._row(parent, label, hint)
        var = tk.StringVar()
        e = _entry(vf, width=36, textvariable=var)
        e.pack(side='left', padx=(0, 4))
        _btn(vf, '…', lambda v=var: self._browse_dir(v),
             bg=C['btn_add'], padx=6, pady=2).pack(side='left')
        self._widgets[key] = var
        return var

    def _browse_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser('~'),
                                    title='Select folder')
        if d:
            var.set(d)

    def _browse_file(self, var):
        f = filedialog.askopenfilename(title='Select file')
        if f:
            var.set(f)

    # ------------------------------------------------------------------
    # ── TAB: Downloads
    # ------------------------------------------------------------------

    def _build_tab_downloads(self, tab):
        _section_header(tab, 'Local Download Destination')
        _hint(tab, 'Primary folder where videos are saved.')
        self._path_field(tab, 'Download path:', 'dl_local_path')

        _section_header(tab, 'Temporary Storage')
        _hint(tab, 'Temp folder used during download before moving to final destination.')
        self._path_field(tab, 'Temp path:', 'dl_temp_path',
                         hint='(default: /tmp/smutscrape)')

    # ------------------------------------------------------------------
    # ── TAB: Filters
    # ------------------------------------------------------------------

    def _build_tab_filters(self, tab):
        _section_header(tab, 'Ignored Terms')
        _hint(tab, 'Videos whose metadata contains any of these words (case-insensitive) will be skipped.')
        self._ignored_editor = _ListEditor(tab, placeholder='ignored word')
        self._ignored_editor.pack(fill='x', padx=8, pady=4)

    # ------------------------------------------------------------------
    # ── TAB: Timing
    # ------------------------------------------------------------------

    def _build_tab_timing(self, tab):
        _section_header(tab, 'Sleep Delays')
        _hint(tab, 'Seconds to wait between actions to avoid overloading sites.')
        self._field(tab, 'Between videos (s):', 'sleep_between_videos', width=8)
        self._field(tab, 'Between pages (s):', 'sleep_between_pages', width=8)

    # ------------------------------------------------------------------
    # ── TAB: Naming
    # ------------------------------------------------------------------

    def _build_tab_naming(self, tab):
        _section_header(tab, 'File Naming')
        _hint(tab, 'Controls how downloaded files are named on disk.')
        self._field(tab, 'Invalid chars:', 'naming_invalid_chars',
                    hint='stripped from filenames', width=28)
        self._field(tab, 'Default extension:', 'naming_extension', width=8)
        self._field(tab, 'Max filename length:', 'naming_max_chars', width=8)

    # ------------------------------------------------------------------
    # ── TAB: Selenium
    # ------------------------------------------------------------------

    def _build_tab_selenium(self, tab):
        _section_header(tab, 'Selenium / Browser')
        _hint(tab, 'Used for sites requiring JavaScript or HLS streams.')

        # mode combobox
        vf = self._row(tab, 'Mode:', hint='local = uses webdriver-manager')
        self._sel_mode_var = tk.StringVar(value='local')
        cb = ttk.Combobox(vf, textvariable=self._sel_mode_var,
                          values=['local', 'remote'], width=10, state='readonly')
        cb.pack(side='left')
        self._widgets['selenium_mode'] = self._sel_mode_var

        _section_header(tab, 'Local overrides (leave blank to use webdriver-manager)')
        self._path_field(tab, 'chromedriver path:', 'selenium_chromedriver')
        self._path_field(tab, 'chrome binary:', 'selenium_chrome_binary')

        _section_header(tab, 'Remote Selenium (Docker / Selenium Grid)')
        self._field(tab, 'Remote host:', 'selenium_remote_host', width=22)
        self._field(tab, 'Remote port:', 'selenium_remote_port', width=8)

    # ------------------------------------------------------------------
    # ── TAB: VPN
    # ------------------------------------------------------------------

    def _build_tab_vpn(self, tab):
        _section_header(tab, 'VPN Settings')
        _hint(tab, 'Optional — leave disabled if not using a VPN.')
        self._check(tab, 'Enable VPN:', 'vpn_enabled')
        self._path_field(tab, 'VPN binary:', 'vpn_bin')
        self._field(tab, 'Start command:', 'vpn_start_cmd',
                    hint='e.g. {vpn_bin} connect', width=36)
        self._field(tab, 'Stop command:', 'vpn_stop_cmd',
                    hint='e.g. {vpn_bin} disconnect', width=36)
        self._field(tab, 'New node command:', 'vpn_new_node_cmd',
                    hint='e.g. {vpn_bin} connect --random', width=36)
        self._field(tab, 'New node interval (s):', 'vpn_new_node_time',
                    hint='seconds between node switches', width=8)

    # ------------------------------------------------------------------
    # ── TAB: API Server
    # ------------------------------------------------------------------

    def _build_tab_api(self, tab):
        _section_header(tab, 'API Server')
        _hint(tab, 'Host and port for smutscrape server mode.')
        self._field(tab, 'Host:', 'api_host', width=22)
        self._field(tab, 'Port:', 'api_port', width=8)

    # ------------------------------------------------------------------
    # ── TAB: HTTP
    # ------------------------------------------------------------------

    def _build_tab_http(self, tab):
        _section_header(tab, 'User-Agent Strings')
        _hint(tab, 'Rotated randomly for each request. One per line.')
        self._ua_editor = _ListEditor(tab, placeholder='user-agent string')
        self._ua_editor.pack(fill='x', padx=8, pady=4)

        _section_header(tab, 'HTTP Headers')
        _hint(tab, 'Sent with every request. Key: Value rows.')
        self._headers_frame = tk.Frame(tab, bg=C['panel'])
        self._headers_frame.pack(fill='x', padx=8, pady=4)
        self._header_rows = []   # list of (key_var, val_var, frame)
        _btn(tab, '+ Add header', self._add_header_row, bg=C['btn_add'],
             padx=8, pady=2).pack(anchor='w', padx=8, pady=(0, 4))

    def _add_header_row(self, key='', value=''):
        row = tk.Frame(self._headers_frame, bg=C['panel'])
        row.pack(fill='x', pady=1)
        kv = tk.StringVar(value=key)
        vv = tk.StringVar(value=value)
        ke = _entry(row, width=22, textvariable=kv)
        ve = _entry(row, width=30, textvariable=vv)
        ke.pack(side='left', padx=(0, 4))
        tk.Label(row, text=':', bg=C['panel'], fg=C['fg_dim'],
                 font=('Courier', 9)).pack(side='left', padx=2)
        ve.pack(side='left', padx=(0, 4))
        _btn(row, '✕', lambda r=row: self._del_header_row(r),
             bg=C['btn_del'], fg='#ff6666', padx=6, pady=1).pack(side='left')
        self._header_rows.append((kv, vv, row))

    def _del_header_row(self, row_frame):
        self._header_rows = [(k, v, r) for k, v, r in self._header_rows
                             if r is not row_frame]
        row_frame.destroy()

    # ------------------------------------------------------------------
    # ── TAB: Case overrides
    # ------------------------------------------------------------------

    def _build_tab_case(self, tab):
        _section_header(tab, 'Global Case Overrides')
        _hint(tab, 'These strings keep their exact capitalisation in titles and studio names.')
        self._case_editor = _ListEditor(tab, placeholder='e.g. POV')
        self._case_editor.pack(fill='x', padx=8, pady=4)

        _section_header(tab, 'Tag-Only Case Overrides')
        _hint(tab, 'Same but applied only to tags, not titles or studios.')
        self._tag_case_editor = _ListEditor(tab, placeholder='e.g. BBS')
        self._tag_case_editor.pack(fill='x', padx=8, pady=4)

    # ------------------------------------------------------------------
    # ── TAB: Fonts
    # ------------------------------------------------------------------

    def _build_tab_fonts(self, tab):
        _section_header(tab, 'ASCII Art Fonts')
        _hint(tab, 'Fonts used for site headers in terminal output. One name per row.')
        self._fonts_editor = _ListEditor(tab, placeholder='font name')
        self._fonts_editor.pack(fill='x', padx=8, pady=4)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load(self):
        self._path_lbl.config(text=self._config_path)
        if not os.path.isfile(self._config_path):
            self._status.config(text='⚠ config.yaml not found — will create on save',
                                 fg=C['accent'])
            self._cfg = {}
        else:
            try:
                with open(self._config_path) as fh:
                    self._cfg = yaml.safe_load(fh) or {}
            except Exception as exc:
                messagebox.showerror('Load error',
                                     f'Could not parse config.yaml:\n{exc}',
                                     parent=self)
                self._cfg = {}

        cfg = self._cfg

        # ── Downloads ──
        local_dest = next(
            (d for d in cfg.get('download_destinations', [])
             if d.get('type') == 'local'), {}
        )
        self._widgets['dl_local_path'].set(
            local_dest.get('path', os.path.expanduser('~/.xxx')))
        self._widgets['dl_temp_path'].set(
            local_dest.get('temporary_storage', '/tmp/smutscrape'))

        # ── Filters ──
        for item in cfg.get('ignored', []):
            self._ignored_editor._add_row(str(item))

        # ── Timing ──
        sl = cfg.get('sleep', {})
        self._widgets['sleep_between_videos'].set(str(sl.get('between_videos', 3)))
        self._widgets['sleep_between_pages'].set(str(sl.get('between_pages', 5)))

        # ── Naming ──
        fn = cfg.get('file_naming', {})
        self._widgets['naming_invalid_chars'].set(
            fn.get('invalid_chars', '/:*?"<>|\'')
        )
        self._widgets['naming_extension'].set(fn.get('extension', '.mp4'))
        self._widgets['naming_max_chars'].set(str(fn.get('max_chars', 200)))

        # ── Selenium ──
        sel = cfg.get('selenium', {})
        self._widgets['selenium_mode'].set(sel.get('mode', 'local'))
        self._widgets['selenium_chromedriver'].set(
            sel.get('chromedriver_path', ''))
        self._widgets['selenium_chrome_binary'].set(
            sel.get('chrome_binary', ''))
        self._widgets['selenium_remote_host'].set(
            sel.get('host', '127.0.0.1'))
        self._widgets['selenium_remote_port'].set(
            str(sel.get('port', '4444')))

        # ── VPN ──
        vpn = cfg.get('vpn', {})
        self._widgets['vpn_enabled'].set(bool(vpn.get('enabled', False)))
        self._widgets['vpn_bin'].set(vpn.get('vpn_bin', ''))
        self._widgets['vpn_start_cmd'].set(
            vpn.get('start_cmd', '{vpn_bin} connect'))
        self._widgets['vpn_stop_cmd'].set(
            vpn.get('stop_cmd', '{vpn_bin} disconnect'))
        self._widgets['vpn_new_node_cmd'].set(
            vpn.get('new_node_cmd', '{vpn_bin} connect --random'))
        self._widgets['vpn_new_node_time'].set(
            str(vpn.get('new_node_time', 300)))

        # ── API ──
        api = cfg.get('api_server', {})
        self._widgets['api_host'].set(api.get('host', '127.0.0.1'))
        self._widgets['api_port'].set(str(api.get('port', 6999)))

        # ── HTTP – user agents ──
        for ua in cfg.get('user_agents', []):
            self._ua_editor._add_row(str(ua))

        # ── HTTP – headers ──
        for k, v in cfg.get('headers', {}).items():
            self._add_header_row(key=k, value=str(v))

        # ── Case ──
        for item in cfg.get('case_overrides', []):
            self._case_editor._add_row(str(item))
        for item in cfg.get('tag_case_overrides', []):
            self._tag_case_editor._add_row(str(item))

        # ── Fonts ──
        for item in cfg.get('fonts', []):
            self._fonts_editor._add_row(str(item))

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _get(self, key, default=''):
        w = self._widgets.get(key)
        if w is None:
            return default
        try:
            return w.get()
        except Exception:
            return default

    def _int(self, key, default=0):
        try:
            return int(self._get(key, str(default)))
        except (ValueError, TypeError):
            return default

    def _save(self):
        cfg = copy.deepcopy(self._cfg)

        # ── Downloads ──
        local_path = self._get('dl_local_path').strip()
        temp_path  = self._get('dl_temp_path').strip()
        # Keep non-local destinations untouched; upsert the local one.
        dests = [d for d in cfg.get('download_destinations', [])
                 if d.get('type') != 'local']
        local_dest = {'type': 'local', 'path': local_path}
        if temp_path and temp_path != '/tmp/smutscrape':
            local_dest['temporary_storage'] = temp_path
        dests.append(local_dest)
        cfg['download_destinations'] = dests

        # ── Filters ──
        cfg['ignored'] = self._ignored_editor.get_values()

        # ── Timing ──
        cfg['sleep'] = {
            'between_videos': self._int('sleep_between_videos', 3),
            'between_pages':  self._int('sleep_between_pages', 5),
        }

        # ── Naming ──
        cfg['file_naming'] = {
            'invalid_chars': self._get('naming_invalid_chars', '/:*?"<>|\''),
            'extension':     self._get('naming_extension', '.mp4'),
            'max_chars':     self._int('naming_max_chars', 200),
        }

        # ── Selenium ──
        sel = {'mode': self._get('selenium_mode', 'local')}
        cd = self._get('selenium_chromedriver').strip()
        cb = self._get('selenium_chrome_binary').strip()
        rh = self._get('selenium_remote_host').strip()
        rp = self._get('selenium_remote_port').strip()
        if cd: sel['chromedriver_path'] = cd
        if cb: sel['chrome_binary']     = cb
        if rh: sel['host']              = rh
        if rp: sel['port']              = rp
        cfg['selenium'] = sel

        # ── VPN ──
        cfg['vpn'] = {
            'enabled':       bool(self._get('vpn_enabled')),
            'vpn_bin':       self._get('vpn_bin').strip(),
            'start_cmd':     self._get('vpn_start_cmd').strip(),
            'stop_cmd':      self._get('vpn_stop_cmd').strip(),
            'new_node_cmd':  self._get('vpn_new_node_cmd').strip(),
            'new_node_time': self._int('vpn_new_node_time', 300),
        }

        # ── API ──
        cfg['api_server'] = {
            'host': self._get('api_host', '127.0.0.1'),
            'port': self._int('api_port', 6999),
        }

        # ── HTTP – user agents ──
        cfg['user_agents'] = self._ua_editor.get_values()

        # ── HTTP – headers ──
        cfg['headers'] = {
            kv.get(): vv.get()
            for kv, vv, _ in self._header_rows
            if kv.get().strip()
        }

        # ── Case ──
        cfg['case_overrides']     = self._case_editor.get_values()
        cfg['tag_case_overrides'] = self._tag_case_editor.get_values()

        # ── Fonts ──
        cfg['fonts'] = self._fonts_editor.get_values()

        # Write
        try:
            os.makedirs(os.path.dirname(self._config_path)
                        if os.path.dirname(self._config_path) else '.', exist_ok=True)
            with open(self._config_path, 'w') as fh:
                yaml.dump(cfg, fh,
                          default_flow_style=False,
                          allow_unicode=True,
                          sort_keys=False)
            self._cfg = cfg
            self._status.config(text='✔ Saved successfully', fg=C['accent2'])
            self.after(3000, lambda: self._status.config(text=''))
        except Exception as exc:
            messagebox.showerror('Save error',
                                 f'Could not write config.yaml:\n{exc}',
                                 parent=self)
