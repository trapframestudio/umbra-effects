"""
Wound sites for the Umbra Effects mesh baker (PLAN Phase C; docs/formats/wounds.md).

Per model and section, a small set of points on the surface where damage
gathers: the runtime maps a hit to the nearest site and grows a wound there.

  * placement: farthest-point sampling on the section's surface, relaxed by a
    few Lloyd steps (an even spread, deterministic: no random numbers), never
    closer than MIN_SPACING; how many comes from the section's area, clamped
    per class (torso 12-20, head 4-6, limbs 1-4);
  * per site: the bone that holds it (largest weight), the bind-space position
    and outward normal, the local thickness (inward ray to where it leaves
    the body), a radius (how far its patch reaches), the depth of the bone
    under it, and tissue hints (skull, chest, abdomen, back, limb, ...).

Glass (gas-mask visors and the like) never carries sites.
Also: bind matrices per skeleton, so the runtime can take a world hit point
into bind space: P_bind = Bind_b * inverse(world bone b) * P_world.
"""
import hashlib
import re
import numpy as np

MIN_SPACING = 0.08                     # m, closest two sites of one section may be
CLASS_COUNTS = {                       # (min, max, surface area per site m^2)
    'body': (12, 20, 0.035),           # torso (never severed)
    'head': (4, 6, 0.012),
    'upper': (2, 4, 0.03),             # thigh, upper arm
    'lower': (1, 2, 0.035),            # forearm, calf
    'end': (1, 1, 0.05),               # hand, foot, paw, toe
}
GLASS = re.compile(r'window|glass|transparent|selflight|lens|visor', re.I)
HEAD = re.compile(r'head|neck|ponytail|jaw|skull', re.I)
HEAD_ROOTS = {'bone01'}                # boar / pseudodog heads (zgo_dismember HEAD_BY_KEY)
END = re.compile(r'hand|foot|toe|paw|finger|horselink|hoof', re.I)
LOWER = re.compile(r'forearm|calf|shin|leg_1|lower', re.I)
LLOYD_STEPS = 6


def section_class(name):
    """body, head, upper, lower or end (a limb's part, by its root's name)."""
    if name == 'body':
        return 'body'
    if HEAD.search(name) or name in HEAD_ROOTS:
        return 'head'
    if END.search(name):
        return 'end'
    if LOWER.search(name):
        return 'lower'
    return 'upper'


def _is_glass(g):
    return bool(GLASS.search(g.shader)) or bool(GLASS.search(g.texture or ''))


def candidates(geoms):
    """Surface sample points of a section: every unique vertex and every
    triangle centroid. Returns P, N, bones (m,4), weights (m,4), area."""
    Ps, Ns, Bs, Ws = [], [], [], []
    area = 0.0
    for g in geoms:
        if not g.n or not len(g.tris):
            continue
        P = g.P.astype(np.float64)
        a, b, c = P[g.tris[:, 0]], P[g.tris[:, 1]], P[g.tris[:, 2]]
        fn = np.cross(b - a, c - a)
        fa = np.linalg.norm(fn, axis=1)
        area += float(fa.sum()) / 2
        ok = fa > 1e-12
        fn = fn[ok] / fa[ok, None]
        q = np.round(P / 1e-4).astype(np.int64)
        _, first = np.unique(q, axis=0, return_index=True)
        first.sort()
        N = g.N.astype(np.float64)
        ln = np.linalg.norm(N, axis=1, keepdims=True)
        N = N / np.where(ln > 1e-9, ln, 1)
        Ps.append(P[first])
        Ns.append(N[first])
        Bs.append(g.bones[first].astype(np.int64))
        Ws.append(g.weights[first].astype(np.float64))
        t = g.tris[ok]
        Ps.append((a[ok] + b[ok] + c[ok]) / 3)
        Ns.append(fn)
        # a centroid takes the weights of its triangle's first vertex
        Bs.append(g.bones[t[:, 0]].astype(np.int64))
        Ws.append(g.weights[t[:, 0]].astype(np.float64))
    if not Ps:
        return None
    return np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Bs), np.concatenate(Ws), area


