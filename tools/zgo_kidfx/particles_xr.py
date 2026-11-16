#!/usr/bin/env python3
"""
particles.xr, the game's compiled particle library, and the loose .pe / .pg files the game
also reads (gamedata/particles/<name>.pe|.pg). A loose file beats the particles.xr entry of
the same name, whichever mod ships which.

This reads particles.xr the way the engine does and writes any entry as the loose file the
X-Ray SDK would export, except that every float is written with as many decimals as it needs
to read back bit for bit (the SDK rounds to six). The two are the same effect in the game.

    python3 particles_xr.py list <particles.xr> [--groups] [--prefix hit_fx\\]
    python3 particles_xr.py export <particles.xr> <gamedata/particles folder> [--prefix P]... [--name N]...
    python3 particles_xr.py check <particles.xr>...     every entry: binary -> loose -> back, bit for bit

Sources (xray-monolith, src/Layers/xrRender): PSLibrary.cpp CPSLibrary::Load / Save2,
ParticleEffectDef.cpp CPEDef::Load / Save2 / Load2, ParticleGroup.cpp CPGDef::Load / Save2 /
Load2, ParticleEffectActions.cpp (each action's parameters), xrParticles/psystem.h (ids).

  particles.xr   chunk 1 u16 version (1); chunk 3 effects; chunk 4 groups (chunk i = entry i)
  effect         1 u16 version (1), 2 name, 3 u32 max particles, 4 compiled actions (the game
                 rebuilds them from 0x24), 5 u32 flags, 7 sprite (shader, texture), 6 frame,
                 8 time limit, 0x21 collision, 0x22 velocity scale, 0x25 align to path,
                 0x24 the actions: u32 n, then n x (u32 type, u32 version, name, u32 flags,
                 floats, vectors, domains, u8 bools, s32 ints), each kind in the editor's
                 parameter order, which the loose file numbers flt_0000.. in the same order
  group          1 u16 version (3), 2 name, 3 u32 flags, 4 effects (u32 n, n x (name, play
                 child, birth child, death child, f32 time0, f32 time1, u32 flags)), 5 time limit

Importable: load(path) -> Library; Library.effects / .groups (name -> Effect / Group);
effect_ini(e) / group_ini(g) -> bytes of the loose file; parse_pe / parse_pg (loose -> model).
"""
import os
import re
import struct
import sys

sys.dont_write_bytecode = True

PS_VERSION = 1
PED_VERSION = 1
PGD_VERSION = 3
ACTION_VERSION = 1

# effect flags (ParticleEffectDef.h)
DF_SPRITE = 1 << 0
DF_FRAMED = 1 << 10
DF_TIMELIMIT = 1 << 14
DF_ALIGN_TO_PATH = 1 << 15
DF_COLLISION = 1 << 16
DF_VELOCITY_SCALE = 1 << 18
# group effect flags (ParticleGroup.h)
FL_ON_PLAY_CHILD = 1 << 1
FL_ON_BIRTH_CHILD = 1 << 5
FL_ON_DEAD_CHILD = 1 << 6

# action type -> (name, floats, vectors, domains, bools, ints): what each EPA* constructor appends
ACTIONS = {
    0: ('avoid', 3, 0, 1, 1, 0),
    1: ('bounce', 3, 0, 1, 1, 0),
    3: ('copyvertexb', 0, 0, 0, 1, 0),
    4: ('damping', 2, 1, 0, 0, 0),
    5: ('explosion', 5, 1, 0, 1, 0),
    6: ('follow', 3, 0, 0, 0, 0),
    7: ('gravitate', 3, 0, 0, 0, 0),
    8: ('gravity', 0, 1, 0, 1, 0),
    9: ('jet', 3, 1, 1, 1, 0),
    10: ('killold', 1, 0, 0, 1, 0),
    11: ('matchvelocity', 3, 0, 0, 0, 0),
    12: ('move', 0, 0, 0, 0, 0),
    13: ('orbitline', 3, 2, 0, 1, 0),
    14: ('orbitpoint', 3, 1, 0, 1, 0),
    15: ('randomaccel', 0, 0, 1, 1, 0),
    16: ('randomdisplace', 0, 0, 1, 1, 0),
    17: ('randomvelocity', 0, 0, 1, 1, 0),
    18: ('restore', 1, 0, 0, 0, 0),
    19: ('sink', 0, 0, 1, 2, 0),
    20: ('sinkvelocity', 0, 0, 1, 2, 0),
    21: ('source', 5, 0, 5, 2, 0),
    22: ('speedlimit', 2, 0, 0, 0, 0),
    23: ('targetcolor', 4, 1, 0, 0, 0),
    24: ('targetsize', 0, 2, 0, 0, 0),
    25: ('targetrotate', 1, 1, 0, 0, 0),
    26: ('targetrotate', 1, 1, 0, 0, 0),
    27: ('targetvelocity', 1, 1, 0, 1, 0),
    28: ('targetvelocity', 1, 1, 0, 1, 0),
    29: ('vortex', 3, 2, 0, 1, 0),
    30: ('turbulence', 3, 1, 0, 0, 1),
    31: ('scatter', 3, 1, 0, 1, 0),
}

