#!/usr/bin/env python3
"""
shadercheck: compile Umbra Gore & Effects' DX11 shaders the way the game does,
against this machine's mod list, before anyone starts the game.

    dev/run.sh dev/shadercheck/check.sh                  every ZGO shader
    dev/run.sh dev/shadercheck/check.sh zgo_particle.ps  one file (name, r3/name or a path)
    dev/run.sh dev/shadercheck/check.sh --overrides      which mods replace ZGO's shaders
                                                         or the stock files they include
    dev/run.sh dev/shadercheck/check.sh --selftest       stock shaders + a known-bad one
    dev/run.sh dev/shadercheck/check.sh --which-compiler which d3dcompiler the game loads

See README.md next to this file. Reads the game, MO2 and the mods; writes only
to ~/.cache/zgo_shadercheck (the assembled tree, compiler copies, reports).
Exit status: 0 everything passed, 1 a check failed, 2 the tool could not run.
"""
import argparse
import concurrent.futures
import difflib
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import sc_tree        # noqa: E402
import sc_engine      # noqa: E402
import sc_compilers   # noqa: E402
import sc_blenders    # noqa: E402

MOCK = os.path.join(HERE, 'blender_mock.lua')
STAGE_EXT = tuple(sc_engine.STAGES)
# system values the rasterizer generates for the pixel shader (no VS output needed)
SYS_GENERATED = {'sv_isfrontface', 'sv_sampleindex', 'sv_primitiveid', 'sv_coverage', 'sv_innercoverage'}
BASELINE_RE = re.compile(rb'shadercheck-baseline:[ \t]*([^\s*]+)')
PARITY_RE = re.compile(rb'shadercheck-parity:[ \t]*([^\s]+)')
OVERLAY_PREFIX = '__zgo_sc_'
D3D_SIT = {0: 'cbuffer', 1: 'tbuffer', 2: 'texture', 3: 'sampler', 4: 'uav', 5: 'structured', 6: 'uav_struct',
           7: 'byteaddress', 8: 'uav_byteaddress', 9: 'append', 10: 'consume', 11: 'uav_counter'}


def log(*a):
    print(*a, flush=True)


# ===================================================================== include graph
class IncGraph:
    """#include edges with the engine's resolution: r3\\<name>, then <name>,
    relative to the shaders folder, case blind. Keys are 'shaders/...'."""
    INC = re.compile(rb'^[ \t]*#[ \t]*include[ \t]*["<]([^">]+)[">]', re.M)

    def __init__(self, tree):
        self.tree = tree
        self.files = set()
        top = os.path.join(tree, 'shaders')
        for dp, dns, fns in os.walk(top):
            for fn in fns:
                p = os.path.join(dp, fn)
                if not os.path.islink(p):
                    self.files.add(os.path.relpath(p, tree).replace(os.sep, '/'))
        self._inc = {}
        self._clo = {}

    def path(self, rel):
        return os.path.join(self.tree, *rel.split('/'))

    def resolve(self, name):
        n = name.replace('\\', '/').lower().lstrip('/')
        for c in ('shaders/r3/' + n, 'shaders/' + n):
            if c in self.files:
                return c
        return None

    def includes(self, rel):
        if rel not in self._inc:
            try:
                data = open(self.path(rel), 'rb').read()
            except OSError:
                data = b''
            self._inc[rel] = [(m.group(1).decode('latin1'), self.resolve(m.group(1).decode('latin1')))
                              for m in self.INC.finditer(data)]
        return self._inc[rel]

    def closure(self, rel):
        """Every file rel pulls in (static: ignores #if), itself included."""
        if rel in self._clo:
            return self._clo[rel]
        seen, stack = set(), [rel]
        while stack:
            r = stack.pop()
            if r in seen:
                continue
            seen.add(r)
            stack.extend(x for _, x in self.includes(r) if x and x not in seen)
        self._clo[rel] = seen
        return seen

    def missing(self, rel):
        return sorted({(r, n) for r in self.closure(rel) for n, x in self.includes(r) if x is None})

    def dependents(self, rel):
        return sorted(f for f in self.files if f.startswith('shaders/r3/') and f.endswith(STAGE_EXT)
                      and f != rel and rel in self.closure(f))


