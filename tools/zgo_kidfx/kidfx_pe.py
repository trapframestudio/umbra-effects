#!/usr/bin/env python3
"""
kidfx: kid mode for particles already on screen.

Gory particle effects (blood, flesh, gore) are pointed at Umbra Effects' copies of the
stock particle shaders (zgo\\particle_blend, _add, _aadd, _set). Those draw
exactly like the stock ones, except that their pixel shader discards every
pixel while the shader bus lane zgo_view says so (x = kid mode on, w = 1 when
the experimental "hide particles on screen" option is on). Only the
`shader = ...` line of a .pe file is ever changed.

    python3 tools/zgo_kidfx/kidfx_pe.py status        what is pointed where; exit 1 if inconsistent
    python3 tools/zgo_kidfx/kidfx_pe.py list [--gore|--clean|--carrier|--unsure]
    python3 tools/zgo_kidfx/kidfx_pe.py apply         gory effects -> zgo\\particle_*, refresh the snapshot
    python3 tools/zgo_kidfx/kidfx_pe.py revert        escape hatch: every zgo\\particle_* line back to stock
    python3 tools/zgo_kidfx/kidfx_pe.py shaders [--write] [--legacy]   rebuild the zgo_particle_* shaders
                                                     from this mod list's particle.ps / shaders.xr (a per-modlist
                                                     bake); --legacy adds the r1\\ / r2\\ fallbacks the DX8 / DX9
                                                     renderers need to start at all once effects use zgo\\particle_*
    python3 tools/zgo_kidfx/kidfx_pe.py copies [--write|--remove]   copies of gory effects the game plays
                                                     from other mods (identical except the shader line)
    python3 tools/zgo_kidfx/kidfx_pe.py bake          shaders --write --legacy, copies --write, apply

Add --json for machine-readable output (the setup GUI). `status`, `list`,
`apply` and `revert` need only this folder; `shaders`, `copies` and `bake`
read the game and MO2 (never write there).

Importable: kidfx_pe.scan(), .apply(), .revert(), .status(), .gen_shaders(),
.copies(), .bake() return report dicts; nothing prints unless run as a script.
"""
import hashlib
import json
import os
import re
import struct
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
MOD_ROOT = os.path.dirname(os.path.dirname(HERE))
PART = os.path.join(MOD_ROOT, 'gamedata', 'particles')
R3 = os.path.join(MOD_ROOT, 'gamedata', 'shaders', 'r3')
SNAPSHOT = os.path.join(HERE, 'kidfx_snapshot.txt')
COPIES = os.path.join(HERE, 'kidfx_copies.json')

# stock C++ particle blender -> ZGO's Lua copy (and back: the map is one to one)
SHADER_MAP = {
    'particles\\blend': 'zgo\\particle_blend',
    'particles\\add': 'zgo\\particle_add',
    'particles\\alpha_add': 'zgo\\particle_aadd',
    'particles\\set': 'zgo\\particle_set',
}
REVERSE = {v: k for k, v in SHADER_MAP.items()}

# ---------------------------------------------------------------- classification
# A name (file, then folder) decides first; the texture only when the name
# says nothing. Anything without a marker stays visible ("clean"): missing a
# gory effect in kid mode is the safe mistake, hiding dust or sparks is not.
GORE_WORDS = ('blood', 'flesh', 'gore', 'brain', 'skull', 'skin', 'hair', 'gush', 'splurt', 'wound', 'guts',
              'giblet', 'meat', 'bone', 'dismember', 'backsplash', 'body_tear', 'krovisha', 'bleed', 'exit')
CLEAN_WORDS = ('spark', 'armor', 'armour', 'glass', 'cloth', 'dust', 'smoke', 'concrete', 'brick', 'metal', 'dirt',
               'wood', 'stone', 'stucco', 'chips', 'powder', 'chem', 'leak', 'water', 'rain', 'pilot', 'linger',
               'distort', 'plaster', 'earth', 'grit', 'crater', 'breach', 'splinter', 'clods', 'fire', 'steam',
               'puff_grey', 'tracer')
TEXTURE_GORE = ('blood', 'flesh', 'skin', 'zgo\\fx_streak', 'gore')
# textures that draw nothing: an effect with one only spawns child effects
CARRIER_TEXTURES = ('srbd\\srbd-finger-tracer',)
# decisions the rules above can't make, with the reason (path under particles/)
_PILOT = ('gore', 'additive glow tinted blood red (0.45, 0, 0), played by the flesh-hit groups '
                  'srbd\\srbd_hit_flesh_02a and srbd\\headshot\\srbd_head_dust: reads as a blood puff')
