#!/usr/bin/env python3
"""
Umbra Effects Setup: bakes Umbra Gore & Effects' body models (and breakable props, and
kid mode for particles) for your own MO2 mod list, checks whether that bake is
still up to date, and removes it. It finds MO2 and the profile by itself: it lives in
<MO2>/mods/<Umbra Gore & Effects>/tools/zgo_setup.

  Umbra Effects Setup.exe / zgo-setup-linux    the ready-made program (no Python needed)
  python3 zgo_setup.py               the same with your own Python (3.8+, numpy, tkinter)

Without a window (any of these):
  --check      is the bake up to date? (exit 0 = yes; the last line is "RESULT body=.. props=.. kid=..")
  --match DIR  would the prebaked bake whose report is in DIR fit this mod list? (exit 0 = yes)
  --plan       what a bake would make, and its size
  --bake       bake in this terminal          --props   cut the props only
  --remove     remove the bake                --selftest  check that this program works
  --kid-particles-apply    kid mode for particles on (gory effects use Umbra Effects' particle shaders)
  --kid-particles-revert   undo: every particle effect back to the game's own shaders
  --version    print the version
Options: --mo2 DIR --profile NAME --game DIR --mod DIR --jobs N
         --no-caps --no-pieces --no-wounds --no-props --no-kid-particles
         --experimental-caps --experimental-damage --experimental-props
         --yes (do not ask) --log FILE (also write the output there)
"""
import argparse
import os
import sys
import time

FROZEN = getattr(sys, 'frozen', False)


def program_dir():
    return os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))


def no_xcursor():
    """The Linux program only: load the empty libXcursor.so.1 it carries
    before Tk starts. Its tkinter has its own libX11, which would otherwise
    dlopen the system's libXcursor for the first text box's cursor, bring the
    system's libX11 along, and abort ("[xcb] Unknown sequence number").
    Cursors are then the classic X ones. See dev/build_setup/nocursor.c."""
    if not (FROZEN and sys.platform.startswith('linux')):
        return
    stub = os.path.join(getattr(sys, '_MEIPASS', ''), 'libXcursor.so.1')
    if os.path.isfile(stub):
        try:
            import ctypes
            ctypes.CDLL(stub)
        except OSError:
            pass