def place(P, count, spacing=MIN_SPACING, steps=LLOYD_STEPS):
    """Indices into P of up to count evenly spread points (farthest-point
    sampling from the point nearest the centroid, then Lloyd relaxation that
    snaps every site to the sample nearest its cell's centroid)."""
    m = len(P)
    if m == 0 or count <= 0:
        return []
    first = int(np.argmin(((P - P.mean(0)) ** 2).sum(1)))
    sel = [first]
    d = np.sqrt(((P - P[first]) ** 2).sum(1))
    while len(sel) < count:
        i = int(np.argmax(d))
        if d[i] < spacing:
            break
        sel.append(i)
        d = np.minimum(d, np.sqrt(((P - P[i]) ** 2).sum(1)))
    sel = np.array(sel)
    for _ in range(steps):
        D = ((P[:, None, :] - P[None, sel, :]) ** 2).sum(2)
        cell = D.argmin(1)
        new = sel.copy()
        for k in range(len(sel)):
            mem = np.nonzero(cell == k)[0]
            if len(mem) == 0:
                continue
            c = P[mem].mean(0)
            new[k] = mem[int(np.argmin(((P[mem] - c) ** 2).sum(1)))]
        if (new == sel).all():
            break
        sel = new
    # keep the spacing (Lloyd may pull two sites together): drop the later one
    keep = []
    for i in sel.tolist():
        if all(np.sqrt(((P[i] - P[j]) ** 2).sum()) >= spacing * 0.999 for j in keep) and i not in keep:
            keep.append(i)
    return keep


def model_triangles(model):
    """All non-glass triangles of the source model (bind space): a, e1, e2, face normals."""
    A, E1, E2 = [], [], []
    for g in model.children:
        if _is_glass(g) or not len(g.tris):
            continue
        P = g.P.astype(np.float64)
        a, b, c = P[g.tris[:, 0]], P[g.tris[:, 1]], P[g.tris[:, 2]]
        A.append(a)
        E1.append(b - a)
        E2.append(c - a)
    if not A:
        return None
    a, e1, e2 = np.concatenate(A), np.concatenate(E1), np.concatenate(E2)
    fn = np.cross(e1, e2)
    return a, e1, e2, fn


def thickness(tris, o, d, max_t=0.8, skip=0.015):
    """Distance from o along d (unit) to the first surface that faces away
    from o (where the ray leaves the body), or None. Exits closer than skip
    (eyelids, teeth, a mask's inner layer) count only when nothing else does."""
    a, e1, e2, fn = tris
    h = np.cross(d, e2)
    det = (e1 * h).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    s = o - a
    u = (s * h).sum(1) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = (e2 * q).sum(1) * inv
    exit_ = (fn @ d) > 0
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0.003) & (t < max_t) & exit_
    if not hit.any():
        return None
    far = hit & (t >= skip)
    return float(t[far].min() if far.any() else t[hit].min())


def bone_segment(skel, b):
    """Start and end of bone b's shaft in bind space (origin to its children's mean)."""
    p0 = skel.pos(b)
    kids = [skel.pos(c) for c in skel.bones[b].children]
    if kids:
        p1 = np.mean(kids, 0)
        if np.linalg.norm(p1 - p0) > 0.01:
            return p0, p1
    return p0, p0


def seg_dist(p, a, b):
    ab = b - a
    L = float(ab @ ab)
    t = 0.0 if L < 1e-12 else float(np.clip((p - a) @ ab / L, 0, 1))
    return float(np.linalg.norm(p - (a + t * ab)))


def tissue(cls, bone, n):
    """Tissue hint letters: what lies under the site (docs/formats/wounds.md)."""
    b = bone.lower()
    if cls == 'head' or 'head' in b or 'jaw' in b or 'eye' in b:
        if 'neck' in b:
            return 'n'
        return 'f' if ('jaw' in b or n[2] > 0.55) else 's'
    if 'neck' in b:
        return 'n'
    if any(x in b for x in ('hand', 'finger', 'foot', 'toe', 'paw')):
        return 'x'
    if cls in ('upper', 'lower', 'end'):
        return 'l'
    side = 'F' if n[2] > 0.3 else ('B' if n[2] < -0.3 else 'S')
    if 'clavicle' in b or 'upperarm' in b or 'arm' in b:
        return 'h' + side
    if 'pelvis' in b or 'thigh' in b or 'tail' in b or 'leg' in b:
        return 'p' + side
    if side == 'B':
        return 'k' + side
    if 'spine1' in b or 'spine2' in b or 'spine3' in b or 'chest' in b:
        return 'c' + side
    return 'a' + side


