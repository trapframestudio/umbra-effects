"""
Fitted stump caps for the ZGO mesh baker (PLAN Phase B, item 2).

A cut at section root s (parent bone p) leaves a hole in what remains: the
seam between the triangles of s's subtree and the rest of the mesh. This
module finds those seam loops in the bind pose and builds a cap over each:

  * the rim IS the seam: the same positions and the same (cleaned) bone
    weights as the body's own seam vertices, so the cap closes the hole
    exactly and, skinned to the same bones, deforms with it;
  * rings of interior vertices make a bulge (muscle pushing out of the cut);
    the first ring is jittered into a ragged lip; interior weights blend from
    the rim's toward the anchor bone (p for the stump, s for a limb piece's
    open end), so the middle of the cap stays with the bone that holds it;
  * a short jagged bone stub, weighted to the anchor bone alone, stands out of
    the main loop where the joint is.

Everything here is in the model's bind space with the model's bone ids, and
deterministic: the random jitter is seeded from the seam's own geometry, so
identical seams in different models give identical caps (and files).
parts.py turns the result into attachment OGFs or K_s sub-meshes.
"""
import zlib
import numpy as np
import ogf

# The cut face: ZGO's own stump texture (gamedata/textures/zgo/wounds/stump.dds,
# made by tools/zgo_wounds: clot, muscle, fat ring and skin over the face's UV
# square FLESH_BOX). The stub: the dry skeleton texture's pale skull region,
# which every Anomaly install has (textures_actors.db0).
FLESH_TEX = 'zgo\\wounds\\stump'
BONE_TEX = 'act\\act_skeleton'
SHADER = 'models\\model'
FLESH_BOX = (0.15, 0.15, 0.85, 0.85)      # u0, v0, u1, v1 of the face's texture area
BONE_BOX = (0.02, 0.70, 0.10, 0.76)

WELD = 1e-5            # m: vertices this close are one point (UV / normal seam copies)
MIN_RADIUS = 0.004     # m: smaller loops are not capped
RINGS = (0.16, 0.40, 0.64, 0.86)          # interior rings (fraction of the way to the centre)
STUB_SIDES = 7


class Loop:
    """One closed seam loop, ordered along the remaining surface's boundary.
    P (k,3) float64 bind positions; bones (k,4) u16 / weights (k,4) of the body's
    seam vertices; child: the source sub-mesh it came from."""

    def __init__(self, P, bones, weights, child):
        self.P, self.bones, self.weights, self.child = P, bones, weights, child

    @property
    def perimeter(self):
        return float(np.linalg.norm(self.P - np.roll(self.P, -1, 0), axis=1).sum())


def weld(P):
    """Welded id of every vertex (same position = same id)."""
    q = np.round(np.asarray(P, np.float64) / WELD).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return inv.ravel()


def seam_loops(g, removed_mask):
    """Closed seam loops of one source sub-mesh g when the triangles in
    removed_mask go: lists of original vertex ids (one per welded position,
    taken from the remaining side), each ordered along the boundary of the
    remaining surface (its own winding)."""
    if not removed_mask.any() or removed_mask.all():
        return []
    wid = weld(g.P)
    n = int(wid.max()) + 1
    T = wid[g.tris]
    keep = ~removed_mask
    tk, orig = T[keep], g.tris[keep]
    a = np.concatenate([tk[:, 0], tk[:, 1], tk[:, 2]])
    b = np.concatenate([tk[:, 1], tk[:, 2], tk[:, 0]])
    oa = np.concatenate([orig[:, 0], orig[:, 1], orig[:, 2]])
    tr = T[removed_mask]
    ra = np.concatenate([tr[:, 0], tr[:, 1], tr[:, 2]])
    rb = np.concatenate([tr[:, 1], tr[:, 2], tr[:, 0]])
    rem_keys = np.unique(np.minimum(ra, rb) * n + np.maximum(ra, rb))
    keys = np.minimum(a, b) * n + np.maximum(a, b)
    on = np.isin(keys, rem_keys) & (a != b)
    if not on.any():
        return []
    rep = {}
    nxt = {}
    for x, y, ox in zip(a[on].tolist(), b[on].tolist(), oa[on].tolist()):
        rep.setdefault(x, ox)
        nxt.setdefault(x, []).append(y)
    used = set()
    loops = []
    for start in sorted(nxt):
        for first in nxt[start]:
            if (start, first) in used:
                continue
            loop, cur, prev = [start], first, start
            used.add((start, first))
            closed = False
            while len(loop) <= len(rep) + 1:
                if cur == start:
                    closed = True
                    break
                loop.append(cur)
                cand = [y for y in nxt.get(cur, []) if (cur, y) not in used]
                if not cand:
                    break
                prev, cur = cur, cand[0]
                used.add((prev, cur))
            if closed and len(loop) >= 3 and all(v in rep for v in loop):
                loops.append([rep[v] for v in loop])
    return loops


