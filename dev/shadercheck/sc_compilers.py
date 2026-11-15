"""
The compilers shadercheck runs, and which one the player's game loads.

  ms-<version>  Microsoft d3dcompiler_47.dll, run under Wine through
                d3dc/zgo_d3dc.exe (D3DCompile with the engine's includer,
                macros and flags). Windows 10/11 load a 10.0.x copy from
                System32; Proton prefixes with winetricks d3dcompiler_47 load
                6.3.9600.16384.
  wine          Wine's builtin d3dcompiler_47 (vkd3d-shader inside), same
                driver: what a Proton prefix without the native DLL uses.
  vkd3d         vkd3d-shader's HLSL compiler (vkd3d-compiler from dnf), run
                natively on a wrapper file that #defines the macros and
                #includes the source from r3\\ (same include root).

Copies of every Microsoft DLL found go to ~/.cache/zgo_shadercheck/compilers/
ms-<version>/ with their SHA-256; the game's prefix and folders are only read.
"""
import glob
import hashlib
import os
import re
import shutil
import struct
import subprocess
import tempfile

import sc_tree

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_SRC = os.path.join(HERE, 'd3dc', 'zgo_d3dc.c')
CACHE = sc_tree.CACHE
WINEPREFIX = os.environ.get('ZGO_SHADERCHECK_WINEPREFIX') or os.path.join(os.path.expanduser('~'), '.cache',
                                                                             'zgo-wine-shadercheck')


# ----------------------------------------------------------------- PE helpers
def pe_info(path):
    """{'arch', 'builtin', 'version', 'company', 'description', 'sha256'} or None."""
    try:
        with open(path, 'rb') as f:
            d = f.read()
    except OSError:
        return None
    if d[:2] != b'MZ':
        return None
    pe, = struct.unpack_from('<I', d, 0x3C)
    if d[pe:pe + 4] != b'PE\0\0':
        return None
    machine, = struct.unpack_from('<H', d, pe + 4)
    out = {'arch': {0x8664: 'x64', 0x14c: 'x86'}.get(machine, hex(machine)),
           'builtin': b'Wine builtin DLL' in d[:0x400] or b'Wine placeholder DLL' in d[:0x400],
           'sha256': hashlib.sha256(d).hexdigest(), 'size': len(d)}
    for key in ('FileVersion', 'CompanyName', 'FileDescription', 'ProductName'):
        k = key.encode('utf-16-le')
        i = d.find(k)
        if i < 0:
            continue
        j = i + len(k)
        while d[j:j + 2] == b'\0\0':
            j += 2
        e = d.find(b'\0\0', j)
        while e > 0 and (e - j) % 2:
            e = d.find(b'\0\0', e + 1)
        out[key] = d[j:e].decode('utf-16-le', 'replace')
    m = re.match(r'([\d.]+)', out.get('FileVersion', ''))
    out['version'] = m.group(1) if m else '?'
    return out


# ----------------------------------------------------------------- Steam / Proton
def _steam_roots():
    h = os.path.expanduser('~')
    for p in (os.path.join(h, '.local/share/Steam'), os.path.join(h, '.steam/steam'),
              os.path.join(h, '.var/app/com.valvesoftware.Steam/.local/share/Steam')):
        if os.path.isdir(p):
            yield os.path.realpath(p)


def _shortcuts():
    """[(appid, name, exe)] from every Steam user's shortcuts.vdf (non-Steam games)."""
    out = []
    for root in set(_steam_roots()):
        for vdf in glob.glob(os.path.join(root, 'userdata', '*', 'config', 'shortcuts.vdf')):
            try:
                d = open(vdf, 'rb').read()
            except OSError:
                continue
            for m in re.finditer(rb'\x02appid\x00(.{4})\x01AppName\x00([^\x00]*)\x00\x01Exe\x00([^\x00]*)\x00', d,
                                 re.S | re.I):
                out.append((struct.unpack('<I', m.group(1))[0], m.group(2).decode('utf-8', 'replace'),
                            m.group(3).decode('utf-8', 'replace').strip('"')))
    return out