def bake_sites(model, kids, info):
    """{section name: [site dict, ...]} for every section with surface."""
    skel = model.skeleton
    tris = model_triangles(model)
    by_sec = {}
    for k in kids:
        if _is_glass(k):
            continue
        by_sec.setdefault(k.section, []).append(k)
    out = {}
    for sec, geoms in sorted(by_sec.items()):
        name = 'body' if sec < 0 else skel.bones[sec].name
        cls = section_class(name)
        c = candidates(geoms)
        if c is None:
            continue
        P, N, B, W, area = c
        lo, hi, per = CLASS_COUNTS[cls]
        count = int(np.clip(round(area / per), lo, hi))
        idx = place(P, count)
        if not idx:
            continue
        S = P[idx]
        # how far each site's patch reaches: 90th percentile of its cell
        D = ((P[:, None, :] - S[None, :, :]) ** 2).sum(2)
        cell = D.argmin(1)
        sites = []
        for j, i in enumerate(idx):
            mem = np.sqrt(D[cell == j, j])
            radius = float(np.clip(np.percentile(mem, 90) if len(mem) else 0.05, 0.02, 0.15))
            n = N[i] / max(np.linalg.norm(N[i]), 1e-9)
            bone = int(B[i][int(np.argmax(W[i]))])
            t = thickness(tris, P[i] + 0.001 * n, -n) if tris is not None else None
            a, b = bone_segment(skel, bone)
            depth = seg_dist(P[i], a, b)
            if t is None:
                t = 2 * depth if depth > 0.005 else 0.05
            depth = min(depth, t)
            sites.append({'bone': bone, 'p': P[i], 'n': n, 'thick': t, 'radius': radius, 'depth': depth,
                          'hint': tissue(cls, skel.bones[bone].name, n)})
        out[name] = sites
    return out


def encode_sites(sites):
    """'bone,x,y,z,nx,ny,nz,thick,radius,depth,hint;...': position, thickness,
    radius and depth in mm, the normal x100 (docs/formats/wounds.md)."""
    out = []
    for s in sites:
        p = np.round(s['p'] * 1000).astype(int)
        n = np.round(s['n'] * 100).astype(int)
        out.append('%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s' % (
            s['bone'], p[0], p[1], p[2], n[0], n[1], n[2], round(s['thick'] * 1000), round(s['radius'] * 1000),
            round(s['depth'] * 1000), s['hint']))
    return ';'.join(out)


def decode_sites(text):
    """Inverse of encode_sites (metres, unit normal), for tests and tools."""
    out = []
    for item in filter(None, text.split(';')):
        f = item.split(',')
        v = [int(x) for x in f[:10]]
        n = np.array(v[4:7], np.float64)
        n /= max(np.linalg.norm(n), 1e-9)
        out.append({'bone': v[0], 'p': np.array(v[1:4]) / 1000, 'n': n,
                    'thick': v[7] / 1000, 'radius': v[8] / 1000, 'depth': v[9] / 1000, 'hint': f[10]})
    return out


def quat(r):
    """Unit quaternion (w, x, y, z), w >= 0, of a rotation matrix (column vectors)."""
    t = r[0, 0] + r[1, 1] + r[2, 2]
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [0.25 * s, (r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [(r[2, 1] - r[1, 2]) / s, 0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s]
    elif r[1, 1] > r[2, 2]:
        s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [(r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [(r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    q /= np.linalg.norm(q)
    return -q if q[0] < 0 else q


def quat_matrix(q):
    """Rotation matrix (column vectors) of a quaternion (w, x, y, z), normalised first."""
    w, x, y, z = np.asarray(q, np.float64) / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def encode_bind(skel):
    """Bind pose (model space) of every bone, in bone id order:
    'name,parent,qw,qx,qy,qz,cx,cy,cz;...' with the rotation as a unit
    quaternion x10000 and the origin in 0.1 mm; parent is a bone id, -1 for
    the root (docs/formats/wounds.md)."""
    out = []
    for b in skel.bones:
        q = np.round(quat(b.world[:3, :3]) * 10000).astype(int)
        c = np.round(b.world[:3, 3] * 10000).astype(int)
        out.append('%s,%d,%s,%s' % (b.name, b.parent, ','.join(map(str, q.tolist())), ','.join(map(str, c.tolist()))))
    return ';'.join(out)


def decode_bind(text):
    """[(name, parent, 4x4 world bind)] from encode_bind."""
    out = []
    for item in filter(None, text.split(';')):
        f = item.split(',')
        m = np.eye(4)
        m[:3, :3] = quat_matrix([int(x) / 10000 for x in f[2:6]])
        m[:3, 3] = [int(x) / 10000 for x in f[6:9]]
        out.append((f[0], int(f[1]), m))
    return out