def section_loops(model, labels, removed_sections):
    """Every seam loop (Loop objects) a cut removing removed_sections leaves,
    over all source sub-meshes, largest first; and the centroid of what goes."""
    out, gone = [], []
    rs = np.array(sorted(removed_sections), np.int64)
    for ci, g in enumerate(model.children):
        rem = np.isin(labels[ci], rs)
        if rem.any():
            gone.append(g.P[np.unique(g.tris[rem])].astype(np.float64))
        for ids in seam_loops(g, rem):
            ids = np.array(ids, np.int64)
            out.append(Loop(g.P[ids].astype(np.float64), g.bones[ids].copy(), g.weights[ids].copy(), ci))
    out.sort(key=lambda lp: -lp.perimeter)
    centre = np.concatenate(gone).mean(0) if gone else None
    return out, centre


# ---------------------------------------------------------------- geometry

def _seed(P, salt):
    return zlib.crc32(np.round(np.asarray(P, np.float64) * 1e4).astype(np.int64).tobytes() + salt.encode())


def _blend(bones, weights, t, anchor):
    """Rim weights scaled by (1-t) plus t on the anchor bone, top 4."""
    acc = {}
    for b, w in zip(bones.tolist(), weights.tolist()):
        if w > 0:
            acc[b] = acc.get(b, 0.0) + w * (1 - t)
    acc[anchor] = acc.get(anchor, 0.0) + t
    top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
    s = sum(w for _, w in top)
    return [b for b, _ in top], [w / s for _, w in top]


