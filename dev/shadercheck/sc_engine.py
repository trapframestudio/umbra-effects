"""
How the engine compiles a DX11 (R4) shader, from xray-monolith b86d733f4a.
The exe is xrRazom's private build of monolith; its strings list the same
macro names in the same order (checked with `strings AnomalyDX11AVX.exe`).

CResourceManager::_CreateVS/_CreatePS/_CreateGS (dx10ResourceManager_Resources.cpp)
  - file  = "r3\\" + name up to '(' + ".vs" / ".ps" / ".gs"; a missing file is
    replaced by stub_default.vs / .ps with a log line (no error);
  - entry "main", target "vs_2_0" / "ps_2_0" unless the source contains
    main_vs_1_1 / main_vs_2_0 / main_ps_1_x / main_ps_2_0 (then that entry and
    that legacy target, which shader_compile does NOT remap);
  - flags D3D10_SHADER_PACK_MATRIX_ROW_MAJOR (8);
  - a failed compile is fatal: CHECK_OR_EXIT("Shader compilation failed").
  - VS names get _0.._4 for skinned visuals (m_skinning), PS names _0.._7 for
    MSAA samples; the macros follow the current m_skinning for VS and PS alike.
CRender::shader_compile (r4.cpp)
  - for entry "main": vs/ps/gs -> *_5_0 (the renderer asserts feature level 11_0),
    cs -> cs_5_0;
  - macros: m_ShaderOptions first, then the option list below, in that order;
  - the shader cache key (sh_name) is the same option list as digits; the
    game's own cache folder (appdata/shaders_cache/r4/<name>.<ext>/<sh_name>)
    therefore tells which options a player really uses (decode_sh_name).
"""
import os
import re

FLAGS = 8                                   # D3D10_SHADER_PACK_MATRIX_ROW_MAJOR
STAGES = {'.vs': 'vs', '.ps': 'ps', '.gs': 'gs', '.cs': 'cs', '.hs': 'hs', '.ds': 'ds'}

# ----------------------------------------------------------------- options
# One renderer configuration. Keys are r4.cpp's option fields.
BASE = dict(
    smapsize=2048, fp16_filter=1, fp16_blend=1, hw_smap=1, hw_smap_pcf=1, fetch4=0, sjitter=0,
    branching=1, vtf=1, tshadows=0, mblur=0, sunfilter=0, sunstatic=0, forceskinw=0, ssao_blur=0,
    hdao=0, hbao=0, ssao_half=0, hbao_vectorized=0, msaa=0, msaa_samples=0, msaa_opt=0, msaa_atest=0,
    skinning=-1, soft_water=1, soft_particles=1, dof=1, sun_shafts=2, ssao=2, sun_quality=2,
    steep_parallax=1, reflections=1, smaa=0, vendor='nvidia', sm4_1=1, minmax_sm=0,
    rain=2, grass=0, ssr=2, water=1, water_parallax=1, il=16, ao=4, pom_refine=0, terra_pom_refine=0,
    sss_dir=12, sss_omni=4,
)