F32_HALF_PI = struct.unpack('<f', struct.pack('<f', 1.5707963267948966))[0]


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------- floats
def f32(x):
    """x rounded to float32 (as a C cast from double does)."""
    return struct.unpack('<f', struct.pack('<f', x))[0]


def _bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def _from_bits(b):
    return struct.unpack('<f', struct.pack('<I', b & 0xFFFFFFFF))[0]


_NUM = re.compile(r'^\s*([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?\s*$')


def _rational(s):
    """A decimal string as an exact (numerator, denominator); integers only (no fractions
    module: Umbra Effects Setup bundles only the standard library its own list names)."""
    m = _NUM.match(s)
    if not m or not (m.group(2) or m.group(3)):
        raise ValueError('not a number: %r' % s)
    ip, fp = m.group(2) or '', m.group(3) or ''
    n = int(ip + fp or '0') * (-1 if m.group(1) == '-' else 1)
    e = int(m.group(4) or 0) - len(fp)
    return (n * 10 ** e, 1) if e >= 0 else (n, 10 ** -e)


def _f32_exact(s):
    """The float32 nearest the decimal s, rounded once (strtof), ties to even."""
    if s.strip().lower().lstrip('+-') in ('inf', 'infinity', 'nan'):
        return f32(float(s))
    n, d = _rational(s)
    if n == 0:
        return -0.0 if s.lstrip().startswith('-') else 0.0
    c = f32(n / d)
    best = None
    b = _bits(c)
    for cand in (c, _from_bits(b - 1), _from_bits(b + 1)):
        if cand != cand or cand in (float('inf'), float('-inf')):
            continue
        p, q = cand.as_integer_ratio()
        dist = (abs(p * d - n * q), q * d)          # |cand - s| as a fraction
        if best is None or dist[0] * best[0][1] < best[0][0] * dist[1] or (
                dist[0] * best[0][1] == best[0][0] * dist[1] and _bits(cand) % 2 == 0):
            best = (dist, cand)
    return best[1]


def fmt_float(v):
    """v (a float32 value) as the shortest '%.Nf' (N >= 6, the SDK's format) that both of the
    engine's readers turn back into exactly v: atof then a cast (r_float), and strtof (sscanf
    '%f', r_fvector). Infinities are 'inf' / '-inf' (the UCRT, and Wine's, read those)."""
    if v in (float('inf'), float('-inf')):
        return '-inf' if v < 0 else 'inf'       # what the SDK's C runtime prints, and its strtod/strtof read
    if v != v:
        raise FormatError('NaN cannot be written so that it reads back the same')
    want = _bits(v)
    for n in range(6, 160):
        s = '%.*f' % (n, v)
        if _bits(f32(float(s))) == want and _bits(_f32_exact(s)) == want:
            return s
    raise FormatError('no decimal form reads back as %r' % v)


# ---------------------------------------------------------------- binary
def chunks(data):
    """[(id, body)] in file order."""
    out, o = [], 0
    while o + 8 <= len(data):
        cid, sz = struct.unpack_from('<II', data, o)
        if o + 8 + sz > len(data):
            raise FormatError('chunk 0x%x runs past the end' % cid)
        out.append((cid, data[o + 8:o + 8 + sz]))
        o += 8 + sz
    return out