OVERRIDES = {
    'srbd/effects/hfx/smoke_point_pilot.pe': _PILOT,
    'srbd/effects/misc/srbd_smoke_point_pilot_omni.pe': _PILOT,
}
# gory effects the game plays from other mods (material pairs, anomalies):
# copies of their gory .pe go into ZGO with only the shader line changed
COPY_ROOTS = (
    ('hit_fx\\hit_knife_flesh_00', 'material pair: knife on flesh (gamemtl.xr)'),
    ('anomaly2\\body_tear_00', 'anomalies tearing a body (configs/zones/zone_mine_*.ltx)'),
    ('anomaly2\\body_tear_01', 'anomalies tearing a body (configs/zones/zone_mine_*.ltx)'),
)

SECTION_RE = re.compile(rb'^[ \t]*\[([^\]\r\n]*)\][^\r\n]*?\r?$', re.M)
KEY_RE = re.compile(rb'^([ \t]*%s[ \t]*=[ \t]*)([^\r\n]*?)([ \t]*)(?=\r?$)', re.M | re.I)
CHILD_RE = re.compile(rb'(?im)^[ \t]*(?:effect_name|on_\w+_child)[ \t]*=[ \t]*([^\s;]+)')


def _section(data, name):
    """(start, end) byte span of [name]'s body, or None."""
    for m in SECTION_RE.finditer(data):
        if m.group(1).strip().lower() == name.encode():
            nxt = SECTION_RE.search(data, m.end())
            return m.end(), (nxt.start() if nxt else len(data))
    return None


def _key(data, section, key):
    """(value, span of the value) of key in [section], or (None, None)."""
    sp = _section(data, section)
    if not sp:
        return None, None
    rx = re.compile(KEY_RE.pattern.replace(b'%s', re.escape(key.encode())), re.M | re.I)
    m = rx.search(data, sp[0], sp[1])
    if not m:
        return None, None
    return m.group(2).decode('latin1'), m.span(2)


def read_sprite(data):
    shader, sspan = _key(data, 'sprite', 'shader')
    texture, _ = _key(data, 'sprite', 'texture')
    return shader, sspan, texture


def set_shader(data, value):
    """data with [sprite] shader = value; nothing else changes."""
    cur, span = read_sprite(data)[:2]
    if span is None:
        raise ValueError('no [sprite] shader line')
    return data[:span[0]] + value.encode('latin1') + data[span[1]:]


def normalized(data):
    """The file as it would be with the stock shader line (what the snapshot hashes)."""
    cur = read_sprite(data)[0]
    if cur is not None and cur.lower() in REVERSE:
        return set_shader(data, REVERSE[cur.lower()])
    return data


def _words(s, words):
    s = s.lower()
    return [w for w in words if w in s]


def blood_red(color):
    """Red with neither fire's yellow nor a pink cast: green and blue both well under red,
    and the hue within 10 degrees of pure red. Blood (0.45, 0, 0), (0.27, 0.15, 0.15) is;
    explosion fire (1, 0.49, 0.2) and muzzle sparks (1, 0.62, 0.34) are orange (hue 20-25)."""
    if not color:
        return False
    r, g, b = color[:3]
    lo = min(g, b)
    if r < 0.1 or r < 1.6 * max(g, b):
        return False
    return abs(g - b) <= (r - lo) / 6.0         # |hue| <= 10 degrees


def classify(rel, shader, texture, color=None):
    """('gore'|'clean'|'carrier', reason) for a .pe at particles/<rel>."""
    rel = rel.replace('\\', '/').lower()
    if rel in OVERRIDES:
        return OVERRIDES[rel]
    tex = (texture or '').lower().replace('/', '\\')
    if any(tex == c for c in CARRIER_TEXTURES):
        return 'carrier', 'texture %s is one transparent texel: draws nothing, only spawns its child effects' % tex
    name = rel.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    folder = rel.rsplit('/', 1)[0] if '/' in rel else ''
    for where, s in (('name', name), ('folder', folder)):
        g = _words(s, GORE_WORDS)
        if g:
            return 'gore', '%s says %s' % (where, g[0])
        c = _words(s, CLEAN_WORDS)
        if c:
            return 'clean', '%s says %s' % (where, c[0])
    g = _words(tex, TEXTURE_GORE)
    if g:
        return 'gore', 'texture %s' % tex
    if blood_red(color):
        return 'gore', 'no marker in name or texture %s, but it fades to blood red %s' % (
            tex, '(%.2f, %.2f, %.2f)' % tuple(color))
    return 'clean', 'no gore marker in name, folder or texture %s (left visible)' % tex


