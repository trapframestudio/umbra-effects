"""
shaders.xr (in db/files.db0): the C++ blender library, read only.

Layout (xray-monolith b86d733f4a, ResourceManager_Loader.cpp, Blender.h,
xrEngine/Properties.h):
  chunk 2 holds one sub-chunk per blender; each starts with CBlender_DESC
  (CLS u64, cName[128], cComputer[32], cTime u32, version u16, #pragma pack 4
  = 176 bytes), then the properties IBlender::Load and the subclass's Load
  read in order: u32 type, stringZ name, then the value:
    INTEGER {value,min,max} 12 bytes, FLOAT 12, BOOL 4,
    TOKEN {IDselected,Count} + Count * {u32 id, char[64]} items,
    CLSID {u64, Count} + Count * u64, MATRIX/CONSTANT/TEXTURE char[64],
    MARKER nothing.

Particle blender (Blender_Particle.cpp) in R4: element 0/1 =
  r_Pass(vs, ps, fog=FALSE, ztest=TRUE, zwrite, ablend, src, dst, atest=TRUE, aref)
  then s_base / smp_base (+clamp when "Texture clamp"), s_position = $user$position,
  smp_nofilter. Element 2 (shadow) uses particle-clip + particle_s-*.
"""
import struct

PID = ['MARKER', 'MATRIX', 'CONSTANT', 'TEXTURE', 'INTEGER', 'FLOAT', 'BOOL', 'TOKEN', 'CLSID', 'OBJECT',
       'STRING', 'MARKER_TEMPLATE']
DESC_SIZE = 176

# D3DBLEND values (d3d9types.h), as the .s Lua "blend" enum exposes them
D3DBLEND = {'zero': 1, 'one': 2, 'srccolor': 3, 'invsrccolor': 4, 'srcalpha': 5, 'invsrcalpha': 6,
            'destalpha': 7, 'invdestalpha': 8, 'destcolor': 9, 'invdestcolor': 10, 'srcalphasat': 11}
BLEND_NAME = {v: k for k, v in D3DBLEND.items()}

# Blender_Particle.cpp (R4 branch): oBlend.IDselected -> normal element pass
PARTICLE_MODES = {
    0: dict(name='SET', vs='deffer_particle', ps='deffer_particle', zwrite=True, ablend=False,
            src='one', dst='zero', atest=False, aref=200),
    1: dict(name='BLEND', vs='particle', ps='particle', zwrite=False, ablend=True,
            src='srcalpha', dst='invsrcalpha', atest=True, aref=0),
    2: dict(name='ADD', vs='particle', ps='particle', zwrite=False, ablend=True,
            src='one', dst='one', atest=True, aref=0),
    3: dict(name='MUL', vs='particle', ps='particle', zwrite=False, ablend=True,
            src='destcolor', dst='zero', atest=True, aref=0),
    4: dict(name='MUL_2X', vs='particle', ps='particle', zwrite=False, ablend=True,
            src='destcolor', dst='srccolor', atest=True, aref=0),
    5: dict(name='ALPHA-ADD', vs='particle', ps='particle', zwrite=False, ablend=True,
            src='srcalpha', dst='one', atest=True, aref=0),
}
# ... and the shadow element (SE_R2_SHADOW = 2)
PARTICLE_SHADOW = {
    0: dict(vs='particle', ps='particle', zwrite=True, ablend=False, src='one', dst='zero', atest=True,
            aref=200, colorwrite=(False, False, False, False)),
    1: dict(vs='particle-clip', ps='particle_s-blend', zwrite=False, ablend=True, src='destcolor', dst='zero',
            atest=True, aref=0),
    2: dict(vs='particle-clip', ps='particle_s-add', zwrite=False, ablend=True, src='destcolor', dst='zero',
            atest=True, aref=0),
    3: dict(vs='particle-clip', ps='particle_s-mul', zwrite=False, ablend=True, src='destcolor', dst='zero',
            atest=True, aref=0),
    4: dict(vs='particle-clip', ps='particle_s-mul', zwrite=False, ablend=True, src='destcolor', dst='zero',
            atest=True, aref=0),
    5: dict(vs='particle-clip', ps='particle_s-aadd', zwrite=False, ablend=True, src='destcolor', dst='zero',
            atest=True, aref=0),
}


def _chunks(data):
    o = 0
    while o + 8 <= len(data):
        cid, sz = struct.unpack_from('<II', data, o)
        yield cid, data[o + 8:o + 8 + sz]
        o += 8 + sz


def _cstr(b):
    return b.split(b'\0', 1)[0].decode('latin1')


def _props(body):
    """[(type, name, value)] after the description."""
    out = []
    o = DESC_SIZE
    while o + 4 <= len(body):
        t, = struct.unpack_from('<I', body, o)
        o += 4
        e = body.index(b'\0', o)
        name = body[o:e].decode('latin1')
        o = e + 1
        kind = PID[t] if t < len(PID) else str(t)
        if kind == 'MARKER':
            val = None
        elif kind in ('INTEGER',):
            val = struct.unpack_from('<iii', body, o)
            o += 12
        elif kind == 'FLOAT':
            val = struct.unpack_from('<fff', body, o)
            o += 12
        elif kind == 'BOOL':
            val = struct.unpack_from('<i', body, o)[0]
            o += 4
        elif kind == 'TOKEN':
            sel, cnt = struct.unpack_from('<II', body, o)
            o += 8
            items = []
            for _ in range(cnt):
                iid, = struct.unpack_from('<I', body, o)
                items.append((iid, _cstr(body[o + 4:o + 68])))
                o += 68
            val = (sel, items)
        elif kind == 'CLSID':
            sel, cnt = struct.unpack_from('<QI', body, o)
            o += 12 + 8 * cnt
            val = sel
        elif kind in ('MATRIX', 'CONSTANT', 'TEXTURE'):
            val = _cstr(body[o:o + 64])
            o += 64
        else:
            break                               # unknown property type: stop
        out.append((kind, name, val))
    return out


def blenders(data):
    """{name: {'cls': str, 'version': int, 'props': [(kind, name, value)]}}"""
    out = {}
    for cid, body in _chunks(data):
        if cid & 0x7FFFFFFF != 2:
            continue
        for sub_id, sub in _chunks(body):
            if len(sub) < DESC_SIZE:
                continue
            cls = sub[:8][::-1].decode('latin1')        # MK_CLSID packs the first letter in the high byte
            name = _cstr(sub[8:136])
            version, = struct.unpack_from('<H', sub, 172)
            out[name.lower()] = {'cls': cls, 'version': version, 'props': _props(sub)}
    return out


def particle_params(b):
    """Priority, strict sorting, blend mode, clamp, aref of a particle blender."""
    p = {name: val for kind, name, val in b['props'] if kind != 'MARKER'}
    return {
        'priority': p.get('Priority', (1,))[0],
        'strict': bool(p.get('Strict sorting', 0)),
        'blend': p.get('Blending', (0, []))[0],
        'clamp': bool(p.get('Texture clamp', 1)),
        'aref': p.get('Alpha ref', (32,))[0],
    }