def _find(chs, cid):
    """The first chunk with this id (IReader::find_chunk), or None."""
    for c, body in chs:
        if c == cid:
            return body
    return None


class _R:
    def __init__(self, data):
        self.d, self.o = data, 0

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.d, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v

    def u32(self):
        return self.take('I')[0]

    def s(self):
        e = self.d.index(b'\0', self.o)
        v = self.d[self.o:e].decode('latin1')
        self.o = e + 1
        return v

    def floats(self, n):
        return list(self.take('%df' % n)) if n else []


class Action:
    __slots__ = ('type', 'version', 'name', 'flags', 'floats', 'vectors', 'domains', 'bools', 'ints')

    def __init__(self, type_, name=None, flags=0, floats=None, vectors=None, domains=None, bools=None, ints=None,
                 version=ACTION_VERSION):
        if type_ not in ACTIONS:
            raise FormatError('unknown action type %d' % type_)
        _, nf, nv, nd, nb, ni = ACTIONS[type_]
        self.type, self.version, self.flags = type_, version, flags
        self.name = ACTIONS[type_][0] if name is None else name
        self.floats = list(floats) if floats is not None else [0.0] * nf
        self.vectors = [list(v) for v in vectors] if vectors is not None else [[0.0] * 3 for _ in range(nv)]
        self.domains = [(d[0], [list(x) for x in d[1]]) for d in domains] if domains is not None else \
            [(0, [[0.0] * 3, [0.0] * 3, [0.0] * 3]) for _ in range(nd)]
        self.bools = list(bools) if bools is not None else [0] * nb
        self.ints = list(ints) if ints is not None else [0] * ni
        if (len(self.floats), len(self.vectors), len(self.domains), len(self.bools), len(self.ints)) != (nf, nv, nd,
                                                                                                        nb, ni):
            raise FormatError('action type %d takes %s parameters' % (type_, ACTIONS[type_][1:]))


class Effect:
    def __init__(self, name):
        self.name = name
        self.max_particles = 0
        self.flags = 0
        self.shader = self.texture = ''
        self.frame = None           # (tex_size x, y, reserved x, y, dim_x, frame_count, speed)
        self.time_limit = 0.0
        self.collision = (1.0, 0.0, 0.0)
        self.velocity_scale = (0.0, 0.0, 0.0)
        self.align_rotation = (-F32_HALF_PI, 0.0, 0.0)
        self.actions = []
        self.raw = None             # the entry's bytes in particles.xr


class Group:
    def __init__(self, name):
        self.name = name
        self.flags = 0
        self.effects = []           # [name, play child, birth child, death child, time0, time1, flags]
        self.time_limit = 0.0
        self.raw = None