TARGETCOLOR_RE = re.compile(rb'(?ims)^[ \t]*action_name[ \t]*=[ \t]*targetcolor\w*\s.*?^[ \t]*vec_0000[ \t]*=[ \t]*'
                            rb'([-\d.]+)[ \t]*,[ \t]*([-\d.]+)[ \t]*,[ \t]*([-\d.]+)')


def target_color(data):
    """The colour the first targetcolor action fades particles to, or None."""
    m = TARGETCOLOR_RE.search(data)
    if not m:
        return None
    try:
        return [float(x) for x in m.groups()]
    except ValueError:
        return None


class Effect:
    def __init__(self, rel, data):
        self.rel = rel                  # 'srbd/effects/burst/x.pe' (under particles/)
        self.kind = rel.rsplit('.', 1)[-1].lower()
        self.data = data
        self.shader, self.span, self.texture = read_sprite(data) if self.kind == 'pe' else (None, None, None)
        cur = (self.shader or '').lower()
        self.stock = REVERSE.get(cur, self.shader)
        if self.kind == 'pg':
            self.cls, self.reason = 'group', 'particle group: no shader of its own'
        elif self.shader is None:
            self.cls, self.reason = 'clean', 'no [sprite] shader line'
        else:
            self.cls, self.reason = classify(rel, self.stock, self.texture, target_color(data))
        self.target = self.stock
        self.problem = None
        if self.cls == 'gore':
            t = SHADER_MAP.get((self.stock or '').lower())
            if t:
                self.target = t
            else:
                self.problem = 'gory, but its shader %s has no kid-mode copy: stays visible in kid mode' % self.stock
        self.sha1 = hashlib.sha1(normalized(data)).hexdigest() if self.kind == 'pe' else hashlib.sha1(
            data).hexdigest()

    @property
    def applied(self):
        return (self.shader or '').lower() in REVERSE


def scan(root=None):
    root = root or PART
    out = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            if fn.lower().endswith(('.pe', '.pg')):
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root).replace(os.sep, '/')
                with open(p, 'rb') as f:
                    out.append(Effect(rel, f.read()))
    return out


def _load_copies():
    try:
        with open(COPIES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'copies': {}}


def write_snapshot(effects):
    copies = _load_copies().get('copies', {})
    lines = ['# kidfx snapshot: every particle file in gamedata/particles, its class and the SHA-1 of its',
             '# bytes with the stock shader line (zgo\\particle_* read as particles\\*). tests/zgo_test_kidfx.lua',
             '# checks the files against it. Refresh with: python3 tools/zgo_kidfx/kidfx_pe.py apply',
             '# path\tclass\tstock shader\tsha1\treason']
    for e in sorted(effects, key=lambda e: e.rel.lower()):
        reason = e.reason
        if e.rel.lower() in copies:
            reason += '; copy of %s' % copies[e.rel.lower()]['source']
        if e.problem:
            reason += '; ' + e.problem
        lines.append('\t'.join([e.rel, e.cls, e.stock or '-', e.sha1, reason]))
    data = ('\n'.join(lines) + '\n').encode('utf-8')
    try:
        with open(SNAPSHOT, 'rb') as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    with open(SNAPSHOT + '.part', 'wb') as f:
        f.write(data)
    os.replace(SNAPSHOT + '.part', SNAPSHOT)
    return True


def _write(rel, data, root=None):
    p = os.path.join(root or PART, *rel.split('/'))
    with open(p + '.kidfx-part', 'wb') as f:
        f.write(data)
    os.replace(p + '.kidfx-part', p)


def _set_all(to_zgo, root=None, dry_run=False, snapshot=True):
    effects = scan(root)
    changed, problems = [], []
    for e in effects:
        if e.kind != 'pe' or e.shader is None:
            continue
        want = e.target if to_zgo else e.stock
        if e.problem and to_zgo:
            problems.append({'file': e.rel, 'problem': e.problem})
        if want and want != e.shader:
            new = set_shader(e.data, want)
            assert normalized(new) == normalized(e.data), 'only the shader line may change: ' + e.rel
            changed.append({'file': e.rel, 'from': e.shader, 'to': want})
            if not dry_run:
                _write(e.rel, new, root)
    if not dry_run and snapshot and (root is None or root == PART):
        write_snapshot(scan(root))
    return {'changed': changed, 'problems': problems, 'dry_run': dry_run}


def apply(root=None, dry_run=False):
    """Point every gory effect at zgo\\particle_* (and only those)."""
    r = _set_all(True, root, dry_run)
    r['action'] = 'apply'
    return r


def revert(root=None, dry_run=False):
    """The escape hatch: every zgo\\particle_* shader line back to the stock one."""
    r = _set_all(False, root, dry_run, snapshot=False)
    r['action'] = 'revert'
    return r