def game_prefix(paths):
    """The Proton prefix that runs this MO2 (Steam non-Steam shortcut), or None."""
    mo2 = os.path.realpath(paths.mo2)
    for appid, name, exe in _shortcuts():
        e = exe.replace('\\', '/')
        if os.path.realpath(os.path.dirname(e)) == mo2 or os.path.realpath(e).startswith(mo2 + os.sep):
            for root in set(_steam_roots()):
                pfx = os.path.join(root, 'steamapps', 'compatdata', str(appid), 'pfx')
                if os.path.isdir(pfx):
                    return {'appid': appid, 'name': name, 'exe': exe, 'pfx': pfx,
                            'proton': _read(os.path.join(os.path.dirname(pfx), 'version')).strip()}
    return None


def _read(p):
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def _reg_overrides(reg_text, section):
    out = {}
    m = re.search(r'^\[' + re.escape(section) + r'\][^\n]*\n(.*?)(?=^\[|\Z)', reg_text, re.S | re.M)
    if m:
        for k, v in re.findall(r'^"([^"]+)"="([^"]*)"', m.group(1), re.M):
            out[k.lower().lstrip('*')] = v
    return out


def which_game_compiler(paths):
    """Which d3dcompiler_47.dll the player's AnomalyDX11 exe loads, and why."""
    lines = []
    found = None
    game = paths.game or ''
    exes = [e for e in ('AnomalyDX11AVX.exe', 'AnomalyDX11.exe') if os.path.isfile(os.path.join(game, 'bin', e))]
    for e in exes:
        data = open(os.path.join(game, 'bin', e), 'rb').read()
        lines.append('%s imports %s' % (e, 'D3DCOMPILER_47.dll' if b'D3DCOMPILER_47.dll' in data.upper() else
                                         'no d3dcompiler (check!)'))
    local = os.path.join(game, 'bin', 'd3dcompiler_47.dll')
    if os.path.isfile(local):
        i = pe_info(local)
        lines.append('the game folder ships bin/d3dcompiler_47.dll %s (%s): Windows and Wine load it first' % (
            i and i['version'], 'Wine builtin' if i and i['builtin'] else 'native'))
        found = ('bin', local, i)
    else:
        lines.append('no d3dcompiler_47.dll in the game\'s bin folder: Windows loads System32\'s copy '
                     '(10.0.x on Windows 10/11), Wine/Proton follows its DLL overrides')
    pfx = game_prefix(paths)
    if pfx:
        lines.append('Steam shortcut "%s" (appid %d) runs %s in prefix %s, Proton %s' % (
            pfx['name'], pfx['appid'], pfx['exe'], pfx['pfx'], pfx['proton'] or '?'))
        reg = _read(os.path.join(pfx['pfx'], 'user.reg'))
        glob_ov = _reg_overrides(reg, 'Software\\\\Wine\\\\DllOverrides').get('d3dcompiler_47')
        app_ov = None
        for e in exes + ['ModOrganizer.exe']:
            v = _reg_overrides(reg, 'Software\\\\Wine\\\\AppDefaults\\\\%s\\\\DllOverrides' % e).get('d3dcompiler_47')
            if v:
                app_ov = (e, v)
        lines.append('DllOverrides d3dcompiler_47: global=%s%s' % (
            glob_ov or '(none: builtin)', '' if not app_ov else ', %s=%s' % app_ov))
        sysdll = os.path.join(pfx['pfx'], 'drive_c', 'windows', 'system32', 'd3dcompiler_47.dll')
        i = pe_info(sysdll)
        if i:
            lines.append('prefix system32/d3dcompiler_47.dll: %s %s, sha256 %s' % (
                'Wine builtin' if i['builtin'] else i.get('CompanyName', '?'), i['version'], i['sha256'][:16]))
        ov = (app_ov[1] if app_ov else glob_ov) or ''
        if not found:
            if ov.startswith('n') and i and not i['builtin']:
                found = ('prefix', sysdll, i)
                lines.append('=> the game loads Microsoft d3dcompiler_47 %s (native override)' % i['version'])
            else:
                lines.append('=> the game loads Wine\'s builtin d3dcompiler_47 (vkd3d-shader)')
                found = ('builtin', None, None)
    else:
        lines.append('no Steam shortcut found for this MO2: cannot tell which compiler Proton/Wine uses')
    return found, lines


