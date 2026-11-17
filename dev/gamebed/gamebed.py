"""
A headless copy of the game for testing Umbra Gore & Effects in the real engine, without
touching anyone's install, MO2 instance or saves.

    python3 dev/gamebed/gamebed.py run [--save NAME] [--without zgo|bake|static] [SCENARIO ...]
    python3 dev/gamebed/gamebed.py coop [--client-without bake] [--client-baked-models-off]
    python3 dev/gamebed/gamebed.py scenarios         what the driver can do

It reads (never writes) an MO2 install: --mo2 (default ~/gamma/gamma), its profile --profile
(G.A.M.M.A), the Anomaly folder --game (~/gamma/anomaly), and the Umbra Gore & Effects folder in
its mods (--zgo, "Umbra Gore & Effects"), whose bake the bed uses. A bed lives in
~/.cache/zgo-gamebed (ZGO_GAMEBED; the co-op client's in ~/.cache/zgo-gamebed-client), outside
the repo:

  game/bin       reflinked copy of the game's bin, the enabled mods' bin files over it, and this
                 repo's bin/ (zgo_native.dll)
  game/db        links to the game's archives and every enabled mod's db/ files, MO2's order;
                 Umbra Gore & Effects': its folder's bake archives and db/mods/zgo_static.db0,
                 built from this repo (dev/package.py)
  game/gamedata  links: every winning loose file of the profile (MO2's order, overwrite on top,
                 the game folder's own gamedata/ under them all). Umbra Gore & Effects sits at its
                 place in modlist.txt, ticked or not, laid out as dev/deploy.py would deploy this
                 repo over that folder (the bake and kid mode copies made there stay; the
                 textures now in the archive are not loose); then configs/axr_options.ltx (a copy
                 with the debug log on) and the driver
  game/appdata   own user.ltx (copied once, then windowed, no sound, no hosting unless the co-op
                 host), a copy of the save
  compat/        own Proton prefix

It runs in gamescope's headless backend with GE-Proton. The driver (zz_zgo_gamebed.script) runs
the SCENARIOs and logs "[zgobed] CHECK <name> PASS|FAIL <detail>" lines. The engine's screenshot
command writes nothing under gamescope, so the driver asks for each shot through
appdata/zgobed_req.txt and this script takes it with gamescopectl.

coop runs two beds: a host that loads the save and hosts an xrRazom LAN session on 127.0.0.1,
and a client that starts at the main menu and joins it. This script relays between them through
files in their appdata: the host says when it listens (zgobed_connect.txt for the client), the
client when it is in the level (zgobed_go.txt for the host), the host what it cut and gibbed
(zgobed_relay.txt for the client), the client when it has checked (zgobed_end.txt for the host).

Shots, the engine logs and a summary land in ~/.cache/zgo-gamebed/out/<stamp>/. The exit code
is 0 only when every check passed and every driver finished.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'dev'))

import package  # noqa: E402

BED = os.environ.get('ZGO_GAMEBED', os.path.expanduser('~/.cache/zgo-gamebed'))
OUT = os.path.join(BED, 'out')
DRIVER = os.path.join(HERE, 'zz_zgo_gamebed.script')
MENU_HOOK = os.path.join(HERE, 'modxml_zz_zgobed.script')   # the driver at the main menu
PROTON = os.environ.get('ZGO_GAMEBED_PROTON', os.path.expanduser(
    '~/.local/share/Steam/compatibilitytools.d/GE-Proton11-7/proton'))
# the Visual C++ / D3D runtime DLLs the game needs in its prefix (Umbra Setup keeps a copy)
RUNTIME_DLLS = os.environ.get('ZGO_GAMEBED_RUNTIME', os.path.expanduser(
    '~/Games/Umbra/.umbra/cache/runtime/1/prefix'))
EXE = 'AnomalyDX11AVX.exe'
SCENARIOS = ['start', 'cut', 'gib', 'respawn', 'respawn_unfixed', 'load']
DEFAULT = ['start', 'cut', 'gib', 'respawn', 'respawn_unfixed']
COOP_SCENARIOS = ['start', 'cut', 'gib']
LAN_PORT = 27015
USER_LTX = [('keypress_on_start', 'off'), ('rs_screenmode', 'windowed'),
            ('snd_volume_eff', '0.'), ('snd_volume_music', '0.'), ('snd_volume_master', '0.'),
            ('xrr_host_session', 'off'), ('xrr_host_steam', 'off')]
FILES = ('zgobed_req.txt', 'zgobed_ack.txt', 'zgobed_go.txt', 'zgobed_connect.txt', 'zgobed_relay.txt',
         'zgobed_end.txt')


def log(msg):
    print('[gamebed] ' + msg, flush=True)


# ---------------------------------------------------------------- MO2 as the game would see it

def mod_order(mo2, profile, zgo):
    """The mods the game would load, highest priority first: the ticked ones, and zgo where
    modlist.txt has it, ticked or not."""
    out = []
    with open(os.path.join(mo2, 'profiles', profile, 'modlist.txt'), encoding='utf-8-sig') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line or line.startswith('#'):
                continue
            flag, name = line[0], line[1:]
            if name.endswith('_separator'):
                continue
            if flag == '+' or name == zgo:
                out.append(name)
    if zgo not in out:
        out.insert(0, zgo)
    return out


def walk(root, prefix=''):
    """{lower-case rel: path} of the files under root (rel prefixed with prefix)."""
    files = {}
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = prefix + os.path.relpath(p, root).replace(os.sep, '/')
            files.setdefault(rel.lower(), p)
    return files


def zgo_layer(folder, without=()):
    """Umbra Gore & Effects as dev/deploy.py would leave folder after deploying this repo:
    ({lower rel under the mod: path}, [archived (rel, size)]). Files made on that machine (the
    bake, kid mode's copies) stay; this repo's files win over the rest; the textures that go
    into db/mods/zgo_static.db0 are not loose."""
    loose, static, _ = package.release()
    if 'static' in without:
        loose, static = loose + static, []
    archived = {rel.lower() for rel, _ in static}
    try:
        import deploy
        prot = deploy.protected(folder)
        protected = lambda rel: deploy.is_protected(rel, prot)   # noqa: E731
    except Exception as e:                       # (an older deploy.py: the bake's files win anyway)
        log('deploy.py\'s list of files made on that machine is unavailable (%s)' % e)
        protected = lambda rel: False            # noqa: E731
    live = walk(folder)
    layer = {}
    for rel, _ in loose:
        if not protected(rel) or rel.lower() not in live:
            layer[rel.lower()] = os.path.join(REPO, rel)
    for rel, p in live.items():
        if rel in archived or rel == package.STATIC_ARCHIVE.lower():
            continue
        if 'bake' in without and (protected(rel) or rel.startswith('db/mods/zgo_bake_')
                                  or rel.startswith('gamedata/scripts/zgo_bake_')):
            continue
        layer.setdefault(rel, p)
    return layer, static


def relink(path):
    if os.path.lexists(path):
        os.remove(path)


def clear(d):
    """Remove a bed folder of links (never follows them: their targets are untouched)."""
    if os.path.islink(d):
        os.remove(d)
    elif os.path.isdir(d):
        shutil.rmtree(d)


def lua_str(s):
    return '"%s"' % str(s).replace('\\', '\\\\').replace('"', '\\"')


class Bed:
    """One throwaway copy of the game: its folder, its Proton prefix, its process."""

    def __init__(self, root, role, width=1920, height=1080):
        self.root, self.role, self.width, self.height = root, role, width, height
        self.game = os.path.join(root, 'game')
        self.compat = os.path.join(root, 'compat')
        self.app = os.path.join(self.game, 'appdata')
        self.logf = os.path.join(self.app, 'logs', 'xray_steamuser.log')
        self.proc, self.pos, self.last_req = None, 0, None
        self.checks, self.shots, self.lines = [], [], []
        self.done, self.end = False, None

    # ------------------------------------------------------------ layout
    def build(self, args, without=(), mcm=(), plan=None):
        """Lay out game/ for one run. Returns facts for the summary."""
        mo2, game, profile = args.mo2, args.game, args.profile
        folder = os.path.join(mo2, 'mods', args.zgo)
        order = mod_order(mo2, profile, args.zgo)
        if 'zgo' in without:
            order = [m for m in order if m != args.zgo]
        zgo, static = zgo_layer(folder, without)
        if 'zgo' in without:
            static = []
        os.makedirs(self.game, exist_ok=True)

        # the textures' archive, built from this repo (kept while it still matches)
        arch = os.path.join(BED, 'zgo_static.db0')
        if static and not (os.path.isfile(arch) and package.static_matches(arch, static)):
            package.build_static(arch, static)

        def files_of(m):
            return zgo if m == args.zgo else walk(os.path.join(mo2, 'mods', m))
        layers = [walk(os.path.join(mo2, 'overwrite'))] + [files_of(m) for m in order]
        # the game folder's own loose files: below every mod, above the archives
        base = walk(os.path.join(game, 'gamedata'), 'gamedata/')

        gd = os.path.join(self.game, 'gamedata')
        clear(gd)
        seen = {}
        for files in layers + [base]:
            for rel, p in files.items():
                if rel.startswith('gamedata/'):
                    seen.setdefault(rel[len('gamedata/'):], p)
        made = set()

        def link(dst, src):
            d = os.path.dirname(dst)
            if d not in made:
                os.makedirs(d, exist_ok=True)
                made.add(d)
            relink(dst)
            os.symlink(src, dst)
        for rel, p in seen.items():
            link(os.path.join(gd, rel), p)
        loose_archived = [rel for rel, _ in static if rel.lower()[len('gamedata/'):] in seen]

        # MCM: the profile's settings, with Umbra Gore & Effects' debug log on (and mcm's)
        opt = os.path.join(gd, 'configs', 'axr_options.ltx')
        text = ''
        if os.path.lexists(opt):
            with open(opt, 'rb') as f:
                text = f.read().decode('utf-8', 'replace')
            os.remove(opt)
        want = [('zgo/general/debug', 'true')] + list(mcm)
        keys = {k for k, _ in want}
        lines = [l for l in text.splitlines() if l.split('=')[0].strip() not in keys]
        if not any(l.strip() == '[mcm]' for l in lines):
            lines.append('[mcm]')
        i = [n for n, l in enumerate(lines) if l.strip() == '[mcm]'][0]
        for k, val in want:
            lines.insert(i + 1, '        %-32s = %s' % (k, val))
        os.makedirs(os.path.dirname(opt), exist_ok=True)
        with open(opt, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('\n'.join(lines) + '\n')

        # the driver and its plan
        link(os.path.join(gd, 'scripts', 'zz_zgo_gamebed.script'), DRIVER)
        link(os.path.join(gd, 'scripts', 'modxml_zz_zgobed.script'), MENU_HOOK)
        sample = [rel[len('gamedata/textures/'):].replace('/', '\\') for rel, _ in sorted(static)][::400][:8]
        plan = dict(plan or {})
        with open(os.path.join(gd, 'scripts', 'zz_zgo_gamebed_plan.script'), 'w') as f:
            f.write('-- written by dev/gamebed/gamebed.py for one run\n')
            for k, val in sorted(plan.items()):
                f.write('%s = %s\n' % (k, lua_str(val)))
            f.write('version = %s\n' % lua_str(package.version()))
            f.write('textures = { %s }\n' % ', '.join(lua_str(t) for t in sample))

        # db: the game's archives, then the mods' (lowest priority first, so higher ones replace)
        db = os.path.join(self.game, 'db')
        clear(db)
        os.makedirs(db)
        src_db = os.path.join(game, 'db')
        for e in sorted(os.listdir(src_db)):
            s = os.path.join(src_db, e)
            if os.path.isdir(s):
                for rel, p in walk(s, e + '/').items():
                    link(os.path.join(db, rel), p)
            else:
                os.symlink(s, os.path.join(db, e))
        for files in reversed(layers):
            for rel, p in files.items():
                if rel.startswith('db/') and rel != package.STATIC_ARCHIVE.lower():
                    link(os.path.join(db, rel[3:]), p)
        if static:
            link(os.path.join(self.game, package.STATIC_ARCHIVE), arch)

        # bin: the game's, then the mods' files over it (lowest priority first)
        src_bin, bin_ = os.path.join(game, 'bin'), os.path.join(self.game, 'bin')
        clear(bin_)
        subprocess.run(['cp', '-a', '--reflink=auto', src_bin, bin_], check=True)
        for files in reversed(layers):
            for rel, p in files.items():
                if rel.startswith('bin/'):
                    dst = os.path.join(bin_, rel[4:])
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    relink(dst)
                    shutil.copy2(p, dst)
        shutil.copy2(os.path.join(game, 'fsgame.ltx'), os.path.join(self.game, 'fsgame.ltx'))
        return {'mods': len(order), 'gamedata': len(seen), 'static': len(static), 'loose_archived': loose_archived,
                'zgo_files': sum(1 for r in zgo if r.startswith('gamedata/'))}

    def appdata(self, args, save, ltx=()):
        """Own user.ltx (copied once from the game's, then the run's settings), and the save."""
        os.makedirs(os.path.join(self.app, 'savedgames'), exist_ok=True)
        src_app = os.path.join(args.game, 'appdata')
        ltxf = os.path.join(self.app, 'user.ltx')
        if not os.path.isfile(ltxf):
            shutil.copy2(os.path.join(src_app, 'user.ltx'), ltxf)
            if os.path.isdir(os.path.join(src_app, 'shaders_cache')):
                shutil.copytree(os.path.join(src_app, 'shaders_cache'), os.path.join(self.app, 'shaders_cache'))
        lines = open(ltxf, encoding='latin1').read().splitlines()
        for k, val in USER_LTX + [('vid_mode', '%dx%d' % (self.width, self.height))] + list(ltx):
            hit = [i for i, l in enumerate(lines) if l.split(' ', 1)[0] == k]
            if hit:
                lines[hit[0]] = '%s %s' % (k, val)
            else:
                lines.append('%s %s' % (k, val))
        open(ltxf, 'w', encoding='latin1', newline='\r\n').write('\n'.join(lines) + '\n')
        for f in os.listdir(os.path.join(self.app, 'savedgames')):
            os.remove(os.path.join(self.app, 'savedgames', f))
        if save:
            for ext in ('.scop', '.scoc', '.xrr_peers', '.dds'):
                p = os.path.join(src_app, 'savedgames', save + ext)
                if os.path.isfile(p):
                    shutil.copy2(p, os.path.join(self.app, 'savedgames', 'zgobed' + ext))
            if not os.path.isfile(os.path.join(self.app, 'savedgames', 'zgobed.scop')):
                sys.exit('no save %r in %s' % (save, os.path.join(src_app, 'savedgames')))
        for f in FILES:
            if os.path.isfile(os.path.join(self.app, f)):
                os.remove(os.path.join(self.app, f))
        # the driver's role: here, not in gamedata, so the host's and the client's gamedata
        # match (xrRazom compares the peers' mod sets)
        self.write('zgobed_role.txt', self.role)
        logs = os.path.join(self.app, 'logs')
        for f in os.listdir(logs) if os.path.isdir(logs) else []:
            if f.startswith('xray_') and f.endswith('.log'):
                os.remove(os.path.join(logs, f))

    # ------------------------------------------------------------ Proton, gamescope
    def env(self):
        e = dict(os.environ)
        e.update({
            'STEAM_COMPAT_CLIENT_INSTALL_PATH': os.path.expanduser('~/.local/share/Steam'),
            'STEAM_COMPAT_DATA_PATH': self.compat,
            'WINEPREFIX': os.path.join(self.compat, 'pfx'),
            'WINEDEBUG': '-all', 'DXVK_LOG_LEVEL': 'warn', 'PROTON_LOG': '0',
            'WINEDLLOVERRIDES': 'd3dcompiler_47=n;d3dx11_43=n;d3dx10_43=n;d3dx9_43=n;msvcp140=n,b;'
                                'msvcp140_1=n,b;msvcp140_2=n,b;vcruntime140=n,b;vcruntime140_1=n,b;'
                                'concrt140=n,b;vcomp140=n,b',
        })
        return e

    def pids(self):
        """Processes carrying this bed's compat path (the game, Wine, gamescope's helpers)."""
        want = ('STEAM_COMPAT_DATA_PATH=' + self.compat).encode()
        out = {}
        for p in os.listdir('/proc'):
            if not p.isdigit() or int(p) == os.getpid():
                continue
            try:
                env_ = open('/proc/%s/environ' % p, 'rb').read().split(b'\0')
            except OSError:
                continue
            if want in env_:
                out[int(p)] = env_
        return out

    def kill(self):
        """Kill whatever still runs in this bed's prefix (Wine leaves winedevice.exe behind,
        which keeps gamescope open)."""
        for p in self.pids():
            try:
                os.kill(p, 9)
            except OSError:
                pass

    def display(self):
        for env_ in self.pids().values():
            for kv in env_:
                if kv.startswith(b'GAMESCOPE_WAYLAND_DISPLAY='):
                    return kv.split(b'=', 1)[1].decode()
        return None

    def init_prefix(self):
        os.makedirs(self.compat, exist_ok=True)
        mark = os.path.join(self.compat, '.runtime_dlls_installed')
        if os.path.isfile(mark):
            return
        log('making the Proton prefix for the %s (once)' % self.role)
        subprocess.run([PROTON, 'run', 'cmd.exe', '/c', 'exit'], cwd=self.game, env=self.env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        win = os.path.join(self.compat, 'pfx', 'drive_c', 'windows')
        for sub, dst in (('x64', 'system32'), ('x86', 'syswow64')):
            for f in os.listdir(os.path.join(RUNTIME_DLLS, sub)):
                if f.lower().endswith('.dll'):
                    shutil.copy2(os.path.join(RUNTIME_DLLS, sub, f), os.path.join(win, dst, f))
        open(mark, 'w').close()

    def shoot(self, path):
        disp = self.display()
        if not disp:
            return False
        e = dict(os.environ, GAMESCOPE_WAYLAND_DISPLAY=disp)
        subprocess.run(['gamescopectl', 'screenshot', path], env=e, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20)
        for _ in range(50):
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------ running
    def start(self, out, timeout, start_args):
        self.out = out
        fsltx = 'Z:' + os.path.join(self.game, 'fsgame.ltx').replace('/', '\\')
        cmd = ['timeout', '--kill-after=30', str(timeout),
               'gamescope', '--backend', 'headless', '-W', str(self.width), '-H', str(self.height),
               '-w', str(self.width), '-h', str(self.height), '--',
               PROTON, 'run', os.path.join(self.game, 'bin', EXE), '-fsltx', fsltx, '-nointro',
               '-silent_error_mode'] + list(start_args)
        self.con = open(os.path.join(out, '%s-console.txt' % self.role), 'w')
        self.proc = subprocess.Popen(cmd, cwd=self.game, env=self.env(), stdout=self.con, stderr=subprocess.STDOUT)

    def poll(self):
        """Answer a screenshot request; return the new [zgobed] lines of the engine log."""
        req, ack = os.path.join(self.app, 'zgobed_req.txt'), os.path.join(self.app, 'zgobed_ack.txt')
        try:
            r = open(req).read().strip()
        except OSError:
            r = ''
        if r and r != self.last_req:
            self.last_req = r
            n, name = r.split(' ', 1)
            time.sleep(0.3)
            path = os.path.join(self.out, '%s-%02d-%s.png' % (self.role, int(n), name.replace(' ', '-')))
            ok = self.shoot(path)
            self.shots.append(path if ok else name + ' (FAILED)')
            print('  %s shot %s %s' % (self.role, n, name if ok else name + ': no file'), flush=True)
            open(ack, 'w').write(n)
        new = []
        if os.path.isfile(self.logf):
            with open(self.logf, encoding='latin1') as f:
                f.seek(self.pos)
                chunk = f.read()
            # (only whole lines: the engine may be half-way through writing the last one)
            cut = chunk.rfind('\n') + 1
            self.pos += len(chunk[:cut].encode('latin1'))
            for line in chunk[:cut].splitlines():
                if '[zgobed]' in line:
                    text = line[line.find('[zgobed]') + 9:]
                    if not text.startswith('shot '):
                        print('  %s: %s' % (self.role, text), flush=True)
                    if text.startswith('CHECK '):
                        self.checks.append(text[6:])
                    if text == 'done':
                        self.done = True
                    new.append(text)
                if self.end is None and ('[zgobed] done' in line or 'FATAL ERROR' in line or 'stack trace:' in line):
                    self.end = (time.time() + 8, line.strip()[:160])
        return new

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def finish(self):
        self.kill()
        if self.proc is not None:
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.con.close()
        self.kill()
        xlog = []
        if os.path.isfile(self.logf):
            shutil.copy2(self.logf, os.path.join(self.out, '%s-xray.log' % self.role))
            with open(self.logf, encoding='latin1') as f:
                xlog = f.read().splitlines()
        return xlog

    def write(self, name, text, append=False):
        with open(os.path.join(self.app, name), 'a' if append else 'w') as f:
            f.write(text)


def summarize(title, beds, logs, t0):
    lines = [title, '%ds' % (time.time() - t0)]
    ok = True
    for bed in beds:
        xlog = logs[bed.role]
        fails = [c for c in bed.checks if re.search(r' FAIL( |$)', c)]
        ok = ok and bed.done and bool(bed.checks) and not fails
        lines.append('== %s: %s' % (bed.role, bed.end[1] if bed.end else 'no end line (killed or timed out)'))
        lines += [l.strip() for l in xlog if 'Init FileSystem' in l][:1]
        lines.append('checks: %d passed, %d failed' % (len(bed.checks) - len(fails), len(fails)))
        lines += ['  ' + c for c in bed.checks]
        zerr = [l.strip() for l in xlog if '[ZGO]' in l and any(
            w in l.lower() for w in ('failed', 'error', 'not in use', 'not shown', 'has none'))]
        if zerr:
            lines += ['[ZGO] lines about failures (%d):' % len(zerr)] + ['  ' + l[:220] for l in zerr[:15]]
        miss = [l.strip() for l in xlog if "can't find texture" in l.lower() and 'zgo' in l.lower()]
        if miss:
            lines += ['missing zgo textures (%d):' % len(miss)] + ['  ' + l[:200] for l in miss[:10]]
        lines += ['screenshots: %d' % len(bed.shots)] + ['  ' + os.path.basename(s) for s in bed.shots]
    return ok, lines


def prepared(bed, args, without, mcm, plan, save, ltx):
    if bed.pids():
        sys.exit('the %s bed runs already (pids %s); wait or kill it' % (bed.role, list(bed.pids())))
    facts = bed.build(args, without, mcm, plan)
    bed.appdata(args, save, ltx)
    if without:
        log('%s WITHOUT: %s' % (bed.role, ', '.join(without)))
    log('%s: %d mods, %d gamedata files linked (Umbra Gore & Effects: %d loose, %d textures in %s)%s' % (
        bed.role, facts['mods'], facts['gamedata'], facts['zgo_files'], facts['static'], package.STATIC_ARCHIVE,
        (' ; MCM ' + ', '.join('%s=%s' % m for m in mcm)) if mcm else ''))
    if facts['loose_archived']:
        log('WARNING: %d archived textures are loose too (they win over the archive): %s'
            % (len(facts['loose_archived']), facts['loose_archived'][:3]))
    bed.init_prefix()
    bed.kill()


def run(args):
    t0 = time.time()
    bed = Bed(BED, 'sp')
    prepared(bed, args, args.without, [], {'scenarios': ','.join(args.scenarios)}, args.save, [])
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = os.path.join(OUT, stamp)
    os.makedirs(out, exist_ok=True)
    log('starting the game (timeout %ds); save %r; scenarios %s' % (args.timeout, args.save, ','.join(args.scenarios)))
    bed.start(out, args.timeout, ['-start', 'server(zgobed/single/alife/load)', 'client(localhost)'])
    while bed.running():
        time.sleep(0.2)
        bed.poll()
        if bed.end and time.time() > bed.end[0]:
            break
    logs = {bed.role: bed.finish()}
    ok, lines = summarize('Umbra Gore & Effects game bed, %s; scenarios %s; save %s' % (
        stamp, ','.join(args.scenarios), args.save), [bed], logs, t0)
    with open(os.path.join(out, 'summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    log('ended: %s' % out)
    return 0 if ok else 1


def coop(args):
    """A host bed and a client bed on this machine, joined over xrRazom's LAN session."""
    t0 = time.time()
    host = Bed(BED, 'host')
    client = Bed(BED + '-client', 'client', 1280, 720)
    addr = '127.0.0.1:%d' % LAN_PORT
    mcm = [('zgo/dismember/baked_models', 'false')] if args.client_baked_models_off else []
    differs = bool(mcm or args.client_without)
    # the same plan on both (gamedata must match for xrRazom's mod check); a client set up
    # differently on purpose needs the host to waive that check
    plan = {'scenarios': ','.join(COOP_SCENARIOS), 'connect': addr}
    skip = [('xrr_skip_mod_check', 'on' if differs else 'off')]
    prepared(host, args, [], [], plan, args.save,
             [('xrr_host_session', 'on'), ('xrr_host_steam', 'off'), ('xrr_host_lan_port', str(LAN_PORT)),
              ('xrr_player_name', 'zgobed_host')] + skip)
    prepared(client, args, args.client_without, mcm, plan, None, [('xrr_player_name', 'zgobed_client')] + skip)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = os.path.join(OUT, stamp + '-coop')
    os.makedirs(out, exist_ok=True)
    log('starting the host (save %r) and the client (joins %s); timeout %ds' % (args.save, addr, args.timeout))
    host.start(out, args.timeout, ['-start', 'server(zgobed/single/alife/load)', 'client(localhost)'])
    client.start(out, args.timeout, [])
    beds = [host, client]
    grace = None
    while any(b.running() for b in beds):
        time.sleep(0.2)
        for line in host.poll():
            if line.startswith('host listening'):
                client.write('zgobed_connect.txt', addr)
            elif line.startswith('RELAY '):
                client.write('zgobed_relay.txt', line[6:] + '\n', append=True)
        for line in client.poll():
            if line.startswith('client in level'):
                host.write('zgobed_go.txt', 'go')
            elif line == 'done':
                host.write('zgobed_end.txt', 'end')
        if client.end and not os.path.isfile(os.path.join(host.app, 'zgobed_end.txt')):
            host.write('zgobed_end.txt', 'end')      # the client crashed: the host stops waiting
        # each side ends on its own (the host waits for the client's word); once one has ended
        # or its game is gone, the other gets a minute to finish
        gone = [b for b in beds if b.end or (b.proc is not None and b.proc.poll() is not None)]
        if gone:
            if grace is None:
                grace = time.time() + 60
            if all(b.end and time.time() > b.end[0] for b in beds) or time.time() > grace:
                break
    logs = {b.role: b.finish() for b in beds}
    title = 'Umbra Gore & Effects co-op game bed, %s; client %s' % (stamp, ', '.join(
        (['without ' + w for w in args.client_without]) + (['baked models off'] if mcm else [])) or 'like the host')
    ok, lines = summarize(title, beds, logs, t0)
    with open(os.path.join(out, 'summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    log('ended: %s' % out)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p):
        p.add_argument('--mo2', default=os.path.expanduser('~/gamma/gamma'))
        p.add_argument('--profile', default='G.A.M.M.A')
        p.add_argument('--game', default=os.path.expanduser('~/gamma/anomaly'))
        p.add_argument('--zgo', default='Umbra Gore & Effects', help="the mod's folder name in MO2")
        p.add_argument('--save', default='player - autosave', help="a save in the game's appdata/savedgames")
        p.add_argument('--timeout', type=int, default=900)
    r = sub.add_parser('run')
    r.add_argument('scenarios', nargs='*', default=DEFAULT)
    common(r)
    r.add_argument('--without', action='append', default=[], choices=['zgo', 'bake', 'static'],
                   help='leave out Umbra Gore & Effects altogether, its bake (the folder\'s baked files and '
                        'archives), or the textures\' archive (its textures loose instead); for bisecting')
    c = sub.add_parser('coop')
    common(c)
    c.add_argument('--client-without', action='append', default=[], choices=['bake', 'static'],
                   help="the client lacks the bake (or the textures' archive)")
    c.add_argument('--client-baked-models-off', action='store_true',
                   help='the client has the bake but MCM "Use baked models" off')
    sub.add_parser('scenarios')
    args = ap.parse_args()
    if args.cmd == 'scenarios':
        print('\n'.join(SCENARIOS))
        return 0
    if args.cmd == 'coop':
        return coop(args)
    bad = [s for s in args.scenarios if s not in SCENARIOS]
    if bad:
        sys.exit('unknown scenario(s) %s; known: %s' % (', '.join(bad), ', '.join(SCENARIOS)))
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