def status(root=None):
    effects = scan(root)
    counts = {}
    wrong, problems = [], []
    pe = [e for e in effects if e.kind == 'pe' and e.shader is not None]
    n_applied = sum(1 for e in pe if e.applied)
    state = 'applied' if n_applied else 'reverted'
    for e in effects:
        counts[e.cls] = counts.get(e.cls, 0) + 1
        if e.problem:
            problems.append({'file': e.rel, 'problem': e.problem})
    for e in pe:
        want = e.target if state == 'applied' else e.stock
        if e.shader != want:
            wrong.append({'file': e.rel, 'class': e.cls, 'shader': e.shader, 'expected': want})
    gory = [e for e in pe if e.cls == 'gore' and not e.problem]
    if state == 'applied' and len(wrong) > len(gory) // 2:
        state = 'partial'
    shaders = {}
    for e in pe:
        shaders[e.shader] = shaders.get(e.shader, 0) + 1
    return {'state': state, 'files': len(effects), 'counts': counts, 'shaders': shaders, 'inconsistent': wrong,
            'problems': problems, 'snapshot_current': _snapshot_current(effects, root)}


def _snapshot_current(effects, root):
    if root not in (None, PART):
        return None
    try:
        with open(SNAPSHOT, encoding='utf-8') as f:
            rows = [l.rstrip('\n').split('\t') for l in f if l.strip() and not l.startswith('#')]
    except OSError:
        return False
    snap = {r[0]: (r[1], r[3]) for r in rows}
    now = {e.rel: (e.cls, e.sha1) for e in effects}
    return snap == now


# ---------------------------------------------------------------- shaders (per-modlist bake)
KID_UNIFORM = ('uniform float4 bus_zgo_view;\t// ZGO kid mode (shader bus): x = 1 kid mode, '
               'w = 1 hide particles on screen')
KID_TEST = '\tif (bus_zgo_view.x > 0.5 && abs(bus_zgo_view.w - 1.0) < 0.001) discard;\t// ZGO kid mode'
PS_SOURCES = (('zgo_particle_kid.ps', 'particle.ps'), ('zgo_particle_kid_deffer.ps', 'deffer_particle.ps'))
S_FILES = (('zgo_particle_blend.s', 'particles\\blend'), ('zgo_particle_add.s', 'particles\\add'),
           ('zgo_particle_aadd.s', 'particles\\alpha_add'), ('zgo_particle_set.s', 'particles\\set'))
BLEND_LUA = {'zero': 'blend.zero', 'one': 'blend.one', 'srcalpha': 'blend.srcalpha',
             'invsrcalpha': 'blend.invsrcalpha', 'destcolor': 'blend.destcolor', 'srccolor': 'blend.srccolor'}


def kid_ps(src, stock_name, provider, sha1):
    """The stock pixel shader plus the kid-mode uniform and discard."""
    text = src.decode('latin1')
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)
    # the uniform goes after the last top-level #include (before any #if around main)
    inc = [i for i, l in enumerate(lines) if re.match(r'\s*#\s*include\b', l)]
    if not inc:
        raise ValueError('%s: no #include to put the uniform after' % stock_name)
    lines.insert(inc[-1] + 1, KID_UNIFORM)
    text = nl.join(lines)
    m = re.search(r'\bmain\s*\(', text)
    if not m:
        raise ValueError('%s: no main()' % stock_name)
    b = text.index('{', m.end())
    text = text[:b + 1] + nl + KID_TEST + text[b + 1:]
    head = nl.join([
        '// Umbra Gore & Effects, kid mode for particles: r3\\%s from %s (sha1 %s)' % (stock_name, provider, sha1),
        '// with two lines added, both marked "ZGO kid mode": the shader bus uniform bus_zgo_view and a',
        '// discard while x (kid mode) is on and w = 1 (the experimental option is on). With the lane at 0',
        '// or never set the shader does exactly what the stock one does.',
        '// Generated by tools/zgo_kidfx/kidfx_pe.py shaders --write (rebuild it when another mod',
        '// changes %s); compiled by dev/shadercheck/check.sh.' % stock_name,
        '// shadercheck-baseline: %s' % stock_name, ''])
    return (head + nl + text).encode('latin1')


