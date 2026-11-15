"""
Umbra Effects Setup, the window (tkinter). All logic lives in setup_core; this file
only shows it and turns clicks into calls. Long work runs off the window's
thread: the plan and the up-to-date check on threads, bakes in a worker
process (setup_core.Job).
"""
import os
import queue
import threading
import time
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import setup_core as core
import typeface

PAD = 6
WRAP = 470
# Umbra's colours (the Umbra repo's branding/README.md); WARN is this window's own amber
SOOT, PANEL, PANEL2, LINE = '#14130f', '#1c1a15', '#24211b', '#3a352b'
BONE, MUTED, PAPER = '#d9cca6', '#9a907a', '#cdbf99'
UMBER, UMBER_HI, OK, BAD, WARN = '#5e4532', '#71533c', '#8fa66b', '#d0614a', '#d39b4a'

EXPLAIN = {
    'models': "Every character and mutant model your mod list loads, rebuilt so each body part can be cut off "
              "cleanly. They look exactly the same as the originals.",
    'caps': 'A fitted flesh-and-bone cap for every cut, made from the model itself. About 250 MB.',
    'pieces': 'Light models of severed limbs, closed at the cut. The largest part (about 3.2 GB); without them a '
              'cut limb is drawn from a copy of the whole body.',
    'wounds': 'Where wounds can open on every body. A few MB.',
    'gibs': "The pieces an explosion tears out of a body, cut from that body's own model: its clothes, skin or fur "
            'outside, raw flesh inside. About 650 MB and a minute; without them, explosions throw meat models.',
    'props': 'Cuts the barrels, crates, bottles and stools of your mod list into pieces, for '
             '"Objects break apart". A few MB, a few seconds.',
    'kid_particles': 'Lets kid mode hide blood and gore particles already flying (MCM: General -> Kid mode: hide '
                     "particles already flying). Rebuilds Umbra Effects' particle shaders from your mod list and copies the "
                     'gory effects other mods play. Under 1 MB, a few seconds.',
    'experimental_caps': 'Also puts the stump caps inside every body model as hidden parts, for a cut method that '
                         'is not switched on yet. If the game cannot hide them, every NPC shows them all the time. '
                         'Only for testing (Diagnostics probe 1 must pass).',
    'experimental_damage': 'Dense copies of every body part for future wound damage, plus gib chunks. About ten '
                           'times larger (25-30 GB) and about an hour. Only for testing (Diagnostics probes 1-3).',
    'experimental_props': 'Lets the game itself break crates and stools into the cut pieces (knife, bullets, '
                          'explosions). Not checked in co-op yet. Only for testing.',
}
LABEL = {
    'models': 'Body models (always)', 'caps': 'Stump caps', 'pieces': 'Limb pieces', 'wounds': 'Wound sites',
    'gibs': 'Body gibs',
    'props': 'Breakable props', 'kid_particles': 'Kid mode for particles',
    'experimental_caps': 'Caps inside every model (experimental)',
    'experimental_damage': 'Damage meshes and gib chunks (experimental)',
    'experimental_props': 'Game breaks crates and stools itself (experimental)',
}
# the bake's state -> the style of its headline
STATE_STYLE = {'ok': 'Good.TLabel', 'stale': 'BoldWarn.TLabel', 'order': 'BoldWarn.TLabel',
               'broken': 'BoldBad.TLabel', 'none': 'Bold.TLabel', 'busy': 'Bold.TLabel', 'off': 'Bold.TLabel'}
# kid mode for particles, the short line beside its Apply now / Undo buttons
KID_STATE = {'ok': "On: gory particles use Umbra Effects' particle shaders.",
             'off': "Off: every particle uses the game's own shaders.",
             'stale': 'Only partly on: press "Apply now".', 'none': ''}
# what runs, in words (closing the window while it runs)
BUSY_TEXT = {'bake': 'bake', 'remove': 'removal', 'props': 'props cut', 'kidfx_apply': 'particle shader change',
             'kidfx_revert': 'particle shader change'}


class Scrolled(ttk.Frame):
    """A frame whose content (.inner) scrolls when the window is too small
    for it (small laptop screens). The scroll bar always keeps its place, so
    showing it never changes the layout (which could flicker forever)."""

    def __init__(self, parent):
        super().__init__(parent)
        bg = ttk.Style(self).lookup('TFrame', 'background') or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=bg)
        self.sb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = ttk.Frame(self.canvas, padding=PAD)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.sb.grid(row=0, column=1, sticky='ns')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._req = None
        self.inner.bind('<Configure>', self._inner_changed)
        self.canvas.bind('<Configure>', self._canvas_changed)
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.canvas.bind_all(seq, self._wheel, add='+')

    def _inner_changed(self, event=None):
        req = (self.inner.winfo_reqwidth(), self.inner.winfo_reqheight())
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_width(), self.inner.winfo_height()))
        if req != self._req:
            self._req = req
            self.canvas.configure(width=req[0], height=req[1])

    def _canvas_changed(self, event):
        if int(self.canvas.itemcget(self.win, 'width') or 0) != event.width:
            self.canvas.itemconfigure(self.win, width=event.width)

    def scrollable(self):
        lo, hi = self.canvas.yview()
        return lo > 0.0 or hi < 1.0

    def _wheel(self, event):
        if not self.scrollable():
            return
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return
        while w is not None and w is not self:
            if isinstance(w, (ttk.Treeview, tk.Text)):
                return                       # those scroll themselves
            w = getattr(w, 'master', None)
        if w is None:
            return
        if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0:
            self.canvas.yview_scroll(-2, 'units')
        else:
            self.canvas.yview_scroll(2, 'units')