def read_effect(body):
    """CPEDef::Load, with the game's pCreateEAction: the actions come from chunk 0x24.
    Raises FormatError for an entry the game would drop or that has no actions to export."""
    chs = chunks(body)
    v = _find(chs, 1)
    if v is None or struct.unpack_from('<H', v)[0] != PED_VERSION:
        raise FormatError('effect version is not %d (the game skips it)' % PED_VERSION)
    name = _find(chs, 2)
    if name is None:
        raise FormatError('effect without a name')
    e = Effect(name.split(b'\0', 1)[0].decode('latin1'))
    e.raw = body
    d = _find(chs, 3)
    if d is None or _find(chs, 4) is None:
        raise FormatError('%s: no effect data or action list' % e.name)
    e.max_particles = struct.unpack_from('<I', d)[0]
    fl = _find(chs, 5)
    if fl is not None:
        e.flags = struct.unpack_from('<I', fl)[0]

    def need(cid, what):
        b = _find(chs, cid)
        if b is None:
            raise FormatError('%s: flags say %s but there is no chunk 0x%x' % (e.name, what, cid))
        return b
    if e.flags & DF_SPRITE:
        r = _R(need(7, 'sprite'))
        e.shader, e.texture = r.s(), r.s()
    if e.flags & DF_FRAMED:
        e.frame = struct.unpack_from('<4f2if', need(6, 'framed'))
    if e.flags & DF_TIMELIMIT:
        e.time_limit = struct.unpack_from('<f', need(8, 'time limit'))[0]
    if e.flags & DF_COLLISION:
        e.collision = struct.unpack_from('<3f', need(0x21, 'collision'))
    if e.flags & DF_VELOCITY_SCALE:
        e.velocity_scale = struct.unpack_from('<3f', need(0x22, 'velocity scale'))
    if e.flags & DF_ALIGN_TO_PATH:
        b = _find(chs, 0x25)
        if b is not None:
            e.align_rotation = struct.unpack_from('<3f', b)
    ed = _find(chs, 0x24)
    if ed is None:
        raise FormatError('%s: no editor actions (chunk 0x24); only compiled ones, which a loose file cannot hold'
                          % e.name)
    r = _R(ed)
    for _ in range(r.u32()):
        t = r.u32()
        if t not in ACTIONS:
            raise FormatError('%s: unknown action type %d' % (e.name, t))
        ver = r.u32()
        if ver != ACTION_VERSION:
            raise FormatError('%s: action version %d (the game falls back to the compiled list)' % (e.name, ver))
        _, nf, nv, nd, nb, ni = ACTIONS[t]
        a = Action(t, name=r.s(), flags=r.u32())
        a.floats = r.floats(nf)
        a.vectors = [r.floats(3) for _ in range(nv)]
        a.domains = [(r.u32(), [r.floats(3), r.floats(3), r.floats(3)]) for _ in range(nd)]
        a.bools = list(r.take('%dB' % nb)) if nb else []
        a.ints = list(r.take('%di' % ni)) if ni else []
        e.actions.append(a)
    if r.o != len(ed):
        raise FormatError('%s: %d bytes left after the actions (parameter counts differ from this engine)'
                          % (e.name, len(ed) - r.o))
    return e


def read_group(body):
    """CPGDef::Load."""
    chs = chunks(body)
    v = _find(chs, 1)
    if v is None or struct.unpack_from('<H', v)[0] != PGD_VERSION:
        raise FormatError('group version is not %d (the game skips it)' % PGD_VERSION)
    name = _find(chs, 2)
    if name is None:
        raise FormatError('group without a name')
    g = Group(name.split(b'\0', 1)[0].decode('latin1'))
    g.raw = body
    fl = _find(chs, 3)
    if fl is not None:
        g.flags = struct.unpack_from('<I', fl)[0]
    tl = _find(chs, 5)
    g.time_limit = struct.unpack_from('<f', tl)[0] if tl is not None else 0.0
    fixed = g.time_limit > 0.0
    b = _find(chs, 4)
    if b is not None:
        r = _R(b)
        for _ in range(r.u32()):
            ent = [r.s(), r.s(), r.s(), r.s()] + list(r.take('2fI'))
            g.effects.append(ent)
            if not fixed:
                g.time_limit = max(g.time_limit, ent[5])
    return g


class Library:
    def __init__(self):
        self.effects = {}           # name -> Effect (names as stored)
        self.groups = {}
        self.skipped = []           # (kind, index, reason): entries the game drops or a loose file can't hold

    def find(self, name):
        """('pe'|'pg', entry) for a particle name (any slash, any case), or None."""
        k = name.replace('/', '\\').lower()
        e = self._lower('effects').get(k)
        if e:
            return 'pe', e
        g = self._lower('groups').get(k)
        return ('pg', g) if g else None

    def _lower(self, what):
        attr = '_lc_' + what
        if not hasattr(self, attr):
            setattr(self, attr, {n.lower(): v for n, v in getattr(self, what).items()})
        return getattr(self, attr)


def loads(data):
    """CPSLibrary::Load (the particles.xr half)."""
    top = chunks(data)
    v = _find(top, 1)
    if v is None or struct.unpack_from('<H', v)[0] != PS_VERSION:
        raise FormatError('not a particles.xr (version chunk)')
    lib = Library()
    for kind, cid, reader, store in (('effect', 3, read_effect, lib.effects), ('group', 4, read_group, lib.groups)):
        body = _find(top, cid)
        for i, (_, ent) in enumerate(chunks(body) if body is not None else []):
            try:
                x = reader(ent)
            except (FormatError, struct.error, ValueError) as ex:
                lib.skipped.append((kind, i, str(ex)))
                continue
            if x.name in store:     # the engine keeps both; the lookup finds one: report it
                lib.skipped.append((kind, i, '%s: a second entry with this name' % x.name))
                continue
            store[x.name] = x
    return lib