def _pass_lua(fn, pass_, prio, strict, ps_map):
    vs, ps = pass_['vs'], ps_map.get(pass_['ps'], pass_['ps'])
    out = ['function %s(shader, t_base, t_second, t_detail)' % fn,
           '\tshader:begin("%s", "%s")' % (vs, ps),
           '\t\t:sorting(%d, %s)' % (prio, 'true' if strict else 'false'),
           '\t\t:fog(false)',
           '\t\t:zb(true, %s)' % ('true' if pass_['zwrite'] else 'false'),
           '\t\t:blend(%s, %s, %s)' % ('true' if pass_['ablend'] else 'false', BLEND_LUA[pass_['src']],
                                       BLEND_LUA[pass_['dst']]),
           '\t\t:aref(%s, %d)' % ('true' if pass_['atest'] else 'false', pass_['aref'])]
    if pass_.get('colorwrite'):
        out.append('\t\t:color_write_enable(%s)' % ', '.join('true' if c else 'false' for c in pass_['colorwrite']))
    out += ['\tshader:dx10texture("s_base", t_base)',
            '\tshader:dx10sampler("smp_base")%s' % (':clamp()' if pass_['clamp'] else ''),
            '\tshader:dx10texture("s_position", "$user$position")',
            '\tshader:dx10sampler("smp_nofilter")',
            'end']
    return out


def kid_s(blender_name, params, xr_provider):
    """A Lua .s with the C++ particle blender's R4 elements (Blender_Particle.cpp)."""
    import sc_blenders
    mode = sc_blenders.PARTICLE_MODES[params['blend']]
    shadow = sc_blenders.PARTICLE_SHADOW[params['blend']]
    ps_map = {'particle': 'zgo_particle_kid', 'deffer_particle': 'zgo_particle_kid_deffer'}
    normal = dict(mode, clamp=params['clamp'])
    head = ['-- Umbra Gore & Effects, kid mode for particles: %s for gory effects.' % blender_name,
            '-- The C++ particle blender\'s R4 elements (xray-monolith Blender_Particle.cpp) with this',
            '-- mod list\'s shaders.xr settings for %s (from %s): priority %d, strict sorting %s,' % (
                blender_name, xr_provider, params['priority'], 'on' if params['strict'] else 'off'),
            '-- blending %s, texture clamp %s. Only the pixel shader differs: zgo_particle_kid*.ps is the' % (
                mode['name'], 'on' if params['clamp'] else 'off'),
            '-- stock one plus a discard while the shader bus lane zgo_view hides gore.',
            '-- Generated by tools/zgo_kidfx/kidfx_pe.py shaders --write; checked by dev/shadercheck/check.sh.',
            '-- shadercheck-parity: %s' % blender_name, '']
    body = _pass_lua('normal', normal, params['priority'], params['strict'], ps_map)
    if params['priority'] // 2 != 1:
        # priority 0/1 particles are drawn into the shadow map with element 2 (l_point in Lua);
        # priority 2/3 never are (dsgraph pmask), so the stock element 2 is dead there
        sh = dict(shadow, clamp=params['clamp'])
        body += [''] + _pass_lua('l_point', sh, params['priority'], params['strict'], ps_map)
    return ('\n'.join(head + body) + '\n').encode('latin1')


LEGACY = ('r1', 'r2')          # the DX8 (R1) and DX9 (R2) renderers' shader folders


def _pass_lua_dx9(fn, pass_, prio, strict, soft):
    out = ['function %s(shader, t_base, t_second, t_detail)' % fn,
           '\tshader:begin("%s", "%s")' % (pass_['vs'], pass_['ps']),
           '\t\t:sorting(%d, %s)' % (prio, 'true' if strict else 'false'),
           '\t\t:fog(false)',
           '\t\t:zb(true, %s)' % ('true' if pass_['zwrite'] else 'false'),
           '\t\t:blend(%s, %s, %s)' % ('true' if pass_['ablend'] else 'false', BLEND_LUA[pass_['src']],
                                       BLEND_LUA[pass_['dst']]),
           '\t\t:aref(%s, %d)' % ('true' if pass_['atest'] else 'false', pass_['aref']),
           '\tshader:sampler("s_base"):texture(t_base)%s' % (':clamp()' if pass_['clamp'] else '')]
    if soft:
        out.append('\tshader:sampler("s_position"):texture("$user$position")')
    out.append('end')
    return out