class App:
    def __init__(self, root, mod_root=None, paths=None, log=None):
        self.root = root
        self.log = log or core.Log()
        self.q = queue.Queue()
        self.job = None
        self.busy = None             # what runs now: 'check', 'bake', 'remove', 'props', 'kidfx_apply', 'kidfx_revert'
        self.closing = False
        self.tools = None
        self.plan = None
        self.status = None
        self.kid_state = 'none'      # kid mode for particles: core.check_kidfx's state
        self.with_props = self.with_particles = False
        self._plan_after = None
        self._t_job = None
        self._warned = set()
        self._refit_pending = False
        self._fitted = False
        # where the bake goes and the baker's work folder, when not the
        # defaults (--cache; tests bake into a temporary folder)
        self._out = paths.out if paths is not None and paths.out and paths.out != paths.mod else None
        self._cache = paths.cache if paths is not None else None
        root.title('Umbra Effects Setup - Umbra Gore & Effects')
        root.minsize(820, 560)
        self._style()
        self._build()
        self._fit()
        self.log.listeners.append(self._log_line)
        for line in self.log.lines:
            self._log_line(*line)
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.after(100, self._pump)
        self.set_mod(mod_root, paths)

    # ------------------------------------------------------------ layout
    def _style(self):
        """Umbra's look: its colours, and its typefaces (typeface.py draws them where
        Tk can't load a font file, as in the Linux program)."""
        r = self.root
        typeface.setup(r)
        st = ttk.Style(r)
        try:
            st.theme_use('clam')
        except tk.TclError:
            pass
        f, body = typeface.font, typeface.BODY_SIZE
        # what Tk draws itself (tabs, column heads) can't use the font files when typeface
        # draws text as images (the Linux program): the best system font then
        tk_font = f if typeface.MODE == 'native' else (lambda role, size: 'TkDefaultFont')
        st.configure('.', background=SOOT, foreground=BONE, fieldbackground=PANEL2, bordercolor=LINE,
                     lightcolor=LINE, darkcolor=LINE, troughcolor=PANEL, focuscolor=UMBER, arrowcolor=BONE,
                     selectbackground=UMBER, selectforeground=PAPER, insertcolor=BONE)
        st.map('.', foreground=[('disabled', MUTED)])
        st.configure('TFrame', background=SOOT)
        st.configure('TLabel', background=SOOT, foreground=BONE)
        for name, fg, font in (('Muted', MUTED, None), ('Bad', BAD, None), ('Warn', WARN, None),
                               ('Small', MUTED, f('body', body - 1)), ('SmallWarn', WARN, f('body', body - 1)),
                               ('Bold', BONE, f('bold', body)), ('BoldBad', BAD, f('bold', body)),
                               ('BoldWarn', WARN, f('bold', body)), ('Good', OK, f('bold', body)),
                               ('Head', BONE, f('head', 22)), ('Frame', BONE, f('head', body + 1))):
            st.configure(name + '.TLabel', background=SOOT, foreground=fg, **({'font': font} if font else {}))
        st.configure('TLabelframe', background=SOOT, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        st.configure('TLabelframe.Label', background=SOOT, foreground=BONE, font=tk_font('head', body + 1))
        st.configure('TButton', background=PANEL2, foreground=BONE, padding=(12, 5), borderwidth=1,
                     font=f('head', body))
        st.map('TButton', background=[('active', LINE), ('disabled', PANEL)], foreground=[('disabled', MUTED)])
        st.configure('Primary.TButton', background=UMBER, foreground=PAPER, padding=(22, 6), font=f('head', body + 1))
        st.map('Primary.TButton', background=[('active', UMBER_HI), ('disabled', PANEL)],
               foreground=[('disabled', MUTED)])
        st.configure('Small.TButton', padding=(8, 1), font=f('head', body - 1))
        st.configure('TCheckbutton', background=SOOT, foreground=BONE, indicatorbackground=PANEL2,
                     indicatorforeground=BONE)
        st.map('TCheckbutton', background=[('active', SOOT)], foreground=[('disabled', MUTED)],
               indicatorbackground=[('disabled', PANEL), ('pressed', LINE)])
        st.configure('TEntry', foreground=BONE, fieldbackground=PANEL2, insertcolor=BONE, padding=3)
        st.configure('TSpinbox', foreground=BONE, fieldbackground=PANEL2, background=PANEL2, arrowcolor=BONE,
                     insertcolor=BONE)
        st.configure('TCombobox', fieldbackground=PANEL2, foreground=BONE, background=PANEL2, arrowcolor=BONE)
        # clam paints a read-only box light grey: keep it dark, and its list too
        st.map('TCombobox', fieldbackground=[('readonly', PANEL2), ('disabled', PANEL)],
               foreground=[('disabled', MUTED), ('readonly', BONE)], background=[('active', LINE)],
               selectbackground=[('readonly', PANEL2)], selectforeground=[('readonly', BONE)])
        for k, v in (('background', PANEL2), ('foreground', BONE), ('selectBackground', UMBER),
                     ('selectForeground', PAPER)):
            r.option_add('*TCombobox*Listbox.' + k, v)
        st.configure('TNotebook', background=SOOT, bordercolor=LINE, tabmargins=(0, 2, 0, 0))
        st.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, bordercolor=LINE, padding=(14, 5),
                     font=tk_font('head', body))
        st.map('TNotebook.Tab', background=[('selected', PANEL2), ('active', LINE)],
               foreground=[('selected', BONE), ('active', BONE)])
        st.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=BONE, bordercolor=LINE,
                     rowheight=22)
        st.configure('Treeview.Heading', background=PANEL2, foreground=BONE, bordercolor=LINE,
                     font=tk_font('head', body))
        st.map('Treeview.Heading', background=[('active', LINE)])
        st.configure('Vertical.TScrollbar', background=PANEL2, troughcolor=PANEL, bordercolor=LINE,
                     arrowcolor=MUTED)
        st.map('Vertical.TScrollbar', background=[('active', LINE)])
        st.configure('Horizontal.TProgressbar', background=UMBER, troughcolor=PANEL, bordercolor=LINE, thickness=14)
        r.configure(background=SOOT)

    def _frame(self, parent, text):
        """A labelled frame whose title is in Umbra's heading face."""
        lf = ttk.LabelFrame(parent, padding=(PAD, PAD // 2))
        lf.configure(labelwidget=typeface.Label(lf, text=text, style='Frame.TLabel'))
        return lf

    def _image(self, name):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', name)
        try:
            return tk.PhotoImage(master=self.root, file=p) if os.path.isfile(p) else None
        except tk.TclError:
            return None

    def _build(self):
        """Two tabs (Bake, Log) above the buttons and the progress bar, so it
        fits a 1366x768 screen; the explanations sit beside their tick boxes."""
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)
        self._icons = [i for i in (self._image('umbra-icon-256.png'), self._image('umbra-icon-64.png')) if i]
        if self._icons:
            try:
                r.iconphoto(True, *self._icons)
            except tk.TclError:
                pass
        head = ttk.Frame(r, padding=(PAD * 2, PAD * 2, PAD * 2, 0))
        head.grid(row=0, column=0, sticky='ew')
        if len(self._icons) > 1:
            ttk.Label(head, image=self._icons[1]).pack(side='left', padx=(0, PAD * 2))
        titles = ttk.Frame(head)
        titles.pack(side='left', fill='x')
        typeface.Label(titles, text='UMBRA GORE & EFFECTS', style='Head.TLabel').pack(anchor='w')
        typeface.Label(titles, text='Setup: bakes the body models for your own mod list. Close the game before baking.',
                       style='Muted.TLabel').pack(anchor='w')
        self.nb = ttk.Notebook(r)
        self.nb.grid(row=1, column=0, sticky='nsew', padx=PAD * 2, pady=(PAD, 0))
        self.p_bake = Scrolled(self.nb)
        page = self.p_bake.inner
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.nb.add(self.p_bake, text='Bake')
        self.p_log = ttk.Frame(self.nb, padding=PAD)
        self.nb.add(self.p_log, text='Log')
        self._unseen = 0
        self.nb.bind('<<NotebookTabChanged>>', self._tab_changed)

        # ---- where
        where = self._frame(page, 'Your game')
        where.grid(row=0, column=0, sticky='ew')
        where.columnconfigure(1, weight=1)
        self.v_mo2, self.v_profile, self.v_game, self.v_mod = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        rows = (('Mod Organizer 2 folder', self.v_mo2, self.pick_mo2),
                ('MO2 profile', self.v_profile, None),
                ('Game folder (Anomaly)', self.v_game, self.pick_game),
                ('Umbra Gore & Effects folder', self.v_mod, self.pick_mod))
        for i, (label, var, pick) in enumerate(rows):
            typeface.Label(where, text=label).grid(row=i, column=0, sticky='w', padx=(0, PAD), pady=1)
            if pick is None:
                self.cb_profile = ttk.Combobox(where, textvariable=var, state='readonly', width=40)
                self.cb_profile.grid(row=i, column=1, sticky='w', pady=1)
                self.cb_profile.bind('<<ComboboxSelected>>', lambda e: self.paths_changed())
                continue
            e = ttk.Entry(where, textvariable=var)
            e.grid(row=i, column=1, sticky='ew', pady=1)
            e.bind('<FocusOut>', lambda ev: self.paths_changed())
            e.bind('<Return>', lambda ev: self.paths_changed())
            typeface.Button(where, text='Change...', style='Small.TButton', command=pick).grid(
                row=i, column=2, padx=(PAD, 0), pady=1)
        self.l_problems = typeface.Label(where, text='', style='Bad.TLabel', wraplength=900, justify='left')
        self.l_problems.grid(row=len(rows), column=0, columnspan=3, sticky='w')
        self.l_problems.grid_remove()
        where.bind('<Configure>', lambda e: self.l_problems.configure(wraplength=max(300, e.width - 3 * PAD)))

        # ---- what (left) | models and your bake (right)
        mid = ttk.Frame(page)
        mid.grid(row=1, column=0, sticky='nsew', pady=(PAD, 0))
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)
        what = self._frame(mid, 'What to bake')
        what.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, PAD))
        what.columnconfigure(1, weight=1)
        self.v = {k: tk.BooleanVar(value=False) for k in core.Choices.FIELDS}
        self.v['models'] = tk.BooleanVar(value=True)
        self.checks = {}
        self._explain = []
        row = 0
        for k in ('models', 'caps', 'pieces', 'wounds', 'gibs', 'props', 'kid_particles'):
            row = self._check(what, k, row)
        # kid mode for particles on / off at once (only the ZGO folder changes; no bake needed)
        kf = ttk.Frame(what)
        kf.grid(row=row, column=1, sticky='w', padx=(PAD, 0), pady=(0, 3))
        self.b_kid_apply = typeface.Button(kf, text='Apply now', style='Small.TButton', command=self.kidfx_apply)
        self.b_kid_undo = typeface.Button(kf, text='Undo...', style='Small.TButton', command=self.kidfx_revert)
        self.b_kid_apply.pack(side='left')
        self.b_kid_undo.pack(side='left', padx=(PAD // 2, PAD))
        self.l_kidfx = typeface.Label(kf, text='', style='Small.TLabel', wraplength=WRAP - 300, justify='left')
        self.l_kidfx.pack(side='left')
        row += 1
        # the experimental parts: folded away until asked for (or ticked last time)
        self.v_show_exp = tk.BooleanVar(value=False)
        typeface.Checkbutton(what, text='Show the experimental parts (leave them off unless you are testing Umbra Effects)',
                        variable=self.v_show_exp, command=self.show_experimental).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(PAD // 2, 0))
        row += 1
        self.f_exp = self._frame(what, 'Experimental: not checked in the game yet')
        self.f_exp.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(PAD // 2, 0))
        self.f_exp.columnconfigure(1, weight=1)
        erow = 0
        for k in ('experimental_caps', 'experimental_damage', 'experimental_props'):
            erow = self._check(self.f_exp, k, erow)
        self.f_exp.grid_remove()
        row += 1
        cores = ttk.Frame(what)
        cores.grid(row=row, column=0, columnspan=2, sticky='w', pady=(PAD // 2, 0))
        typeface.Label(cores, text='CPU cores to use').pack(side='left')
        self.v_jobs = tk.IntVar(value=core.default_jobs())
        ttk.Spinbox(cores, from_=1, to=max(1, os.cpu_count() or 1), textvariable=self.v_jobs, width=4,
                    command=self.choices_changed).pack(side='left', padx=PAD)
        typeface.Label(cores, text='(fewer keeps the computer responsive; each needs about 300 MB of memory)',
                       style='Small.TLabel').pack(side='left')
        row += 1
        self.l_estimate = typeface.Label(what, text='', wraplength=WRAP, justify='left', style='Bold.TLabel')
        self.l_estimate.grid(row=row, column=0, columnspan=2, sticky='w', pady=(PAD // 2, 0))
        self._wrapped_for = None
        r.bind('<Configure>', lambda e: e.widget is r and self.root.after_idle(self._rewrap))

        right = self._frame(mid, 'Models your mod list loads')
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(right, columns=('n',), height=4, selectmode='none')
        self.tree.heading('#0', text='Comes from')
        self.tree.heading('n', text='Models')
        self.tree.column('#0', width=220, stretch=True)
        self.tree.column('n', width=60, anchor='e', stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        sb = ttk.Scrollbar(right, orient='vertical', command=self.tree.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure('over', foreground=BAD)

        stat = self._frame(mid, 'Your bake')
        stat.grid(row=1, column=1, sticky='nsew', pady=(PAD, 0))
        stat.columnconfigure(0, weight=1)
        self.l_head = typeface.Label(stat, text='', style='Bold.TLabel', wraplength=340, justify='left')
        self.l_head.grid(row=0, column=0, sticky='w')
        self.l_reasons = typeface.Label(stat, text='', wraplength=340, justify='left')
        self.l_reasons.grid(row=1, column=0, sticky='w')
        stat.bind('<Configure>', lambda e: [w.configure(wraplength=max(200, e.width - 2 * PAD - 4))
                                            for w in (self.l_head, self.l_reasons)])

        # ---- the log (its own tab)
        self.p_log.columnconfigure(0, weight=1)
        self.p_log.rowconfigure(0, weight=1)
        self.t_log = ScrolledText(self.p_log, height=10, wrap='word', state='disabled', bg=PANEL, fg=BONE,
                                  insertbackground=BONE, selectbackground=UMBER, selectforeground=PAPER,
                                  relief='flat', borderwidth=0, highlightthickness=1, highlightbackground=LINE,
                                  highlightcolor=LINE, padx=8, pady=6)
        try:
            self.t_log.vbar.configure(bg=PANEL2, troughcolor=PANEL, activebackground=LINE, highlightthickness=0,
                                      borderwidth=0, relief='flat')
        except (tk.TclError, AttributeError):
            pass
        self.t_log.grid(row=0, column=0, sticky='nsew')
        self.t_log.tag_configure('warn', foreground=WARN)
        self.t_log.tag_configure('error', foreground=BAD)
        lb = ttk.Frame(self.p_log)
        lb.grid(row=1, column=0, sticky='w', pady=(PAD // 2, 0))
        typeface.Button(lb, text='Save log...', command=self.save_log).pack(side='left')
        typeface.Button(lb, text='Copy log', command=self.copy_log).pack(side='left', padx=PAD)
        self.l_logpath = typeface.Label(lb, text=('Also written to %s' % self.log.path) if self.log.path else '',
                                        style='Small.TLabel')
        self.l_logpath.pack(side='left')

        # ---- buttons + progress (always in view)
        act = ttk.Frame(r, padding=(PAD * 2, PAD, PAD * 2, PAD))
        act.grid(row=2, column=0, sticky='ew')
        act.columnconfigure(5, weight=1)
        self.b_bake = typeface.Button(act, text='Bake', style='Primary.TButton', command=self.bake)
        self.b_check = typeface.Button(act, text='Check if my bake is up to date', command=self.check)
        self.b_remove = typeface.Button(act, text='Remove bake', command=self.remove)
        self.b_cancel = typeface.Button(act, text='Cancel', command=self.cancel, state='disabled')
        self.b_props_only = typeface.Button(act, text='Cut props only', command=self.bake_props)
        for i, b in enumerate((self.b_bake, self.b_check, self.b_remove, self.b_cancel)):
            b.grid(row=0, column=i, padx=(0, PAD))
        self.b_props_only.grid(row=0, column=6, sticky='e')
        self.progress = ttk.Progressbar(act, mode='determinate', maximum=1000)
        self.progress.grid(row=1, column=0, columnspan=7, sticky='ew', pady=(PAD // 2, 0))
        self.l_progress = typeface.Label(act, text='Ready.')
        self.l_progress.grid(row=2, column=0, columnspan=7, sticky='w')

    def _tab_changed(self, event=None):
        if self.nb.index('current') == 1:
            self._unseen = 0
            self.nb.tab(self.p_log, text='Log')

    def _fit(self):
        """At first as large as the content wants (never larger than the
        screen; the Bake tab scrolls then); later only taller when content
        appears, so the width (and the text wrapping that follows it) settles."""
        r = self.root
        try:
            r.update_idletasks()
            sh = r.winfo_screenheight() - 90
            cw, ch = r.winfo_width(), r.winfo_height()
            if not self._fitted:
                self._fitted = True
                w = min(max(r.winfo_reqwidth(), 980), r.winfo_screenwidth() - 40)
                r.geometry('%dx%d' % (w, min(r.winfo_reqheight(), sh)))
            else:
                h = min(r.winfo_reqheight(), sh)
                if h > ch > 1:
                    r.geometry('%dx%d' % (cw, h))
        except tk.TclError:
            pass

    def refit(self):
        if not self._refit_pending:
            self._refit_pending = True

            def go():
                self._refit_pending = False
                self._fit()
            self.root.after_idle(go)

    def show_experimental(self):
        if self.v_show_exp.get():
            self.f_exp.grid()
        else:
            self.f_exp.grid_remove()
        self.refit()

    def _check(self, parent, key, row):
        """A tick box with its explanation beside it."""
        cb = typeface.Checkbutton(parent, text=LABEL[key], variable=self.v[key],
                             command=lambda k=key: self.on_tick(k))
        cb.grid(row=row, column=0, sticky='nw', pady=(0, 3))
        if key == 'models':
            cb.state(['disabled'])
        self.checks[key] = cb
        lab = typeface.Label(parent, text=EXPLAIN[key], wraplength=WRAP - 120, justify='left', style='Small.TLabel')
        lab.grid(row=row, column=1, sticky='nw', padx=(PAD, 0), pady=(2, 3))
        self._explain.append((lab, cb))
        return row + 1

    def set_problems(self, text, style='Bad.TLabel'):
        self.l_problems.configure(text=text, style=style)
        if text:
            self.l_problems.grid()
        else:
            self.l_problems.grid_remove()
        self.refit()

    def _rewrap(self, event=None):
        """Explanation text follows the window's width (only that: wrapping by
        the widgets' own sizes can make Tk re-layout forever)."""
        try:
            width = self.root.winfo_width()
        except tk.TclError:
            return
        if width < 200 or (self._wrapped_for is not None and abs(width - self._wrapped_for) < 8):
            return
        self._wrapped_for = width
        left = (width - 8 * PAD) * 3 // 5                # the "What to bake" column
        try:
            for lab, cb in self._explain:
                boxes = max(c.winfo_reqwidth() for l2, c in self._explain if l2.master is lab.master)
                inset = 4 * PAD if lab.master is self.f_exp else 2 * PAD
                lab.configure(wraplength=max(160, left - boxes - inset - 3 * PAD))
                if cb is self.checks.get('kid_particles'):
                    buttons = self.b_kid_apply.winfo_reqwidth() + self.b_kid_undo.winfo_reqwidth() + 2 * PAD
                    self.l_kidfx.configure(wraplength=max(120, left - boxes - inset - 3 * PAD - buttons))
            self.l_estimate.configure(wraplength=max(200, left - 3 * PAD))
        except tk.TclError:
            pass

    # ------------------------------------------------------------ helpers
    def say(self, msg, level='info'):
        self.log(msg, level)

    def _log_line(self, level, line):
        try:
            if level in ('warn', 'error') and self.nb.index('current') != 1:
                self._unseen += 1
                self.nb.tab(self.p_log, text='Log (%d new warning%s)' % (self._unseen, '' if self._unseen == 1 else 's'))
            self.t_log.configure(state='normal')
            self.t_log.insert('end', line + '\n', (level,) if level in ('warn', 'error') else ())
            self.t_log.see('end')
            self.t_log.configure(state='disabled')
        except tk.TclError:
            pass

    def run_thread(self, name, fn, *args):
        """fn(*args) on a thread; its result comes back to on_<name>."""
        def body():
            try:
                self.q.put((name, True, fn(*args)))
            except Exception as e:  # noqa: BLE001
                self.q.put((name, False, (e, traceback.format_exc())))
        threading.Thread(target=body, daemon=True).start()

    def _pump(self):
        try:
            while True:
                name, ok, value = self.q.get_nowait()
                getattr(self, 'on_' + name)(ok, value)
        except queue.Empty:
            pass
        if self.job is not None:
            self._poll_job()
        if not self.closing or self.job is not None:
            self.root.after(120, self._pump)

    def paths(self):
        return core.Paths(self.tools.mod if self.tools else None, self.v_mo2.get().strip() or None,
                          self.v_profile.get().strip() or None, self.v_game.get().strip() or None,
                          out=self._out, cache=self._cache)

    def choices(self):
        c = core.Choices(**{k: bool(self.v[k].get()) for k in core.Choices.FIELDS})
        try:
            c.jobs = max(1, int(self.v_jobs.get()))
        except (tk.TclError, ValueError):
            c.jobs = core.default_jobs()
        if not (self.tools and self.tools.fracture):
            c.props = c.experimental_props = False
        if not (self.tools and self.tools.kidfx):
            c.kid_particles = False
        return c

    def set_buttons(self):
        idle = self.busy is None
        ready = idle and self.tools is not None and not core.problems(self.tools, self.paths())
        self.b_bake.state(['!disabled'] if ready else ['disabled'])
        self.b_check.state(['!disabled'] if ready else ['disabled'])
        out = self.paths().out if self.tools is not None else None
        has_bake = out is not None and (
            os.path.exists(os.path.join(out, self.tools.bake.REPORT)) or (
                self.tools.fracture is not None and os.path.exists(os.path.join(out, self.tools.fracture.REPORT))))
        self.b_remove.state(['!disabled'] if idle and has_bake else ['disabled'])
        props_ok = ready and self.tools.fracture is not None
        self.b_props_only.state(['!disabled'] if props_ok else ['disabled'])
        self.b_cancel.state(['!disabled'] if self.job is not None else ['disabled'])
        # apply / undo need only the ZGO folder, not MO2 or the game
        kid_ok = idle and self.tools is not None and core.kidfx_for(self.tools, self.paths()) is not None
        for b in (self.b_kid_apply, self.b_kid_undo):
            b.state(['!disabled'] if kid_ok else ['disabled'])

    # ------------------------------------------------------------ the ZGO folder and paths
    def set_mod(self, mod_root, paths=None):
        self.tools = None
        self.show_kidfx('none')
        if not mod_root:
            mod_root = core.find_mod_root()
        if mod_root:
            try:
                self.tools = core.Tools(mod_root)
            except core.SetupError as e:
                self.say(str(e), 'error')
            except Exception as e:  # noqa: BLE001
                self.say(core.friendly(e), 'error')
        if self.tools is None:
            self.v_mod.set(mod_root or '')
            self.set_problems('Choose the Umbra Gore & Effects folder (inside your MO2 "mods" folder) '
                              'with the "Change..." button next to it.')
            self.set_buttons()
            return
        for line in core.environment_lines(self.tools):
            self.say(line)
        self.v_mod.set(self.tools.mod)
        found = core.detect(self.tools)
        if paths is None:
            paths = found
        else:                        # what was given wins; the rest is found
            paths = core.Paths(self.tools.mod, paths.mo2 or found.mo2, paths.profile or found.profile,
                               paths.game or found.game)
        self.v_mo2.set(paths.mo2 or '')
        self.v_game.set(paths.game or '')
        self._fill_profiles(paths.profile)
        last = core.last_choices(self.tools, self.paths().out)
        for k in core.Choices.FIELDS:
            self.v[k].set(bool(getattr(last, k)))
        if any(getattr(last, k) for k in ('experimental_caps', 'experimental_damage', 'experimental_props')):
            self.v_show_exp.set(True)
            self.show_experimental()
        if not self.tools.fracture:
            for k in ('props', 'experimental_props'):
                self.v[k].set(False)
                self.checks[k].state(['disabled'])
            if self.tools.fracture_problem:
                self.say('The props tool could not be loaded: %s' % self.tools.fracture_problem, 'warn')
        else:
            for k in ('props', 'experimental_props'):
                self.checks[k].state(['!disabled'])
        if not self.tools.kidfx:
            self.v['kid_particles'].set(False)
            self.checks['kid_particles'].state(['disabled'])
            if self.tools.kidfx_problem:
                self.say('Kid mode for particles could not be loaded: %s' % self.tools.kidfx_problem, 'warn')
        else:
            self.checks['kid_particles'].state(['!disabled'])
        self.refresh_kidfx()
        self.paths_changed(check=True)

    def _fill_profiles(self, want=None):
        names = core.profiles(self.v_mo2.get().strip())
        self.cb_profile.configure(values=names)
        cur = want or self.v_profile.get()
        if cur not in names:
            cur = 'G.A.M.M.A' if 'G.A.M.M.A' in names else (names[0] if len(names) == 1 else '')
        self.v_profile.set(cur)

    def pick_mo2(self):
        d = filedialog.askdirectory(title='Choose the Mod Organizer 2 folder (it holds "mods" and "profiles")',
                                    initialdir=self.v_mo2.get() or None, mustexist=True)
        if d:
            self.v_mo2.set(os.path.normpath(d))
            self._fill_profiles()
            self.paths_changed()

    def pick_game(self):
        d = filedialog.askdirectory(title='Choose the game folder (it holds "db" and "bin")',
                                    initialdir=self.v_game.get() or None, mustexist=True)
        if d:
            self.v_game.set(os.path.normpath(d))
            self.paths_changed()

    def pick_mod(self):
        d = filedialog.askdirectory(title='Choose the Umbra Gore & Effects folder (inside MO2\'s "mods" folder)',
                                    initialdir=self.v_mod.get() or None, mustexist=True)
        if d:
            if self.tools and os.path.normcase(os.path.abspath(d)) != os.path.normcase(self.tools.mod):
                messagebox.showinfo('Umbra Effects Setup', 'Close Umbra Effects Setup and start it again from that folder '
                                                 '(tools/zgo_setup) to switch to another copy of Umbra Effects.')
                return
            self.set_mod(os.path.normpath(d))

    def paths_changed(self, check=False):
        if self.tools is None:
            return
        bad = core.problems(self.tools, self.paths())
        warn = core.warnings(self.tools, self.paths()) if not bad else []
        self.set_problems('\n'.join(bad + warn), 'Bad.TLabel' if bad else 'Warn.TLabel')
        for w in warn:
            if w not in self._warned:
                self._warned.add(w)
                self.say(w, 'warn')
        self.set_buttons()
        self.schedule_plan()
        if check and not bad:
            self.check()
        elif not bad and self.status is None:
            self.show_status(core.Status('none', 'Press "Check if my bake is up to date" to compare the bake '
                                                 'with your mod list.'))

    def on_tick(self, key):
        if key == 'experimental_damage' and self.v[key].get():
            if not messagebox.askyesno('Umbra Effects Setup', 'Damage meshes make the bake about ten times larger (25-30 GB) '
                                                    'and take about an hour. Nothing in the game uses them yet; they '
                                                    'are only for testing. Tick it anyway?', icon='warning'):
                self.v[key].set(False)
        if key == 'pieces' and not self.v[key].get():
            self.say('Limb pieces off: severed limbs will be drawn from a copy of the whole body, as before 1.7.')
        if key == 'gibs' and not self.v[key].get():
            self.say('Body gibs off: explosions and head bursts throw meat models, as before 1.7.1.')
        if key == 'kid_particles' and not self.v[key].get():
            self.say('Kid mode for particles unticked: a bake leaves the particle shaders and copies as they are. '
                     '"Undo..." next to it switches kid mode for particles off.')
        self.choices_changed()

    def choices_changed(self):
        self.schedule_plan()

    # ------------------------------------------------------------ plan (what will be baked)
    def schedule_plan(self):
        if self._plan_after is not None:
            self.root.after_cancel(self._plan_after)
        self._plan_after = self.root.after(350, self.start_plan)

    def start_plan(self):
        self._plan_after = None
        if self.tools is None or core.problems(self.tools, self.paths()):
            self.l_estimate.configure(text='')
            return
        if self.busy in ('plan',):
            self.schedule_plan()
            return
        self.l_estimate.configure(text='Counting the models in your mod list...')
        self.run_thread('plan', core.plan, self.tools, self.paths(), self.choices())

    def on_plan(self, ok, value):
        if not ok:
            e, tb = value
            self.say('Could not count the models: %s' % core.friendly(e), 'error')
            self.say(tb, 'error')
            self.l_estimate.configure(text='')
            return
        p = value
        self.plan = p
        parts = ['%s %s' % (name.replace('_', ' '), core.human_bytes(n)) for name, n in sorted(p.estimate.items(), key=lambda kv: -kv[1]) if n >= 1e6]
        free = [f for f in p.free.values() if f is not None]
        text = ('%d models from %d source%s. About %s on disk%s; about %s on %d cores.%s'
                % (p.models, len(p.by_source), '' if len(p.by_source) == 1 else 's', core.human_bytes(p.total),
                   (' (%s)' % ', '.join(parts)) if parts else '',
                   core.human_seconds(p.seconds), self.choices().jobs,
                   (' Free: %s.' % core.human_bytes(min(free))) if free else ''))
        for n in p.notes:
            text += '\n' + n
        for s in core.space_problems(p):
            text += '\n' + s
        self.l_estimate.configure(text=text, style='BoldBad.TLabel' if core.space_problems(p) else 'Bold.TLabel')
        self.refit()
        self.tree.delete(*self.tree.get_children())
        over = dict(p.overrides)
        for name, n in p.by_source:
            self.tree.insert('', 'end', text=name or "The game's own archives", values=(n,))
        for name, n in p.overrides:
            self.tree.insert('', 0, text='%s replaces %d baked models (load order)' % (name, n), values=(n,), tags=('over',))
        if over:
            self.say('Load order: %s load after Umbra Effects and replace some of its baked models. In MO2, drag Umbra Gore & Effects below '
                     'them in the left pane.' % ', '.join('"%s"' % m for m in over), 'warn')

    # ------------------------------------------------------------ check
    def check(self):
        if self.tools is None or self.busy:
            return
        self.busy = 'check'
        self.set_buttons()
        self.l_progress.configure(text='Checking the bake against your mod list...')
        self.progress.configure(mode='indeterminate')
        self.progress.start(15)
        paths = self.paths()

        def work():
            st = core.check(self.tools, paths)
            props = core.check_props(self.tools, paths)
            kid = core.check_kidfx(self.tools, paths)
            return st, props, kid
        self.run_thread('check', work)

    def on_check(self, ok, value):
        self.busy = None
        self.progress.stop()
        self.progress.configure(mode='determinate', value=0)
        self.l_progress.configure(text='Ready.')
        if not ok:
            e, tb = value
            self.say('The check did not finish: %s' % core.friendly(e), 'error')
            self.say(tb, 'error')
            self.set_buttons()
            return
        st, (pstate, ptext), (kstate, ktext) = value
        if ptext:
            st.info.append(ptext)
            if pstate == 'stale' and st.state == 'ok':
                st.state, st.headline = 'stale', 'The body models are up to date; the props need a new cut.'
                st.advice = 'Press "Cut props only" (or "Bake").'
        if ktext:
            st.info.append(ktext)
            if kstate == 'stale' and st.state == 'ok':
                st.state, st.headline = 'stale', 'The body models are up to date; kid mode for particles is only partly on.'
                st.advice = 'Press "Apply now" next to "Kid mode for particles" (or "Bake").'
        self.show_kidfx(kstate)
        self.show_status(st)
        self.say('Check: ' + st.text().replace('\n', ' / '))
        for d in st.details[:60]:
            self.say('  ' + d)
        self.set_buttons()

    def refresh_kidfx(self):
        """The kid-mode particle line beside Apply now / Undo (it needs only
        the Umbra Effects folder, so it shows before MO2 and the game are set)."""
        if self.tools is None or core.kidfx_for(self.tools, self.paths()) is None:
            self.show_kidfx('none')
            return
        self.run_thread('kidfx_state', core.check_kidfx, self.tools, self.paths())

    def on_kidfx_state(self, ok, value):
        if not ok:
            e, tb = value
            self.say('Could not read kid mode for particles: %s' % core.friendly(e), 'warn')
            self.log(tb, 'warn')
            return
        self.show_kidfx(value[0])

    def show_kidfx(self, state):
        self.kid_state = state
        try:
            self.l_kidfx.configure(text=KID_STATE.get(state, ''),
                                   style='SmallWarn.TLabel' if state == 'stale' else 'Small.TLabel')
        except (tk.TclError, AttributeError):
            pass

    def show_status(self, st):
        self.refit()
        self.status = st
        self.l_head.configure(text=st.headline, style=STATE_STYLE.get(st.state, 'Bold.TLabel'))
        lines = ['- ' + r for r in st.reasons[:8]]
        if len(st.reasons) > 8:
            lines.append('- ... and %d more (see the log)' % (len(st.reasons) - 8))
        if st.advice:
            lines.append(st.advice)
        lines += st.info
        self.l_reasons.configure(text='\n'.join(lines))

    # ------------------------------------------------------------ jobs
    def bake(self):
        if self.busy or self.tools is None:
            return
        paths, choices = self.paths(), self.choices()
        bad = core.problems(self.tools, paths)
        if bad:
            messagebox.showerror('Umbra Effects Setup', bad[0])
            return
        if self.plan:
            space = core.space_problems(self.plan)
            if space and not messagebox.askyesno('Umbra Effects Setup', space[0] + '\n\nBake anyway?', icon='warning'):
                return
        exp = [LABEL[k] for k in ('experimental_caps', 'experimental_damage', 'experimental_props') if getattr(choices, k)]
        if exp and not messagebox.askyesno('Umbra Effects Setup', 'You ticked experimental parts:\n\n  %s\n\nThey change models '
                                                        'every NPC or object uses and are not checked in the game yet. '
                                                        'Bake with them?' % '\n  '.join(exp), icon='warning'):
            return
        self.start_job('bake', paths, choices)

    def bake_props(self):
        if self.busy or self.tools is None or not self.tools.fracture:
            return
        self.start_job('props', self.paths(), self.choices())

    def remove(self):
        if self.busy or self.tools is None:
            return
        if not messagebox.askyesno('Umbra Effects Setup', 'Remove every file the bake wrote into the Umbra Effects folder (body models, '
                                                'caps, pieces, the index, the props pieces and the copies of other '
                                                "mods' gory particle effects)?\n\nThe game then uses the original "
                                                'models again, and Umbra Effects falls back to cutting without baked models. '
                                                'You can bake again at any time.', icon='question'):
            return
        self.start_job('remove', self.paths(), self.choices())

    def kidfx_apply(self):
        """Kid mode for particles on again, at once (no bake)."""
        if self.busy or self.tools is None or core.kidfx_for(self.tools, self.paths()) is None:
            return
        self.start_job('kidfx_apply', self.paths(), self.choices())

    def kidfx_revert(self):
        """The escape hatch: every particle effect back to the game's own shaders."""
        if self.busy or self.tools is None or core.kidfx_for(self.tools, self.paths()) is None:
            return
        if not messagebox.askyesno('Umbra Effects Setup', "Set every particle effect back to the game's own particle "
                                                'shaders?\n\nUse this if particles look wrong, or the game has '
                                                'trouble starting, since you installed Umbra Effects. Kid mode then cannot hide '
                                                'blood and gore particles that are already flying, or the blood other '
                                                'mods play (knife hits, anomalies). It still stops new blood from Umbra Effects.'
                                                '\n\n"Apply now" (or a bake with "Kid mode for particles" ticked) '
                                                'turns it back on. The game picks the change up the next time it '
                                                'starts.', icon='question'):
            return
        self.start_job('kidfx_revert', self.paths(), self.choices())

    def start_job(self, action, paths, choices):
        self.busy = action
        self.with_props = action == 'bake' and choices.props and self.tools.fracture is not None
        self.with_particles = action == 'bake' and choices.kid_particles and \
            core.kidfx_for(self.tools, paths) is not None
        self.say({'bake': 'Baking for profile "%s"...' % paths.profile, 'remove': 'Removing the bake...',
                  'props': 'Cutting props...',
                  'kidfx_apply': "Kid mode for particles: pointing gory effects at Umbra Effects' particle shaders...",
                  'kidfx_revert': "Kid mode for particles: setting every effect back to the game's own shaders..."}[action])
        try:
            self.job = core.Job(self.tools, action, paths, choices).start()
        except Exception as e:  # noqa: BLE001
            self.busy = None
            self.job = None
            self.say('Could not start: %s' % core.friendly(e), 'error')
            messagebox.showerror('Umbra Effects Setup', core.friendly(e))
            self.set_buttons()
            return
        self._t_job = time.time()
        self.progress.configure(mode='determinate', value=0)
        self.l_progress.configure(text='Starting...')
        self.set_buttons()

    def _poll_job(self):
        job = self.job
        for ev in job.poll():
            t = ev.get('t')
            if t == 'progress':
                f = core.overall_fraction(ev.get('task'), ev.get('stage'), ev.get('done', 0), ev.get('total', 0),
                                          self.with_props, self.with_particles)
                self.progress.configure(value=int(f * 1000))
                elapsed = time.time() - self._t_job
                stage = core.STAGE_TEXT.get(ev.get('stage'), ev.get('stage', ''))
                if ev.get('task') == 'props':
                    stage = 'Props: ' + stage
                left = ''
                if f > 0.08 and ev.get('stage') == 'bake':
                    left = ', about %s left' % core.human_seconds(elapsed * (1 - f) / f)
                count = (' %d / %d' % (ev['done'], ev['total'])) if ev.get('total', 0) > 1 else ''
                self.l_progress.configure(text='%s%s (%s)%s' % (stage, count, ev.get('msg', ''), left))
                if ev.get('stage') == 'install' and ev.get('done', 0) == 0:
                    self.say('Installing: this step cannot be cancelled.')
            elif t == 'log':
                self.say(ev.get('msg', ''), ev.get('level', 'info'))
                if ev.get('trace'):
                    self.log(ev['trace'], 'warn')
            elif t == 'done':
                self.job_done(ev)
        if job.result is not None and self.job is job and self.busy is not None:
            self.job_done(job.result)

    def job_done(self, ev):
        job, action = self.job, self.busy
        self.job = None
        self.busy = None
        if job is not None:
            job.close()
        if ev.get('ok'):
            self.progress.configure(value=1000)
            self.l_progress.configure(text=ev.get('msg', 'Done.'))
            self.say(ev.get('msg', 'Done.'))
            s = ev.get('summary') or {}
            if action == 'bake':
                text = 'Baked %d models (%s) in %s.' % (s.get('baked', 0), core.human_bytes(s.get('bytes', 0)),
                                                          core.human_seconds(s.get('seconds', 0)))
                if s.get('errors'):
                    text += ' %d models could not be baked; the game uses them unchanged (see the log).' % s['errors']
                if s.get('props_error'):
                    text += '\n\nThe props were not cut: %s' % s['props_error']
                if s.get('kidfx_error'):
                    text += '\n\nKid mode for particles was not updated for your mod list: %s' % s['kidfx_error']
                text += '\n\nStart the game through MO2 as usual.'
                if not self.closing:
                    messagebox.showinfo('Umbra Effects Setup', text)
            elif action in ('kidfx_apply', 'kidfx_revert'):
                # what a later bake does follows what was just chosen (as last_choices does)
                self.v['kid_particles'].set(action == 'kidfx_apply')
            if ev.get('kidfx_error'):
                self.say("The copies of other mods' particle effects were not removed: %s" % ev['kidfx_error'], 'warn')
        elif ev.get('cancelled'):
            self.progress.configure(value=0)
            self.l_progress.configure(text=ev.get('msg', 'Cancelled.'))
            self.say(ev.get('msg', 'Cancelled.'), 'warn')
        else:
            self.progress.configure(value=0)
            self.l_progress.configure(text='Stopped: see the message.')
            self.say(ev.get('msg', 'Failed.'), 'error')
            if ev.get('trace'):
                self.log(ev['trace'], 'error')
            if job is not None and ev.get('kind') == 'crash':
                wl = job.worker_log()
                if wl.strip():
                    self.log('worker output:\n' + wl, 'error')
            if not self.closing:
                messagebox.showerror('Umbra Effects Setup', ev.get('msg', 'The bake stopped.'))
        self.set_buttons()
        if self.closing:
            self.root.destroy()
            return
        self.status = None
        self.refresh_kidfx()
        if self.tools is not None and not core.problems(self.tools, self.paths()):
            self.check()            # (apply / undo and remove also run while MO2 or the game is not set)
        self.schedule_plan()

    def cancel(self):
        if self.job is None:
            return
        self.say('Cancelling...')
        self.l_progress.configure(text='Cancelling (the bake stops after the models it is working on)...')
        self.job.cancel()

    # ------------------------------------------------------------ log buttons, closing
    def save_log(self):
        p = filedialog.asksaveasfilename(title='Save the Umbra Effects Setup log', defaultextension='.txt',
                                         initialfile='zgo_setup_log.txt', filetypes=[('Text', '*.txt')])
        if p:
            try:
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(self.log.text())
                self.say('Log saved to %s' % p)
            except OSError as e:
                messagebox.showerror('Umbra Effects Setup', core.friendly(e))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.text())
        self.say('Log copied to the clipboard.')

    def on_close(self):
        if self.job is not None:
            if not messagebox.askyesno('Umbra Effects Setup', 'A %s is running. Stop it and close? (If it is already '
                                                    'installing, it finishes that first.)'
                                       % BUSY_TEXT.get(self.busy, self.busy)):
                return
            self.closing = True
            self.cancel()
            return
        self.closing = True
        self.root.destroy()


def main(mod_root=None, paths=None, log=None, smoke=None):
    """Open the window. smoke=seconds: close it by itself after that long
    (for the self-test), returning the App."""
    root = tk.Tk()
    app = App(root, mod_root, paths, log)
    if smoke:
        def finish():
            app.closing = True
            try:
                root.destroy()
            except tk.TclError:
                pass
        root.after(int(smoke * 1000), finish)
    root.mainloop()
    return app