def load(path):
    with open(path, 'rb') as f:
        return loads(f.read())


# ---------------------------------------------------------------- loose files (CInifile)
def _vec(v):
    return ', '.join(fmt_float(x) for x in v)


def _string(s, what):
    if s != s.strip() or any(c in s for c in ';\r\n'):
        raise FormatError('%s %r cannot be written to an ini line as it is' % (what, s))
    return s


def _ini(sections):
    out = []
    for sect in sorted(sections):
        out.append('[%s]' % sect)
        for k in sorted(sections[sect]):
            v = sections[sect][k]
            out.append(('        %-32s =' % k) + (' ' + v if v != '' else ''))
        out.append(' ')
    return ('\n'.join(out) + '\n').encode('latin1')


def effect_ini(e):
    """CPEDef::Save2 (the .pe file)."""
    s = {'_effect': {'version': str(PED_VERSION), 'max_particles': str(e.max_particles), 'flags': str(e.flags),
                     'action_count': str(len(e.actions))}}
    if e.flags & DF_SPRITE:
        s['sprite'] = {'shader': _string(e.shader, 'shader'), 'texture': _string(e.texture, 'texture')}
    if e.flags & DF_FRAMED:
        f = e.frame
        s['frame'] = {'tex_size': _vec(f[0:2]), 'reserved': _vec(f[2:4]), 'dim_x': str(f[4]),
                      'frame_count': str(f[5]), 'speed': fmt_float(f[6])}
    if e.flags & DF_TIMELIMIT:
        s['timelimit'] = {'value': fmt_float(e.time_limit)}
    if e.flags & DF_COLLISION:
        s['collision'] = {'one_minus_friction': fmt_float(e.collision[0]),
                          'collide_resilence': fmt_float(e.collision[1]),
                          'collide_sqr_cutoff': fmt_float(e.collision[2])}
    if e.flags & DF_VELOCITY_SCALE:
        s['velocity_scale'] = {'value': _vec(e.velocity_scale)}
    if e.flags & DF_ALIGN_TO_PATH:
        s['align_to_path'] = {'default_rotation': _vec(e.align_rotation)}
    for i, a in enumerate(e.actions):
        sect = 'action_%04d' % i
        d = {'version': str(ACTION_VERSION), 'action_type': str(a.type), 'action_name': _string(a.name, 'action name'),
             'flags': str(a.flags)}
        for j, v in enumerate(a.floats):
            d['flt_%04d' % j] = fmt_float(v)
        for j, v in enumerate(a.vectors):
            d['vec_%04d' % j] = _vec(v)
        for j, (t, vs) in enumerate(a.domains):
            s['domain_%s_%04d' % (sect, j)] = {'type': str(t), 'v0': _vec(vs[0]), 'v1': _vec(vs[1]),
                                              'v2': _vec(vs[2])}
        for j, v in enumerate(a.bools):
            d['bool_%04d' % j] = 'on' if v else 'off'
        for j, v in enumerate(a.ints):
            d['int_%04d' % j] = str(v)
        s[sect] = d
    return _ini(s)


def group_ini(g):
    """CPGDef::Save2 (the .pg file): a child name only where its flag is set, as the SDK
    writes it (the game uses a child only when its flag is set)."""
    s = {'_group': {'version': str(PGD_VERSION), 'flags': str(g.flags), 'effects_count': str(len(g.effects)),
                    'timelimit': fmt_float(g.time_limit)}}
    for i, (name, play, birth, dead, t0, t1, fl) in enumerate(g.effects):
        s['effect_%04d' % i] = {
            'effect_name': _string(name, 'effect name'),
            'on_play_child': _string(play if fl & FL_ON_PLAY_CHILD else '', 'child'),
            'on_birth_child': _string(birth if fl & FL_ON_BIRTH_CHILD else '', 'child'),
            'on_death_child': _string(dead if fl & FL_ON_DEAD_CHILD else '', 'child'),
            'time0': fmt_float(t0), 'time1': fmt_float(t1), 'flags': str(fl)}
    return _ini(s)