def _vertex_normals(P, tris):
    N = np.zeros_like(P)
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(N, tris[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(ln > 1e-12, ln, 1)


def _orient(P, tris, face):
    """Flip triangles so cross(b-a, c-a) points along face (the engine's
    front-face convention, checked on the stock models)."""
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    bad = (np.cross(b - a, c - a) @ face) < 0
    tris = tris.copy()
    tris[bad] = tris[bad][:, [0, 2, 1]]
    return tris


def _ear_clip(xy):
    """Triangles of a simple CCW polygon (indices), or None."""
    idx = list(range(len(xy)))
    out = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 10 * len(xy):
        guard += 1
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = xy[i0], xy[i1], xy[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            inside = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = xy[j]
                if cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0:
                    inside = True
                    break
            if not inside:
                out.append((i0, i1, i2))
                idx.pop(k)
                break
        else:
            return None
    if len(idx) == 3:
        out.append(tuple(idx))
    return out if len(out) == len(xy) - 2 else None


class Surface:
    """Vertex arrays + triangles in bind space (float64), weights as lists."""

    def __init__(self):
        self.P, self.uv, self.bw, self.tris = [], [], [], []

    def add(self, p, uv, bones, weights):
        self.P.append(np.asarray(p, np.float64))
        self.uv.append(uv)
        self.bw.append((list(bones), list(weights)))
        return len(self.P) - 1

    def geom(self, texture, shader):
        if not self.tris:
            return None
        P = np.array(self.P)
        tris = np.array(self.tris, np.int64)
        N = _vertex_normals(P, tris)
        n = len(P)
        bones = np.zeros((n, 4), np.int64)
        w = np.zeros((n, 4), np.float64)
        for i, (bb, ww) in enumerate(self.bw):
            bones[i, :len(bb)] = bb
            bones[i, len(bb):] = bb[0]
            w[i, :len(ww)] = ww
        uv = np.array(self.uv, np.float64)
        # tangent frame from the planar mapping
        T, B = _tangents(P, N, uv, tris)
        return ogf.Geom.new(texture, shader, P, N, T, B, uv, bones.astype(np.uint16), w, tris)


def _tangents(P, N, uv, tris):
    """Per-vertex dP/du, dP/dv (the stock models' T / B convention)."""
    T = np.zeros_like(P)
    B = np.zeros_like(P)
    p0, p1, p2 = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    u0, u1, u2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    e1, e2, d1, d2 = p1 - p0, p2 - p0, u1 - u0, u2 - u0
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(det) > 1e-12, 1 / np.where(det == 0, 1, det), 0)[:, None]
    du = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    dv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for k in range(3):
        np.add.at(T, tris[:, k], du)
        np.add.at(B, tris[:, k], dv)
    out = []
    for X in (T, B):
        X = X - (X * N).sum(1, keepdims=True) * N
        ln = np.linalg.norm(X, axis=1, keepdims=True)
        fallback = np.cross(N, np.array([0.0, 1.0, 0.0]))
        X = np.where(ln > 1e-9, X / np.where(ln > 1e-9, ln, 1), fallback)
        out.append(X)
    return out


class Cap:
    """Cap geometry of one cut side: face (flesh) and stub (bone) surfaces,
    plus what the runtime may want to know."""

    def __init__(self):
        self.face, self.stub = Surface(), Surface()
        self.loops = 0
        self.normal = None        # the main loop's facing direction
        self.centre = None
        self.radius = 0.0


def build(loops, toward, anchor, joint, salt, cap=None):
    """Caps over every loop. toward: a point on the side the cap must face
    (the removed part's centroid for a stump, the body's for a limb piece);
    anchor: bone id the middle and the stub are weighted to; joint: bind
    position of the cut root (where the bone stub stands)."""
    cap = cap or Cap()
    for li, lp in enumerate(loops):
        _one(cap, lp, toward, anchor, joint if li == 0 else None, salt + ':%d' % li, main=(li == 0))
    return cap


def _angles(D, U, V, monotonic=False):
    """Unwrapped angle about the centre of each point (rows of D = point - c);
    monotonic: never step back (a zigzag rim keeps its previous angle)."""
    a = np.unwrap(np.arctan2(D @ V, D @ U))
    if monotonic:
        a = np.maximum.accumulate(a)
        a = np.minimum(a, a[0] + 2 * np.pi - 1e-9)
    return a


def _is_star(D, U, V):
    """Is the CCW polygon (rows of D, relative to the centre) star-shaped
    about the centre: angles strictly increasing, once around?"""
    a = np.unwrap(np.arctan2(D @ V, D @ U))
    steps = np.diff(np.append(a, a[0] + 2 * np.pi))
    return bool((steps > 1e-6).all()) and abs(a[-1] - a[0]) < 2 * np.pi


def _zip(S, a, pa, b, pb):
    """Stitch two closed CCW loops (outer a, inner b) parametrised by
    increasing angles pa / pb (both starting near the same angle)."""
    ka, kb = len(a), len(b)
    pa = np.append(pa, pa[0] + 2 * np.pi)
    pb = np.append(pb, pb[0] + 2 * np.pi)
    i = j = 0
    while i < ka or j < kb:
        if j >= kb or (i < ka and pa[i + 1] <= pb[j + 1]):
            S.tris.append((a[i % ka], a[(i + 1) % ka], b[j % kb]))
            i += 1
        else:
            S.tris.append((a[i % ka], b[(j + 1) % kb], b[j % kb]))
            j += 1


def _one(cap, lp, toward, anchor, joint, salt, main):
    P = lp.P
    k = len(P)
    c0 = P.mean(0)
    d = P - c0
    w, v = np.linalg.eigh(d.T @ d)
    n = v[:, 0]
    U = v[:, 2]
    face = (toward - c0) if toward is not None else n
    if n @ face < 0:
        n = -n
    V = np.cross(n, U)
    x2, y2 = d @ U, d @ V
    area2 = float((x2 * np.roll(y2, -1) - np.roll(x2, -1) * y2).sum())
    order = np.arange(k)
    if area2 < 0:
        order = order[::-1]
        x2, y2 = x2[order], y2[order]
        area2 = -area2
    P = P[order]
    rb, rw = lp.bones[order], lp.weights[order]
    # polygon centroid (in-plane), lifted to the mean plane
    if area2 > 1e-10:
        cr = x2 * np.roll(y2, -1) - np.roll(x2, -1) * y2
        cx = float(((x2 + np.roll(x2, -1)) * cr).sum() / (3 * area2))
        cy = float(((y2 + np.roll(y2, -1)) * cr).sum() / (3 * area2))
    else:
        cx, cy = float(x2.mean()), float(y2.mean())
    c = c0 + cx * U + cy * V
    rx, ry = x2 - cx, y2 - cy
    rad = np.hypot(rx, ry)
    r_mean = float(rad.mean())
    if r_mean < MIN_RADIUS:
        return
    r_max = float(rad.max())
    rng = np.random.default_rng(_seed(P, salt))
    H = float(np.clip(0.22 * r_mean, 0.004, 0.03))
    S = cap.face
    u0, v0, u1, v1 = FLESH_BOX

    def uv_of(p):
        q = p - c
        return (u0 + (u1 - u0) * (0.5 + 0.5 * float(q @ U) / r_max),
                v0 + (v1 - v0) * (0.5 + 0.5 * float(q @ V) / r_max))

    t0 = len(S.tris)
    rim = [S.add(P[i], uv_of(P[i]), rb[i][rw[i] > 0] if (rw[i] > 0).any() else rb[i][:1],
                 rw[i][rw[i] > 0] if (rw[i] > 0).any() else [1.0]) for i in range(k)]
    # the interior is built on the rim smoothed until it is star-shaped about
    # c (a seam follows triangle edges and zigzags); the rim itself is kept
    Q = P.copy()
    smooth = 0
    while not _is_star(Q - c, U, V) and smooth < 40:
        Q = 0.5 * Q + 0.25 * (np.roll(Q, 1, 0) + np.roll(Q, -1, 0))
        smooth += 1
    if _is_star(Q - c, U, V):
        rings = []
        for j, t in enumerate(RINGS):
            h = H * (1 - (1 - t) ** 2)
            ring = []
            for i in range(k):
                jit = rng.uniform(-0.09, 0.09) if j == 0 else rng.uniform(-0.03, 0.03)
                lift = rng.uniform(-0.15, 0.3) * H if j == 0 else rng.uniform(-0.08, 0.08) * H
                p = c + (1 - t) * (1 + jit) * (Q[i] - c) + (h + lift) * n
                bb, ww = _blend(rb[i], rw[i], t, anchor)
                ring.append(S.add(p, uv_of(p), bb, ww))
            rings.append(ring)
        _zip(S, rim, _angles(P - c, U, V, monotonic=True), rings[0], _angles(Q - c, U, V))
        for a, b in zip(rings, rings[1:]):
            for i in range(k):
                i1 = (i + 1) % k
                S.tris.append((a[i], a[i1], b[i1]))
                S.tris.append((a[i], b[i1], b[i]))
        ctr = S.add(c + H * n, uv_of(c), [anchor], [1.0])
        last = rings[-1]
        for i in range(k):
            S.tris.append((last[i], last[(i + 1) % k], ctr))
    else:
        tri = _ear_clip(list(zip(x2.tolist(), y2.tolist())))
        if tri is not None:
            for t3 in tri:
                S.tris.append(tuple(rim[i] for i in t3))
        else:
            ctr = S.add(c + 0.5 * H * n, uv_of(c), [anchor], [1.0])
            for i in range(k):
                S.tris.append((rim[i], rim[(i + 1) % k], ctr))
        H = 0.0
    # front faces look along n (this loop's own facing)
    Pa = np.array(S.P)
    S.tris[t0:] = [tuple(t) for t in _orient(Pa, np.array(S.tris[t0:], np.int64), n).tolist()]
    cap.loops += 1
    if main:
        cap.normal, cap.centre, cap.radius = n, c, r_mean
        if joint is not None:
            _stub(cap.stub, c, n, U, V, x2 - cx, y2 - cy, joint, r_mean, H, anchor, rng)


def _inside(px, py, xs, ys):
    j, inside = len(xs) - 1, False
    for i in range(len(xs)):
        if (ys[i] > py) != (ys[j] > py) and px < (xs[j] - xs[i]) * (py - ys[i]) / (ys[j] - ys[i] + 1e-30) + xs[i]:
            inside = not inside
        j = i
    return inside


def _stub(S, c, n, U, V, xs, ys, joint, r_mean, H, anchor, rng):
    q = joint - c
    bx, by = float(q @ U), float(q @ V)
    if not _inside(bx, by, xs, ys):
        bx, by = 0.0, 0.0
    b0 = c + bx * U + by * V
    rad = float(np.clip(0.2 * r_mean, 0.005, 0.02))
    L = float(np.clip(0.45 * r_mean, 0.008, 0.035))
    radii = rad * (1 + rng.uniform(-0.12, 0.12, STUB_SIDES))
    heights = H + L * rng.uniform(0.55, 1.0, STUB_SIDES)       # a jagged break
    bu0, bv0, bu1, bv1 = BONE_BOX
    base, top = [], []
    for s in range(STUB_SIDES + 1):          # the last column repeats the first (UV seam)
        a = 2 * np.pi * (s % STUB_SIDES) / STUB_SIDES
        off = radii[s % STUB_SIDES] * (np.cos(a) * U + np.sin(a) * V)
        u = bu0 + (bu1 - bu0) * s / STUB_SIDES
        base.append(S.add(b0 + off - (0.3 * H + 0.002) * n, (u, bv1), [anchor], [1.0]))
        top.append(S.add(b0 + off * 0.92 + heights[s % STUB_SIDES] * n, (u, bv0), [anchor], [1.0]))
    # sides wind outward and the end faces +n by construction (CCW about n)
    for s in range(STUB_SIDES):
        S.tris.append((base[s], base[s + 1], top[s + 1]))
        S.tris.append((base[s], top[s + 1], top[s]))
    # the broken end, sunk in the middle (marrow)
    mid = S.add(b0 + (H + 0.55 * L) * n, ((bu0 + bu1) / 2, (bv0 + bv1) / 2), [anchor], [1.0])
    for s in range(STUB_SIDES):
        S.tris.append((top[s], top[s + 1], mid))