def legacy_s(renderer, blender_name, params, xr_provider):
    """r1\\ / r2\\ zgo_particle_*.s: the stock particle blender on DX8 / DX9, nothing more.

    The DX8 and DX9 renderers only read their own shader folder. Without these a .pe naming
    zgo\\particle_* finds neither a Lua shader nor a C++ blender there, and the DX9 build's
    CResourceManager::_GetBlender calls Debug.fatal ("Shader ... not found in library") while
    the particle library loads at start-up. Kid mode does not hide particles on those renderers.
    """
    import sc_blenders
    mode = sc_blenders.PARTICLE_MODES[params['blend']]
    shadow = dict(sc_blenders.PARTICLE_SHADOW[params['blend']], clamp=params['clamp'])
    shadow.pop('colorwrite', None)         # R1 / R2 never turn colour writes off here
    prio, strict = params['priority'], params['strict']
    head = ['-- Umbra Gore & Effects, kid mode for particles: %s on the %s renderer.' % (
                blender_name, {'r1': 'DX8 (R1)', 'r2': 'DX9 (R2)'}[renderer]),
            '-- Exactly the C++ particle blender (xray-monolith Blender_Particle.cpp, %s branch) with this' % (
                'R1' if renderer == 'r1' else 'R2'),
            '-- mod list\'s shaders.xr settings for %s (from %s): priority %d, strict sorting %s,' % (
                blender_name, xr_provider, prio, 'on' if strict else 'off'),
            '-- blending %s, texture clamp %s. It only exists so that effects pointed at zgo\\particle_*' % (
                mode['name'], 'on' if params['clamp'] else 'off'),
            '-- load on this renderer (a missing shader name is fatal there); kid mode hides nothing here.',
            '-- Generated by tools/zgo_kidfx/kidfx_pe.py shaders --write; tests/zgo_test_kidfx.lua checks it.',
            '']
    if renderer == 'r1':
        # R1: Compile() ignores the element, so every element gets the same pass
        p = dict(mode, clamp=params['clamp'])
        if params['blend'] == 0:
            p.update(vs='particle', ps='particle', atest=True, aref=200)
        body = []
        for fn in ('normal', 'l_point', 'l_spot', 'l_special'):
            body += _pass_lua_dx9(fn, p, prio, strict, False) + ['']
        body.pop()
    else:
        body = _pass_lua_dx9('normal', dict(mode, clamp=params['clamp']), prio, strict, True)
        if prio // 2 != 1:
            body += [''] + _pass_lua_dx9('l_point', shadow, prio, strict, True)
    return ('\n'.join(head + body) + '\n').encode('latin1')


def gen_shaders(write=False, paths=None, legacy=False, shaders_root=None):
    """The zgo_particle_* files this mod list needs, compared with the ones on disk.
    legacy: also the r1\\ / r2\\ fallbacks (DX8 / DX9 renderers, see legacy_s)."""
    import sc_tree
    import sc_blenders
    paths = paths or sc_tree.Paths()
    bad = paths.check()
    if bad:
        raise RuntimeError('cannot find the game / MO2: ' + '; '.join(bad))
    res = sc_tree.Resolved(paths, ('shaders/r3/particle.ps', 'shaders/r3/deffer_particle.ps', 'shaders.xr'),
                           include_zgo=False)
    want = {}
    sroot = shaders_root or os.path.dirname(R3)
    def winner(rel):
        w = res.winner(rel)
        if not w:
            raise RuntimeError('the game\'s %s was not found (neither in the game\'s archives nor in a mod)' % rel)
        return w
    for out, stock in PS_SOURCES:
        L, src = winner('shaders/r3/' + stock)
        data = L.read(src)
        want[out] = kid_ps(data, stock, L.label, hashlib.sha1(data).hexdigest())
    L, src = winner('shaders.xr')
    bl = sc_blenders.blenders(L.read(src))
    want = {'r3/' + k: v for k, v in want.items()}
    for out, name in S_FILES:
        b = bl.get(name)
        if not b or b['cls'].strip() != 'PARTICLE':
            raise RuntimeError('%s is not a C++ particle blender in this shaders.xr' % name)
        want['r3/' + out] = kid_s(name, sc_blenders.particle_params(b), L.label)
        if legacy:
            for r in LEGACY:
                want[r + '/' + out] = legacy_s(r, name, sc_blenders.particle_params(b), L.label)
    report = {'files': []}
    for name, data in sorted(want.items()):
        p = os.path.join(sroot, *name.split('/'))
        try:
            cur = open(p, 'rb').read()
        except OSError:
            cur = None
        st = 'same' if cur == data else ('missing' if cur is None else 'differs')
        if write and st != 'same':
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p + '.part', 'wb') as f:
                f.write(data)
            os.replace(p + '.part', p)
            st += ', written'
        report['files'].append({'file': 'gamedata/shaders/' + name, 'status': st})
    report['ok'] = all(f['status'].startswith('same') or f['status'].endswith('written') for f in report['files'])
    return report


# ---------------------------------------------------------------- copies (per-modlist bake)
class _XrEntry:
    """A particles.xr entry as a source of a loose file (particles_xr writes it out)."""

    def __init__(self, label, data):
        self.label, self.data = label, data

    def read(self, _src):
        return self.data