def entry_ini(kind, entry):
    return effect_ini(entry) if kind == 'pe' else group_ini(entry)


def read_ini(data):
    """{section: {key: value}} as CInifile reads a particle file (';' starts a comment)."""
    out, cur = {}, None
    for line in data.decode('latin1').splitlines():
        line = line.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('['):
            cur = out.setdefault(line[1:line.index(']')].strip(), {})
            continue
        if cur is None or '=' not in line:
            continue
        k, v = line.split('=', 1)
        cur[k.strip()] = v.strip()
    return out


def _rf(s):
    return f32(float(s))                       # r_float: atof, then the cast


def _rv(s, n=3):
    v = [_f32_exact(x.strip()) for x in s.split(',')[:n]]   # r_fvector: sscanf '%f'
    if len(v) != n:
        raise FormatError('expected %d numbers: %r' % (n, s))
    return v


def _rb(s):
    return 1 if s.strip().lower() in ('on', 'yes', 'true', '1') else 0


def parse_pe(data, name=''):
    """CPEDef::Load2: a loose .pe file -> Effect."""
    ini = read_ini(data)
    ef = ini['_effect']
    e = Effect(name)
    e.max_particles = int(ef['max_particles'])
    e.flags = int(ef['flags']) & 0xFFFFFFFF
    if e.flags & DF_SPRITE:
        e.shader, e.texture = ini['sprite']['shader'], ini['sprite']['texture']
    if e.flags & DF_FRAMED:
        f = ini['frame']
        e.frame = tuple(_rv(f['tex_size'], 2) + _rv(f['reserved'], 2) + [int(f['dim_x']), int(f['frame_count']),
                                                                          _rf(f['speed'])])
    if e.flags & DF_TIMELIMIT:
        e.time_limit = _rf(ini['timelimit']['value'])
    if e.flags & DF_COLLISION:
        c = ini['collision']
        e.collision = (_rf(c['one_minus_friction']), _rf(c['collide_resilence']), _rf(c['collide_sqr_cutoff']))
    if e.flags & DF_VELOCITY_SCALE:
        e.velocity_scale = tuple(_rv(ini['velocity_scale']['value']))
    if e.flags & DF_ALIGN_TO_PATH:
        e.align_rotation = tuple(_rv(ini['align_to_path']['default_rotation']))
    for i in range(int(ef['action_count'])):
        sect = 'action_%04d' % i
        d = ini[sect]
        t = int(d['action_type'])
        _, nf, nv, nd, nb, ni = ACTIONS[t]
        ver = int(d.get('version', ACTION_VERSION))
        a = Action(t, name=d.get('action_name', ''), flags=int(d['flags']) & 0xFFFFFFFF, version=ver)
        a.floats = [_rf(d['flt_%04d' % j]) if ('flt_%04d' % j) in d or ver != 0 else 0.0 for j in range(nf)]
        a.vectors = [_rv(d['vec_%04d' % j]) for j in range(nv)]
        a.domains = []
        for j in range(nd):
            dd = ini['domain_%s_%04d' % (sect, j)]
            a.domains.append((int(dd['type']), [_rv(dd['v0']), _rv(dd['v1']), _rv(dd['v2'])]))
        a.bools = [_rb(d['bool_%04d' % j]) for j in range(nb)]
        a.ints = [int(d['int_%04d' % j]) for j in range(ni)]
        e.actions.append(a)
    return e


def parse_pg(data, name=''):
    """CPGDef::Load2: a loose .pg file -> Group."""
    ini = read_ini(data)
    gr = ini['_group']
    g = Group(name)
    g.flags = int(gr['flags']) & 0xFFFFFFFF
    for i in range(int(gr['effects_count'])):
        d = ini['effect_%04d' % i]
        g.effects.append([d.get('effect_name', ''), d.get('on_play_child', ''), d.get('on_birth_child', ''),
                          d.get('on_death_child', ''), _rf(d['time0']), _rf(d['time1']),
                          int(d['flags']) & 0xFFFFFFFF])
    g.time_limit = _rf(gr['timelimit'])
    return g


def parse(kind, data, name=''):
    return parse_pe(data, name) if kind == 'pe' else parse_pg(data, name)