# ----------------------------------------------------------------- Microsoft DLLs
def find_ms_dlls(paths):
    """Copy every distinct Microsoft d3dcompiler_47.dll (x64) into the cache.
    [(label, path, info, origin)]"""
    cands = []
    for p in (os.environ.get('ZGO_D3DCOMPILER') or '').split(os.pathsep):
        if p:
            cands.append((p, 'ZGO_D3DCOMPILER'))
    if paths.game:
        cands.append((os.path.join(paths.game, 'bin', 'd3dcompiler_47.dll'), 'game bin'))
    pfx = game_prefix(paths)
    if pfx:
        cands.append((os.path.join(pfx['pfx'], 'drive_c', 'windows', 'system32', 'd3dcompiler_47.dll'),
                      'game prefix %d' % pfx['appid']))
    cands.append((os.path.join(paths.mo2, 'dlls', 'd3dcompiler_47.dll'), 'MO2 dlls'))
    cands += [(p, 'cache') for p in sorted(glob.glob(os.path.join(CACHE, 'compilers', 'ms-*', 'd3dcompiler_47.dll')))]

    def others():                     # only when none of the above has one
        for root in set(_steam_roots()):
            for p in sorted(glob.glob(os.path.join(root, 'steamapps', 'compatdata', '*', 'pfx', 'drive_c', 'windows',
                                                   'system32', 'd3dcompiler_47.dll'))):
                yield p, 'Steam prefix'
    seen = {}
    for p, origin in list(cands) + [None] + list(others()):
        if p is None:
            if seen:
                break
            continue
        p, origin = p, origin
        if isinstance(p, tuple):
            p, origin = p
        i = pe_info(p)
        if not i or i['builtin'] or i['arch'] != 'x64' or 'Microsoft' not in i.get('CompanyName', ''):
            continue
        if i['sha256'] in seen:
            continue
        label = 'ms-' + i['version']
        d = os.path.join(CACHE, 'compilers', label)
        dst = os.path.join(d, 'd3dcompiler_47.dll')
        if not os.path.isfile(dst) or pe_info(dst)['sha256'] != i['sha256']:
            os.makedirs(d, exist_ok=True)
            shutil.copyfile(p, dst)
            with open(os.path.join(d, 'SOURCE.txt'), 'w') as f:
                f.write('copied from %s (%s)\nsha256 %s\nFileVersion %s\n' % (p, origin, i['sha256'],
                                                                              i.get('FileVersion')))
        seen[i['sha256']] = (label, dst, i, origin)
    return sorted(seen.values(), key=lambda x: [int(v) if v.isdigit() else 0 for v in x[0][3:].split('.')])


# ----------------------------------------------------------------- jobs / results
class Job:
    def __init__(self, jid, rel, entry, target, defs, flags=8):
        self.id = jid
        self.rel = rel              # 'shaders/r3/particle.ps'
        self.entry = entry
        self.target = target
        self.defs = defs            # [(name, value)]
        self.flags = flags


class Result:
    def __init__(self, job, compiler):
        self.job = job
        self.compiler = compiler
        self.ok = False
        self.hr = None
        self.messages = []
        self.includes = []
        self.sig_in = []            # (semantic, index, register, sysvalue, comptype, mask, rwmask)
        self.sig_out = []
        self.resources = []         # (name, type, bindpoint, count)
        self.cbvars = []            # (cbuffer, name, offset, size, used)
        self.error = None           # tool problem, not a shader problem

    def errors(self):
        return [m for m in self.messages if re.search(r'\berror\b|: E\d{4}', m, re.I)]

    def warnings(self):
        return [m for m in self.messages if m not in self.errors()]