def defines(o):
    """[(name, value)] exactly as CRender::shader_compile builds them."""
    d = [('SMAP_size', '%04d' % o['smapsize'])]
    for key, name in (('fp16_filter', 'FP16_FILTER'), ('fp16_blend', 'FP16_BLEND'), ('hw_smap', 'USE_HWSMAP'),
                      ('hw_smap_pcf', 'USE_HWSMAP_PCF'), ('fetch4', 'USE_FETCH4'), ('sjitter', 'USE_SJITTER'),
                      ('branching', 'USE_BRANCHING'), ('vtf', 'USE_VTF'), ('tshadows', 'USE_TSHADOWS'),
                      ('mblur', 'USE_MBLUR'), ('sunfilter', 'USE_SUNFILTER'), ('sunstatic', 'USE_R2_STATIC_SUN'),
                      ('forceskinw', 'SKIN_COLOR'), ('ssao_blur', 'USE_SSAO_BLUR')):
        if o[key]:
            d.append((name, '1'))
    if o['hdao']:
        d.append(('HDAO', '1'))
    elif o['hbao']:
        d.append(('SSAO_OPT_DATA', '2' if o['ssao_half'] else '1'))
        if o['hbao_vectorized']:
            d.append(('VECTORIZED_CODE', '1'))
        d.append(('USE_HBAO', '1'))
    if o['msaa']:
        d.append(('ISAMPLE', '0'))
    s = o['skinning']
    if s < 0:
        d.append(('SKIN_NONE', '1'))
    for i in range(5):
        if s == i:
            d.append(('SKIN_%d' % i, '1'))
    # "advancedpp" options (r2 advanced post-process is always on in R4)
    if o['soft_water']:
        d.append(('USE_SOFT_WATER', '1'))
    if o['soft_particles']:
        d.append(('USE_SOFT_PARTICLES', '1'))
    if o['dof']:
        d.append(('USE_DOF', '1'))
    if o['sun_shafts']:
        d.append(('SUN_SHAFTS_QUALITY', str(o['sun_shafts'])))
    if o['ssao']:
        d.append(('SSAO_QUALITY', str(o['ssao'])))
    if o['sun_quality']:
        d.append(('SUN_QUALITY', str(o['sun_quality'])))
    if o['steep_parallax']:
        d.append(('ALLOW_STEEPPARALLAX', '1'))
    if o['reflections']:
        d.append(('USE_REFLECTIONS', '1'))
    if o['smaa']:
        d.append(('SMAA_QUALITY', str(o['smaa'])))
    if o['vendor'] == 'amd':
        d.append(('INT_RENDER_AMD', '1'))
    elif o['vendor'] == 'nvidia':
        d.append(('INT_RENDER_NVIDIA', '1'))
    if o['sm4_1']:
        d.append(('SM_4_1', '1'))
    d.append(('SM_5', '1'))
    if o['minmax_sm']:
        d.append(('USE_MINMAX_SM', '1'))
    if o['rain'] > 0:
        d.append(('SSFX_RAIN_QUALITY', str(o['rain'])))
    if o['grass'] > 0:
        d.append(('SSFX_INT_GRASS', str(o['grass'])))
    d.append(('SSFX_SSR_QUALITY', str(min(max(o['ssr'], 0), 5))))
    d.append(('SSFX_WATER_QUALITY', str(min(max(o['water'], 0), 4))))
    d.append(('SSFX_WATER_PARALLAX', str(min(max(o['water_parallax'], 0), 3))))
    d.append(('SSFX_IL_QUALITY', str(min(max(o['il'], 0), 64))))
    d.append(('SSFX_AO_QUALITY', str(min(max(o['ao'], 2), 8))))
    d.append(('SSFX_POM_REFINE', str(min(max(o['pom_refine'], 0), 1))))
    d.append(('SSFX_TERRA_POM_REFINE', str(min(max(o['terra_pom_refine'], 0), 1))))
    d.append(('SSFX_SSS_DIR_QUALITY', str(min(max(o['sss_dir'], 1), 24))))
    d.append(('SSFX_SSS_OMNI_QUALITY', str(min(max(o['sss_omni'], 1), 12))))
    d.append(('SSFX_MODEXE', '1'))
    if o['msaa']:
        d.append(('USE_MSAA', '1'))
        d.append(('MSAA_SAMPLES', str(o['msaa_samples'])))
        if o['msaa_opt']:
            d.append(('MSAA_OPTIMIZATION', '1'))
        name = {1: 'MSAA_ALPHATEST_DX10_0_ATOC', 2: 'MSAA_ALPHATEST_DX10_1_ATOC', 3: 'MSAA_ALPHATEST_DX10_1'}.get(
            o['msaa_atest'])
        if name:
            d.append((name, '1'))
    return d


