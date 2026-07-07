import json
import os
import sys
import subprocess
import shutil
import hashlib
import platform
import traceback
import sqlite3
import webbrowser
import zipfile
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

RUN_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
CONFIG_PATH = RUN_DIR / 'config.json'
LOG_DIR = RUN_DIR / 'logs'
SESSION_LOG_PATH = LOG_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
FEEDBACK_DIR = RUN_DIR / 'feedback'
UPDATES_DIR = RUN_DIR / 'updates'
BACKUP_DIR = RUN_DIR / 'backups'
DB_DIR = RUN_DIR / 'database'
LANG_DIR = RUN_DIR / 'language'
HELP_DIR = RUN_DIR / 'help'
for p in (LOG_DIR, FEEDBACK_DIR, UPDATES_DIR, BACKUP_DIR, DB_DIR, LANG_DIR, HELP_DIR):
    p.mkdir(exist_ok=True)

THEMES = {
    'insightec_light': {
        'bg': '#f5f8fb', 'panel': '#ffffff', 'panel2': '#eef5fb', 'text': '#1f2d3a',
        'muted': '#64788d', 'primary': '#0067a8', 'accent': '#00a3d9', 'ok': '#148a5b',
        'warn': '#c78400', 'bad': '#b3261e', 'entry': '#ffffff', 'border': '#d6e3ef'
    },
    'insightec_dark': {
        'bg': '#07111f', 'panel': '#101c2d', 'panel2': '#0b1728', 'text': '#eaf6ff',
        'muted': '#9fb6c9', 'primary': '#55c7ff', 'accent': '#00a3d9', 'ok': '#31c48d',
        'warn': '#f4b740', 'bad': '#ff6b6b', 'entry': '#02091a', 'border': '#17324d'
    }
}

LANGUAGE_METADATA = {
    'en': {'name': 'English', 'native': 'English', 'flag': '🇺🇸', 'enabled': True, 'completion': 100},
    'ja': {'name': 'Japanese', 'native': '日本語', 'flag': '🇯🇵', 'enabled': True, 'completion': 100},
    'zh_TW': {'name': 'Traditional Chinese', 'native': '繁體中文', 'flag': '🇹🇼', 'enabled': True, 'completion': 100},
    'ko': {'name': 'Korean', 'native': '한국어', 'flag': '🇰🇷', 'enabled': False, 'completion': 25},
    'es': {'name': 'Spanish', 'native': 'Español', 'flag': '🇪🇸', 'enabled': True, 'completion': 100},
}

SUPPORTED_LANGUAGES = {code: meta['native'] for code, meta in LANGUAGE_METADATA.items()}

LANGUAGE_FONT = {
    'en': ('Segoe UI', 10),
    'ja': ('Yu Gothic UI', 10),
    'zh_TW': ('Microsoft JhengHei UI', 10),
    'ko': ('Malgun Gothic', 10),
    'es': ('Segoe UI', 10),
}



def normalize_tool_manifest(manifest, folder_path):
    """Normalize a module manifest into the internal tool dictionary format."""
    data = dict(manifest or {})
    data.setdefault('folder', str(folder_path.relative_to(RUN_DIR)) if folder_path.is_relative_to(RUN_DIR) else str(folder_path))
    data.setdefault('enabled', data.get('status', 'active') != 'future')
    data.setdefault('status', 'active' if data.get('enabled', True) else 'future')
    if 'display_name' in data and 'name' not in data:
        data['name'] = data.get('display_name')
    if 'entry' in data and 'exe' not in data:
        data['exe'] = data.get('entry')
    return data

def discover_tool_manifests():
    """Read manifest.json files from tools/ and plugins/ so modules own their version metadata."""
    discovered = []
    for base_name in ('tools', 'plugins'):
        base = RUN_DIR / base_name
        if not base.exists():
            continue
        for manifest_path in sorted(base.glob('*/manifest.json')):
            manifest = load_json(manifest_path, {})
            if manifest:
                tool = normalize_tool_manifest(manifest, manifest_path.parent)
                tool['_manifest_path'] = str(manifest_path)
                discovered.append(tool)
    return discovered

def localized_value(value, language_code='en'):
    """Return localized text from either a plain string or a language dictionary."""
    if isinstance(value, dict):
        return value.get(language_code) or value.get('en') or next(iter(value.values()), '')
    return value or ''

class AppLogger:
    def __init__(self):
        self.path = LOG_DIR / f"hub_{datetime.now().strftime('%Y%m%d')}.log"
    def write(self, msg):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass
        return line
logger = AppLogger()

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def load_config():
    return load_json(CONFIG_PATH, {})

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def sha256_short(path):
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()[:12]
    except Exception:
        return 'N/A'

def tool_folder_path(tool):
    return RUN_DIR / tool.get('folder', '')

def tool_abs_path(tool):
    """Return configured EXE path. If ZIP extraction created nested folders, find the EXE recursively."""
    folder = tool_folder_path(tool)
    exe_name = tool.get('exe', '')
    direct = folder / exe_name
    if direct.exists() and direct.is_file():
        return direct
    if exe_name and folder.exists():
        matches = list(folder.rglob(exe_name))
        if matches:
            return matches[0]
    return direct

def tool_validation(tool):
    if tool.get('status') == 'future':
        return {'ready': False, 'status': 'Coming Soon', 'detail': 'Reserved future plug-in'}
    if not tool.get('enabled'):
        return {'ready': False, 'status': 'Disabled', 'detail': 'Tool is disabled in config'}
    folder = tool_folder_path(tool)
    p = tool_abs_path(tool)
    if not folder.exists():
        return {'ready': False, 'status': 'Missing', 'detail': f'Folder not found: {folder}'}
    if not p.exists() or not p.is_file():
        return {'ready': False, 'status': 'Missing', 'detail': f'EXE not found: {tool.get("exe", "")}. Use Install ZIP or place EXE under {folder}'}
    try:
        st = p.stat()
        return {
            'ready': True,
            'status': 'Ready',
            'detail': f'{st.st_size/1024/1024:.1f} MB | {datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")} | hash {sha256_short(p)}',
            'path': str(p)
        }
    except Exception as e:
        return {'ready': False, 'status': 'Error', 'detail': str(e)}

def tool_is_ready(tool):
    return bool(tool_validation(tool).get('ready'))

def tool_runtime_info(tool):
    v = tool_validation(tool)
    if v.get('ready'):
        return f"{tool.get('version', '')} | {v.get('detail')}"
    return f"{tool.get('version', '')} | {v.get('status')}: {v.get('detail')}"

class HubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.ui_scale = 1.0
        self.developer_mode = False
        self.developer_mode_until = None
        self._resize_after = None
        self.cfg = load_config()
        self.ensure_developer_password()
        self.lang_en = load_json(LANG_DIR / 'en.json', {})
        self.lang = self.load_language(self.cfg.get('language', 'en'))
        self.theme_name = self.cfg.get('theme', 'insightec_light')
        self.theme = THEMES.get(self.theme_name, THEMES['insightec_light'])
        self.current_page = 'dashboard'
        self.selected_tool_id = None
        self.title(f"{self.cfg.get('console_name', 'InSightec Service Hub')} v{self.cfg.get('console_version', '')}")
        self.geometry('1180x720')
        self.minsize(960, 620)
        self.bind('<Configure>', self.on_window_configure)
        self._apply_style()
        self._build_shell()
        self.init_parts_db()
        self.cfg['session_log'] = str(SESSION_LOG_PATH)
        save_config(self.cfg)
        logger.write('InSightec Service Hub started')
        self.write_session('Hub started')
        if self.cfg.get('startup_page', 'dashboard') == 'tools':
            self.show_tools()
        else:
            self.show_dashboard()

    def t(self, key):
        return self.lang.get(key, self.lang_en.get(key, key))

    def tr_tool(self, tool, field):
        return localized_value(tool.get(field, ''), self.cfg.get('language', 'en'))

    def load_language(self, code):
        self.lang_en = load_json(LANG_DIR / 'en.json', {})
        data = load_json(LANG_DIR / f'{code}.json', {})
        if not data:
            data = self.lang_en.copy()
        else:
            merged = self.lang_en.copy()
            merged.update(data)
            data = merged
        return data

    def language_label(self, code):
        meta = LANGUAGE_METADATA.get(code, {'native': code, 'flag': '', 'completion': 0, 'enabled': False})
        state = 'Ready' if meta.get('enabled') else 'Coming Soon'
        return f"{code} - {meta.get('flag','')} {meta.get('native', code)} ({state})"

    def language_values(self):
        return [self.language_label(code) for code in SUPPORTED_LANGUAGES]

    def parse_language_value(self, value):
        return str(value).split(' - ', 1)[0].strip()

    def language_enabled(self, code):
        return bool(LANGUAGE_METADATA.get(code, {}).get('enabled'))

    def language_completion(self, code):
        return int(LANGUAGE_METADATA.get(code, {}).get('completion', 0))

    def language_menu_button(self, parent, variable, command, width=28):
        """Create a language selector where incomplete languages are visible but disabled."""
        mb = ttk.Menubutton(parent, textvariable=variable, width=width)
        menu = tk.Menu(mb, tearoff=0)
        for code in SUPPORTED_LANGUAGES:
            meta = LANGUAGE_METADATA.get(code, {})
            label = self.language_label(code)
            state = 'normal' if meta.get('enabled') else 'disabled'
            menu.add_command(
                label=label,
                state=state,
                command=lambda c=code: (variable.set(self.language_label(c)), command(c))
            )
        mb.configure(menu=menu)
        return mb

    def language_status_lines(self):
        lines = []
        for code in SUPPORTED_LANGUAGES:
            meta = LANGUAGE_METADATA.get(code, {})
            status = self.t('ready') if meta.get('enabled') else self.t('coming_soon')
            lines.append(f"{meta.get('flag','')} {meta.get('native', code)}: {meta.get('completion', 0)}% - {status}")
        return lines


    def ensure_developer_password(self):
        """Initialize developer password hash. Default password is 5963."""
        if not self.cfg.get('developer_password_hash'):
            self.cfg['developer_password_hash'] = hashlib.sha256('5963'.encode('utf-8')).hexdigest()
            save_config(self.cfg)

    def verify_developer_password(self, password):
        return hashlib.sha256(str(password).encode('utf-8')).hexdigest() == self.cfg.get('developer_password_hash', '')

    def developer_mode_valid(self):
        if not self.developer_mode or not self.developer_mode_until:
            return False
        if datetime.now() > self.developer_mode_until:
            self.developer_mode = False
            self.developer_mode_until = None
            self.set_status(self.t('developer_mode_expired'))
            return False
        return True

    def enable_developer_mode(self):
        self.developer_mode = True
        self.developer_mode_until = datetime.now() + timedelta(minutes=30)
        self.set_status(self.t('developer_mode_enabled'))

    def prompt_developer_mode(self):
        win = tk.Toplevel(self)
        win.title(self.t('developer_password'))
        win.transient(self)
        win.grab_set()
        win.configure(bg=self.theme['bg'])
        win.geometry('360x170')
        ttk.Label(win, text=self.t('developer_password'), font=('Segoe UI Semibold', 12)).pack(anchor='w', padx=18, pady=(18, 6))
        pwd = tk.StringVar()
        entry = ttk.Entry(win, textvariable=pwd, show='*', width=28)
        entry.pack(anchor='w', padx=18, pady=6)
        msg = tk.StringVar(value='')
        ttk.Label(win, textvariable=msg, foreground=self.theme['bad'], background=self.theme['bg']).pack(anchor='w', padx=18, pady=(0, 4))
        def ok():
            if self.verify_developer_password(pwd.get()):
                self.enable_developer_mode()
                win.destroy()
                self.show_update()
            else:
                msg.set(self.t('invalid_password'))
                entry.selection_range(0, 'end')
        row = ttk.Frame(win)
        row.pack(fill='x', padx=18, pady=8)
        ttk.Button(row, text='OK', style='Accent.TButton', command=ok).pack(side='right')
        ttk.Button(row, text=self.t('cancel'), command=win.destroy).pack(side='right', padx=8)
        entry.bind('<Return>', lambda e: ok())
        entry.focus_set()
        self.wait_window(win)

    def on_window_configure(self, event):
        if event.widget is not self:
            return
        if self._resize_after:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(160, self.apply_responsive_scale)

    def apply_responsive_scale(self):
        width = max(1, self.winfo_width())
        if width < 1050:
            new_scale = 0.88
        elif width < 1250:
            new_scale = 0.94
        else:
            new_scale = 1.0
        if abs(new_scale - self.ui_scale) > 0.01:
            self.ui_scale = new_scale
            self._apply_style()

    def _apply_style(self):
        c = self.theme
        self.configure(bg=c['bg'])
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except Exception:
            pass
        base_family = LANGUAGE_FONT.get(self.cfg.get('language', 'en'), ('Segoe UI', 10))[0]
        s.configure('.', font=(base_family, max(8, int(self.ui_scale * 10))))
        s.configure('TFrame', background=c['bg'])
        s.configure('Panel.TFrame', background=c['panel'], relief='flat')
        s.configure('Panel2.TFrame', background=c['panel2'], relief='flat')
        s.configure('TLabel', background=c['bg'], foreground=c['text'])
        s.configure('Panel.TLabel', background=c['panel'], foreground=c['text'])
        s.configure('Muted.TLabel', background=c['panel'], foreground=c['muted'])
        s.configure('Title.TLabel', background=c['bg'], foreground=c['primary'], font=('Segoe UI Semibold', max(18, int(self.ui_scale * 24))))
        s.configure('PageTitle.TLabel', background=c['panel'], foreground=c['primary'], font=('Segoe UI Semibold', max(14, int(self.ui_scale * 18))))
        s.configure('Metric.TLabel', background=c['panel'], foreground=c['text'], font=('Segoe UI Semibold', max(18, int(self.ui_scale * 24))))
        s.configure('Section.TLabel', background=c['panel'], foreground=c['primary'], font=('Segoe UI Semibold', max(10, int(self.ui_scale * 12))))
        s.configure('Card.TFrame', background=c['panel'])
        s.configure('Nav.TButton', font=('Segoe UI Semibold', max(9, int(self.ui_scale * 10))), padding=(14, 10), anchor='w')
        s.configure('TButton', font=('Segoe UI', max(8, int(self.ui_scale * 10))), padding=8)
        s.configure('Accent.TButton', font=('Segoe UI Semibold', max(9, int(self.ui_scale * 10))), padding=8)
        s.configure('Tool.TButton', font=('Segoe UI Semibold', max(9, int(self.ui_scale * 11))), padding=10)
        s.configure('TEntry', fieldbackground=c['entry'], foreground=c['text'])
        s.configure('TCombobox', fieldbackground=c['entry'], foreground=c['text'])
        s.configure('Treeview', background=c['panel'], fieldbackground=c['panel'], foreground=c['text'], rowheight=30)
        s.configure('Treeview.Heading', background=c['panel2'], foreground=c['text'], font=('Segoe UI Semibold', max(9, int(self.ui_scale * 10))))
        s.map('Treeview', background=[('selected', c['primary'])], foreground=[('selected', '#ffffff')])

    def _build_shell(self):
        c = self.theme
        header = ttk.Frame(self)
        header.pack(fill='x', padx=18, pady=(14, 8))
        ttk.Label(header, text='InSightec Service Hub', style='Title.TLabel').pack(side='left')
        ttk.Label(header, text=f"v{self.cfg.get('console_version', '')}  |  One Hub for Every Service Engineer", foreground=c['muted'], background=c['bg']).pack(side='left', padx=18, pady=(12,0))
        self.lang_var = tk.StringVar(value=self.language_label(self.cfg.get('language', 'en')))
        lang = self.language_menu_button(header, self.lang_var, self.change_language, width=28)
        lang.pack(side='right', pady=(8,0))
        ttk.Label(header, text='🌐', background=c['bg'], foreground=c['text']).pack(side='right', padx=(0,6), pady=(8,0))
        self.search_var = tk.StringVar()
        search = ttk.Entry(self, textvariable=self.search_var, font=('Segoe UI', max(9, int(self.ui_scale * 11))))
        search.pack(fill='x', padx=18, pady=(0, 10))
        search.insert(0, self.t('search'))
        search.bind('<FocusIn>', lambda e: self._clear_search_placeholder())
        search.bind('<Return>', lambda e: self.search())
        shell = ttk.Frame(self)
        shell.pack(fill='both', expand=True, padx=18, pady=(0, 10))
        self.nav = ttk.Frame(shell, style='Panel.TFrame', width=190)
        self.nav.pack(side='left', fill='y', padx=(0, 12))
        self.nav.pack_propagate(False)
        self.content = ttk.Frame(shell, style='Panel.TFrame')
        self.content.pack(side='left', fill='both', expand=True)
        self.status_var = tk.StringVar(value=self.t('status_ready'))
        status = ttk.Frame(self)
        status.pack(fill='x', padx=18, pady=(0, 12))
        ttk.Label(status, textvariable=self.status_var, background=c['bg'], foreground=c['muted']).pack(side='left')
        ttk.Label(status, text=f"Log: {logger.path.name}", background=c['bg'], foreground=c['muted']).pack(side='right')
        self._build_nav()

    def _build_nav(self):
        for w in self.nav.winfo_children():
            w.destroy()
        items = [
            ('dashboard', '🏠', self.t('dashboard'), self.show_dashboard),
            ('tools', '🛠', self.t('tools'), self.show_tools),
            ('parts', '📦', self.t('parts'), lambda: self.show_coming_soon('Part Search')),
            ('documents', '📚', self.t('documents'), lambda: self.show_coming_soon('Document Search')),
            ('feedback', '💬', self.t('feedback'), self.show_feedback),
            ('update', '⬆', self.t('update'), self.show_update),
            ('help', '❓', self.t('help'), self.show_help),
            ('settings', '⚙', self.t('settings'), self.show_settings),
            ('about', 'ℹ', self.t('about'), self.show_about),
        ]
        ttk.Label(self.nav, text='  MENU', style='Muted.TLabel').pack(anchor='w', padx=10, pady=(16,8))
        for key, icon, text, cmd in items:
            ttk.Button(self.nav, text=f'{icon}  {text}', style='Nav.TButton', command=cmd).pack(fill='x', padx=10, pady=4)

    def clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def write_session(self, event, detail=''):
        try:
            line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {event}"
            if detail:
                line += f" | {detail}"
            with open(SESSION_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    def set_status(self, msg):
        line = logger.write(msg)
        self.write_session('Status', msg)
        self.status_var.set(msg)
        return line

    def page_title(self, title, subtitle=''):
        top = ttk.Frame(self.content, style='Panel.TFrame')
        top.pack(fill='x', padx=18, pady=(18, 8))
        ttk.Label(top, text=title, style='PageTitle.TLabel').pack(side='left')
        if subtitle:
            ttk.Label(top, text=subtitle, style='Muted.TLabel').pack(side='left', padx=14, pady=(4,0))

    def card(self, parent, title='', width=None):
        frame = ttk.Frame(parent, style='Panel.TFrame')
        frame.configure(padding=16)
        if title:
            ttk.Label(frame, text=title, style='Panel.TLabel', font=('Segoe UI Semibold', 13)).pack(anchor='w', pady=(0, 10))
        return frame

    def metric_card(self, parent, title, value, subtitle=''):
        f = self.card(parent, title)
        ttk.Label(f, text=str(value), style='Metric.TLabel').pack(anchor='w')
        if subtitle:
            ttk.Label(f, text=subtitle, style='Muted.TLabel').pack(anchor='w', pady=(2,0))
        return f

    def get_tools(self):
        """Return installed tools. manifest.json values override config.json fallback entries."""
        manifest_tools = discover_tool_manifests()
        if not manifest_tools:
            return self.cfg.get('tools', [])
        by_id = {t.get('id'): dict(t) for t in self.cfg.get('tools', []) if t.get('id')}
        for mt in manifest_tools:
            tid = mt.get('id')
            if not tid:
                continue
            base = by_id.get(tid, {})
            base.update(mt)
            by_id[tid] = base
        ordered = []
        seen = set()
        for t in self.cfg.get('tools', []):
            tid = t.get('id')
            if tid in by_id:
                ordered.append(by_id[tid]); seen.add(tid)
        for mt in manifest_tools:
            tid = mt.get('id')
            if tid and tid not in seen:
                ordered.append(mt); seen.add(tid)
        return ordered

    def get_tool_by_id(self, tool_id):
        return next((t for t in self.get_tools() if t.get('id') == tool_id), None)


    def validate_all_tools(self, save_report=True):
        rows = []
        for t in self.get_tools():
            v = tool_validation(t)
            folder = tool_folder_path(t)
            exe_path = Path(v.get('path', tool_abs_path(t)))
            checks = {
                'plugin_config': bool(t.get('id') and self.tr_tool(t, 'name')),
                'folder': folder.exists(),
                'exe': bool(v.get('ready')),
                'version': bool(t.get('version')),
                'help': (folder / 'help').exists() or (HELP_DIR.exists()),
                'log_folder': LOG_DIR.exists(),
                'feedback_ready': FEEDBACK_DIR.exists(),
            }
            if t.get('status') == 'future':
                result = 'SKIP'
            elif checks['exe'] and checks['plugin_config'] and checks['version']:
                result = 'PASS'
            elif checks['folder'] or checks['plugin_config']:
                result = 'WARNING'
            else:
                result = 'FAIL'
            rows.append({
                'id': t.get('id'),
                'name': self.tr_tool(t, 'name'),
                'version': t.get('version'),
                'status': v.get('status'),
                'result': result,
                'ready': bool(v.get('ready')),
                'path': v.get('path', str(tool_abs_path(t))),
                'detail': v.get('detail', ''),
                'checks': checks,
            })
        if save_report:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            txt_report = LOG_DIR / f'tool_validation_{stamp}.txt'
            html_report = LOG_DIR / f'tool_validation_{stamp}.html'
            lines = [f'InSightec Service Hub Tool Validation - {stamp}', '']
            for r in rows:
                lines.append(f"[{r['result']}] {r['name']}  v{r['version']}  status={r['status']}")
                for k, ok in r['checks'].items():
                    lines.append(f"  {'OK' if ok else 'NG'} {k}")
                lines.append(f"  Path   : {r['path']}")
                lines.append(f"  Detail : {r['detail']}")
                lines.append('')
            txt_report.write_text('\n'.join(lines), encoding='utf-8')
            def color(result):
                return {'PASS':'#148a5b','WARNING':'#c78400','FAIL':'#b3261e','SKIP':'#64788d'}.get(result, '#64788d')
            html = ['<!doctype html><html><head><meta charset="utf-8"><title>Tool Validation</title>',
                    '<style>body{font-family:Segoe UI,Arial;margin:24px;color:#1f2d3a} table{border-collapse:collapse;width:100%} th,td{border:1px solid #d6e3ef;padding:8px;text-align:left} th{background:#eef5fb}.badge{font-weight:700}</style></head><body>',
                    f'<h1>InSightec Service Hub - Tool Validation</h1><p>Build: {self.cfg.get("console_version","")} / {stamp}</p>',
                    '<table><tr><th>Tool</th><th>Version</th><th>Result</th><th>Checks</th><th>Path / Detail</th></tr>']
            for r in rows:
                checks = '<br>'.join(f"{'✓' if ok else '×'} {k}" for k, ok in r['checks'].items())
                detail = f"{r['path']}<br><small>{r['detail']}</small>"
                html.append(f"<tr><td>{r['name']}</td><td>{r['version']}</td><td><span class='badge' style='color:{color(r['result'])}'>{r['result']}</span></td><td>{checks}</td><td>{detail}</td></tr>")
            html.append('</table></body></html>')
            html_report.write_text('\n'.join(html), encoding='utf-8')
            self.cfg['last_validation_report'] = str(html_report)
            save_config(self.cfg)
            self.set_status(f'Tool validation completed: {html_report.name}')
        return rows

    def status_badge(self, parent, status):
        c = self.theme
        color = c['ok'] if status == 'Ready' else (c['warn'] if status in ('Coming Soon','Disabled') else c['bad'])
        return tk.Label(parent, text=f"● {status}", bg=c['panel'], fg=color, font=('Segoe UI Semibold', max(9, int(self.ui_scale * 10))))

    def install_tool_zip(self, tool):
        zip_path = filedialog.askopenfilename(title=f"Select ZIP for {tool.get('name')}", filetypes=[('ZIP file','*.zip'),('All files','*.*')])
        if not zip_path:
            return
        folder = tool_folder_path(tool)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(folder)
            v = tool_validation(tool)
            if v.get('ready'):
                messagebox.showinfo('Install complete', f"{tool.get('name')} is ready.\n\n{v.get('path')}")
                self.set_status(f"Installed tool ZIP: {tool.get('name')}")
            else:
                messagebox.showwarning('Install checked', f"ZIP extracted, but EXE was not detected.\n\n{v.get('detail')}")
                self.set_status(f"Tool ZIP extracted but not ready: {tool.get('name')}")
            self.show_tools()
        except Exception as e:
            self.set_status(f'Tool ZIP install failed: {e}')
            messagebox.showerror('Install failed', str(e))

    def show_dashboard(self):
        self.current_page = 'dashboard'
        self.clear_content()
        ready = sum(1 for t in self.get_tools() if tool_is_ready(t))
        active_tools = [t for t in self.get_tools() if t.get('status') != 'future']
        active = len(active_tools)
        user = self.cfg.get('user_name', 'Service Engineer')
        self.page_title(self.t('dashboard'), f"{self.t('welcome')}, {user}")

        # Top KPI cards
        metrics = ttk.Frame(self.content, style='Panel.TFrame')
        metrics.pack(fill='x', padx=18, pady=(4, 8))
        self.metric_card(metrics, self.t('tool_health'), f'{ready}/{active}', self.t('ready_tools')).pack(side='left', fill='both', expand=True, padx=(0,8))
        self.metric_card(metrics, self.t('favorites'), len(self.cfg.get('favorites', [])), self.t('favorite_tools')).pack(side='left', fill='both', expand=True, padx=8)
        self.metric_card(metrics, self.t('recent_files'), len(self.cfg.get('recent_files', [])), self.t('tracked_files')).pack(side='left', fill='both', expand=True, padx=8)
        self.metric_card(metrics, self.t('notifications'), len(self.cfg.get('notifications', [])), self.t('active_messages')).pack(side='left', fill='both', expand=True, padx=(8,0))

        body = ttk.Frame(self.content, style='Panel.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=8)
        left = ttk.Frame(body, style='Panel.TFrame')
        left.pack(side='left', fill='both', expand=True, padx=(0, 12))
        right = ttk.Frame(body, style='Panel.TFrame', width=390)
        right.pack(side='right', fill='both', padx=(0,0))
        right.pack_propagate(False)

        # Favorite tool cards
        fav_card = self.card(left, self.t('favorites'))
        fav_card.pack(fill='x', pady=(0, 10))
        fav_ids = self.cfg.get('favorites', [])
        fav_tools = [self.get_tool_by_id(x) for x in fav_ids if self.get_tool_by_id(x)]
        if not fav_tools:
            fav_tools = active_tools[:3]
        grid = ttk.Frame(fav_card, style='Panel.TFrame')
        grid.pack(fill='x')
        for idx, tool in enumerate(fav_tools[:4]):
            self.tool_mini_card(grid, tool).grid(row=idx//2, column=idx%2, sticky='nsew', padx=6, pady=6)
            grid.columnconfigure(idx%2, weight=1)

        # Recent files and activity
        recent = self.card(left, self.t('recent_files'))
        recent.pack(fill='both', expand=True, pady=(0, 10))
        files = self.cfg.get('recent_files', [])[:8]
        if files:
            for item in files:
                label = item.get('name') if isinstance(item, dict) else str(item)
                ttk.Label(recent, text=f"📄 {label}", style='Panel.TLabel').pack(anchor='w', pady=2)
        else:
            ttk.Label(recent, text=self.t('no_recent_files'), style='Muted.TLabel').pack(anchor='w', pady=4)

        activity = self.card(left, self.t('recent_activity'))
        activity.pack(fill='both', expand=True)
        entries = self.cfg.get('recent_activity', [])[:8]
        if not entries:
            entries = self.cfg.get('recent_tools', [])[:8]
        if entries:
            for a in entries:
                if isinstance(a, dict):
                    when = a.get('time', '')
                    name = a.get('name') or a.get('event') or a.get('tool', '')
                    ttk.Label(activity, text=f"🕒 {when}  {name}", style='Panel.TLabel').pack(anchor='w', pady=2)
                else:
                    ttk.Label(activity, text=f"🕒 {a}", style='Panel.TLabel').pack(anchor='w', pady=2)
        else:
            ttk.Label(activity, text=self.t('no_recent_activity'), style='Muted.TLabel').pack(anchor='w', pady=4)

        # Right-side quick actions / health / release notes
        qa = self.card(right, self.t('quick_actions'))
        qa.pack(fill='x', pady=(0, 10))
        ttk.Button(qa, text=self.t('open_tools'), style='Accent.TButton', command=self.show_tools).pack(fill='x', pady=3)
        ttk.Button(qa, text=self.t('send_feedback'), command=self.show_feedback).pack(fill='x', pady=3)
        ttk.Button(qa, text=self.t('validate_tools'), command=lambda: self.validate_all_tools(True)).pack(fill='x', pady=3)
        ttk.Button(qa, text=self.t('open_logs_folder'), command=lambda: self.open_path(LOG_DIR)).pack(fill='x', pady=3)
        ttk.Button(qa, text=self.t('install_upgrade'), command=self.install_upgrade_zip).pack(fill='x', pady=3)

        health = self.card(right, self.t('tool_health'))
        health.pack(fill='both', expand=True, pady=(0, 10))
        for t in self.get_tools():
            status = self.t('future') if t.get('status') == 'future' else (self.t('status_ready') if tool_is_ready(t) else self.t('missing'))
            icon = '🟢' if tool_is_ready(t) else ('🟡' if t.get('status') == 'future' else '🔴')
            ttk.Label(health, text=f"{icon} {self.tr_tool(t, 'name')}  -  {status}", style='Panel.TLabel').pack(anchor='w', pady=2)

        notes = self.card(right, self.t('whats_new'))
        notes.pack(fill='x')
        ttk.Label(notes, text=self.t('commit0003_note'), style='Muted.TLabel', wraplength=460).pack(anchor='w')
        self.set_status(self.t('dashboard_loaded'))

    def tool_row(self, parent, tool, compact=False):
        row = ttk.Frame(parent, style='Panel.TFrame')
        row.pack(fill='x', pady=4)
        mark = '✓' if tool_is_ready(tool) else ('…' if tool.get('status') == 'future' else '!')
        ttk.Label(row, text=f"{mark} {self.tr_tool(tool, 'name')}", style='Panel.TLabel', font=('Segoe UI Semibold', max(9, int(self.ui_scale * 10)))).pack(side='left')
        ttk.Label(row, text=tool.get('version', ''), style='Muted.TLabel').pack(side='left', padx=10)
        if not compact:
            ttk.Label(row, text=self.tr_tool(tool, 'description'), style='Muted.TLabel').pack(side='left', padx=10)
        ttk.Button(row, text=self.t('launch'), command=lambda t=tool: self.launch_tool(t)).pack(side='right')
        ttk.Button(row, text='★' if tool.get('id') in self.cfg.get('favorites', []) else '☆', command=lambda t=tool: self.toggle_favorite(t)).pack(side='right', padx=4)

    def tool_mini_card(self, parent, tool):
        f = self.card(parent)
        v = tool_validation(tool)
        icon = '🟢' if v.get('ready') else ('🟡' if tool.get('status') == 'future' else '🔴')
        ttk.Label(f, text=f"{icon} {self.tr_tool(tool, 'name')}", style='Panel.TLabel', font=('Segoe UI Semibold', 12)).pack(anchor='w')
        ttk.Label(f, text=f"v{tool.get('version', '')}  |  {v.get('status')}", style='Muted.TLabel').pack(anchor='w', pady=(2, 6))
        row = ttk.Frame(f, style='Panel.TFrame')
        row.pack(fill='x')
        ttk.Button(row, text='▶ ' + self.t('launch'), style='Accent.TButton', command=lambda t=tool: self.launch_tool(t), state='normal' if v.get('ready') else 'disabled').pack(side='left', ipadx=12, ipady=3)
        ttk.Button(row, text='★' if tool.get('id') in self.cfg.get('favorites', []) else '☆', command=lambda t=tool: self.toggle_favorite(t)).pack(side='right')
        return f

    def show_tools(self):
        self.current_page = 'tools'
        self.clear_content()
        self.page_title(self.t('tools'), self.t('tool_launcher_subtitle') if 'tool_launcher_subtitle' in self.lang else 'FEU validation launcher')

        toolbar = ttk.Frame(self.content, style='Panel.TFrame')
        toolbar.pack(fill='x', padx=10, pady=(0, 6))
        ttk.Button(toolbar, text=self.t('validate_tools'), style='Accent.TButton', command=lambda: (self.validate_all_tools(True), self.show_tools())).pack(side='left')
        ttk.Button(toolbar, text=self.t('open_hub_folder'), command=lambda: self.open_path(RUN_DIR)).pack(side='left', padx=4)
        ttk.Button(toolbar, text=self.t('open_logs_folder'), command=lambda: self.open_path(LOG_DIR)).pack(side='left', padx=4)
        ttk.Button(toolbar, text=self.t('refresh'), command=self.show_tools).pack(side='right')

        rows = self.validate_all_tools(save_report=False)
        ready_count = sum(1 for r in rows if r['ready'])
        active_count = sum(1 for t in self.get_tools() if t.get('status') != 'future')
        summary = ttk.Frame(self.content, style='Panel.TFrame')
        summary.pack(fill='x', padx=10, pady=(2, 4))
        ttk.Label(summary, text=f"{self.t('tool_validation') if 'tool_validation' in self.lang else 'Tool validation'}: {ready_count}/{active_count} {self.t('status_ready')}", style='Panel.TLabel', font=('Segoe UI Semibold', max(10, int(self.ui_scale * 12)))).pack(side='left')
        ttk.Label(summary, text=self.t('tool_manifest_note') if 'tool_manifest_note' in self.lang else 'Tool versions are read from manifest.json.', style='Muted.TLabel').pack(side='left', padx=12)

        tools = self.get_tools()
        installed = [t for t in tools if t.get('status') != 'future']
        future = [t for t in tools if t.get('status') == 'future']

        canvas = tk.Canvas(self.content, bg=self.theme['panel'], highlightthickness=0)
        vsb = ttk.Scrollbar(self.content, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True, padx=(10,0), pady=4)
        vsb.pack(side='right', fill='y', padx=(0,10), pady=4)
        holder = ttk.Frame(canvas, style='Panel.TFrame')
        window_id = canvas.create_window((0, 0), window=holder, anchor='nw')

        def calc_cols(width):
            # Keep cards readable on 1366x768 laptops. More columns only on wide displays.
            if width >= 1560:
                return 3
            if width >= 980:
                return 2
            return 1

        def build_grid():
            for child in holder.winfo_children():
                child.destroy()
            available_width = max(700, canvas.winfo_width() - 4)
            cols = calc_cols(available_width)
            for c in range(cols):
                holder.columnconfigure(c, weight=1, uniform='toolcards')

            row_index = 0
            if installed:
                ttk.Label(holder, text=self.t('installed_tools') if 'installed_tools' in self.lang else 'Installed Tools', style='Section.TLabel').grid(row=row_index, column=0, columnspan=cols, sticky='w', padx=8, pady=(4, 4))
                row_index += 1
                for idx, t in enumerate(installed):
                    self.tool_card(holder, t, cols).grid(row=row_index + idx//cols, column=idx%cols, sticky='nsew', padx=6, pady=5)
                row_index += (len(installed) + cols - 1) // cols
            if future:
                ttk.Label(holder, text=self.t('available_tools') if 'available_tools' in self.lang else 'Available Tools', style='Section.TLabel').grid(row=row_index, column=0, columnspan=cols, sticky='w', padx=8, pady=(8, 4))
                row_index += 1
                for idx, t in enumerate(future):
                    self.tool_card(holder, t, cols).grid(row=row_index + idx//cols, column=idx%cols, sticky='nsew', padx=6, pady=5)

        def _configure_canvas(event=None):
            canvas.itemconfigure(window_id, width=canvas.winfo_width())
            build_grid()
            holder.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox('all'))
        canvas.bind('<Configure>', _configure_canvas)
        holder.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        self.after(50, _configure_canvas)
        self.set_status('Tool Launcher loaded')

    def tool_card(self, parent, tool, cols=2):
        v = tool_validation(tool)
        f = self.card(parent)
        f.columnconfigure(0, weight=1)

        header = ttk.Frame(f, style='Panel.TFrame')
        header.pack(fill='x')
        name = self.tr_tool(tool, 'name')
        icon = '🟢' if v.get('ready') else ('🟡' if tool.get('status') == 'future' else '🔴')
        ttk.Label(header, text=f"{icon} {name}", style='Panel.TLabel', font=('Segoe UI Semibold', max(11, int(self.ui_scale * 13)))).pack(side='left', anchor='w')
        ttk.Label(header, text=f"v{tool.get('version', '')}", style='Muted.TLabel').pack(side='right', anchor='e')

        meta = ttk.Frame(f, style='Panel.TFrame')
        meta.pack(fill='x', pady=(3, 2))
        status_text = self.t('future') if tool.get('status') == 'future' else (self.t('status_ready') if v.get('ready') else self.t('missing'))
        ttk.Label(meta, text=f"• {status_text}", foreground=self.theme['ok'] if v.get('ready') else self.theme['warn'], background=self.theme['panel'], font=('Segoe UI', max(9, int(self.ui_scale*10)))).pack(side='left')
        source = 'manifest.json' if tool.get('_manifest_path') else 'config.json'
        ttk.Label(meta, text=f"  {self.t('version_source') if 'version_source' in self.lang else 'Source'}: {source}", style='Muted.TLabel').pack(side='right')

        desc = self.tr_tool(tool, 'description')
        if desc:
            ttk.Label(f, text=desc, style='Muted.TLabel', wraplength=360 if cols >= 2 else 620).pack(anchor='w', pady=(2, 4))

        buttons = ttk.Frame(f, style='Panel.TFrame')
        buttons.pack(fill='x', pady=(2, 0))
        launch_state = 'normal' if v.get('ready') else 'disabled'
        ttk.Button(buttons, text='▶ ' + self.t('launch'), style='Accent.TButton', command=lambda x=tool: self.launch_tool(x), state=launch_state).pack(side='left', padx=(0, 4), ipadx=10, ipady=3)
        ttk.Button(buttons, text=self.t('details') if 'details' in self.lang else 'Details', command=lambda: toggle_details()).pack(side='left', padx=4)
        ttk.Button(buttons, text=self.t('information'), command=lambda x=tool: self.show_tool_info(x)).pack(side='left', padx=4)
        ttk.Button(buttons, text='★' if tool.get('id') in self.cfg.get('favorites', []) else '☆', command=lambda x=tool: self.toggle_favorite(x)).pack(side='right')

        detail_frame = ttk.Frame(f, style='Panel.TFrame')
        def toggle_details(df=detail_frame, t=tool, val=v):
            if df.winfo_ismapped():
                df.pack_forget()
                return
            for child in df.winfo_children():
                child.destroy()
            ttk.Separator(df).pack(fill='x', pady=5)
            detail_text = (
                f"{self.t('build') if 'build' in self.lang else 'Build'}: {t.get('build','N/A')}\n"
                f"{self.t('manifest') if 'manifest' in self.lang else 'Manifest'}: {t.get('_manifest_path', 'config.json')}\n"
                f"EXE: {tool_abs_path(t)}\n"
                f"{self.t('folder')}: {tool_folder_path(t)}\n"
                f"{self.t('details') if 'details' in self.lang else 'Details'}: {val.get('detail','')}"
            )
            ttk.Label(df, text=detail_text, style='Muted.TLabel', justify='left', wraplength=420 if cols >= 2 else 700).pack(anchor='w')
            extra = ttk.Frame(df, style='Panel.TFrame')
            extra.pack(fill='x', pady=(5, 0))
            ttk.Button(extra, text=self.t('folder'), command=lambda x=t: self.open_path(tool_folder_path(x))).pack(side='left', padx=(0,4))
            ttk.Button(extra, text=self.t('install_zip'), command=lambda x=t: self.install_tool_zip(x), state='disabled' if t.get('status') == 'future' else 'normal').pack(side='left', padx=4)
            df.pack(fill='x', pady=(4, 0))
        return f

    def launch_tool(self, tool):
        if tool.get('status') == 'future' or not tool.get('enabled'):
            self.show_coming_soon(tool.get('name', 'Tool'))
            return
        exe = tool_abs_path(tool)
        if not exe.exists():
            messagebox.showerror('Not found', f'Executable not found:\n{exe}\n\nPlace the EXE under the configured tool folder.')
            self.set_status(f"Missing tool: {tool.get('name')}")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), shell=False)
            self.write_session('Launch Tool', f"{tool.get('name')} | {exe}")
            recent = self.cfg.setdefault('recent_tools', [])
            recent.insert(0, {'id': tool.get('id'), 'name': tool.get('name'), 'time': datetime.now().strftime('%Y-%m-%d %H:%M')})
            self.cfg['recent_tools'] = recent[:10]
            save_config(self.cfg)
            self.set_status(f"Launched: {tool.get('name')}")
        except Exception as e:
            self.set_status(f"Launch failed: {e}")
            messagebox.showerror('Launch failed', str(e))

    def show_tool_info(self, tool):
        text = (
            f"{self.tr_tool(tool, 'name')}\n\n"
            f"{self.t('version')}: {tool.get('version','')}\n"
            f"Build: {tool.get('build','N/A')}\n"
            f"Status: {tool_validation(tool).get('status')}\n"
            f"Manifest: {tool.get('_manifest_path', 'config.json')}\n"
            f"Path: {tool_abs_path(tool)}\n"
            f"Runtime: {tool_runtime_info(tool)}\n\n"
            f"Description:\n{self.tr_tool(tool, 'description')}"
        )
        messagebox.showinfo(self.t('information'), text)

    def toggle_favorite(self, tool):
        fav = self.cfg.setdefault('favorites', [])
        tid = tool.get('id')
        if tid in fav:
            fav.remove(tid)
            self.set_status(f"Removed favorite: {tool.get('name')}")
        else:
            fav.append(tid)
            self.set_status(f"Added favorite: {tool.get('name')}")
        save_config(self.cfg)
        if self.current_page == 'tools': self.show_tools()
        else: self.show_dashboard()

    def show_coming_soon(self, name):
        self.clear_content()
        self.page_title(name, self.t('future'))
        f = self.card(self.content, name)
        f.pack(fill='both', expand=True, padx=18, pady=12)
        ttk.Label(f, text=f'{name} is reserved for a future plug-in. It can be added later without changing Hub core code.', style='Panel.TLabel', font=('Segoe UI', 13), wraplength=800).pack(anchor='w', pady=10)
        ttk.Label(f, text=self.cfg.get('future_plugin_policy', ''), style='Muted.TLabel', wraplength=800).pack(anchor='w', pady=8)
        ttk.Button(f, text='Open Plugins Folder', command=lambda: self.open_path(RUN_DIR / 'plugins')).pack(anchor='w', pady=10)
        self.set_status(f'{name}: coming soon')

    def show_feedback(self):
        self.current_page = 'feedback'
        self.clear_content()
        self.page_title(self.t('feedback'), 'FEU validation feedback package')
        f = self.card(self.content, self.t('feedback'))
        f.pack(fill='both', expand=True, padx=18, pady=12)

        top = ttk.Frame(f, style='Panel.TFrame')
        top.pack(fill='x')
        category_var = tk.StringVar(value='Bug Report')
        tool_var = tk.StringVar(value='InSightec Service Hub')
        severity_var = tk.StringVar(value='Normal')
        reproducible_var = tk.StringVar(value='Unknown')
        mode_var = tk.StringVar(value=self.cfg.get('feedback_mode', 'template'))
        tools = ['InSightec Service Hub'] + [self.tr_tool(t, 'name') for t in self.get_tools()]
        self.form_row(top, 'Category', ttk.Combobox(top, textvariable=category_var, values=['Bug Report','Feature Request','Question','Suggestion','Validation Result'], width=28, state='readonly'))
        self.form_row(top, 'Related Tool', ttk.Combobox(top, textvariable=tool_var, values=tools, width=32, state='readonly'))
        self.form_row(top, 'Severity', ttk.Combobox(top, textvariable=severity_var, values=['Low','Normal','High','Critical'], width=28, state='readonly'))
        self.form_row(top, 'Reproducible', ttk.Combobox(top, textvariable=reproducible_var, values=['Unknown','Yes','No','Sometimes'], width=28, state='readonly'))
        self.form_row(top, 'Send Mode', ttk.Combobox(top, textvariable=mode_var, values=['template','outlook'], width=28, state='readonly'))

        ttk.Label(f, text='Comment / Issue detail', style='Panel.TLabel').pack(anchor='w', pady=(12,0))
        txt = scrolledtext.ScrolledText(f, height=9, bg=self.theme['entry'], fg=self.theme['text'], insertbackground=self.theme['text'], relief='solid', borderwidth=1)
        txt.pack(fill='both', expand=True, pady=6)
        txt.insert('1.0', 'Observed behavior:\n\nSteps to reproduce:\n\nExpected behavior:\n')

        files = []
        flabel = tk.StringVar(value='No attachment selected')
        def refresh_file_label():
            flabel.set(f'{len(files)} attachment(s) selected')
        def add_files():
            selected = filedialog.askopenfilenames(title='Select screenshot/photo/log files')
            for s in selected:
                if s not in files:
                    files.append(s)
            refresh_file_label()
        def add_recent_logs():
            for log in sorted(LOG_DIR.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                if str(log) not in files:
                    files.append(str(log))
            refresh_file_label()
        def capture_screenshot():
            try:
                from PIL import ImageGrab
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                path = FEEDBACK_DIR / f'screenshot_{stamp}.png'
                img = ImageGrab.grab()
                img.save(path)
                files.append(str(path))
                refresh_file_label()
                self.set_status(f'Screenshot captured: {path.name}')
            except Exception as e:
                messagebox.showwarning('Screenshot unavailable', f'Automatic screenshot capture failed. Please attach a photo or screenshot manually.\n\n{e}')
        btns = ttk.Frame(f, style='Panel.TFrame')
        btns.pack(fill='x', pady=(4,0))
        ttk.Button(btns, text='Capture Screenshot', command=capture_screenshot).pack(side='left')
        ttk.Button(btns, text='Add Screenshot / Photo / File', command=add_files).pack(side='left', padx=6)
        ttk.Button(btns, text='Attach Recent Logs', command=add_recent_logs).pack(side='left', padx=6)
        ttk.Label(f, textvariable=flabel, style='Muted.TLabel').pack(anchor='w', pady=(4,0))

        def submit():
            meta = {
                'category': category_var.get(),
                'tool': tool_var.get(),
                'severity': severity_var.get(),
                'reproducible': reproducible_var.get(),
                'mode': mode_var.get()
            }
            old_mode = self.cfg.get('feedback_mode', 'template')
            self.cfg['feedback_mode'] = mode_var.get()
            self.create_feedback(txt.get('1.0', 'end'), files, meta)
            self.cfg['feedback_mode'] = old_mode
        ttk.Button(f, text=self.t('create_feedback'), style='Accent.TButton', command=submit).pack(anchor='e', pady=12)

    def make_feedback_text(self, comment, attachments, meta=None):
        meta = meta or {}
        validation_rows = self.validate_all_tools(save_report=False)
        validation_text = '\n'.join(f"- {r['name']} v{r['version']}: {r['status']} ({r['detail']})" for r in validation_rows)
        recent = '\n'.join(str(p.name) for p in sorted(LOG_DIR.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:5])
        return f"""Service Tool Feedback / FEU Validation

To: {self.cfg.get('feedback_to', 'masakii@insightec.com')}
Subject: [{meta.get('category','Feedback')}] {meta.get('tool','InSightec Service Hub')} - Hub v{self.cfg.get('console_version', '')}

Category: {meta.get('category','Feedback')}
Related tool: {meta.get('tool','InSightec Service Hub')}
Severity: {meta.get('severity','Normal')}
Reproducible: {meta.get('reproducible','Unknown')}

Hub version: {self.cfg.get('console_version', '')}
Language: {self.cfg.get('language', 'en')}
Theme: {self.cfg.get('theme', '')}
PC: {platform.platform()}
Python: {platform.python_version()}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Normal permission update only: {self.cfg.get('normal_permission_update_only', True)}

Comment:
{comment.strip() or '(no comment)'}

Tool validation:
{validation_text or '(no tool configured)'}

Attachments to include:
{chr(10).join(attachments) if attachments else '(none selected)'}

Recent console logs:
{recent or '(no log found)'}
"""

    def create_feedback(self, comment, files, meta=None):
        body = self.make_feedback_text(comment, files, meta)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        out = FEEDBACK_DIR / f'feedback_template_{stamp}.txt'
        out.write_text(body, encoding='utf-8')
        manifest = FEEDBACK_DIR / f'feedback_manifest_{stamp}.json'
        manifest.write_text(json.dumps({'created': stamp, 'attachments': files, 'meta': meta or {}, 'template': str(out)}, indent=2, ensure_ascii=False), encoding='utf-8')
        if self.cfg.get('feedback_mode') == 'outlook' and self.try_outlook(body, files):
            self.set_status('Feedback draft opened in Outlook')
            return
        self.show_template(body)
        self.set_status(f'Feedback template created: {out.name}')

    def try_outlook(self, body, files):
        try:
            import win32com.client
            outlook = win32com.client.Dispatch('Outlook.Application')
            mail = outlook.CreateItem(0)
            mail.To = self.cfg.get('feedback_to', 'masakii@insightec.com')
            mail.Subject = f"InSightec Service Hub Feedback v{self.cfg.get('console_version', '')}"
            mail.Body = body
            for f in files:
                if Path(f).exists():
                    mail.Attachments.Add(str(f))
            for log in sorted(LOG_DIR.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                mail.Attachments.Add(str(log))
            mail.Display()
            return True
        except Exception as e:
            self.set_status(f'Outlook unavailable. Showing template. Detail: {e}')
            return False

    def show_template(self, body):
        win = tk.Toplevel(self)
        win.title('Mail Template')
        win.geometry('820x680')
        win.configure(bg=self.theme['bg'])
        ttk.Label(win, text='Copy this template into email').pack(anchor='w', padx=14, pady=(14,4))
        box = scrolledtext.ScrolledText(win, bg=self.theme['entry'], fg=self.theme['text'], insertbackground=self.theme['text'], relief='solid', borderwidth=1)
        box.pack(fill='both', expand=True, padx=14, pady=4)
        box.insert('1.0', body)
        def copy():
            self.clipboard_clear(); self.clipboard_append(box.get('1.0', 'end'))
            self.set_status('Template copied to clipboard')
        ttk.Button(win, text=self.t('copy_template'), command=copy, style='Accent.TButton').pack(anchor='e', padx=14, pady=14)

    def show_update(self):
        self.current_page = 'update'
        self.clear_content()
        self.page_title(self.t('update'), self.t('normal_permission'))

        f = self.card(self.content, self.t('update_center'))
        f.pack(fill='both', expand=True, padx=18, pady=12)

        top = ttk.Frame(f, style='Panel.TFrame')
        top.pack(fill='x')
        left = ttk.Frame(top, style='Panel.TFrame')
        left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(top, style='Panel.TFrame')
        right.pack(side='right', fill='y')

        ttk.Label(left, text=self.t('simple_update_title'), style='Section.TLabel').pack(anchor='w', pady=(0, 4))
        ttk.Label(left, text=self.t('simple_update_description'), style='Panel.TLabel', wraplength=760).pack(anchor='w', pady=(0, 12))
        ttk.Label(left, text=f"{self.t('current_version')}: {self.cfg.get('console_version','')}", style='Muted.TLabel').pack(anchor='w')
        ttk.Label(left, text=f"{self.t('latest_version')}: {self.t('manual_update_package')}", style='Muted.TLabel').pack(anchor='w', pady=(0, 8))

        ttk.Button(right, text=self.t('install_update'), style='Accent.TButton', command=self.install_upgrade_zip).pack(fill='x', pady=(0, 8), ipadx=12, ipady=5)
        ttk.Button(right, text=self.t('advanced'), command=self.prompt_developer_mode).pack(fill='x', pady=4)

        ttk.Separator(f).pack(fill='x', pady=12)
        ttk.Label(f, text=self.t('release_notes'), style='Section.TLabel').pack(anchor='w')
        notes = scrolledtext.ScrolledText(f, height=8, bg=self.theme['entry'], fg=self.theme['text'], insertbackground=self.theme['text'], relief='solid', borderwidth=1)
        notes.pack(fill='both', expand=True, pady=(6, 10))
        notes.insert('1.0', self.release_notes_text())
        notes.configure(state='disabled')

        if self.developer_mode_valid():
            ttk.Separator(f).pack(fill='x', pady=10)
            dev = self.card(f, self.t('advanced'))
            dev.pack(fill='x', pady=(0, 0))
            ttk.Label(dev, text='DEV MODE', foreground=self.theme['warn'], background=self.theme['panel'], font=('Segoe UI Semibold', 11)).pack(anchor='w', pady=(0, 6))
            row1 = ttk.Frame(dev, style='Panel.TFrame')
            row1.pack(fill='x', pady=3)
            ttk.Button(row1, text=self.t('rollback_last_upgrade'), command=self.rollback_last_upgrade).pack(side='left', padx=(0, 6))
            ttk.Button(row1, text=self.t('open_updates_folder'), command=lambda: self.open_path(UPDATES_DIR)).pack(side='left', padx=6)
            ttk.Button(row1, text=self.t('open_backups_folder'), command=lambda: self.open_path(BACKUP_DIR)).pack(side='left', padx=6)
            ttk.Button(row1, text=self.t('open_logs_folder'), command=lambda: self.open_path(LOG_DIR)).pack(side='left', padx=6)
            row2 = ttk.Frame(dev, style='Panel.TFrame')
            row2.pack(fill='x', pady=3)
            ttk.Button(row2, text=self.t('open_workspace_folder'), command=lambda: self.open_path(RUN_DIR / 'workspace')).pack(side='left', padx=(0, 6))
            ttk.Button(row2, text=self.t('run_update'), command=self.run_update_bat).pack(side='left', padx=6)
            ttk.Button(row2, text=self.t('validate_tools'), command=lambda: self.validate_all_tools(True)).pack(side='left', padx=6)
            ttk.Label(dev, text=self.t('developer_mode_timeout'), style='Muted.TLabel').pack(anchor='w', pady=(6,0))

        self.set_status(self.t('update_center_loaded'))

    def _resolve_upgrade_root(self, tmp_dir):
        root = tmp_dir
        nested = [p for p in tmp_dir.iterdir() if p.is_dir()]
        if len(nested) == 1 and not any(p.is_file() for p in tmp_dir.iterdir()):
            root = nested[0]
        return root

    def _backup_upgrade_targets(self, root, backup_dir):
        blocked = {'logs', 'workspace', 'backups', '__pycache__'}
        copied = []
        for item in root.iterdir():
            if item.name in blocked or item.name == 'upgrade_manifest.json':
                continue
            target = RUN_DIR / item.name
            if target.exists():
                try:
                    if target.is_dir():
                        shutil.copytree(target, backup_dir / item.name, dirs_exist_ok=True)
                    else:
                        shutil.copy2(target, backup_dir / item.name)
                except Exception as e:
                    logger.write(f'Backup warning for {target}: {e}')
            copied.append(item.name)
        (backup_dir / 'backup_manifest.json').write_text(json.dumps({
            'created': datetime.now().isoformat(timespec='seconds'),
            'run_dir': str(RUN_DIR),
            'items': copied
        }, indent=2, ensure_ascii=False), encoding='utf-8')
        return copied

    def _restart_command(self):
        if getattr(sys, 'frozen', False):
            return f'"{sys.executable}"'
        run_bat = RUN_DIR / 'Run_Hub.bat'
        if run_bat.exists():
            return f'"{run_bat}"'
        return f'"{sys.executable}" "{Path(__file__).resolve()}"'

    def _write_windows_apply_bat(self, source_dir, label):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        bat_path = UPDATES_DIR / f'apply_{label}_{stamp}.bat'
        restart_cmd = self._restart_command()
        lines = [
            '@echo off',
            'setlocal',
            'title InSightec Service Hub Updater',
            f'echo InSightec Service Hub - applying {label}...',
            'echo Please do not close this window.',
            'timeout /t 2 /nobreak >nul',
            f'robocopy "{source_dir}" "{RUN_DIR}" /E /XD logs workspace backups __pycache__ /XF upgrade_manifest.json backup_manifest.json /NFL /NDL /NJH /NJS',
            'set RC=%ERRORLEVEL%',
            'if %RC% LEQ 7 (',
            '  echo Update applied successfully.',
            f'  start "" {restart_cmd}',
            '  exit /b 0',
            ') else (',
            '  echo Update failed. Robocopy error: %RC%',
            '  pause',
            '  exit /b %RC%',
            ')',
        ]
        bat_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return bat_path


    def show_update_progress(self):
        win = tk.Toplevel(self)
        win.title(self.t('updating_title'))
        win.transient(self)
        win.grab_set()
        win.configure(bg=self.theme['bg'])
        win.geometry('520x340')
        ttk.Label(win, text=self.t('updating_title'), font=('Segoe UI Semibold', 18)).pack(anchor='w', padx=24, pady=(24, 6))
        ttk.Label(win, text=self.t('updating_message'), background=self.theme['bg'], foreground=self.theme['muted']).pack(anchor='w', padx=24, pady=(0, 12))
        steps = [self.t('update_step_backup'), self.t('update_step_verify'), self.t('update_step_install'), self.t('update_step_restart')]
        vars_ = []
        for i, step in enumerate(steps):
            v = tk.StringVar(value=f"□ {step}")
            vars_.append(v)
            ttk.Label(win, textvariable=v, font=('Segoe UI', 11)).pack(anchor='w', padx=34, pady=6)
        ttk.Label(win, text=self.t('do_not_close'), background=self.theme['bg'], foreground=self.theme['warn']).pack(anchor='w', padx=24, pady=(14, 0))
        def set_step(idx, state='active'):
            prefix = '▶' if state == 'active' else ('✓' if state == 'done' else '□')
            vars_[idx].set(f"{prefix} {steps[idx]}")
            win.update_idletasks()
            win.update()
        win.set_step = set_step
        win.update()
        return win

    def install_upgrade_zip(self):
        zip_path = filedialog.askopenfilename(title=self.t('select_upgrade_zip'), filetypes=[('Upgrade ZIP', '*.zip'), ('All files', '*.*')])
        if not zip_path:
            return
        if not messagebox.askyesno(self.t('confirm_upgrade_title'), self.t('confirm_upgrade_message')):
            return
        progress = self.show_update_progress()
        progress_start = time.time()
        progress.set_step(0, 'active')
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = BACKUP_DIR / f'upgrade_backup_{stamp}'
        stage_dir = UPDATES_DIR / f'staged_upgrade_{stamp}'
        backup_dir.mkdir(parents=True, exist_ok=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix='ish_upgrade_'))
        try:
            progress.set_step(1, 'active')
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(tmp_dir)
            root = self._resolve_upgrade_root(tmp_dir)
            manifest = load_json(root / 'upgrade_manifest.json', {})
            progress.set_step(1, 'done')
            self._backup_upgrade_targets(root, backup_dir)
            progress.set_step(0, 'done')
            progress.set_step(2, 'active')
            shutil.copytree(root, stage_dir, dirs_exist_ok=True)
            progress.set_step(2, 'done')
            (stage_dir / 'upgrade_applied_from.txt').write_text(str(zip_path), encoding='utf-8')
            if platform.system() == 'Windows':
                progress.set_step(3, 'active')
                bat_path = self._write_windows_apply_bat(stage_dir, 'upgrade')
                msg = self.t('upgrade_ready_restart') + f"\n\n{self.t('backup_folder')}: {backup_dir}\n{self.t('stage_folder')}: {stage_dir}"
                if manifest:
                    msg += f"\n{self.t('upgrade_version')}: {manifest.get('version', manifest.get('build', 'N/A'))}"
                elapsed = time.time() - progress_start
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                progress.destroy()
                messagebox.showinfo(self.t('upgrade_ready_title'), msg)
                logger.write(f'Launching upgrade apply BAT: {bat_path}')
                os.startfile(str(bat_path))
                self.destroy()
                sys.exit(0)
            else:
                for item in root.iterdir():
                    if item.name in {'logs', 'workspace', 'backups', '__pycache__', 'upgrade_manifest.json'}:
                        continue
                    target = RUN_DIR / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
                progress.set_step(3, 'done')
                elapsed = time.time() - progress_start
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                progress.destroy()
                messagebox.showinfo(self.t('upgrade_complete_title'), self.t('upgrade_complete'))
                self.set_status(self.t('upgrade_complete'))
        except Exception as e:
            try:
                progress.destroy()
            except Exception:
                pass
            logger.write(f'Upgrade failed: {e}\n{traceback.format_exc()}')
            messagebox.showerror(self.t('upgrade_failed_title'), f"{self.t('upgrade_failed')}\n\n{e}")
            self.set_status(self.t('upgrade_failed'))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def rollback_last_upgrade(self):
        backups = sorted(BACKUP_DIR.glob('upgrade_backup_*'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            messagebox.showinfo(self.t('rollback_title'), self.t('rollback_no_backup'))
            return
        backup_dir = backups[0]
        if not messagebox.askyesno(self.t('rollback_title'), self.t('rollback_confirm') + f"\n\n{backup_dir}"):
            return
        try:
            if platform.system() == 'Windows':
                bat_path = self._write_windows_apply_bat(backup_dir, 'rollback')
                messagebox.showinfo(self.t('rollback_ready_title'), self.t('rollback_ready_message'))
                logger.write(f'Launching rollback apply BAT: {bat_path}')
                os.startfile(str(bat_path))
                self.destroy()
                sys.exit(0)
            else:
                for item in backup_dir.iterdir():
                    if item.name == 'backup_manifest.json':
                        continue
                    target = RUN_DIR / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
                messagebox.showinfo(self.t('rollback_title'), self.t('rollback_complete'))
                self.set_status(self.t('rollback_complete'))
        except Exception as e:
            logger.write(f'Rollback failed: {e}\n{traceback.format_exc()}')
            messagebox.showerror(self.t('rollback_title'), f"{self.t('rollback_failed')}\n\n{e}")

    def run_update_bat(self):
        bat = filedialog.askopenfilename(title='Select update BAT', filetypes=[('Batch file', '*.bat'), ('All files', '*.*')])
        if not bat:
            return
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = BACKUP_DIR / f'config_backup_{stamp}.json'
        try:
            shutil.copy2(CONFIG_PATH, backup)
        except Exception:
            pass
        target = UPDATES_DIR / f"update_{stamp}_{Path(bat).name}"
        shutil.copy2(bat, target)
        self.set_status(f'Running update BAT with normal user permission: {target.name}')
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(['cmd.exe', '/c', str(target)], cwd=str(RUN_DIR), shell=False)
            else:
                subprocess.Popen(['bash', str(target)], cwd=str(RUN_DIR))
            messagebox.showinfo('Update started', 'Update BAT started with normal user permission.\nA config backup was created before execution.')
        except Exception as e:
            self.set_status(f'Update failed: {e}')
            messagebox.showerror('Update failed', str(e))

    def show_help(self):
        self.current_page = 'help'
        self.clear_content()
        self.page_title(self.t('help'), self.t('help_subtitle'))
        outer = ttk.Frame(self.content, style='Panel.TFrame')
        outer.pack(fill='both', expand=True, padx=18, pady=12)
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        for key, title in [('quick_start', self.t('quick_start')), ('guided_tour', self.t('guided_tour')), ('release_notes', self.t('release_notes'))]:
            frame = ttk.Frame(tabs, style='Panel.TFrame')
            tabs.add(frame, text=title)
            text = scrolledtext.ScrolledText(frame, bg=self.theme['entry'], fg=self.theme['text'], insertbackground=self.theme['text'], relief='flat', font=('Segoe UI', max(9, int(self.ui_scale * 11))))
            text.pack(fill='both', expand=True, padx=8, pady=8)
            text.insert('1.0', self.help_text(key))
            text.configure(state='disabled')
        self.set_status('Help Center loaded')

    def help_text(self, key):
        lang = self.cfg.get('language', 'en')
        if key == 'quick_start':
            if lang == 'ja':
                return 'クイックスタート\n\n1. Dashboardでツール状態を確認します。\n2. Toolsで必要なEXEを起動します。\n3. Feedbackでコメントと添付をまとめます。\n4. Outlookが使えない場合はテンプレートをコピーします。\n5. Updateは通常権限のBATで実行します。'
            if lang == 'zh_TW':
                return '快速開始\n\n1. 在 Dashboard 確認工具狀態。\n2. 在 Tools 啟動需要的 EXE。\n3. 使用 Feedback 彙整註解與附件。\n4. 如果無法使用 Outlook，請複製郵件範本。\n5. Update 以一般使用者權限執行 BAT。'
            if lang == 'ko':
                return '빠른 시작\n\n1. Dashboard에서 도구 상태를 확인합니다.\n2. Tools에서 필요한 EXE를 실행합니다.\n3. Feedback에서 의견과 첨부 파일을 정리합니다.\n4. Outlook을 사용할 수 없으면 메일 템플릿을 복사합니다.\n5. Update는 일반 사용자 권한의 BAT로 실행합니다.'
            return 'Quick Start\n\n1. Check tool status in Dashboard.\n2. Open Tools and launch the required EXE.\n3. Use Feedback to collect comments and attachments.\n4. If Outlook is unavailable, copy the email template.\n5. Run updates using normal-permission BAT files.'
        if key == 'guided_tour':
            if lang == 'ja':
                return 'ガイドツアー\n\nM1ではHelp内ガイドとして実装。次の段階で画面上に吹き出しを重ねるInteractive Guideへ拡張します。\n\nDashboard → Tools → Feedback → Update → Settings の順で確認してください。'
            if lang == 'zh_TW':
                return '導覽\n\nM1 先以 Help 內的導覽實作。下一階段會加入畫面上的互動提示。\n\n建議順序：Dashboard → Tools → Feedback → Update → Settings。'
            if lang == 'ko':
                return '가이드 투어\n\nM1에서는 Help 기반 가이드로 제공합니다. 다음 단계에서 실제 UI 위에 안내 말풍선을 추가합니다.\n\n권장 순서: Dashboard → Tools → Feedback → Update → Settings.'
            return 'Guided Tour\n\nM1 provides this Help-based guide. The next step will add overlay callouts on the live UI.\n\nRecommended path: Dashboard → Tools → Feedback → Update → Settings.'
        if lang == 'ja':
            return 'リリースノート\n\nValidation Build 003.1\n- 4言語切替を追加。\n- UI、Help、Feedback、Validationの翻訳キーを追加。\n- 再起動不要のリアルタイム切替に対応。'
        if lang == 'zh_TW':
            return '版本資訊\n\nValidation Build 003.1\n- 新增四語言切換。\n- 新增 UI、Help、Feedback、Validation 翻譯鍵。\n- 支援不重新啟動的即時切換。'
        if lang == 'ko':
            return '릴리스 노트\n\nValidation Build 003.1\n- 4개 언어 전환을 추가했습니다.\n- UI, Help, Feedback, Validation 번역 키를 추가했습니다.\n- 재시작 없는 실시간 전환을 지원합니다.'
        return self.t('release_notes_text')

    def show_settings(self):
        self.current_page = 'settings'
        self.clear_content()
        self.page_title(self.t('settings'), self.t('settings_subtitle'))
        f = self.card(self.content, self.t('settings'))
        f.pack(fill='both', expand=True, padx=18, pady=12)
        lang_var = tk.StringVar(value=self.language_label(self.cfg.get('language', 'en')))
        theme_var = tk.StringVar(value=self.cfg.get('theme', 'insightec_light'))
        mode_var = tk.StringVar(value=self.cfg.get('feedback_mode', 'template'))
        to_var = tk.StringVar(value=self.cfg.get('feedback_to', 'masakii@insightec.com'))
        user_var = tk.StringVar(value=self.cfg.get('user_name', 'Masaki'))
        startup_var = tk.StringVar(value=self.cfg.get('startup_page', 'dashboard'))
        fields = ttk.Frame(f, style='Panel.TFrame')
        fields.pack(anchor='nw', fill='x')
        self.form_row(fields, self.t('language'), self.language_menu_button(fields, lang_var, lambda c: lang_var.set(self.language_label(c)), width=34))
        lang_note = ttk.Label(fields, text=self.t('language_note'), style='Muted.TLabel')
        lang_note.pack(anchor='w', padx=160, pady=(0, 8))
        self.form_row(fields, self.t('theme'), ttk.Combobox(fields, textvariable=theme_var, values=list(THEMES.keys()), width=28, state='readonly'))
        self.form_row(fields, self.t('user_name'), ttk.Entry(fields, textvariable=user_var, width=32))
        self.form_row(fields, self.t('startup_page'), ttk.Combobox(fields, textvariable=startup_var, values=['dashboard', 'tools'], width=28, state='readonly'))
        self.form_row(fields, self.t('feedback_mode'), ttk.Combobox(fields, textvariable=mode_var, values=['template', 'outlook'], width=28, state='readonly'))
        self.form_row(fields, self.t('feedback_to'), ttk.Entry(fields, textvariable=to_var, width=50))
        def save():
            requested_language = self.parse_language_value(lang_var.get())
            if not self.language_enabled(requested_language):
                messagebox.showinfo(self.t('language_not_available_title'), self.t('language_not_available_message'))
                lang_var.set(self.language_label(self.cfg.get('language', 'en')))
                return
            old_page = self.current_page
            self.cfg['startup_page'] = startup_var.get()
            self.cfg['language'] = requested_language
            self.cfg['theme'] = theme_var.get()
            self.cfg['feedback_mode'] = mode_var.get()
            self.cfg['feedback_to'] = to_var.get().strip()
            self.cfg['user_name'] = user_var.get().strip() or 'Service Engineer'
            save_config(self.cfg)
            self.lang = self.load_language(requested_language)
            self.theme_name = self.cfg.get('theme', 'insightec_light')
            self.theme = THEMES.get(self.theme_name, THEMES['insightec_light'])
            self.rebuild_ui(old_page)
            self.set_status(self.t('settings_saved'))
        ttk.Button(f, text=self.t('save'), command=save, style='Accent.TButton').pack(anchor='e', pady=18)
        self.translation_progress_widget(f)

    def form_row(self, parent, label, widget):
        row = ttk.Frame(parent, style='Panel.TFrame')
        row.pack(fill='x', pady=6)
        ttk.Label(row, text=label, style='Panel.TLabel', width=18).pack(side='left')
        widget.pack(side='left')

    def show_about(self):
        self.current_page = 'about'
        self.clear_content()
        self.page_title(self.t('about_system_information'), self.t('about_copy_instruction'))
        rows = self.validate_all_tools(save_report=False)
        info = [
            f"Hub: {self.cfg.get('console_name', 'InSightec Service Hub')}",
            f"Build: {self.cfg.get('console_version', '')}",
            f"Build Date: {self.cfg.get('build_date', '')}",
            f"Python: {platform.python_version()}",
            f"OS: {platform.platform()}",
            f"Run Folder: {RUN_DIR}",
            '',
            'Language Status:',
            *self.language_status_lines(),
            '',
            f"Hub Log: {logger.path}",
            f"Session Log: {SESSION_LOG_PATH}",
            '',
            'Installed Tools:',
        ]
        for r in rows:
            info.append(f"- {r['name']} {r['version']}: {r['result']} / {r['status']}")
        text = '\n'.join(info)
        f = self.card(self.content, self.t('system_information'))
        f.pack(fill='both', expand=True, padx=18, pady=12)
        box = scrolledtext.ScrolledText(f, height=22, font=('Consolas', 10))
        box.pack(fill='both', expand=True)
        box.insert('1.0', text)
        box.configure(state='disabled')
        def copy_info():
            self.clipboard_clear()
            self.clipboard_append(text)
            self.set_status('System information copied')
        ttk.Button(f, text=self.t('copy_system_information'), style='Accent.TButton', command=copy_info).pack(anchor='e', pady=10)
        self.set_status(self.t('about_loaded'))

    def search(self):
        q = self.search_var.get().strip()
        if not q or q == self.t('search'):
            return
        matches = []
        low = q.lower()
        for t in self.get_tools():
            name = self.tr_tool(t, 'name')
            desc = self.tr_tool(t, 'description')
            if low in name.lower() or low in desc.lower() or low in t.get('id', '').lower():
                matches.append(t)
        self.clear_content()
        self.page_title(self.t('search_title'), q)
        f = self.card(self.content, f"{len(matches)} {self.t('tool_result_count')}")
        f.pack(fill='both', expand=True, padx=18, pady=12)
        if matches:
            for t in matches:
                self.tool_row(f, t)
        else:
            ttk.Label(f, text=self.t('no_result'), style='Panel.TLabel').pack(anchor='w')
        self.set_status(f'Search: {q}')

    def _clear_search_placeholder(self):
        if self.search_var.get() == self.t('search'):
            self.search_var.set('')

    def rebuild_ui(self, page=None):
        current = page or self.current_page
        for w in self.winfo_children():
            w.destroy()
        self._apply_style()
        self._build_shell()
        page_map = {
            'dashboard': self.show_dashboard,
            'tools': self.show_tools,
            'feedback': self.show_feedback,
            'update': self.show_update,
            'help': self.show_help,
            'settings': self.show_settings,
            'about': self.show_about,
        }
        page_map.get(current, self.show_dashboard)()

    def change_language(self, code):
        if code not in SUPPORTED_LANGUAGES:
            code = 'en'
        if not self.language_enabled(code):
            messagebox.showinfo(self.t('language_not_available_title'), self.t('language_not_available_message'))
            self.lang_var.set(self.language_label(self.cfg.get('language', 'en')))
            return
        self.cfg['language'] = code
        save_config(self.cfg)
        self.lang = self.load_language(code)
        self.rebuild_ui(self.current_page)
        self.set_status(f"{self.t('language_changed')}: {SUPPORTED_LANGUAGES.get(code, code)}")

    def translation_progress_widget(self, parent):
        f = ttk.Frame(parent, style='Panel.TFrame')
        f.pack(fill='x', pady=(18, 4))
        ttk.Label(f, text=self.t('translation_status'), style='Panel.TLabel', font=('Segoe UI Semibold', max(9, int(self.ui_scale * 11)))).pack(anchor='w', pady=(0, 6))
        for code in SUPPORTED_LANGUAGES:
            meta = LANGUAGE_METADATA.get(code, {})
            status = self.t('ready') if meta.get('enabled') else self.t('coming_soon')
            ttk.Label(f, text=f"{meta.get('flag','')} {meta.get('native', code):<12}  {meta.get('completion', 0)}%  -  {status}", style='Muted.TLabel').pack(anchor='w', padx=8)

    def init_parts_db(self):
        db = DB_DIR / 'parts.db'
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute('create table if not exists parts(part_number text, description text, system text, notes text, photo_path text)')
        con.commit()
        con.close()

    def open_path(self, path):
        try:
            if platform.system() == 'Windows':
                os.startfile(str(path))
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path)])
        except Exception as e:
            messagebox.showerror('Open failed', str(e))

if __name__ == '__main__':
    try:
        HubApp().mainloop()
    except Exception:
        logger.write(traceback.format_exc())
        raise