def _winpath(p):
    return 'Z:' + os.path.abspath(p).replace('/', '\\')


class D3DCBackend:
    """zgo_d3dc.exe under Wine with one d3dcompiler_47 (Microsoft or builtin)."""

    def __init__(self, label, dll, expect_builtin, note=''):
        self.name = label
        self.dll = dll              # path, or None for Wine's builtin
        self.expect_builtin = expect_builtin
        self.note = note
        self.loaded = None

    def available(self):
        if not shutil.which('wine'):
            return False, 'wine not found (run inside the zgo-dev container: dev/run.sh)'
        exe = driver_exe()
        if not exe:
            return False, 'cannot build d3dc/zgo_d3dc.exe (needs x86_64-w64-mingw32-gcc)'
        return True, ''

    def run(self, jobs, tree):
        exe = driver_exe()
        root = _winpath(os.path.join(tree, 'shaders'))
        os.makedirs(os.path.join(CACHE, 'jobs'), exist_ok=True)
        fd, jf = tempfile.mkstemp(prefix='%s-' % self.name, suffix='.txt', dir=os.path.join(CACHE, 'jobs'))
        with os.fdopen(fd, 'w') as f:
            for j in jobs:
                f.write('JOB %s\nROOT %s\nFILE %s\nENTRY %s\nTARGET %s\nFLAGS %d\n' % (
                    j.id, root, j.rel.split('/', 1)[1].replace('/', '\\'), j.entry, j.target, j.flags))
                for n, v in j.defs:
                    f.write('DEF %s %s\n' % (n, v))
                f.write('END\n')
        env = dict(os.environ, WINEPREFIX=WINEPREFIX, WINEDEBUG='-all',
                   WINEDLLOVERRIDES='d3dcompiler_47=%s;mscoree=;mshtml=' % ('b' if self.dll is None else 'n'))
        try:
            p = subprocess.run(['wine', exe, 'builtin' if self.dll is None else _winpath(self.dll), _winpath(jf)],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        finally:
            os.unlink(jf)
        out = p.stdout.decode('utf-8', 'replace')
        res = {j.id: Result(j, self.name) for j in jobs}
        for line in out.splitlines():
            f = line.split('\t')
            tag = f[0]
            if tag == 'DLL' and len(f) >= 5:
                self.loaded = {'path': f[2], 'kind': f[3], 'version': f[4]}
            elif tag == 'FATAL':
                for r in res.values():
                    r.error = line
            elif len(f) >= 2 and f[1] in res:
                r = res[f[1]]
                if tag == 'MSG':
                    r.messages.append('\t'.join(f[2:]))
                elif tag == 'INC':
                    r.includes.append((f[2], f[3]))
                elif tag == 'SIG':
                    rec = (f[3], int(f[4]), int(f[5]), int(f[6]), int(f[7]), int(f[8]), int(f[9]))
                    (r.sig_in if f[2] == 'IN' else r.sig_out).append(rec)
                elif tag == 'RES':
                    r.resources.append((f[2], int(f[3]), int(f[4]), int(f[5])))
                elif tag == 'CB':
                    r.cbvars.append((f[2], f[3], int(f[4]), int(f[5]), f[6] == '1'))
                elif tag == 'RESULT':
                    r.ok = f[2] == 'OK'
                    r.hr = f[3]
        problem = None
        if self.loaded is None:
            problem = 'driver produced no DLL line: %s' % (p.stderr.decode('utf-8', 'replace')[-400:] or out[-400:])
        elif (self.loaded['kind'] == 'builtin') != self.expect_builtin:
            problem = 'Wine loaded the %s d3dcompiler_47 (%s) instead of the %s one' % (
                self.loaded['kind'], self.loaded['version'], 'builtin' if self.expect_builtin else 'native')
        for r in res.values():
            if problem:
                r.error = problem
            elif r.hr is None and not r.error:
                r.error = 'no result from the driver'
        return res


class VkdBackend:
    """vkd3d-compiler (native) on a wrapper in the tree's r3 folder."""
    name = 'vkd3d'

    def __init__(self):
        self.version = None
        self.note = 'vkd3d-compiler'

    def available(self):
        exe = shutil.which('vkd3d-compiler')
        if not exe:
            return False, 'vkd3d-compiler not found (dev/run.sh sudo dnf install -y vkd3d-compiler)'
        v = subprocess.run([exe, '--version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
        self.version = v.decode().strip().splitlines()[0] if v else '?'
        return True, ''

    def run(self, jobs, tree):
        res = {}
        r3 = os.path.join(tree, 'shaders', 'r3')
        for n, j in enumerate(jobs):
            r = Result(j, self.name)
            res[j.id] = r
            inc = j.rel.split('/', 2)[2] if j.rel.startswith('shaders/r3/') else '../' + j.rel.split('/', 1)[1]
            ext = os.path.splitext(j.rel)[1]
            wrap = os.path.join(r3, '__zgo_sc_%d_%d%s' % (os.getpid(), n, ext))
            with open(wrap, 'w') as f:
                for name, val in j.defs:
                    f.write('#define %s %s\n' % (name, val))
                f.write('#include "%s"\n' % inc)
            try:
                args = ['vkd3d-compiler', '-x', 'hlsl', '-p', j.target, '-e', j.entry, '-b', 'dxbc-tpf',
                        '--matrix-storage-order=%s' % ('row' if j.flags & 8 else 'column'), '-o', os.devnull,
                        os.path.basename(wrap)]
                p = subprocess.run(args, cwd=r3, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
                txt = p.stdout.decode('utf-8', 'replace')
                r.messages = [l.replace(os.path.basename(wrap), '<wrapper>') for l in txt.splitlines() if l.strip()]
                r.ok = p.returncode == 0
                r.hr = 'exit %d' % p.returncode
            except subprocess.TimeoutExpired:
                r.error = 'vkd3d-compiler timed out'
            finally:
                os.unlink(wrap)
        return res


# ----------------------------------------------------------------- driver build
def driver_exe():
    exe = os.path.join(CACHE, 'bin', 'zgo_d3dc.exe')
    if os.path.isfile(exe) and os.path.getmtime(exe) >= os.path.getmtime(DRIVER_SRC):
        return exe
    cc = shutil.which('x86_64-w64-mingw32-gcc')
    if not cc:
        return exe if os.path.isfile(exe) else None
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    p = subprocess.run([cc, '-O2', '-Wall', '-Wno-unused-parameter', '-Wno-cast-function-type',
                        '-Wno-format-truncation', '-o', exe + '.part', DRIVER_SRC, '-lversion'],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError('building zgo_d3dc.exe failed:\n' + p.stdout.decode('utf-8', 'replace'))
    os.replace(exe + '.part', exe)
    return exe


def backends(paths, wanted=None):
    """Every compiler shadercheck knows, in report order. wanted: set of names
    or families ('ms', 'wine', 'vkd3d')."""
    out = []
    game, _ = which_game_compiler(paths)
    game_sha = game[2]['sha256'] if game and game[2] else None
    for label, dll, info, origin in find_ms_dlls(paths):
        note = 'Microsoft %s (%s)%s' % (info['version'], origin,
                                        ', the one this game loads' if info['sha256'] == game_sha else '')
        out.append(D3DCBackend(label, dll, False, note))
    out.append(D3DCBackend('wine', None, True, "Wine's builtin d3dcompiler_47 (vkd3d-shader)%s" % (
        ', the one this game loads' if game and game[0] == 'builtin' else '')))
    out.append(VkdBackend())
    if wanted:
        out = [b for b in out if b.name in wanted or b.name.split('-')[0] in wanted]
    return out