def sh_name(o):
    """The shader-cache key r4.cpp builds from the same options."""
    s = '%04d' % o['smapsize']
    for key in ('fp16_filter', 'fp16_blend', 'hw_smap', 'hw_smap_pcf', 'fetch4', 'sjitter', 'branching', 'vtf',
                'tshadows', 'mblur', 'sunfilter', 'sunstatic', 'forceskinw', 'ssao_blur'):
        s += '1' if o[key] else '0'
    s += '100' if o['hdao'] else '0%d%d' % (1 if o['hbao'] else 0, 1 if o['ssao_half'] else 0)
    s += '0'                                                     # msaa sample (always '0')
    s += '1' if o['skinning'] < 0 else '0'
    s += ''.join('1' if o['skinning'] == i else '0' for i in range(5))
    for key in ('soft_water', 'soft_particles', 'dof'):
        s += '1' if o[key] else '0'
    for key in ('sun_shafts', 'ssao', 'sun_quality'):
        s += str(o[key])
    s += '1' if o['steep_parallax'] else '0'
    s += '1' if o['reflections'] else '0'
    s += str(o['smaa'])
    s += '1' if o['sm4_1'] else '0'
    s += '1'                                                     # SM_5
    s += '1' if o['minmax_sm'] else '0'
    s += str(o['rain']) if o['rain'] > 0 else '0'
    s += str(o['grass']) if o['grass'] > 0 else '0'
    for key, lo, hi in (('ssr', 0, 5), ('water', 0, 4), ('water_parallax', 0, 3), ('il', 0, 64), ('ao', 2, 8),
                        ('pom_refine', 0, 1), ('terra_pom_refine', 0, 1), ('sss_dir', 1, 24), ('sss_omni', 1, 12)):
        s += str(min(max(o[key], lo), hi))
    s += '1'                                                     # SSFX_MODEXE
    if o['msaa']:
        s += '1%d%d' % (o['msaa_samples'], 1 if o['msaa_opt'] else 0)
        s += {1: '100', 2: '010', 3: '001'}.get(o['msaa_atest'], '000')
    else:
        s += '000000'
    return s


_FIXED = ['fp16_filter', 'fp16_blend', 'hw_smap', 'hw_smap_pcf', 'fetch4', 'sjitter', 'branching', 'vtf',
          'tshadows', 'mblur', 'sunfilter', 'sunstatic', 'forceskinw', 'ssao_blur']


def decode_sh_name(s, vendor=None):
    """Options from a shader-cache key; None when it doesn't parse. The
    numeric SSFX tail has variable-width fields; the parse tries every split
    and keeps the one that re-encodes to the same string within range."""
    m = re.match(r'^(\d{4})([01]{14})(100|0[01][01])0([01])([01]{5})([01]{3})(\d)(\d)(\d)([01])([01])(\d)([01])1([01])'
                 r'(\d+)$', s)
    if not m:
        return None
    o = dict(BASE)
    o['smapsize'] = int(m.group(1))
    for k, c in zip(_FIXED, m.group(2)):
        o[k] = int(c)
    a = m.group(3)
    o['hdao'] = 1 if a == '100' else 0
    o['hbao'] = 1 if a[0] == '0' and a[1] == '1' else 0
    o['ssao_half'] = 1 if a[0] == '0' and a[2] == '1' else 0
    skin_none, skins = m.group(4), m.group(5)
    o['skinning'] = -1 if skin_none == '1' else (skins.index('1') if '1' in skins else -1)
    o['soft_water'], o['soft_particles'], o['dof'] = [int(c) for c in m.group(6)]
    o['sun_shafts'], o['ssao'], o['sun_quality'] = int(m.group(7)), int(m.group(8)), int(m.group(9))
    o['steep_parallax'], o['reflections'] = int(m.group(10)), int(m.group(11))
    o['smaa'] = int(m.group(12))
    o['sm4_1'] = int(m.group(13))
    o['minmax_sm'] = int(m.group(14))
    tail = m.group(15)
    # tail = rain grass ssr water parallax il ao pom tpom sssdir sssomni '1' msaa(6)
    if len(tail) < 6 + 1 + 11:
        return None
    msaa = tail[-6:]
    core = tail[:-7]
    if tail[-7] != '1':
        return None
    if msaa != '000000':
        o['msaa'] = 1
        o['msaa_samples'] = int(msaa[1])
        o['msaa_opt'] = int(msaa[2])
        o['msaa_atest'] = {'100': 1, '010': 2, '001': 3}.get(msaa[3:], 0)
    ranges = [('rain', 0, 9), ('grass', 0, 99), ('ssr', 0, 5), ('water', 0, 4), ('water_parallax', 0, 3),
              ('il', 0, 64), ('ao', 2, 8), ('pom_refine', 0, 1), ('terra_pom_refine', 0, 1), ('sss_dir', 1, 24),
              ('sss_omni', 1, 12)]

    def split(rest, i):
        if i == len(ranges):
            return [] if rest == '' else None
        key, lo, hi = ranges[i]
        for w in (1, 2):
            if len(rest) < w or (w == 2 and rest[0] == '0'):
                continue
            v = int(rest[:w])
            if lo <= v <= hi or (key in ('rain', 'grass') and v == 0 and w == 1):
                r = split(rest[w:], i + 1)
                if r is not None:
                    return [v] + r
        return None

    vals = split(core, 0)
    if vals is None:
        return None
    for (key, _, _), v in zip(ranges, vals):
        o[key] = v
    if vendor:
        o['vendor'] = vendor
    return o if sh_name(o) == s else None