def copies(write=False, remove=False, paths=None):
    """Gory effects the game plays from other mods, copied into Umbra Effects with only
    the shader line changed; the source of each goes into kidfx_copies.json. An effect no
    mod ships as a loose file comes from the winning particles.xr (particles_xr writes it
    out exactly), as the game itself would take it."""
    man = _load_copies()
    have = man.setdefault('copies', {})
    report = {'copies': [], 'removed': []}
    if remove:
        for rel, ent in sorted(have.items()):
            p = os.path.join(PART, *rel.split('/'))
            if os.path.isfile(p):
                data = open(p, 'rb').read()
                if hashlib.sha1(normalized(data)).hexdigest() != ent['sha1']:
                    report['removed'].append({'file': rel, 'status': 'kept: changed since it was copied'})
                    continue
                os.unlink(p)
                d = os.path.dirname(p)          # drop the folders the copies created, once empty
                while os.path.normcase(d) != os.path.normcase(PART) and os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
                    d = os.path.dirname(d)
            report['removed'].append({'file': rel, 'status': 'removed'})
        man['copies'] = {k: v for k, v in have.items()
                         if any(r['file'] == k and r['status'].startswith('kept') for r in report['removed'])}
        with open(COPIES, 'w') as f:
            json.dump(man, f, indent=1, sort_keys=True)
        write_snapshot(scan())
        return report
    import sc_tree
    paths = paths or sc_tree.Paths()
    bad = paths.check()
    if bad:
        raise RuntimeError('cannot find the game / MO2: ' + '; '.join(bad))
    res = sc_tree.Resolved(paths, ('particles/', 'particles.xr'))
    todo, seen = [], set()
    xr = {}

    def from_xr(rel):
        """(source, None) for a particle file that only the winning particles.xr has (the game
        reads loose files first and takes an entry of particles.xr only when none has its name)."""
        if 'lib' not in xr:
            import particles_xr
            w = res.winner('particles.xr')
            xr['lib'], xr['label'] = None, None
            if w:
                xr['label'] = '%s particles.xr' % w[0].label
                try:
                    xr['lib'] = particles_xr.loads(w[0].read(w[1]))
                except (ValueError, IndexError, struct.error) as ex:
                    report['particles_xr'] = 'unreadable (%s): %s' % (xr['label'], ex)
            xr['mod'] = particles_xr
        if xr['lib'] is None:
            return None
        name, ext = rel[len('particles/'):].rsplit('.', 1)
        hit = xr['lib'].find(name)
        if not hit or hit[0] != ext:
            return None
        return _XrEntry(xr['label'], xr['mod'].entry_ini(*hit)), None

    def walk(name, why):
        base = 'particles/' + name.replace('\\', '/').lower()
        for ext in ('.pe', '.pg'):
            rel = base + ext
            if rel in seen:
                continue
            w = res.winner(rel) or from_xr(rel)
            if not w:
                continue
            seen.add(rel)
            data = w[0].read(w[1])
            if ext == '.pe':
                todo.append((rel[len('particles/'):], w, data, why))
            for m in CHILD_RE.finditer(data):
                walk(m.group(1).decode('latin1'), why)
    for root, why in COPY_ROOTS:
        walk(root, why)
    for rel, (L, src), data, why in todo:
        e = Effect(rel, data)
        ent = {'file': rel, 'source': L.label, 'why': why, 'class': e.cls, 'reason': e.reason}
        if L.label == sc_tree.ZGO_LABEL:
            ent['status'] = 'Umbra Effects ships it' if rel.lower() not in have else 'ours (copied earlier)'
            if rel.lower() in have:
                src_now = [x for x in res.chain.get('particles/' + rel.lower(), []) if x[0].label != sc_tree.ZGO_LABEL]
                if not src_now:
                    w = from_xr('particles/' + rel.lower())
                    src_now = [w] if w else []
                if src_now:
                    d2 = src_now[-1][0].read(src_now[-1][1])
                    if hashlib.sha1(normalized(d2)).hexdigest() != have[rel.lower()]['sha1']:
                        ent['status'] = 'stale: %s changed it since the copy (run copies --write)' % src_now[-1][0].label
                        if write:
                            new = set_shader(d2, Effect(rel, d2).target)
                            _write(rel, new)
                            have[rel.lower()] = {'source': src_now[-1][0].label, 'sha1': hashlib.sha1(
                                normalized(d2)).hexdigest(), 'why': why}
                            ent['status'] = 'refreshed from ' + src_now[-1][0].label
            report['copies'].append(ent)
            continue
        if e.cls != 'gore' or e.problem:
            ent['status'] = 'skipped: ' + (e.problem or 'not gory (%s)' % e.reason)
            report['copies'].append(ent)
            continue
        new = set_shader(data, e.target)
        ent['status'] = 'to copy' if not write else 'copied'
        if write:
            p = os.path.join(PART, *rel.split('/'))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _write(rel, new)
            have[rel.lower()] = {'source': L.label, 'sha1': hashlib.sha1(normalized(data)).hexdigest(), 'why': why}
        report['copies'].append(ent)
    if write:
        with open(COPIES, 'w') as f:
            json.dump(man, f, indent=1, sort_keys=True)
        write_snapshot(scan())
    return report