# ---------------------------------------------------------------- what the game sees
def _fl(x, y, tol):
    return _bits(x) == _bits(y) if not tol else abs(x - y) <= tol * max(1.0, abs(x), abs(y))


def _seq(a, b, tol):
    return len(a) == len(b) and all(_fl(x, y, tol) for x, y in zip(a, b))


def same(a, b, tol=0.0):
    """True when two Effects (or two Groups) play the same in the game. tol=0 is bit for bit;
    the SDK's six-decimal files need tol (relative, e.g. 2e-6) against particles.xr."""
    if isinstance(a, Group):
        if a.flags != b.flags or not _fl(a.time_limit, b.time_limit, tol) or len(a.effects) != len(b.effects):
            return False
        for x, y in zip(a.effects, b.effects):
            fl = x[6]
            if fl != y[6] or x[0].lower() != y[0].lower() or not _seq(x[4:6], y[4:6], tol):
                return False
            for i, bit in ((1, FL_ON_PLAY_CHILD), (2, FL_ON_BIRTH_CHILD), (3, FL_ON_DEAD_CHILD)):
                if fl & bit and x[i].lower() != y[i].lower():
                    return False
        return True
    if (a.max_particles, a.flags, len(a.actions)) != (b.max_particles, b.flags, len(b.actions)):
        return False
    if a.flags & DF_SPRITE and (a.shader.lower().replace(' ', ''), a.texture.lower().replace(' ', '')) != (
            b.shader.lower().replace(' ', ''), b.texture.lower().replace(' ', '')):
        return False
    if a.flags & DF_FRAMED and not (_seq(a.frame[0:4] + a.frame[6:7], b.frame[0:4] + b.frame[6:7], tol)
                                    and a.frame[4:6] == b.frame[4:6]):
        return False
    for bit, x, y in ((DF_TIMELIMIT, [a.time_limit], [b.time_limit]), (DF_COLLISION, a.collision, b.collision),
                      (DF_VELOCITY_SCALE, a.velocity_scale, b.velocity_scale),
                      (DF_ALIGN_TO_PATH, a.align_rotation, b.align_rotation)):
        if a.flags & bit and not _seq(list(x), list(y), tol):
            return False
    for x, y in zip(a.actions, b.actions):
        if (x.type, x.flags, x.ints) != (y.type, y.flags, y.ints) or [bool(v) for v in x.bools] != [
                bool(v) for v in y.bools]:
            return False
        if not _seq(x.floats, y.floats, tol) or not all(_seq(p, q, tol) for p, q in zip(x.vectors, y.vectors)):
            return False
        for (t1, v1), (t2, v2) in zip(x.domains, y.domains):
            if t1 != t2 or not all(_seq(p, q, tol) for p, q in zip(v1, v2)):
                return False
    return True


def texture_names(e):
    """The textures an effect draws (its sprite's comma-separated list), lower case, as the
    engine looks them up (Texture.cpp fix_texture_name drops .tga, .dds, .bmp and .ogm)."""
    if not e.flags & DF_SPRITE:
        return []
    out = []
    for t in e.texture.split(','):
        t = t.strip().lower().replace('/', '\\')
        if t.endswith(('.tga', '.dds', '.bmp', '.ogm')):
            t = t[:-4]
        if t:
            out.append(t)
    return out


def children(g):
    """Every effect or group a group plays (flags as the game reads them)."""
    out = []
    for name, play, birth, dead, _, _, fl in g.effects:
        out.append(name)
        for v, bit in ((play, FL_ON_PLAY_CHILD), (birth, FL_ON_BIRTH_CHILD), (dead, FL_ON_DEAD_CHILD)):
            if fl & bit and v:
                out.append(v)
    return [n for n in out if n]


def export(lib, dest, names, overwrite=False):
    """Write the named entries (effects or groups) as loose files under dest (a
    gamedata/particles folder). Returns [(name, kind, path)]."""
    out = []
    for n in names:
        hit = lib.find(n)
        if not hit:
            raise KeyError(n)
        kind, ent = hit
        p = os.path.join(dest, *ent.name.lower().split('\\')) + '.' + kind
        if os.path.exists(p) and not overwrite:
            raise FileExistsError(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + '.part', 'wb') as f:
            f.write(entry_ini(kind, ent))
        os.replace(p + '.part', p)
        out.append((ent.name, kind, p))
    return out