def from_shader_cache(game):
    """The non-skinned option string the player's game used most, decoded."""
    top = os.path.join(game or '', 'appdata', 'shaders_cache', 'r4')
    if not os.path.isdir(top):
        return None, None
    counts = {}
    for d in os.listdir(top):
        p = os.path.join(top, d)
        if os.path.isdir(p):
            for k in os.listdir(p):
                counts[k] = counts.get(k, 0) + 1
    for k, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        o = decode_sh_name(k, vendor='unknown')
        if o and o['skinning'] < 0:
            return o, k
    return None, None


# ----------------------------------------------------------------- the sets
def _with(**kw):
    o = dict(BASE)
    o.update(kw)
    return o


def define_sets(game=None):
    """Representative renderer configurations: {name: (options, description)}."""
    sets = {}
    user, key = from_shader_cache(game)
    if user:
        sets['user'] = (user, "this machine's game (from its shader cache, %s)" % key)
    sets['default'] = (_with(), 'GAMMA-like defaults: soft particles and water, DOF, SSR 2, no MSAA, NVIDIA')
    sets['low'] = (_with(smapsize=1024, soft_water=0, soft_particles=0, dof=0, sun_shafts=0, ssao=0, sun_quality=1,
                         steep_parallax=0, reflections=0, sm4_1=0, rain=0, ssr=0, water=0, water_parallax=0, il=0,
                         ao=2, sss_dir=1, sss_omni=1, vendor='amd'),
                   'potato: every optional effect off, SM 4.0 path, AMD')
    sets['hbao_msaa'] = (_with(hbao=1, ssao_half=1, hbao_vectorized=1, ssao_blur=1, msaa=1, msaa_samples=4,
                               msaa_opt=1, msaa_atest=2, vendor='amd', smaa=0),
                         'HBAO (half data, vectorized), MSAA 4x with DX10.1 alpha-to-coverage, AMD')
    sets['ultra'] = (_with(smapsize=4096, hdao=1, sjitter=1, tshadows=1, mblur=1, sun_shafts=3, ssao=3,
                           sun_quality=4, smaa=2, minmax_sm=1, rain=4, grass=8, ssr=5, water=4, water_parallax=3,
                           il=64, ao=8, pom_refine=1, terra_pom_refine=1, sss_dir=24, sss_omni=12, msaa=1,
                           msaa_samples=8, msaa_opt=1, msaa_atest=3),
                     'everything at its maximum, HDAO, MSAA 8x with native DX10.1 alpha test')
    sets['msaa_atoc10'] = (_with(msaa=1, msaa_samples=2, msaa_atest=1, soft_particles=1),
                           'MSAA 2x with DX10.0 alpha-to-coverage')
    return sets


# ----------------------------------------------------------------- targets
def target_for(path, source):
    """(entry, target) the way _Create* and shader_compile pick them."""
    ext = os.path.splitext(path)[1].lower()
    st = STAGES.get(ext)
    if st is None:
        return None, None
    text = source.decode('latin1', 'replace') if isinstance(source, bytes) else source
    entry = 'main'
    legacy = None
    if st == 'vs':
        for e in ('main_vs_1_1', 'main_vs_2_0'):
            if e in text:
                entry, legacy = e, e[5:]
    elif st == 'ps':
        for e in ('main_ps_1_1', 'main_ps_1_2', 'main_ps_1_3', 'main_ps_1_4', 'main_ps_2_0'):
            if e in text:
                entry, legacy = e, e[5:]
    if legacy:
        return entry, legacy                 # not remapped by shader_compile
    return entry, '%s_5_0' % st


def skin_variants(path):
    """Skinning values to compile: the macros follow m_skinning for every stage;
    a VS is only ever compiled skinned for skinned visuals, so both matter."""
    ext = os.path.splitext(path)[1].lower()
    return [-1, 0, 1, 2, 3, 4] if ext == '.vs' else [-1]