def _find_mod_root(start):
    d = os.path.abspath(start)
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'gamedata', 'scripts', 'zgo_main.script')) and \
                os.path.isfile(os.path.join(d, 'tools', 'zgo_baker', 'bake.py')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def use_mod(mod_root):
    """Run this program's logic and the baker from the Umbra Effects folder itself
    (tools/zgo_setup and tools/zgo_baker), so the ready-made program always
    runs the code that came with the installed Umbra Effects."""
    for sub in ('zgo_baker', 'zgo_setup'):
        d = os.path.join(mod_root, 'tools', sub)
        if os.path.isdir(d):
            if d in sys.path:
                sys.path.remove(d)
            sys.path.insert(0, d)


def child_paths():
    """The ready-made program starts itself again for its worker processes
    (multiprocessing). They must import the same baker as the main process:
    the installed Umbra Effects' (ZGO_SETUP_MOD, set by main()), not the copy bundled
    in the program."""
    mod = os.environ.get('ZGO_SETUP_MOD') or _find_mod_root(program_dir())
    if mod:
        use_mod(mod)


def parse(argv):
    ap = argparse.ArgumentParser(prog='zgo_setup', description='Bake Umbra Gore & Effects for your MO2 mod list.')
    ap.add_argument('--mod', help='the Umbra Gore & Effects folder (default: the one this program is in)')
    ap.add_argument('--mo2', help='the Mod Organizer 2 folder (default: the one Umbra Effects is installed in)')
    ap.add_argument('--profile', help="the MO2 profile (default: MO2's selected profile)")
    ap.add_argument('--game', help="the game's folder, holding db/ (default: MO2's game path)")
    ap.add_argument('--out', help=argparse.SUPPRESS)
    ap.add_argument('--cache', help="the baker's work folder (needs as much free space as the bake)")
    ap.add_argument('--jobs', type=int, default=None, help='CPU cores to use')
    for name in ('caps', 'pieces', 'wounds', 'gibs', 'props'):
        ap.add_argument('--no-' + name, action='store_true')
    ap.add_argument('--no-kid-particles', action='store_true',
                    help="--bake: leave kid mode for particles (Umbra Effects' particle shaders and copies) as it is")
    for name in ('caps', 'damage', 'props'):
        ap.add_argument('--experimental-' + name, action='store_true')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--check', action='store_true', help='is the bake up to date? exit 0 = yes')
    g.add_argument('--match', metavar='DIR',
                   help='would the prebaked bake whose report (zgo_bake_report.json) is in DIR fit this mod list, '
                        'before its files are here? exit 0 = yes (Umbra Setup asks this before downloading one)')
    g.add_argument('--plan', action='store_true', help='what a bake would make')
    g.add_argument('--bake', action='store_true', help='bake without the window')
    g.add_argument('--props', action='store_true', help='cut the props only')
    g.add_argument('--remove', action='store_true', help='remove the bake')
    g.add_argument('--kid-particles-apply', action='store_true',
                   help="kid mode for particles on: gory effects use Umbra Effects' particle shaders (no bake)")
    g.add_argument('--kid-particles-revert', action='store_true',
                   help="undo kid mode for particles: every effect back to the game's own particle shaders")
    g.add_argument('--selftest', action='store_true', help='check that this program works')
    g.add_argument('--version', action='store_true', help='print the version and exit')
    g.add_argument('--worker', metavar='JOB', help=argparse.SUPPRESS)
    ap.add_argument('--deep', action='store_true', help='--check: also compare the contents of every file')
    ap.add_argument('--yes', action='store_true', help='do not ask before baking or removing')
    ap.add_argument('--log', help='also write the output to this file')
    ap.add_argument('--smoke', type=float, default=None, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


class Out:
    """Terminal output (when there is a terminal) plus an optional file."""

    def __init__(self, path=None):
        self.f = None
        if path:
            try:
                self.f = open(path, 'a', encoding='utf-8')
            except OSError:
                self.f = None

    def __call__(self, *parts):
        line = ' '.join(str(p) for p in parts)
        if sys.stdout is not None:
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass
        if self.f:
            self.f.write(line + '\n')
            self.f.flush()


def _paths(core, tools, a):
    p = core.detect(tools)
    if a.mo2:
        p.mo2 = os.path.abspath(a.mo2)
        if not a.profile and p.profile not in core.profiles(p.mo2):
            names = core.profiles(p.mo2)
            p.profile = names[0] if len(names) == 1 else None
    if a.profile:
        p.profile = a.profile
    if a.game:
        p.game = os.path.abspath(a.game)
    if a.out:
        p.out = os.path.abspath(a.out)
    if a.cache:
        p.cache = os.path.abspath(a.cache)
    return p


def _choices(core, tools, a, paths):
    c = core.last_choices(tools, paths.out)
    for name in ('caps', 'pieces', 'wounds', 'gibs', 'props'):
        if getattr(a, 'no_' + name):
            setattr(c, name, False)
    if a.experimental_caps:
        c.experimental_caps = True
    if a.experimental_damage:
        c.experimental_damage = True
    if a.experimental_props:
        c.experimental_props = True
    if a.no_kid_particles:
        c.kid_particles = False
    if a.jobs:
        c.jobs = max(1, a.jobs)
    if not tools.fracture:
        c.props = c.experimental_props = False
    if not tools.kidfx:
        c.kid_particles = False
    return c


def cli(a, mod_root, say):
    import setup_core as core
    try:
        tools = core.Tools(mod_root)
    except core.SetupError as e:
        say('Umbra Effects Setup:', e)
        return 2
    for line in core.environment_lines(tools):
        say(line)
    paths = _paths(core, tools, a)
    say('MO2: %s | profile: %s | game: %s | output: %s' % (paths.mo2, paths.profile, paths.game, paths.out))
    kid_action = a.kid_particles_apply or a.kid_particles_revert
    # removing and kid mode on / off need only the ZGO folder
    bad = core.problems(tools, paths) if not (a.remove or kid_action) else []
    if bad:
        for b in bad:
            say('Problem:', b)
        return 2
    for w in core.warnings(tools, paths):
        say('Warning:', w)
    choices = _choices(core, tools, a, paths)
    if a.plan or a.bake:
        p = core.plan(tools, paths, choices)
        say('Plan: %s' % p.short())
        for name, n in p.by_source:
            say('  %5d  %s' % (n, name or "the game's own archives"))
        for part, n in sorted(p.estimate.items(), key=lambda kv: -kv[1]):
            say('  %-22s about %s' % (part, core.human_bytes(n)))
        for m, n in p.overrides:
            say('  Load order: "%s" loads after Umbra Effects and replaces %d baked models; drag Umbra Gore & Effects below it in MO2.' % (m, n))
        for s in core.space_problems(p) + p.notes:
            say('  ' + s)
        if a.plan:
            return 0
    if a.check:
        def progress(done, total, msg):
            pass
        st = core.check(tools, paths, progress, deep=a.deep)
        say(st.text())
        for d in st.details[:200]:
            say('  ' + d)
        pstate, ptext = core.check_props(tools, paths)
        if ptext:
            say(ptext)
        kstate, ktext = core.check_kidfx(tools, paths)
        if ktext:
            say(ktext)
        # for programs that run this one (Umbra Setup): one line, always last
        say('RESULT body=%s props=%s kid=%s' % (st.state, pstate, kstate))
        return 0 if st.state == 'ok' and pstate in ('ok', 'none') and kstate in ('ok', 'off', 'none') else 1
    if a.match:
        rep = tools.bake.read_report(os.path.abspath(a.match))
        if rep is None:
            say('Umbra Effects Setup: no bake report (%s) in %s' % (tools.bake.REPORT, a.match))
            return 2
        st = core.check(tools, paths, deep=a.deep, report=rep, prebaked=True)
        say(st.text())
        for d in st.details[:200]:
            say('  ' + d)
        fits = st.state in ('ok', 'order')
        say('RESULT match=%s fingerprint=%s' % ('yes' if fits else 'no',
                                                (rep.get('inputs') or {}).get('fingerprint') or '-'))
        return 0 if fits else 1
    action = ('bake' if a.bake else 'props' if a.props else 'kidfx_apply' if a.kid_particles_apply else
              'kidfx_revert' if a.kid_particles_revert else 'remove')
    if kid_action and core.kidfx_for(tools, paths) is None:
        say('Umbra Effects Setup:', core.kidfx_unavailable(tools, paths))
        return 2
    if action == 'kidfx_revert':
        say("Undo kid mode for particles: every particle effect goes back to the game's own particle shaders. Kid "
            'mode then cannot hide blood and gore particles already flying; --kid-particles-apply turns it back on.')
    if not a.yes and sys.stdin is not None and sys.stdin.isatty():
        ans = input('%s now? [y/N] ' % {'bake': 'Bake', 'props': 'Cut the props', 'remove': 'Remove the bake',
                                        'kidfx_apply': 'Turn kid mode for particles on',
                                        'kidfx_revert': "Use the game's own particle shaders"}[action])
        if ans.strip().lower() not in ('y', 'yes'):
            say('Nothing done.')
            return 1
    last = {}

    def show(ev):
        t = ev.get('t')
        if t == 'log':
            say(('WARNING: ' if ev.get('level') == 'warn' else '') + ev.get('msg', ''))
        elif t == 'progress':
            key = (ev.get('task'), ev.get('stage'))
            frac = ev['done'] / float(ev['total']) if ev.get('total') else 0
            step = int(frac * 10)
            if last.get(key) != step or ev['done'] == ev.get('total'):
                last[key] = step
                say('  [%s] %s %d/%d %s' % (ev.get('task'), core.STAGE_TEXT.get(ev.get('stage'), ev.get('stage')),
                                            ev.get('done', 0), ev.get('total', 0), ev.get('msg', '')))
    job = core.Job(tools, action, paths, choices).start()
    try:
        res = job.wait(on_event=show)
    except KeyboardInterrupt:
        say('Cancelling...')
        job.cancel()
        res = job.wait(on_event=show)
    say(res.get('msg', ''))
    if res.get('trace') and not res.get('ok'):
        say(res['trace'])
    return 0 if res.get('ok') else (3 if res.get('cancelled') else 2)


# ---------------------------------------------------------------- self-test

def _probe_paths(_):
    import multiprocessing as mp
    return 'sys.path %s, ZGO_SETUP_MOD %s, %s, bake loaded %s' % (
        sys.path[:4], os.environ.get('ZGO_SETUP_MOD'), mp.current_process().name, 'bake' in sys.modules)


def _probe_child(name):
    """Runs in a pool worker: where does it import this module from?"""
    import importlib
    m = importlib.import_module(name)
    return os.path.normcase(os.path.dirname(os.path.abspath(getattr(m, '__file__', '') or '?')))


def selftest(a, mod_root, say):
    """Checks that this program works on this machine: imports, numpy, the
    baker, parallel workers, the worker process, the window. Prints PASS /
    FAIL / SKIP lines and ends with SELFTEST PASSED or SELFTEST FAILED."""
    import platform
    import traceback
    fails = []

    def step(name, fn):
        try:
            r = fn()
            say('PASS %s%s' % (name, (': %s' % r) if r else ''))
        except _Skip as e:
            say('SKIP %s: %s' % (name, e))
        except Exception as e:  # noqa: BLE001
            fails.append(name)
            say('FAIL %s: %s: %s' % (name, type(e).__name__, e))
            for line in traceback.format_exc().splitlines()[-6:]:
                say('     ' + line)

    say('Umbra Effects Setup self-test: %s %s, Python %s, %s' % (platform.system(), platform.release(), platform.python_version(),
                                                       'frozen' if FROZEN else sys.executable))
    step('Umbra Effects folder', lambda: mod_root or (_ for _ in ()).throw(RuntimeError('not found next to %s' % program_dir())))
    if not mod_root:
        say('SELFTEST FAILED')
        return 1

    def t_numpy():
        import numpy as np
        x = np.arange(12, dtype=np.float32).reshape(3, 4)
        assert float((x @ x.T).trace()) == 1.0 * sum(float(v) ** 2 for v in range(12))
        return 'numpy %s' % np.__version__
    step('numpy', t_numpy)

    def t_modules():
        import importlib
        names = []
        for sub in ('zgo_baker', 'zgo_fracture', 'zgo_kidfx', 'zgo_setup'):
            d = os.path.join(mod_root, 'tools', sub)
            if not os.path.isdir(d):
                continue
            if d not in sys.path:
                sys.path.append(d)
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.py') and fn not in ('zgo_setup.py', 'selftest.py', 'setup_gui.py', 'typeface.py'):
                    names.append(fn[:-3])
        for n in names:
            importlib.import_module(n)
        return '%d modules' % len(names)
    step('baker modules', t_modules)

    def t_core():
        import setup_core as core
        tools = core.Tools(mod_root)
        kinds = tools.limbs.load(mod_root)
        assert len(kinds) >= 5, kinds
        if tools.kidfx_problem:
            raise RuntimeError('kid mode for particles (tools/zgo_kidfx) could not be loaded: %s' % tools.kidfx_problem)
        return 'baker %d, Umbra Effects %s, %d creature kinds, props tool %s, kid mode for particles %s' % (
            tools.bake.BAKER_VERSION, tools.bake.zgo_version(mod_root), len(kinds), 'yes' if tools.fracture else 'no',
            'yes' if tools.kidfx else 'no')
    step('baker', t_core)

    def t_pool():
        import multiprocessing as mp
        import importlib
        names = ['bake', 'setup_core']
        with mp.Pool(2) as p:
            got = p.map(_probe_child, names)
        want = [_probe_child(n) for n in names]
        for n, g, w in zip(names, got, want):
            if g != w:
                with mp.Pool(1) as p:
                    where = p.map(_probe_paths, [0])[0]
                raise RuntimeError('the workers load %s from %s, this process from %s (worker: %s)' % (n, g, w, where))
        importlib.import_module('bake')
        return 'the workers use the baker in %s (%s)' % (os.path.relpath(want[0], mod_root), mp.get_start_method())
    step('parallel workers', t_pool)

    def t_worker():
        import setup_core as core
        import tempfile
        import json
        d = tempfile.mkdtemp(prefix='zgo_selftest_')
        tools = core.Tools(mod_root)
        out = os.path.join(d, 'out')
        os.makedirs(out)
        # a "remove" in an empty folder: the worker starts, loads the baker, reports
        job = core.Job(tools, 'remove', core.Paths(mod_root, out=out), core.Choices(), workdir=d)
        res = job.start().wait(timeout=180)
        if not res.get('ok'):
            raise RuntimeError('%s / %s' % (res.get('msg'), job.worker_log()[-500:]))
        evs = [e.get('t') for e in job.events]
        return 'worker process ran (%s) in %.1f s' % (','.join(evs), res.get('seconds', 0))
    step('worker process', t_worker)

    def t_window():
        try:
            import tkinter as tk
        except ImportError as e:
            if FROZEN:
                raise
            raise _Skip('tkinter is not installed (%s); the window needs it, the rest works' % e)
        try:
            root = tk.Tk()
        except tk.TclError as e:
            if os.name == 'nt':
                raise
            raise _Skip('no display (%s)' % e)
        root.destroy()
        import setup_gui
        import setup_core as core
        log = core.Log(path=os.devnull)
        t0 = time.time()
        app = setup_gui.main(mod_root, log=log, smoke=a.smoke or 4.0)
        errs = [l for lv, l in log.lines if lv == 'error']
        if errs:
            raise RuntimeError('the window logged errors: %s' % errs[:3])
        return 'window opened and closed (%.1f s, %d log lines, Tk %s)' % (time.time() - t0, len(log.lines), tk.TkVersion)
    step('window', t_window)
    say('SELFTEST %s' % ('FAILED: ' + ', '.join(fails) if fails else 'PASSED'))
    return 1 if fails else 0


class _Skip(Exception):
    pass


# ---------------------------------------------------------------- main

def _no_window_message(e):
    return ('Umbra Effects Setup could not open its window (%s).\n'
            'On Linux, install tkinter (Debian/Ubuntu: sudo apt install python3-tk; Fedora: sudo dnf install '
            'python3-tkinter; Arch: sudo pacman -S tk), or use the ready-made program zgo-setup-linux.\n'
            'Without a window: python3 zgo_setup.py --check / --bake / --remove' % e)


def main(argv=None):
    a = parse(sys.argv[1:] if argv is None else argv)
    say = Out(a.log)
    mod_root = os.path.abspath(a.mod) if a.mod else _find_mod_root(program_dir())
    if mod_root:
        use_mod(mod_root)
        os.environ['ZGO_SETUP_MOD'] = mod_root          # for the worker processes (child_paths)
    elif not FROZEN:
        sys.path.insert(0, program_dir())
    if a.worker:
        import setup_core as core
        return core.run_worker(a.worker)
    if a.version:
        import platform
        line = 'Umbra Effects Setup, Python %s%s' % (platform.python_version(), ' (ready-made program)' if FROZEN else '')
        if mod_root:
            try:
                import setup_core as core
                tools = core.Tools(mod_root)
                line += ', Umbra Gore & Effects %s, baker %d' % (tools.bake.zgo_version(mod_root), tools.bake.BAKER_VERSION)
            except Exception as e:  # noqa: BLE001
                line += ' (%s)' % e
        say(line)
        return 0
    if a.selftest:
        return selftest(a, mod_root, say)
    if a.check or a.match or a.plan or a.bake or a.props or a.remove or a.kid_particles_apply or \
            a.kid_particles_revert:
        if not mod_root:
            say('Umbra Effects Setup: run it from the Umbra Gore & Effects folder (tools/zgo_setup), or pass --mod DIR.')
            return 2
        return cli(a, mod_root, say)
    if FROZEN and not mod_root:
        # the program runs the tools of the ZGO folder it sits in; moved away, it has none
        msg = ('Umbra Effects Setup has to stay in the Umbra Gore & Effects folder (in %s), next to the files it '
               'came with. It is at %s now. Start it from there (in MO2: the "mods" folder, then Umbra Gore '
               '& Effects, tools, zgo_setup).' % (os.path.join('tools', 'zgo_setup'), program_dir()))
        say(msg)
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror('Umbra Effects Setup', msg)
            r.destroy()
        except Exception:  # noqa: BLE001
            pass
        return 2
    try:
        import setup_core as core
        import setup_gui
    except ImportError as e:
        say(_no_window_message(e))
        return 2
    log = core.Log(echo=None)
    paths = None
    if mod_root and (a.mo2 or a.profile or a.game or a.out or a.cache):
        paths = core.Paths(mod_root, a.mo2 and os.path.abspath(a.mo2), a.profile, a.game and os.path.abspath(a.game),
                           a.out and os.path.abspath(a.out), a.cache and os.path.abspath(a.cache))
    try:
        setup_gui.main(mod_root, paths=paths, log=log, smoke=a.smoke)
    except Exception as e:  # noqa: BLE001  (no display, broken Tk)
        say(_no_window_message(e))
        return 2
    return 0


if __name__ == '__main__':
    import multiprocessing
    if FROZEN:
        child_paths()
        no_xcursor()
    multiprocessing.freeze_support()       # the frozen program runs its pool workers through here
    sys.exit(main())
