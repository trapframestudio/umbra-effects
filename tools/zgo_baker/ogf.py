"""
X-Ray OGF (skinned model) reader / writer for the Umbra Effects mesh baker.

Layouts follow xray-monolith (src/xrEngine/Fmesh.h, bone.h, Layers/xrRender
SkeletonX.cpp, SkeletonCustom.cpp). Chunks the baker does not touch are kept
byte for byte.
"""
import struct
import numpy as np

HEADER, TEXTURE, VERTICES, INDICES, SWIDATA, CHILDREN = 1, 2, 3, 4, 6, 9
S_BONE_NAMES, S_IKDATA, S_USERDATA, S_DESC, S_MOTION_REFS, S_LODS, S_MOTION_REFS2 = 13, 16, 17, 18, 19, 23, 24

MT_SKELETON_ANIM, MT_SKELETON_GEOMDEF_PM, MT_SKELETON_GEOMDEF_ST, MT_SKELETON_RIGID = 3, 4, 5, 10

_V3 = ('<f4', 3)
DT = {
    1: np.dtype([('P', *_V3), ('N', *_V3), ('T', *_V3), ('B', *_V3), ('uv', '<f4', 2), ('m', '<u4')]),
    2: np.dtype([('m', '<u2', 2), ('P', *_V3), ('N', *_V3), ('T', *_V3), ('B', *_V3), ('w', '<f4'), ('uv', '<f4', 2)]),
    3: np.dtype([('m', '<u2', 3), ('P', *_V3), ('N', *_V3), ('T', *_V3), ('B', *_V3), ('w', '<f4', 2), ('uv', '<f4', 2)]),
    4: np.dtype([('m', '<u2', 4), ('P', *_V3), ('N', *_V3), ('T', *_V3), ('B', *_V3), ('w', '<f4', 3), ('uv', '<f4', 2)]),
}
assert [DT[k].itemsize for k in (1, 2, 3, 4)] == [60, 64, 70, 76]
# OGF_VERTEXFORMAT_FVF_xL (Fmesh.h) and the plain 1..4 codes
VCODE = {1: 1, 2: 2, 3: 3, 4: 4,
         0x12071980: 1, 0x240E3300: 2, 0x481C6600: 3, 0x5A237F80: 4}


class OgfError(Exception):
    pass


def read_chunks(b, tail=None):
    """Chunk list. With tail=[] the bytes after the last whole chunk are kept
    there instead of failing (some shipped models have a last chunk whose size
    is short by a few bytes; the engine reads past it, so must we keep them)."""
    out, o = [], 0
    while o + 8 <= len(b):
        cid, sz = struct.unpack_from('<II', b, o)
        if o + 8 + sz > len(b):
            if tail is None:
                raise OgfError('chunk %d runs past the end' % cid)
            break
        out.append([cid, bytes(b[o + 8:o + 8 + sz])])
        o += 8 + sz
    if o != len(b):
        if tail is None:
            raise OgfError('%d trailing bytes' % (len(b) - o))
        tail.append(bytes(b[o:]))
    return out


def write_chunks(chunks):
    return b''.join(struct.pack('<II', cid, len(d)) + d for cid, d in chunks)


def find(chunks, cid):
    for c in chunks:
        if c[0] & 0x7FFFFFFF == cid:
            return c[1]
    return None


def zstr(b, o):
    e = b.index(b'\0', o)
    return b[o:e].decode('latin1'), e + 1


class Header:
    FMT = '<BBH3f3f3ff'          # ogf_header: version, type, shader id, bbox, bsphere

    def __init__(self, b):
        v = struct.unpack_from(self.FMT, b)
        self.version, self.type, self.shader_id = v[0], v[1], v[2]
        self.bb_min, self.bb_max = np.array(v[3:6], np.float32), np.array(v[6:9], np.float32)
        self.bs_c, self.bs_r = np.array(v[9:12], np.float32), float(v[12])
        self.tail = b[struct.calcsize(self.FMT):]

    def pack(self):
        return struct.pack(self.FMT, self.version, self.type, self.shader_id,
                           *self.bb_min.tolist(), *self.bb_max.tolist(), *self.bs_c.tolist(), self.bs_r) + self.tail