# ===================================================================== pass index
def mock_dump(paths_list):
    """{shader name: info} from the blender mock for the given .s files."""
    out = {}
    if not paths_list:
        return out
    luajit = shutil.which('luajit')
    if not luajit:
        raise RuntimeError('luajit not found')
    p = subprocess.run([luajit, MOCK, '--dump'] + paths_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cur = None
    for line in p.stdout.decode('utf-8', 'replace').splitlines():
        f = line.split('\t')
        if f[0] == 'FILE':
            cur = {'path': f[1], 'name': os.path.basename(f[1])[:-2].lower(), 'has': False, 'errors': [],
                   'elements': {}, 'log': []}
            out[cur['name']] = cur
        elif cur is None:
            continue
        elif f[0] == 'SHADER':
            cur['has'] = f[2] == 'true'
        elif f[0] == 'ERR':
            cur['errors'].append('%s: %s' % (f[1], '\t'.join(f[2:])))
        elif f[0] == 'E':
            cur['elements'][int(f[1])] = {'priority': int(f[2]), 'strict': f[3] == 'true', 'emissive': f[4] == 'true',
                                          'distort': f[5] == 'true', 'wmark': f[6] == 'true', 'passes': [],
                                          'notes': []}
        elif f[0] == 'P':
            cur['elements'][int(f[1])]['passes'].append(dict(
                vs=f[3], gs=f[4], ps=f[5], fog=f[6] == 'true', ztest=f[7] == 'true', zfunc=f[8],
                zwrite=f[9] == 'true', ablend=f[10] == 'true', src=f[11], dst=f[12], atest=f[13] == 'true',
                aref=None if f[14] == 'nil' else int(float(f[14])), colorwrite=f[15], textures=[], samplers=[]))
        elif f[0] == 'T':
            cur['elements'][int(f[1])]['passes'][int(f[2]) - 1]['textures'].append((f[3], f[4]))
        elif f[0] == 'S':
            cur['elements'][int(f[1])]['passes'][int(f[2]) - 1]['samplers'].append((f[3], f[4] == 'true'))
        elif f[0] == 'N':
            cur['elements'][int(f[1])]['notes'].append(f[2])
        elif f[0] == 'LOG':
            cur['log'].append(f[1])
    if p.returncode != 0:
        raise RuntimeError('blender mock failed: ' + p.stderr.decode('utf-8', 'replace')[-500:])
    return out


def cpp_particle_passes(blenders):
    """The C++ particle blender's passes (Blender_Particle.cpp, R4), per
    shaders.xr entry: {'particles\\blend': {0: [pass], 1: [pass], 2: [pass]}}."""
    out = {}
    for name, b in blenders.items():
        if b['cls'].strip() != 'PARTICLE':
            continue
        prm = sc_blenders.particle_params(b)
        m = sc_blenders.PARTICLE_MODES.get(prm['blend'])
        sh = sc_blenders.PARTICLE_SHADOW.get(prm['blend'])
        if not m:
            continue

        def mk(d):
            return dict(vs=d['vs'], gs='null', ps=d['ps'], fog=False, ztest=True, zfunc='lessequal',
                        zwrite=d['zwrite'], ablend=d['ablend'], src=d['src'] if d['ablend'] else 'one',
                        dst=d['dst'] if d['ablend'] else 'zero', atest=d['atest'],
                        aref=d['aref'] if d['atest'] else None,
                        colorwrite=','.join(str(x).lower() for x in d['colorwrite']) if 'colorwrite' in d
                        else 'default',
                        textures=[('s_base', '$base0'), ('s_position', '$user$position')],
                        samplers=[('smp_base', prm['clamp']), ('smp_nofilter', False)])
        el = {'priority': prm['priority'], 'strict': prm['strict'], 'emissive': False, 'distort': False,
              'wmark': False, 'notes': []}
        out[name] = {'name': name, 'cpp': True, 'elements': {
            0: dict(el, passes=[mk(m)]), 1: dict(el, passes=[mk(m)]), 2: dict(el, passes=[mk(sh)])}}
    return out


# ===================================================================== targets
class Target:
    def __init__(self, rel, why, overlay=None):
        self.rel = rel            # 'shaders/r3/x.ps'
        self.why = why
        self.overlay = overlay    # source path copied into the tree for this run


def default_targets(res):
    """Every ZGO file under shaders/ that the DX11 renderer can load."""
    out, skipped = [], []
    for rel, chain in sorted(res.chain.items()):
        if not any(L.label == sc_tree.ZGO_LABEL for L, _ in chain):
            continue
        if rel.startswith('shaders/r3/'):
            out.append(Target(rel, 'zgo'))
        else:
            skipped.append(rel)
    return out, skipped


def arg_targets(args, res, paths, tree):
    out = []
    zgo_gd = os.path.realpath(os.path.join(paths.mod_root, 'gamedata'))
    for a in args:
        p = os.path.realpath(a) if os.path.exists(a) else None
        if p and p.startswith(zgo_gd + os.sep):
            rel = os.path.relpath(p, zgo_gd).replace(os.sep, '/').lower()
            out.append(Target(rel, 'argument'))
        elif p and os.path.isfile(p):
            rel = 'shaders/r3/' + os.path.basename(p).lower()
            out.append(Target(rel, 'file outside ZGO, checked as r3\\' + os.path.basename(p).lower(), overlay=p))
        else:
            n = a.replace('\\', '/').lower()
            for pre in ('gamedata/',):
                if n.startswith(pre):
                    n = n[len(pre):]
            if not n.startswith('shaders/'):
                n = ('shaders/' + n) if n.startswith('r3/') else ('shaders/r3/' + n)
            if n not in res.chain:
                raise SystemExit('shadercheck: no shader file %r in the assembled tree (%s)' % (a, n))
            out.append(Target(n, 'argument'))
    return out


# ===================================================================== the check
class Check:
    def __init__(self, opts):
        self.o = opts
        self.paths = sc_tree.Paths()
        bad = self.paths.check()
        if bad:
            raise SystemExit('shadercheck: cannot find the game / MO2: %s' % '; '.join(bad))
        t0 = time.time()
        self.res = sc_tree.Resolved(self.paths, ('shaders/',))
        self.tree = sc_tree.materialize(self.res)
        self.t_tree = time.time() - t0
        self.graph = IncGraph(self.tree)
        self.overlays = []
        self.findings = []           # (level, file, text)
        self.records = []            # compile results for JSON

    # ------------------------------------------------------------- helpers
    def provider(self, rel):
        w = self.res.winner(rel)
        return w[0].label if w else ('overlay' if rel in self.overlay_rels() else '?')

    def overlay_rels(self):
        return {r for r, _ in self.overlays}

    def zgo_provides(self, rel):
        return any(L.label == sc_tree.ZGO_LABEL for L, _ in self.res.chain.get(rel, []))

    def zgo_touched(self, rel):
        if rel in self.overlay_rels():
            return True
        return any(self.zgo_provides(r) for r in self.graph.closure(rel))

    def add_overlay(self, rel, data):
        p = os.path.join(self.tree, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        self.overlays.append((rel, p))
        self.graph = IncGraph(self.tree)

    def cleanup(self):
        for rel, p in self.overlays:
            w = self.res.winner(rel)
            if w:                                   # put the real winner back
                with open(p, 'wb') as f:
                    f.write(w[0].read(w[1]))
            elif os.path.exists(p):
                os.unlink(p)
        self.overlays = []

    def find(self, level, what, text):
        self.findings.append((level, what, text))

    # ------------------------------------------------------------- pass index
    def build_index(self):
        r3 = os.path.join(self.tree, 'shaders', 'r3')
        s_files = sorted(p for p in glob.glob(os.path.join(r3, '*.s')) if not os.path.islink(p))
        self.lua = mock_dump(s_files)
        xr = sc_tree.Resolved(self.paths, ('shaders.xr',))
        try:
            self.blenders = sc_blenders.blenders(xr.read('shaders.xr'))
        except KeyError:
            self.blenders = {}
        self.cpp = cpp_particle_passes(self.blenders)
        # stage file -> [(shader, element, pass index, pass)]
        self.users = {}
        for kind, table in (('lua', self.lua), ('cpp', self.cpp)):
            for name, info in table.items():
                if kind == 'cpp' and name.replace('\\', '_') in self.lua:
                    continue                    # a Lua .s of the same name wins
                for idx, el in info['elements'].items():
                    for i, p in enumerate(el['passes']):
                        for st, ext in (('vs', '.vs'), ('gs', '.gs'), ('ps', '.ps')):
                            if p[st] and p[st] != 'null':
                                rel = 'shaders/r3/%s%s' % (p[st], ext)
                                self.users.setdefault(rel, []).append((kind, name, idx, i, p))

    # ------------------------------------------------------------- units
    def plan(self, targets):
        """-> {rel: role}, pass checks [(label, pass, owner-is-target)]"""
        units = {}
        passes = []
        for t in targets:
            ext = os.path.splitext(t.rel)[1]
            if t.overlay:
                self.add_overlay(t.rel, open(t.overlay, 'rb').read())
            if ext in STAGE_EXT:
                units.setdefault(t.rel, 'target')
                for kind, name, idx, i, p in self.users.get(t.rel, []):
                    passes.append(('%s %s E%d pass %d' % ('C++ blender' if kind == 'cpp' else name + '.s', name,
                                                          idx, i + 1), p, t.rel))
            elif ext == '.s':
                name = os.path.basename(t.rel)[:-2]
                info = self.lua.get(name)
                if info is None:
                    self.find('FAIL', t.rel, 'not in the tree')
                    continue
                units.setdefault(t.rel, 'script')
                for e in info['errors']:
                    self.find('FAIL', t.rel, 'Lua error (fatal in game): ' + e)
                if not info['has']:
                    self.find('FAIL', t.rel, 'no normal() or l_special(): the engine ignores this .s and looks '
                                             'for a C++ blender of the same name')
                for idx, el in sorted(info['elements'].items()):
                    for n in el['notes']:
                        self.find('WARN', t.rel, 'E%d: %s' % (idx, n))
                    for i, p in enumerate(el['passes']):
                        passes.append(('%s.s E%d pass %d' % (name, idx, i + 1), p, t.rel))
            elif ext in ('.h', '.hlsl', '.hlsli', '.inc', '.txt') or ext == '':
                deps = self.graph.dependents(t.rel)
                units.setdefault(t.rel, 'header')
                if not deps:
                    self.find('WARN', t.rel, 'no shader in the tree includes this file')
                for d in deps:
                    units.setdefault(d, 'dependent')
            else:
                self.find('INFO', t.rel, 'not a shader stage, .s or include: skipped')
        for label, p, owner in passes:
            for st, ext in (('vs', '.vs'), ('gs', '.gs'), ('ps', '.ps')):
                if p[st] and p[st] != 'null':
                    rel = 'shaders/r3/%s%s' % (p[st], ext)
                    if rel not in self.graph.files:
                        self.find('FAIL', owner, '%s uses %s, which no mod provides: the game substitutes '
                                                 'stub_default%s (wrong output, a "missing" line in the log)'
                                  % (label, rel[8:], ext))
                    else:
                        units.setdefault(rel, 'pass')
        return units, passes

    # ------------------------------------------------------------- jobs
    def make_jobs(self, units, sets, roles=None):
        jobs, meta = [], {}
        first = next(iter(sets))
        for rel, role in sorted(units.items()):
            if role in ('script', 'header'):
                continue
            if roles and role not in roles:
                continue
            src = open(self.graph.path(rel), 'rb').read()
            entry, target = sc_engine.target_for(rel, src)
            if entry is None:
                continue
            skins = [-1]
            if rel.endswith('.vs') and not self.o.no_skin:
                text = b''.join(open(self.graph.path(r), 'rb').read() for r in self.graph.closure(rel))
                if b'SKIN_' in text:
                    skins = [-1, 0, 1, 2, 3, 4]
            for sname, (opts, _) in sets.items():
                for sk in (skins if sname == first else [-1]):
                    o = dict(opts, skinning=sk)
                    jid = 'j%d' % len(jobs)
                    jobs.append(sc_compilers.Job(jid, rel, entry, target, sc_engine.defines(o)))
                    meta[jid] = (rel, sname, sk)
        return jobs, meta

    def compile_all(self, backends, jobs):
        out = {}

        def one(b):
            t0 = time.time()
            try:
                r = b.run(jobs, self.tree)
            except Exception as e:          # a tool problem, not a shader problem
                r = {}
                for j in jobs:
                    x = sc_compilers.Result(j, b.name)
                    x.error = '%s: %s' % (type(e).__name__, e)
                    r[j.id] = x
            return b.name, r, time.time() - t0
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(backends) or 1) as ex:
            for name, r, dt in ex.map(one, backends):
                out[name] = r
                self.timing[name] = self.timing.get(name, 0) + dt
        return out

    # ------------------------------------------------------------- baselines
    def baseline_for(self, rel):
        """(label, rel of the file to compare with) or None."""
        if rel in self.overlay_rels():
            return None
        below = self.res.below_zgo(rel) if self.zgo_provides(rel) else None
        if below:
            brel = rel.rsplit('/', 1)[0] + '/' + OVERLAY_PREFIX + 'base_' + rel.rsplit('/', 1)[1]
            if brel not in self.overlay_rels():
                self.add_overlay(brel, below[0].read(below[1]))
            return ('%s (the copy ZGO replaces)' % below[0].label, brel)
        try:
            head = open(self.graph.path(rel), 'rb').read(4096)
        except OSError:
            return None
        m = BASELINE_RE.search(head)
        if m:
            b = self.graph.resolve(m.group(1).decode('latin1'))
            if b:
                return ('%s (declared baseline)' % b[11:], b)
            self.find('WARN', rel, 'declared baseline %s is not in the tree' % m.group(1).decode('latin1'))
        return None

    # ------------------------------------------------------------- linkage
    @staticmethod
    def linkage(out_res, in_res, a, b):
        """D3D11 shader linkage: every input the later stage reads must be
        written by the earlier one, same semantic, same register, components
        covered. Returns [problem]."""
        probs = []
        outs = {(s.lower(), i): (reg, mask) for s, i, reg, sv, ct, mask, rw in out_res.sig_out}
        for s, i, reg, sv, ct, mask, rw in in_res.sig_in:
            key = (s.lower(), i)
            if key[0] in SYS_GENERATED:
                continue
            if key not in outs:
                probs.append('%s reads %s%d, which %s does not write' % (b, s, i, a))
                continue
            oreg, omask = outs[key]
            if oreg != reg:
                probs.append('%s%d is in register %d of %s but register %d of %s: the value arrives in the '
                             'wrong input' % (s, i, oreg, a, reg, b))
            if rw & ~omask:
                probs.append('%s reads components %s of %s%d that %s does not write' % (
                    b, _mask(rw & ~omask), s, i, a))
        return probs

    def bindings(self, p, results):
        """Textures and samplers the shaders use vs. what the pass binds."""
        probs, warns = [], []
        used = {}
        for st, ext in (('vs', '.vs'), ('gs', '.gs'), ('ps', '.ps')):
            r = results.get('shaders/r3/%s%s' % (p[st], ext))
            if r is None:
                continue
            for name, typ, bp, cnt in r.resources:
                if typ in (2, 3):
                    used[name] = typ
        tex = {t for t, _ in p['textures']}
        smp = {s for s, _ in p['samplers']}
        for name, typ in sorted(used.items()):
            if typ == 2 and name not in tex:
                if name in smp:
                    probs.append('%s is a texture in the shader but bound with dx10sampler' % name)
                else:
                    warns.append('texture %s is read but the pass binds nothing to it (empty slot)' % name)
            if typ == 3 and name not in smp:
                if name in tex:
                    probs.append('%s is a sampler in the shader but bound with dx10texture: R_ASSERT in game' %
                                 name)
                else:
                    warns.append('sampler %s is used but the pass never sets it (driver default state)' % name)
        for name in sorted(tex):
            if name in used and used[name] == 3:
                probs.append('dx10texture("%s") names a sampler: R_ASSERT(C->type == RC_dx10texture) in game'
                             % name)
        return probs, warns

    # ------------------------------------------------------------- parity
    def parity(self, rel):
        head = open(self.graph.path(rel), 'rb').read(4096)
        m = PARITY_RE.search(head)
        if not m:
            return None
        ref = m.group(1).decode('latin1').lower()
        name = os.path.basename(rel)[:-2]
        mine = self.lua.get(name)
        theirs = self.lua.get(ref.replace('\\', '_')) or self.cpp.get(ref)
        if not mine or not theirs:
            self.find('FAIL', rel, 'parity reference %s not found (neither a .s nor a C++ blender)' % ref)
            return False
        diffs = []
        for idx in sorted(set(mine['elements']) | set(theirs['elements'])):
            a, b = mine['elements'].get(idx), theirs['elements'].get(idx)
            if idx == 2 and b and not a and b['priority'] // 2 == 1:
                continue        # priority 2/3: never drawn into the shadow map (pmask), element unused
            if (a is None) != (b is None):
                diffs.append('E%d %s' % (idx, 'missing' if a is None else 'extra'))
                continue
            for k in ('priority', 'strict', 'emissive', 'distort', 'wmark'):
                if a[k] != b[k]:
                    diffs.append('E%d %s %s, reference %s' % (idx, k, a[k], b[k]))
            if len(a['passes']) != len(b['passes']):
                diffs.append('E%d %d passes, reference %d' % (idx, len(a['passes']), len(b['passes'])))
                continue
            for i, (pa, pb) in enumerate(zip(a['passes'], b['passes'])):
                for k in ('vs', 'gs', 'fog', 'ztest', 'zfunc', 'zwrite', 'ablend', 'src', 'dst', 'atest', 'aref',
                          'colorwrite'):
                    if pa[k] != pb[k]:
                        diffs.append('E%d pass %d %s=%s, reference %s' % (idx, i + 1, k, pa[k], pb[k]))
                if pa['ps'] != pb['ps']:
                    bl = self.baseline_for('shaders/r3/%s.ps' % pa['ps'])
                    if not bl or bl[1] != 'shaders/r3/%s.ps' % pb['ps']:
                        diffs.append('E%d pass %d ps=%s, reference %s (and %s.ps does not declare '
                                     '"shadercheck-baseline: %s.ps")' % (idx, i + 1, pa['ps'], pb['ps'], pa['ps'],
                                                                         pb['ps']))
                ta = sorted(t for t, _ in pa['textures'])
                tb = sorted(t for t, _ in pb['textures'])
                if ta != tb:
                    diffs.append('E%d pass %d textures %s, reference %s' % (idx, i + 1, ta, tb))
                for (t, v) in pa['textures']:
                    ref_v = dict(pb['textures']).get(t)
                    if ref_v and ref_v != v and not (ref_v.startswith('$base') or v == 'zgo\\shadercheck_base'):
                        diffs.append('E%d pass %d %s=%s, reference %s' % (idx, i + 1, t, v, ref_v))
                if sorted(pa['samplers']) != sorted(pb['samplers']):
                    diffs.append('E%d pass %d samplers %s, reference %s' % (idx, i + 1, sorted(pa['samplers']),
                                                                           sorted(pb['samplers'])))
        if diffs:
            for d in diffs:
                self.find('FAIL', rel, 'differs from %s: %s' % (ref, d))
            return False
        self.find('OK', rel, 'same elements and pass state as %s%s' % (
            ref, ' (C++ blender from shaders.xr)' if theirs.get('cpp') else ''))
        return True


def _mask(m):
    return ''.join(c for i, c in enumerate('xyzw') if m & (1 << i)) or '-'


# ===================================================================== run modes
def run_check(opts, targets_from_args=None, quiet_header=False):
    """The normal check. Returns (exit code, report dict)."""
    C = Check(opts)
    C.timing = {}
    try:
        return _run_check(C, opts, targets_from_args, quiet_header)
    finally:
        C.cleanup()


def pick_sets(opts, paths):
    allsets = sc_engine.define_sets(paths.game)
    if opts.sets == 'all':
        names = list(allsets)
    elif opts.sets == 'quick':
        names = ['user'] if 'user' in allsets else ['default']
    else:
        names = [s.strip() for s in opts.sets.split(',') if s.strip()]
        bad = [n for n in names if n not in allsets]
        if bad:
            raise SystemExit('shadercheck: unknown define set(s) %s (have: %s)' % (bad, ', '.join(allsets)))
    return {n: allsets[n] for n in names}


def pick_backends(opts, paths):
    wanted = None
    if opts.compilers != 'all':
        wanted = {c.strip() for c in opts.compilers.split(',') if c.strip()}
    bes = sc_compilers.backends(paths, wanted)
    game, game_lines = sc_compilers.which_game_compiler(paths)
    ok, skipped = [], []
    for b in bes:
        a, why = b.available()
        (ok if a else skipped).append((b, why))
    if opts.game_only:
        gsha = game[2]['sha256'] if game and game[2] else None
        keep = []
        for b, why in ok:
            if isinstance(b, sc_compilers.D3DCBackend) and (
                    (b.dll and gsha and sc_compilers.pe_info(b.dll)['sha256'] == gsha) or
                    (b.dll is None and game and game[0] == 'builtin')):
                keep.append((b, why))
        ok = keep
    return [b for b, _ in ok], skipped, game, game_lines


def _run_check(C, opts, targets_from_args, quiet_header):
    paths = C.paths
    sets = pick_sets(opts, paths)
    backends, skipped, game, game_lines = pick_backends(opts, paths)
    if opts.compilers != 'all' and skipped:
        raise SystemExit('shadercheck: compiler(s) not available: %s' % '; '.join(
            '%s (%s)' % (b.name, w) for b, w in skipped))
    if not backends:
        raise SystemExit('shadercheck: no compiler available: %s' % '; '.join(
            '%s (%s)' % (b.name, w) for b, w in skipped))
    C.build_index()
    if targets_from_args is not None:
        targets = targets_from_args(C)
        skipped_files = []
    elif opts.files:
        targets = arg_targets(opts.files, C.res, paths, C.tree)
        skipped_files = []
    else:
        targets, skipped_files = default_targets(C.res)
    units, passes = C.plan(targets)
    jobs, meta = C.make_jobs(units, sets)

    if not quiet_header:
        log('shadercheck: %d files from %d layers assembled in %.1fs at %s' % (
            len(C.graph.files), len(C.res.layers), C.t_tree, C.tree))
        log('game compiler: ' + (game_lines[-1] if game_lines else '?').lstrip('=> '))
        for b in backends:
            log('  compiler %-20s %s' % (b.name, b.note))
        for b, why in skipped:
            log('  compiler %-20s SKIPPED: %s' % (b.name, why))
        log('define sets: ' + ', '.join('%s' % n for n in sets) + (
            '   (skinned VS variants _0.._4 with "%s")' % next(iter(sets)) if not opts.no_skin else ''))
        for rel in skipped_files:
            log('  %s: not under r3\\, the DX11 renderer never loads it' % rel)
        log('%d targets, %d stage files, %d compile jobs per compiler\n' % (len(targets), sum(
            1 for r in units.values() if r not in ('script', 'header')), len(jobs)))

    results = C.compile_all(backends, jobs)
    for b in backends:
        if getattr(b, 'loaded', None) and isinstance(b, sc_compilers.D3DCBackend):
            b.note += ' [loaded %s %s]' % (b.loaded['kind'], b.loaded['version'])

    # status per job and compiler
    status = {}            # (jid, backend) -> 'PASS'|'FAIL'|'GAP'|'STOCK'|'ERROR'
    base_needed = {}       # rel -> baseline
    for b in backends:
        for j in jobs:
            r = results[b.name][j.id]
            rel = meta[j.id][0]
            if r.error:
                status[(j.id, b.name)] = 'ERROR'
            elif r.ok:
                status[(j.id, b.name)] = 'PASS'
            elif not C.zgo_touched(rel):
                status[(j.id, b.name)] = 'STOCK'
            else:
                status[(j.id, b.name)] = 'FAIL'
                if rel not in base_needed:
                    base_needed[rel] = C.baseline_for(rel)
    # second round: compile the baselines where a ZGO file failed
    bjobs, bmeta = [], {}
    for (jid, bname), st in list(status.items()):
        rel, sname, sk = meta[jid]
        bl = base_needed.get(rel) if st == 'FAIL' else None
        if bl:
            j = next(x for x in jobs if x.id == jid)
            src = open(C.graph.path(bl[1]), 'rb').read()
            entry, target = sc_engine.target_for(bl[1], src)
            nid = 'b%d' % len(bjobs)
            bjobs.append(sc_compilers.Job(nid, bl[1], entry, target, j.defs))
            bmeta[nid] = (jid, bname)
    if bjobs:
        need = {bn for _, bn in bmeta.values()}
        bres = C.compile_all([b for b in backends if b.name in need], bjobs)
        for nid, (jid, bname) in bmeta.items():
            r = bres[bname][nid]
            if not r.error and not r.ok:
                status[(jid, bname)] = 'GAP'

    # ---------------------------------------------------------- report
    fails = 0
    report = {'tree': C.tree, 'game_compiler': game_lines, 'compilers': [
        {'name': b.name, 'note': b.note} for b in backends], 'skipped_compilers': [
        {'name': b.name, 'why': w} for b, w in skipped], 'sets': {n: {'description': d, 'sh_name': sc_engine.sh_name(o)}
                                                               for n, (o, d) in sets.items()},
        'files': [], 'findings': [], 'passes': []}
    by_rel = {}
    for j in jobs:
        by_rel.setdefault(meta[j.id][0], []).append(j)
    order = sorted(by_rel, key=lambda r: (units[r] != 'target', units[r] != 'dependent', r))
    for rel in order:
        role = units[rel]
        chain = [L.label for L, _ in C.res.chain.get(rel, [])]
        tag = {'target': '', 'dependent': ' [includes a checked header]', 'pass': ' [used by a checked pass]'}[role]
        log('%s  (%s)%s' % (rel[8:], ' < '.join(reversed(chain)) or 'overlay', tag))
        frec = {'file': rel, 'role': role, 'chain': chain, 'compilers': {}}
        for b in backends:
            cells, msgs = [], []
            for j in by_rel[rel]:
                _, sname, sk = meta[j.id]
                st = status[(j.id, b.name)]
                r = results[b.name][j.id]
                label = sname + ('' if sk < 0 else '/skin%d' % sk)
                cells.append((label, st))
                frec['compilers'].setdefault(b.name, []).append({'set': sname, 'skin': sk, 'status': st,
                                                                 'messages': r.messages, 'error': r.error})
                if st in ('FAIL', 'ERROR', 'GAP', 'STOCK') or (opts.verbose and r.messages):
                    m = [r.error] if r.error else (r.errors() if st != 'PASS' else []) or r.messages
                    if not opts.verbose:
                        m = m[:6]
                    msgs.append((label, st, m))
                if st == 'FAIL' or st == 'ERROR':
                    fails += 1
            # compact: one status when every set agrees
            sts = {s for _, s in cells}
            if len(sts) == 1:
                log('  %-20s %-5s %s' % (b.name, sts.pop(), ' '.join(l for l, _ in cells if '/skin' not in l) + (
                    ' (+%d skinned)' % sum(1 for l, _ in cells if '/skin' in l) if any(
                        '/skin' in l for l, _ in cells) else '')))
            else:
                log('  %-20s %s' % (b.name, ' '.join('%s:%s' % c for c in cells)))
            seen_m = set()
            for label, st, m in msgs:
                key = (st, tuple(m))
                if key in seen_m and not opts.verbose:
                    continue
                seen_m.add(key)
                expl = {'GAP': ' (the stock file fails too with this compiler: a compiler gap, not counted)',
                        'STOCK': ' (stock file, not changed by ZGO: not counted)'}.get(st, '')
                log('      %s %s%s' % (label, st, expl))
                for x in m:
                    log('        ' + x)
        report['files'].append(frec)

    # linkage and bindings, per pass, with the reflecting compilers
    refl = [b for b in backends if isinstance(b, sc_compilers.D3DCBackend)]
    if passes:
        log('')
    for label, p, owner in passes:
        probs, warns = set(), set()
        checked = 0
        for b in refl:
            for sname in sets:
                per = {}
                for j in jobs:
                    rel, sn, sk = meta[j.id]
                    if sn == sname and sk < 0:
                        per[rel] = results[b.name][j.id]
                stages = [('shaders/r3/%s%s' % (p[st], ext), st) for st, ext in (('vs', '.vs'), ('gs', '.gs'),
                                                                                  ('ps', '.ps'))
                          if p[st] and p[st] != 'null']
                rs = [(per.get(r), st, r) for r, st in stages]
                if any(x is None or not x.ok for x, _, _ in rs):
                    continue
                checked += 1
                for (a, sa, ra), (c, sc, rc) in zip(rs, rs[1:]):
                    for pr in C.linkage(a, c, ra[11:], rc[11:]):
                        probs.add('%s: %s' % (sname, pr) if len(sets) > 1 else pr)
                pb, wb = C.bindings(p, per)
                probs.update(pb)
                warns.update(wb)
        line = '%s: %s -> %s%s' % (label, p['vs'], (p['gs'] + ' -> ') if p['gs'] != 'null' else '', p['ps'])
        if not checked:
            log('pass %s: not checked (a stage did not compile)' % line)
        elif probs:
            fails += 1
            log('pass %s: FAIL' % line)
            for x in sorted(probs):
                log('      ' + x)
        else:
            log('pass %s: linkage OK' % line)
        for x in sorted(warns):
            log('      note: ' + x)
        report['passes'].append({'pass': line, 'owner': owner, 'problems': sorted(probs), 'notes': sorted(warns),
                                 'checked': checked})

    # parity of .s files that declare a reference
    for rel, role in sorted(units.items()):
        if role == 'script':
            C.parity(rel)

    if C.findings:
        log('')
    for level, what, text in C.findings:
        log('%-4s %s: %s' % (level, what[8:] if what.startswith('shaders/') else what, text))
        if level == 'FAIL':
            fails += 1
        report['findings'].append({'level': level, 'file': what, 'text': text})

    n_pass = sum(1 for s in status.values() if s == 'PASS')
    n_gap = sum(1 for s in status.values() if s in ('GAP', 'STOCK'))
    log('\n%d files, %d compiles: %d PASS, %d FAIL/ERROR, %d not counted (stock / compiler gap); %s' % (
        len(by_rel), len(status), n_pass, sum(1 for s in status.values() if s in ('FAIL', 'ERROR')), n_gap,
        ', '.join('%s %.0fs' % kv for kv in sorted(C.timing.items()))))
    log('RESULT: %s' % ('PASS' if fails == 0 else 'FAIL (%d)' % fails))
    report['result'] = 'PASS' if fails == 0 else 'FAIL'
    report['fail_count'] = fails
    return (0 if fails == 0 else 1), report


def run_overrides(opts):
    """Which mods replace ZGO's shader files, or the stock files they include."""
    C = Check(opts)
    log('shadercheck --overrides: %s' % C.paths.describe())
    zgo = [rel for rel, ch in sorted(C.res.chain.items()) if any(L.label == sc_tree.ZGO_LABEL for L, _ in ch)]
    problems = 0
    report = {'zgo_files': [], 'includes': []}
    log('\nZGO shader files (game order: MO2 overwrite > mods above ZGO > ZGO > mods below > base archives)')
    for rel in zgo:
        above = C.res.above_zgo(rel)
        below = C.res.below_zgo(rel)
        ent = {'file': rel, 'above': [L.label for L, _ in above], 'replaces': below[0].label if below else None}
        if above:
            problems += 1
            log('  FAIL %s: %s wins in game, ZGO\'s copy is never loaded' % (rel[8:], above[-1][0].label))
        elif below:
            mine = C.res.read(rel)
            theirs = below[0].read(below[1])
            d = list(difflib.unified_diff(theirs.decode('latin1').splitlines(), mine.decode('latin1').splitlines(),
                                          below[0].label, 'zgo', lineterm='', n=1))
            log('  override %s: replaces %s (%d lines changed)' % (
                rel[8:], below[0].label, sum(1 for x in d if x[:1] in '+-' and x[:3] not in ('+++', '---'))))
            if opts.verbose:
                for x in d:
                    log('      ' + x)
            # every other mod that also ships the file (ZGO hides their version)
            others = [L.label for L, _ in C.res.chain[rel] if L.label not in (sc_tree.ZGO_LABEL, below[0].label)
                      and not L.label.startswith('base:')]
            if others:
                log('      also shipped by %s (hidden by ZGO too)' % ', '.join(others))
            ent['diff_lines'] = len(d)
        else:
            log('  new      %s' % rel[8:])
        report['zgo_files'].append(ent)
    log('\nfiles ZGO\'s shaders include, and who provides them in this mod list')
    seen = set()
    for rel in zgo:
        for r in sorted(C.graph.closure(rel)):
            if r == rel or r in seen or C.zgo_provides(r):
                continue
            seen.add(r)
            ch = [L.label for L, _ in C.res.chain.get(r, [])]
            mods = [x for x in ch if not x.startswith('base:')]
            if mods:
                log('  %s: %s (over %s)' % (r[8:], mods[-1], ' < '.join(ch[:-1])))
            report['includes'].append({'file': r, 'chain': ch})
        for src, name in C.graph.missing(rel):
            problems += 1
            log('  FAIL %s includes "%s" (from %s), which no mod provides' % (rel[8:], name, src[8:]))
    log('\n%d stock include files in use; the ones above that a mod provides are what ZGO\'s shaders compile '
        'against in this mod list.' % len(seen))
    log('RESULT: %s' % ('PASS' if not problems else 'FAIL (%d)' % problems))
    report['result'] = 'PASS' if not problems else 'FAIL'
    return (0 if not problems else 1), report


def run_selftest(opts):
    """Stock shaders and ZGO's wallmark under every compiler, then known-bad
    inputs that must be caught."""
    ok = True
    log('== selftest 1/4: option-string decoder against the game\'s shader cache')
    P = sc_tree.Paths()
    top = os.path.join(P.game or '', 'appdata', 'shaders_cache', 'r4')
    keys = {k for d in glob.glob(os.path.join(top, '*')) for k in os.listdir(d)} if os.path.isdir(top) else set()
    bad = [k for k in keys if (sc_engine.decode_sh_name(k) is None or
                               sc_engine.sh_name(sc_engine.decode_sh_name(k)) != k)]
    for n, (o, d) in sc_engine.define_sets(P.game).items():
        if sc_engine.decode_sh_name(sc_engine.sh_name(o)) is None:
            bad.append('set ' + n)
    log('  %d cache keys, %d undecodable %s' % (len(keys), len(bad), bad[:3]))
    ok &= not bad

    log('\n== selftest 2/4: stock shaders and ZGO\'s effects_wallmark_blood.ps, every compiler, two sets')
    stock = ['particle.ps', 'particle.vs', 'deffer_particle.ps', 'deffer_particle.vs', 'particle-clip.vs',
             'particle_s-blend.ps', 'effects_wallmark_blood.vs', 'effects_wallmark_blood.ps', 'model_def_lq.vs',
             'stub_default.ps', 'stub_default.vs']

    def tg(C):
        out = [Target('shaders/r3/' + n, 'selftest') for n in stock]
        below = C.res.below_zgo('shaders/r3/effects_wallmark_blood.ps')
        if below:
            C.add_overlay('shaders/r3/' + OVERLAY_PREFIX + 'stock_effects_wallmark_blood.ps', below[0].read(below[1]))
            out.append(Target('shaders/r3/' + OVERLAY_PREFIX + 'stock_effects_wallmark_blood.ps', 'selftest'))
        return out
    o2 = argparse.Namespace(**vars(opts))
    if o2.sets == 'all':
        o2.sets = 'user,default' if os.path.isdir(top) else 'default,low'
    code, rep = run_check(o2, tg, quiet_header=False)
    ok &= code == 0
    need = {'ms', 'wine', 'vkd3d'}
    have = {c['name'].split('-')[0] for c in rep['compilers']}
    if need - have and opts.compilers == 'all':
        log('  missing compilers: %s' % ', '.join(sorted(need - have)))
        ok = False

    log('\n== selftest 3/4: known-bad input must FAIL under every compiler')
    badsrc = (b'#include "common.h"\n// shadercheck selftest: an undeclared identifier\n'
              b'float4 main(float4 p : SV_Position) : SV_Target { return zgo_not_declared * 2; }\n')
    vs_src = (b'struct v2p { float2 tc0 : TEXCOORD0; float4 hpos : SV_Position; };\n'
              b'v2p main(float4 p : POSITION) { v2p o; o.tc0 = p.xy; o.hpos = p; return o; }\n')
    ps_src = (b'struct v2p { float4 c : COLOR0; float4 hpos : SV_Position; };\n'
              b'float4 main(v2p I) : SV_Target { return I.c; }\n')
    s_src = (b'function normal(shader, t_base, t_second, t_detail)\n'
             b'  shader:begin("' + OVERLAY_PREFIX.encode() + b'link", "' + OVERLAY_PREFIX.encode() + b'link")\n'
             b'    :blend(true, blend.srcalpha)\nend\n')
    s2_src = (b'function normal(shader, t_base, t_second, t_detail)\n'
              b'  shader:begin("' + OVERLAY_PREFIX.encode() + b'link", "' + OVERLAY_PREFIX.encode() + b'link")\n'
              b'    :sorting(3, true):zb(true, false):fog(false)\n'
              b'  shader:dx10texture("s_base", t_base)\nend\n')
    scratch = os.path.join(sc_tree.CACHE, 'selftest')
    os.makedirs(scratch, exist_ok=True)
    files = {OVERLAY_PREFIX + 'bad.ps': badsrc, OVERLAY_PREFIX + 'link.vs': vs_src,
             OVERLAY_PREFIX + 'link.ps': ps_src, OVERLAY_PREFIX + 'luaerr.s': s_src,
             OVERLAY_PREFIX + 'linkpass.s': s2_src}
    for n, d in files.items():
        with open(os.path.join(scratch, n), 'wb') as f:
            f.write(d)

    def tg2(C):
        out = []
        for n in files:
            C.add_overlay('shaders/r3/' + n, open(os.path.join(scratch, n), 'rb').read())
        C.build_index()             # the .s overlays must be in the pass index
        for n in (OVERLAY_PREFIX + 'bad.ps', OVERLAY_PREFIX + 'luaerr.s', OVERLAY_PREFIX + 'linkpass.s'):
            out.append(Target('shaders/r3/' + n, 'selftest'))
        return out
    o3 = argparse.Namespace(**vars(opts))
    o3.sets = 'default'
    code, rep = run_check(o3, tg2, quiet_header=True)
    bad_rec = [f for f in rep['files'] if f['file'].endswith('bad.ps')]
    caught_compile = bool(bad_rec) and all(all(x['status'] == 'FAIL' for x in v)
                                           for v in bad_rec[0]['compilers'].values())
    caught_lua = any(f['level'] == 'FAIL' and 'luaerr' in f['file'] and 'Lua error' in f['text']
                     for f in rep['findings'])
    caught_link = any('linkpass' in p['owner'] and any('COLOR0' in x for x in p['problems'])
                      for p in rep['passes'])
    log('  compile error caught by every compiler: %s' % caught_compile)
    log('  Lua error in a .s caught: %s' % caught_lua)
    log('  VS/PS signature mismatch caught: %s' % caught_link)
    ok &= code == 1 and caught_compile and caught_lua and caught_link

    log('\n== selftest 4/4: which d3dcompiler the game loads')
    _, lines = sc_compilers.which_game_compiler(P)
    for x in lines:
        log('  ' + x)
    log('\nSELFTEST %s' % ('PASSED' if ok else 'FAILED'))
    return 0 if ok else 1, {}


# ===================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser(prog='shadercheck', description=__doc__.split('\n\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='shader files: a name (zgo_particle.ps), r3/name, or a path; '
                                             'default: every ZGO shader')
    ap.add_argument('--sets', default='all', help='define sets, comma separated, "quick" (the game\'s own) or '
                                                  '"all" (default); --list-sets shows them')
    ap.add_argument('--compilers', default='all', help='ms, ms-<version>, wine, vkd3d (comma separated) or all')
    ap.add_argument('--game-only', action='store_true', help='only the d3dcompiler this game loads')
    ap.add_argument('--no-skin', action='store_true', help='skip the skinned vertex shader variants')
    ap.add_argument('--overrides', action='store_true', help='report mods that replace ZGO shaders or the '
                                                             'stock files they include')
    ap.add_argument('--selftest', action='store_true', help='stock shaders + known-bad inputs')
    ap.add_argument('--which-compiler', action='store_true', help='which d3dcompiler_47 the game loads')
    ap.add_argument('--list-sets', action='store_true', help='print the define sets')
    ap.add_argument('--json', metavar='FILE', help='also write the report as JSON')
    ap.add_argument('-v', '--verbose', action='store_true', help='every compiler message, full diffs')
    opts = ap.parse_args(argv)

    os.makedirs(sc_tree.CACHE, exist_ok=True)
    lock = open(os.path.join(sc_tree.CACHE, '.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log('shadercheck: another run is using %s, waiting...' % sc_tree.CACHE)
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        if opts.which_compiler:
            P = sc_tree.Paths()
            found, lines = sc_compilers.which_game_compiler(P)
            for x in lines:
                log(x)
            for label, dll, info, origin in sc_compilers.find_ms_dlls(P):
                log('cached %s: %s (sha256 %s, from %s)' % (label, dll, info['sha256'], origin))
            return 0
        if opts.list_sets:
            P = sc_tree.Paths()
            for n, (o, d) in sc_engine.define_sets(P.game).items():
                log('%-12s %s\n             %s' % (n, d, ' '.join('%s=%s' % x for x in sc_engine.defines(o))))
            return 0
        if opts.selftest:
            code, report = run_selftest(opts)
        elif opts.overrides:
            code, report = run_overrides(opts)
        else:
            code, report = run_check(opts)
        if opts.json:
            with open(opts.json, 'w') as f:
                json.dump(report, f, indent=1)
        return code
    except SystemExit as e:
        if isinstance(e.code, str):
            log(e.code)
            return 2
        raise
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == '__main__':
    sys.exit(main())