# ---------------------------------------------------------------- binary again (the round trip)
def _w_chunk(cid, body):
    return struct.pack('<II', cid, len(body)) + body


def effect_edata(e):
    """Chunk 0x24's body as CPEDef::Save writes it."""
    b = [struct.pack('<I', len(e.actions))]
    for a in e.actions:
        b.append(struct.pack('<II', a.type, a.version) + a.name.encode('latin1') + b'\0' + struct.pack('<I', a.flags))
        b.append(struct.pack('<%df' % len(a.floats), *a.floats))
        for v in a.vectors:
            b.append(struct.pack('<3f', *v))
        for t, vs in a.domains:
            b.append(struct.pack('<I9f', t, *(vs[0] + vs[1] + vs[2])))
        b.append(struct.pack('<%dB' % len(a.bools), *[min(255, max(0, v)) for v in a.bools]))
        b.append(struct.pack('<%di' % len(a.ints), *a.ints))
    return b''.join(b)


def round_trip(kind, ent):
    """None when the entry's loose file reads back exactly as particles.xr has it, else why not."""
    data = entry_ini(kind, ent)
    back = parse(kind, data, ent.name)
    if kind == 'pg':
        return None if same(ent, back) else 'group differs after the round trip'
    if not same(ent, back):
        return 'effect differs after the round trip'
    if ent.raw is not None:
        orig = _find(chunks(ent.raw), 0x24)
        if effect_edata(ent) != orig:
            return 'chunk 0x24 is not reproduced from what was read'
        if effect_edata(back) != orig:
            return 'actions differ after the round trip (a bool that is neither 0 nor 1?)'
    return None


# ---------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='particles_xr', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('list')
    p.add_argument('xr')
    p.add_argument('--groups', action='store_true')
    p.add_argument('--prefix', action='append', default=[])
    p = sub.add_parser('export')
    p.add_argument('xr')
    p.add_argument('dest')
    p.add_argument('--prefix', action='append', default=[])
    p.add_argument('--name', action='append', default=[])
    p.add_argument('--overwrite', action='store_true')
    p = sub.add_parser('check')
    p.add_argument('xr', nargs='+')
    o = ap.parse_args(argv)

    def pick(lib, prefixes, groups=True):
        pre = tuple(x.replace('/', '\\').lower() for x in prefixes)
        names = list(lib.effects) + (list(lib.groups) if groups else [])
        return sorted(n for n in names if not pre or n.lower().startswith(pre))

    if o.cmd == 'list':
        lib = load(o.xr)
        for n in pick(lib, o.prefix, False):
            e = lib.effects[n]
            print('pe\t%s\t%s\t%s' % (n, e.shader, e.texture))
        if o.groups:
            for n in sorted(x for x in lib.groups if not o.prefix or x.lower().startswith(
                    tuple(p.replace('/', '\\').lower() for p in o.prefix))):
                print('pg\t%s\t%s' % (n, ', '.join(children(lib.groups[n]))))
        return 0
    if o.cmd == 'export':
        lib = load(o.xr)
        names = pick(lib, o.prefix) if o.prefix else []
        names += o.name
        if not names:
            ap.error('export: give --prefix or --name')
        done = export(lib, o.dest, names, o.overwrite)
        print('wrote %d files under %s' % (len(done), o.dest))
        return 0
    bad = 0
    for path in o.xr:
        lib = load(path)
        fails = [(n, round_trip('pe', e)) for n, e in lib.effects.items()]
        fails += [(n, round_trip('pg', g)) for n, g in lib.groups.items()]
        fails = [f for f in fails if f[1]]
        print('%s: %d effects, %d groups; round trip: %s; skipped: %d' % (
            path, len(lib.effects), len(lib.groups), 'exact' if not fails else '%d differ' % len(fails),
            len(lib.skipped)))
        for n, why in fails[:20]:
            print('   %s: %s' % (n, why))
        for k, i, why in lib.skipped[:20]:
            print('   skipped %s #%d: %s' % (k, i, why))
        bad += len(fails)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