class Geom:
    """One skinned sub-mesh (child visual) in a normalised form:
    P N T B (n,3), uv (n,2), bones (n,4) u16, weights (n,4) f32 summing to 1."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.header = Header(find(chunks, HEADER))
        t = find(chunks, TEXTURE)
        self.texture, o = zstr(t, 0)
        self.shader, _ = zstr(t, o)
        vb = find(chunks, VERTICES)
        code, n = struct.unpack_from('<II', vb)
        if code not in VCODE:
            raise OgfError('vertex format %#x' % code)
        self.vcode, self.links = code, VCODE[code]
        v = np.frombuffer(vb, DT[self.links], n, 8)
        self.P, self.N, self.T, self.B = (v[k].astype(np.float32) for k in 'PNTB')
        self.uv = v['uv'].astype(np.float32)
        bones = np.zeros((n, 4), np.uint16)
        w = np.zeros((n, 4), np.float32)
        if self.links == 1:
            bones[:, 0] = v['m'].astype(np.uint16)
            w[:, 0] = 1
        elif self.links == 2:
            bones[:, :2] = v['m']
            w[:, 1] = v['w']
            w[:, 0] = 1 - v['w']
        else:
            k = self.links
            bones[:, :k] = v['m']
            w[:, :k - 1] = v['w']
            w[:, k - 1] = 1 - v['w'].sum(axis=1)
        self.bones, self.weights = bones, w
        ib = find(chunks, INDICES)
        ni, = struct.unpack_from('<I', ib)
        idx = np.frombuffer(ib, '<u2', ni, 4).astype(np.int64)
        sw = find(chunks, SWIDATA)
        if sw is not None:
            # progressive mesh: keep the full-detail window only
            nsw, = struct.unpack_from('<I', sw, 16)
            if nsw:
                off, ntri, _nv = struct.unpack_from('<IHH', sw, 20)
                idx = idx[off:off + ntri * 3]
        self.tris = idx.reshape(-1, 3)

    @classmethod
    def new(cls, texture, shader, P, N, T, B, uv, bones, weights, tris, links=None):
        """A fresh skinned sub-mesh from arrays (positions in the model's bind
        space, bones (n,4) and weights (n,4) summing to 1, tris (m,3)). links
        (1..4) is the vertex format; by default the most weights any vertex uses."""
        g = object.__new__(cls)
        g.chunks = []
        g.texture, g.shader = texture, shader
        n = len(P)
        g.P = np.asarray(P, np.float32).reshape(n, 3)
        g.N = np.asarray(N, np.float32).reshape(n, 3)
        g.T = np.asarray(T, np.float32).reshape(n, 3)
        g.B = np.asarray(B, np.float32).reshape(n, 3)
        g.uv = np.asarray(uv, np.float32).reshape(n, 2)
        b = np.zeros((n, 4), np.uint16)
        w = np.zeros((n, 4), np.float32)
        bb, ww = np.asarray(bones), np.asarray(weights, np.float64)
        b[:, :bb.shape[1]] = bb
        w[:, :ww.shape[1]] = ww
        if links is None:
            links = int(max(1, (w > 0).sum(1).max())) if n else 1
        # live weights first, so the format's implied last weight is a real one
        order = np.argsort(-w, axis=1, kind='stable')
        b = np.take_along_axis(b, order, 1)
        w = np.take_along_axis(w, order, 1)
        w[:, links:] = 0
        s = w.sum(1, keepdims=True)
        w = w / np.where(s > 0, s, 1)
        # unused slots point at the main bone (no stray bone references)
        b[:, 1:] = np.where(w[:, 1:] > 0, b[:, 1:], b[:, :1])
        g.bones, g.weights = b, w.astype(np.float32)
        g.links = links
        g.vcode = links
        g.header = Header(struct.pack(Header.FMT, 4, MT_SKELETON_GEOMDEF_ST, 0, *([0.0] * 10)))
        g.tris = np.asarray(tris, np.int64).reshape(-1, 3)
        return g

    @property
    def n(self):
        return len(self.P)

    def subset(self, tri_mask):
        """A new Geom with the given triangles and only the vertices they use."""
        g = object.__new__(Geom)
        g.chunks, g.texture, g.shader = self.chunks, self.texture, self.shader
        g.vcode, g.links = self.vcode, self.links
        g.header = Header(self.header.pack())
        tris = self.tris[tri_mask]
        used, inv = np.unique(tris, return_inverse=True)
        g.tris = inv.reshape(-1, 3)
        for k in ('P', 'N', 'T', 'B', 'uv', 'bones', 'weights'):
            setattr(g, k, getattr(self, k)[used])
        g.src_verts = used
        return g

    def pack_vertices(self):
        n, k = self.n, self.links
        v = np.zeros(n, DT[k])
        for a in 'PNTB':
            v[a] = getattr(self, a)
        v['uv'] = self.uv
        if k == 1:
            v['m'] = self.bones[:, 0]
        elif k == 2:
            v['m'] = self.bones[:, :2]
            v['w'] = self.weights[:, 1]
        else:
            v['m'] = self.bones[:, :k]
            v['w'] = self.weights[:, :k - 1]
        return struct.pack('<II', self.vcode, n) + v.tobytes()

    def to_chunks(self):
        if self.n > 65535:
            raise OgfError('more than 65535 vertices in a sub-mesh')
        h = self.header
        h.type = MT_SKELETON_GEOMDEF_ST
        p = self.P.astype(np.float64)
        h.bb_min, h.bb_max = p.min(0).astype(np.float32), p.max(0).astype(np.float32)
        c = (p.min(0) + p.max(0)) / 2
        h.bs_c, h.bs_r = c.astype(np.float32), float(np.sqrt(((p - c) ** 2).sum(1)).max())
        idx = self.tris.astype('<u2').ravel()
        out = [[HEADER, h.pack()],
               [TEXTURE, (self.texture + '\0' + self.shader + '\0').encode('latin1')],
               [VERTICES, self.pack_vertices()],
               [INDICES, struct.pack('<I', len(idx)) + idx.tobytes()]]
        # anything else the source sub-mesh carried (not the progressive data)
        keep = {HEADER, TEXTURE, VERTICES, INDICES, SWIDATA}
        out += [c for c in self.chunks if c[0] & 0x7FFFFFFF not in keep]
        return out


class Bone:
    def __init__(self, i, name, parent, obb):
        self.id, self.name, self.parent_name, self.obb = i, name, parent, obb
        self.parent = -1
        self.children = []
        self.mtl, self.shape, self.ik = '', None, None
        self.ik_vers = 0
        self.bind_rot = self.bind_pos = None
        self.mass, self.com = 0.0, None
        self.local = self.world = None       # 4x4, column vectors (p' = M @ p)


def euler_xyzi(x, y, z):
    """Fmatrix::setXYZi -> setHPB(-y, -x, -z); returned as a column-vector 3x3."""
    h, p, b = -y, -x, -z
    sh, ch, sp, cp, sb, cb = np.sin(h), np.cos(h), np.sin(p), np.cos(p), np.sin(b), np.cos(b)
    cc, cs, sc, ss = ch * cb, ch * sb, sh * cb, sh * sb
    i = [cc - sp * ss, -cp * sb, sp * cs + sc]
    j = [sp * sc + cs, cp * cb, ss - sp * cc]
    k = [-cp * sh, sp, cp * ch]
    # rows i, j, k are the images of the basis vectors (transform_tiny)
    return np.array([i, j, k], np.float64).T


def xyzi_from_matrix(r):
    """Angles (x, y, z) with euler_xyzi(x, y, z) == r (r a rotation, column vectors)."""
    sp = float(np.clip(r[1, 2], -1.0, 1.0))
    p = np.arcsin(sp)
    if abs(r[0, 2]) + abs(r[2, 2]) > 1e-12:
        h = np.arctan2(-r[0, 2], r[2, 2])
        b = np.arctan2(-r[1, 0], r[1, 1])
    else:                                   # gimbal lock (cos p = 0): put it all in h
        h = np.arctan2(r[2, 0], r[0, 0])
        b = 0.0
    return (float(-p), float(-h), float(-b))


class Skeleton:
    def __init__(self, names_chunk, ik_chunk):
        n, = struct.unpack_from('<I', names_chunk)
        o, bones = 4, []
        for i in range(n):
            name, o = zstr(names_chunk, o)
            par, o = zstr(names_chunk, o)
            bones.append(Bone(i, name.lower(), par.lower(), names_chunk[o:o + 60]))
            o += 60
        self.bones = bones
        self.by_name = {b.name: b.id for b in bones}
        self.root = -1
        for b in bones:
            if b.parent_name:
                b.parent = self.by_name[b.parent_name]
                bones[b.parent].children.append(b.id)
            else:
                self.root = b.id
        if ik_chunk is not None:
            o = 0
            for b in bones:
                vers, = struct.unpack_from('<I', ik_chunk, o)
                b.ik_vers = vers
                b.mtl, o = zstr(ik_chunk, o + 4)
                b.shape = ik_chunk[o:o + 112]
                o += 112
                iklen = 72 + (4 if vers > 0 else 0)
                b.ik = ik_chunk[o:o + iklen]
                o += iklen
                vals = struct.unpack_from('<3f3ff3f', ik_chunk, o)
                o += 40
                b.bind_rot, b.bind_pos = vals[0:3], vals[3:6]
                b.mass, b.com = vals[6], vals[7:10]
            if o != len(ik_chunk):
                raise OgfError('IK data: read %d of %d bytes' % (o, len(ik_chunk)))
            self._bind()
        self.depth = [0] * n
        for b in self.order():
            self.depth[b] = 0 if bones[b].parent < 0 else self.depth[bones[b].parent] + 1
        self.anc = [0] * n            # bit mask: the bone and all of its ancestors
        for b in self.order():
            p = bones[b].parent
            self.anc[b] = (1 << b) | (self.anc[p] if p >= 0 else 0)

    def order(self):
        """Parents before children."""
        out, st = [], [self.root]
        while st:
            b = st.pop()
            out.append(b)
            st.extend(reversed(self.bones[b].children))
        return out

    def _bind(self):
        for b in self.order():
            bn = self.bones[b]
            m = np.eye(4)
            m[:3, :3] = euler_xyzi(*bn.bind_rot)
            m[:3, 3] = bn.bind_pos
            bn.local = m
            bn.world = m if bn.parent < 0 else self.bones[bn.parent].world @ m

    def descendants(self, b, include=True):
        out, st = ([b] if include else []), list(self.bones[b].children)
        while st:
            c = st.pop()
            out.append(c)
            st.extend(self.bones[c].children)
        return out

    def pos(self, b):
        return self.bones[b].world[:3, 3]


class Model:
    def __init__(self, data):
        t = []
        self.chunks = read_chunks(data, t)
        self.tail = t[0] if t else b''
        self.header = Header(find(self.chunks, HEADER))
        if self.header.type != MT_SKELETON_ANIM and self.header.type != MT_SKELETON_RIGID:
            raise OgfError('not a skinned model (type %d)' % self.header.type)
        ch = find(self.chunks, CHILDREN)
        if ch is None:
            raise OgfError('no sub-meshes')
        self.children = []
        for _, d in read_chunks(ch):
            sub = read_chunks(d)
            t = Header(find(sub, HEADER)).type
            if t not in (MT_SKELETON_GEOMDEF_PM, MT_SKELETON_GEOMDEF_ST):
                raise OgfError('sub-mesh type %d' % t)
            self.children.append(Geom(sub))
        self.skeleton = Skeleton(find(self.chunks, S_BONE_NAMES), find(self.chunks, S_IKDATA))

    def pack(self, children=None):
        """The model with its sub-meshes replaced by `children` (Geom list)."""
        kids = children if children is not None else self.children
        body = write_chunks([[i, write_chunks(g.to_chunks())] for i, g in enumerate(kids)])
        out = [[c[0], body] if c[0] & 0x7FFFFFFF == CHILDREN else c for c in self.chunks]
        return write_chunks(out) + self.tail


def load(path):
    with open(path, 'rb') as f:
        return Model(f.read())


# ---------------------------------------------------------------- writing new skeleton models

def ik_record(bone, bind_rot=None, bind_pos=None, shape=None):
    """One bone's OGF_S_IKDATA record (bone.h CBoneData / SJointIKData),
    optionally with another bind rotation / position or bone shape."""
    rot = bone.bind_rot if bind_rot is None else bind_rot
    pos = bone.bind_pos if bind_pos is None else bind_pos
    sh = bone.shape if shape is None else shape
    if len(sh) != 112:
        raise OgfError('bone shape must be 112 bytes')
    ik = bone.ik
    if len(ik) != 72 + (4 if bone.ik_vers > 0 else 0):
        raise OgfError('IK data size %d for version %d' % (len(ik), bone.ik_vers))
    return (struct.pack('<I', bone.ik_vers) + bone.mtl.encode('latin1') + b'\0' + sh + ik +
            struct.pack('<3f3ff3f', *rot, *pos, bone.mass, *bone.com))


NO_SHAPE = b'\0' * 112            # SBoneShape type stNone, no flags, empty volumes


def default_bone(name, parent_name=''):
    """A plain bone with no shape and a rigid joint (for generated skeletons)."""
    b = Bone(-1, name, parent_name, struct.pack('<9f3f3f', 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    b.mtl, b.shape, b.ik_vers = 'default_object', NO_SHAPE, 1
    b.ik = b'\0' * 76
    b.bind_rot, b.bind_pos, b.mass, b.com = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0, (0.0, 0.0, 0.0)
    return b


def obb_bytes(lo, hi, margin=0.0):
    """An axis-aligned Fobb (rotation, centre, half size) around a box."""
    lo, hi = np.asarray(lo, np.float64) - margin, np.asarray(hi, np.float64) + margin
    c, h = (lo + hi) / 2, np.maximum((hi - lo) / 2, 1e-4)
    return struct.pack('<9f3f3f', 1, 0, 0, 0, 1, 0, 0, 0, 1, *c.tolist(), *h.tolist())


DESC = b'zgo_baker\0zgo_baker\0' + struct.pack('<I', 0) + b'zgo_baker\0' + struct.pack('<I', 0) + \
    b'zgo_baker\0' + struct.pack('<I', 0)


def build_skeleton_model(bones, children):
    """A new MT_SKELETON_RIGID model (CKinematics: bones, no motions), as the
    engine loads it (ModelPool / SkeletonCustom.cpp). bones: list of
    (name, parent_name, obb bytes, ik record bytes), the root's parent ''.
    children: Geom list whose bone indices refer to that list."""
    if not bones or len(bones) > 64:
        raise OgfError('a skeleton needs 1..64 bones, not %d' % len(bones))
    names = [b[0] for b in bones]
    if len(set(names)) != len(names) or sum(1 for b in bones if not b[1]) != 1:
        raise OgfError('bone names must be unique with exactly one root')
    for b in bones:
        if b[1] and b[1] not in names:
            raise OgfError('bone %s: parent %s missing' % (b[0], b[1]))
    if not children:
        raise OgfError('no sub-meshes')
    allp = np.concatenate([g.P for g in children]).astype(np.float64)
    lo, hi = allp.min(0), allp.max(0)
    c = (lo + hi) / 2
    r = float(np.sqrt(((allp - c) ** 2).sum(1)).max())
    for g in children:
        if len(g.tris) and (g.tris.max() >= g.n or g.tris.min() < 0):
            raise OgfError('index out of range')
        if g.n and int(g.bones[:, :g.links].max()) >= len(bones):
            raise OgfError('vertex bone index out of range')
    head = struct.pack(Header.FMT, 4, MT_SKELETON_RIGID, 0, *lo.tolist(), *hi.tolist(), *c.tolist(), r)
    names_chunk = struct.pack('<I', len(bones)) + b''.join(
        n.encode('latin1') + b'\0' + p.encode('latin1') + b'\0' + obb for n, p, obb, _ in bones)
    ik_chunk = b''.join(ik for _, _, _, ik in bones)
    body = write_chunks([[i, write_chunks(g.to_chunks())] for i, g in enumerate(children)])
    return write_chunks([[HEADER, head], [S_DESC, DESC], [CHILDREN, body],
                         [S_BONE_NAMES, names_chunk], [S_IKDATA, ik_chunk]])


def rigid_inverse(m):
    """Inverse of a 4x4 rigid transform (rotation + translation)."""
    out = np.eye(4)
    r = m[:3, :3].T
    out[:3, :3] = r
    out[:3, 3] = -r @ m[:3, 3]
    return out


def transform_geom(g, m, bone_map):
    """A copy of g moved by the rigid 4x4 m (column vectors) with its bone
    indices renumbered through bone_map (dict or array: old id -> new id)."""
    r = m[:3, :3]
    P = (g.P.astype(np.float64) @ r.T) + m[:3, 3]
    with np.errstate(invalid='ignore', over='ignore'):
        N, T, B = ((getattr(g, k).astype(np.float64) @ r.T) for k in 'NTB')
    # some source models carry non-finite normals / tangents: keep them as they were
    N, T, B = (np.where(np.isfinite(getattr(g, k)).all(1, keepdims=True), v, getattr(g, k))
               for k, v in zip('NTB', (N, T, B)))
    lut = np.zeros(max(int(g.bones.max()) + 1, 1), np.int64) if g.n else np.zeros(1, np.int64)
    if isinstance(bone_map, dict):
        lut[:] = -1
        for a, b in bone_map.items():
            if a < len(lut):
                lut[a] = b
    else:
        lut = np.asarray(bone_map, np.int64)
    nb = lut[g.bones.astype(np.int64)]
    live = g.weights > 0
    live[:, 0] = True
    if (nb[live] < 0).any():
        raise OgfError('a vertex uses a bone that is not in the new skeleton')
    nb = np.where(nb < 0, nb[:, :1], nb)
    out = Geom.new(g.texture, g.shader, P, N, T, B, g.uv, nb.astype(np.uint16), g.weights, g.tris, g.links)
    return out