def bake(paths=None):
    """What the setup GUI runs for a mod list: shaders, copies, then apply."""
    return {'shaders': gen_shaders(True, paths, legacy=True), 'copies': copies(True, paths=paths), 'apply': apply()}


# ---------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='kidfx_pe', description=__doc__.split('\n\n')[0])
    ap.add_argument('command', choices=['status', 'list', 'apply', 'revert', 'shaders', 'copies', 'bake'])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--remove', action='store_true')
    ap.add_argument('--legacy', action='store_true', help='shaders: also the r1\\ / r2\\ (DX8 / DX9) fallbacks')
    ap.add_argument('--shaders-root', help='shaders: write under this folder instead of gamedata/shaders')
    ap.add_argument('--json', action='store_true')
    for c in ('gore', 'clean', 'carrier', 'group', 'unsure'):
        ap.add_argument('--' + c, action='store_true')
    o = ap.parse_args(argv)
    try:
        if o.command == 'status':
            r = status()
        elif o.command == 'list':
            sel = {c for c in ('gore', 'clean', 'carrier', 'group') if getattr(o, c)}
            r = {'effects': [{'file': e.rel, 'class': e.cls, 'shader': e.shader, 'stock': e.stock,
                              'texture': e.texture, 'reason': e.reason, 'problem': e.problem}
                             for e in scan() if (not sel or e.cls in sel) and
                             (not o.unsure or 'no gore marker' in e.reason)]}
        elif o.command == 'apply':
            r = apply(dry_run=o.dry_run)
        elif o.command == 'revert':
            r = revert(dry_run=o.dry_run)
        elif o.command == 'shaders':
            r = gen_shaders(o.write, legacy=o.legacy, shaders_root=o.shaders_root)
        elif o.command == 'copies':
            r = copies(o.write, o.remove)
        else:
            r = bake()
    except (RuntimeError, ValueError) as e:
        print('kidfx: %s' % e, file=sys.stderr)
        return 2
    if o.json:
        print(json.dumps(r, indent=1))
        return 0 if r.get('state', 'ok') != 'partial' and not r.get('inconsistent') else 1
    if o.command == 'status':
        print('kid-mode particle shaders: %s; %d files: %s' % (r['state'], r['files'], ', '.join(
            '%d %s' % (v, k) for k, v in sorted(r['counts'].items()))))
        print('shaders in use: ' + ', '.join('%s %d' % kv for kv in sorted(r['shaders'].items(),
                                                                          key=lambda kv: -kv[1])))
        for w in r['inconsistent']:
            print('  INCONSISTENT %s (%s): %s, expected %s' % (w['file'], w['class'], w['shader'], w['expected']))
        for p in r['problems']:
            print('  note %s: %s' % (p['file'], p['problem']))
        print('snapshot: %s' % {True: 'current', False: 'stale (run apply)', None: '-'}[r['snapshot_current']])
        return 1 if r['inconsistent'] or r['state'] == 'partial' or r['snapshot_current'] is False else 0
    if o.command == 'list':
        for e in r['effects']:
            print('%-6s %-70s %-22s %s%s' % (e['class'], e['file'], e['shader'] or '-', e['reason'],
                                            ('  [' + e['problem'] + ']') if e['problem'] else ''))
        print('%d files' % len(r['effects']))
        return 0
    if o.command in ('apply', 'revert'):
        for c in r['changed']:
            print('%s %s: %s -> %s' % ('would set' if o.dry_run else 'set', c['file'], c['from'], c['to']))
        for p in r['problems']:
            print('note %s: %s' % (p['file'], p['problem']))
        print('%s: %d shader lines %s' % (o.command, len(r['changed']), 'to change' if o.dry_run else 'changed'))
        return 0
    if o.command == 'shaders':
        for f in r['files']:
            print('%-45s %s' % (f['file'], f['status']))
        return 0 if r['ok'] else 1
    if o.command == 'copies':
        for c in r['copies']:
            print('%-55s %-12s %s (%s)' % (c['file'], c.get('status'), c['source'], c['why']))
        for c in r['removed']:
            print('%-55s %s' % (c['file'], c['status']))
        return 0
    print(json.dumps(r, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
