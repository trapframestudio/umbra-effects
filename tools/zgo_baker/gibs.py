"""
Body gibs: the pieces an explosion tears out of a body, cut from that body's
own model, so they wear its skin, outfit and gear (docs/formats/gibs.md).

One skeleton model per baked model, gamedata/meshes/zgo/baked/gibs/<h2>/<h12>.ogf:
a root bone "zgo_gibs" and bones gib_1..gib_N. Piece i is every surface layer
of one section inside a torn outline around a centre on the body (only the
triangles facing out there, clipped exactly to the outline), closed underneath
by raw-flesh walls and a floor. It is stored in its own frame: origin halfway
down the piece, z along the surface normal. All its vertices are weighted 100%
to its bone, so the runtime shows one piece per attachment (every other bone
hidden: CSkeletonX drops a sub-mesh whose bones are all hidden) and drives that
bone's matrix while the piece flies (zgo_debris.spawn_gibs).

Centres: up to MAX_GIBS of the model's wound sites (wounds.bake_sites), far
apart (farthest-point order from the site nearest the middle of the body), so
every region has pieces of its own. Hands and feet give none (their fingers
and toes make poor chunks).

The parts line records, per piece, the bone it came from and its frame in that
bone's bind frame (encode_frames: the bind-pose format of wounds.encode_bind,
so zgo_bake.decode_skel reads it). The runtime puts a piece exactly where it
was on the body (bone's world matrix * that frame) and prefers the pieces
nearest the blast or cut.

Everything is deterministic (outline noise is seeded from the site), so every
machine bakes the same bytes for the same mod list.
"""
import numpy as np

import caps as capmod
import ogf
import wounds

GIB_DIR = 'zgo\\baked\\gibs'
MAX_GIBS = 14
R_MIN, R_MAX = 0.05, 0.085          # m: outline radius, fist to palm sized pieces
DEPTH_MIN, DEPTH_MAX = 0.02, 0.05   # m: flesh under the surface
FLOOR = 0.65                        # flesh floor width against the outline
FACING = 0.2                        # cosine: triangles facing out at the centre
ABOVE = 0.03                        # m: highest a piece reaches over the surface (pouches, collars stay)
OUTLINE_K = 9                       # corners of the torn outline
NO_GIBS = ('end',)                  # wounds.section_class values that give no centres
MIN_TOP_TRIS = 3
ISLAND = 0.08                       # a loose bit of surface smaller than this share of the outline is dropped
MIN_COVER = 0.3                     # a piece whose surface covers less of its outline is not made


def pick(sites, n=MAX_GIBS):
    """[(section name, site)]: up to n sites spread over the body, always the same for the same model."""
    allv = [(name, s) for name in sorted(sites) if wounds.section_class(name) not in NO_GIBS for s in sites[name]]
    if not allv:
        return []
    P = np.array([s['p'] for _, s in allv], np.float64)
    start = int(np.argmin(((P - P.mean(0)) ** 2).sum(1)))
    chosen = [start]
    d = ((P - P[start]) ** 2).sum(1)
    while len(chosen) < min(n, len(allv)):
        i = int(np.argmax(d))
        if d[i] <= 1e-8:
            break
        chosen.append(i)
        d = np.minimum(d, ((P - P[i]) ** 2).sum(1))
    return [allv[i] for i in chosen]


def tangent_axes(n):
    n = np.asarray(n, np.float64)
    n = n / max(np.linalg.norm(n), 1e-9)
    U = np.cross(n, [0.0, 1.0, 0.0] if abs(n[1]) < 0.9 else [1.0, 0.0, 0.0])
    U /= np.linalg.norm(U)
    return U, np.cross(n, U), n


def frame(c, n, depth):
    """Piece frame -> bind space (4x4, column vectors): origin halfway down, z = n."""
    U, V, n = tangent_axes(n)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2] = U, V, n
    M[:3, 3] = np.asarray(c, np.float64) - 0.5 * depth * n
    return M


def _hull(pts):
    """Convex hull, counter-clockwise (monotone chain)."""
    p = sorted(map(tuple, pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0:
            hi.pop()
        hi.append(q)
    return np.array(lo[:-1] + hi[:-1], np.float64)


def outline(c, r, k=OUTLINE_K):
    """Torn outline (convex, counter-clockwise, in the tangent plane), seeded from the centre."""
    rng = np.random.default_rng(capmod._seed(c, 'gib'))
    ang = (np.arange(k) + rng.uniform(-0.3, 0.3, k)) * (2 * np.pi / k)
    rad = r * rng.uniform(0.72, 1.0, k)
    return _hull(np.c_[np.cos(ang) * rad, np.sin(ang) * rad])


def _clip(poly, edges, info):
    """Sutherland-Hodgman: poly = [(key, xy)] against convex CCW edges [(e0, e1)].
    A new corner's key is ('x', a, b, edge) for the original-side keys a < b
    (so the triangles on both sides of an edge share it); info[key] = (a, b, t)."""
    for ei, (e0, e1) in enumerate(edges):
        if not poly:
            break
        d = e1 - e0
        out = []
        side = [d[0] * (p[1][1] - e0[1]) - d[1] * (p[1][0] - e0[0]) for p in poly]
        for i in range(len(poly)):
            sa, sb = side[i - 1], side[i]
            if sb >= 0:
                if sa < 0:
                    out.append(_cross_pt(poly[i - 1], poly[i], sa, sb, ei, info))
                out.append(poly[i])
            elif sa >= 0:
                out.append(_cross_pt(poly[i - 1], poly[i], sa, sb, ei, info))
        poly = out
    return poly


def _cross_pt(a, b, sa, sb, ei, info):
    t = sa / (sa - sb)
    if repr(b[0]) < repr(a[0]):
        a, b, t = b, a, 1 - t
    key = ('x', a[0], b[0], ei)
    info[key] = (a[0], b[0], t)
    return key, a[1] + t * (b[1] - a[1])


def cut(kids, site):
    """(top geoms in bind space, flesh Surface, depth) of one piece, or None.
    kids: the sub-meshes of the site's section."""
    c, n = np.asarray(site['p'], np.float64), np.asarray(site['n'], np.float64)
    U, V, n = tangent_axes(n)
    r = float(np.clip(0.75 * site['radius'] + 0.025, R_MIN, R_MAX))
    depth = float(np.clip(0.5 * site['thick'], DEPTH_MIN, DEPTH_MAX))
    hull = outline(c, r)
    edges = [(hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull))]
    tops = []
    for g in kids:
        if g.n == 0 or wounds._is_glass(g):
            continue
        P = g.P.astype(np.float64)
        T3 = g.tris
        cen = P[T3].mean(1)
        fn = np.cross(P[T3[:, 1]] - P[T3[:, 0]], P[T3[:, 2]] - P[T3[:, 0]])
        fl = np.linalg.norm(fn, axis=1)
        fn = fn / np.maximum(fl, 1e-12)[:, None]
        rel = P - c
        uv2 = np.c_[rel @ U, rel @ V]
        hv = (P - c) @ n
        near = (np.linalg.norm(uv2[T3], axis=2).min(1) < r * 1.05) | (np.linalg.norm(cen - c, axis=1) < r)
        keep = near & (fl > 1e-12) & (fn @ n >= FACING) & (hv[T3].min(1) > -depth) & (hv[T3].max(1) < ABOVE)
        sel = np.nonzero(keep)[0]
        if not len(sel):
            continue
        attrs = np.c_[P, g.N.astype(np.float64), g.T.astype(np.float64), g.B.astype(np.float64),
                      g.uv.astype(np.float64)]
        info, memo, index, rows, tris = {}, {}, {}, [], []

        def value(key):
            v = memo.get(key)
            if v is None:
                if key[0] == 'o':
                    v = attrs[key[1]]
                else:
                    ka, kb, t = info[key]
                    v = (1 - t) * value(ka) + t * value(kb)
                memo[key] = v
            return v

        def vid(key):
            i = index.get(key)
            if i is None:
                i = index[key] = len(rows)
                rows.append(value(key))
            return i
        for ti in sel:
            poly = _clip([(('o', int(v)), uv2[v]) for v in T3[ti]], edges, info)
            if len(poly) < 3:
                continue
            ids = [vid(k) for k, _ in poly]
            for j in range(1, len(ids) - 1):
                if len({ids[0], ids[j], ids[j + 1]}) == 3:
                    tris.append([ids[0], ids[j], ids[j + 1]])
        if not tris:
            continue
        A = np.array(rows, np.float64)
        tris = _drop_islands(A[:, 0:3], np.array(tris, np.int64), c, U, V, ISLAND * np.pi * r * r)
        if not len(tris):
            continue
        used, inv = np.unique(tris, return_inverse=True)
        A, tris = A[used], inv.reshape(-1, 3)
        Nn = A[:, 3:6] / np.maximum(np.linalg.norm(A[:, 3:6], axis=1, keepdims=True), 1e-9)
        m = len(A)
        tops.append(ogf.Geom.new(g.texture, g.shader, A[:, 0:3], Nn, A[:, 6:9], A[:, 9:12], A[:, 12:14],
                                 np.zeros((m, 4), np.uint16), np.c_[np.ones(m), np.zeros((m, 3))], tris, 1))
    if not tops or sum(len(t.tris) for t in tops) < MIN_TOP_TRIS:
        return None
    if sum(_flat_area(t.P, t.tris, c, U, V).sum() for t in tops) < MIN_COVER * np.pi * r * r:
        return None
    side = capmod.Surface()
    fx, fy, fX, fY = capmod.FLESH_BOX

    def flesh_uv(p):
        d = p - c
        return (fx + (fX - fx) * (0.5 + 0.5 * float(d @ U) / r), fy + (fY - fy) * (0.5 + 0.5 * float(d @ V) / r))

    def floor_pt(p):
        d = p - c
        d = d - (d @ n) * n
        return c + FLOOR * d - depth * n

    # every top triangle in the tangent plane: a wall goes only on an open edge,
    # one with no top surface (of any layer) just outside it; edges of holes and
    # of layers lying under another (a shirt under a vest) get none
    flat = np.concatenate([np.c_[(t.P.astype(np.float64) - c) @ U, (t.P.astype(np.float64) - c) @ V][t.tris]
                           for t in tops])

    def covered(q):
        a, b, d = flat[:, 0], flat[:, 1], flat[:, 2]
        den = (b[:, 1] - d[:, 1]) * (a[:, 0] - d[:, 0]) + (d[:, 0] - b[:, 0]) * (a[:, 1] - d[:, 1])
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1.0)
        w0 = ((b[:, 1] - d[:, 1]) * (q[0] - d[:, 0]) + (d[:, 0] - b[:, 0]) * (q[1] - d[:, 1])) / den
        w1 = ((d[:, 1] - a[:, 1]) * (q[0] - d[:, 0]) + (a[:, 0] - d[:, 0]) * (q[1] - d[:, 1])) / den
        return bool((ok & (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)).any())

    for top in tops:
        P = top.P.astype(np.float64)
        Q = np.c_[(P - c) @ U, (P - c) @ V]
        wid = capmod.weld(P)
        cnt = {}
        for t in top.tris.tolist():
            for x, y in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
                cnt[k] = cnt.get(k, 0) + 1
        for t in top.tris.tolist():
            for x, y, z in ((t[0], t[1], t[2]), (t[1], t[2], t[0]), (t[2], t[0], t[1])):
                if cnt[(min(wid[x], wid[y]), max(wid[x], wid[y]))] != 1:
                    continue
                e = Q[y] - Q[x]
                el = float(np.hypot(e[0], e[1]))
                if el > 1e-6:
                    out = np.array([e[1], -e[0]]) / el
                    if out @ (Q[z] - Q[x]) > 0:
                        out = -out
                    if covered((Q[x] + Q[y]) / 2 + 0.004 * out):
                        continue
                pa, pb = P[x], P[y]
                fa, fb = floor_pt(pa), floor_pt(pb)
                ids = [side.add(q, flesh_uv(q), [0], [1.0]) for q in (pa, pb, fb, fa)]
                # outward-facing wall (the top runs a->b counter-clockwise seen from outside)
                side.tris += [[ids[0], ids[3], ids[2]], [ids[0], ids[2], ids[1]]]
                cid = side.add(c - depth * n, flesh_uv(c), [0], [1.0])
                side.tris.append([ids[3], cid, ids[2]])
    return tops, side, depth


def _flat_area(P, tris, c, U, V):
    """Area of every triangle seen along the normal (tangent plane)."""
    Q = np.c_[(np.asarray(P, np.float64) - c) @ U, (np.asarray(P, np.float64) - c) @ V]
    a, b, d = Q[tris[:, 0]], Q[tris[:, 1]], Q[tris[:, 2]]
    return 0.5 * np.abs((b[:, 0] - a[:, 0]) * (d[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (d[:, 0] - a[:, 0]))


def _drop_islands(P, tris, c, U, V, min_area):
    """The triangles of the connected parts (welded) whose flat area reaches min_area."""
    if not len(tris):
        return tris
    wid = capmod.weld(P)
    parent = list(range(int(wid.max()) + 1))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for t in tris:
        a = find(int(wid[t[0]]))
        for v in t[1:]:
            b = find(int(wid[v]))
            if a != b:
                parent[b] = a
    comp = np.array([find(int(wid[t[0]])) for t in tris])
    area = _flat_area(P, tris, c, U, V)
    keep = np.zeros(len(tris), bool)
    for k in np.unique(comp):
        m = comp == k
        if area[m].sum() >= min_area:
            keep |= m
    return tris[keep]


def piece(kids, site):
    """(geoms in bind space, bind -> piece 4x4) of one piece, or None."""
    made = cut(kids, site)
    if made is None:
        return None
    tops, side, depth = made
    geoms = tops + [g for g in [side.geom(capmod.FLESH_TEX, capmod.SHADER)] if g is not None]
    return geoms, ogf.rigid_inverse(frame(site['p'], site['n'], depth))


def gib_model(model, kids, sites, n=MAX_GIBS):
    """(model bytes, [(source bone name, piece -> bone bind frame 4x4)]) or None.
    kids: the baked model's sub-meshes (each with .section); sites: wounds.bake_sites."""
    skel = model.skeleton
    by_sec = {}
    for k in kids:
        by_sec.setdefault('body' if k.section < 0 else skel.bones[k.section].name, []).append(k)
    bones = [('zgo_gibs', '', ogf.obb_bytes(np.zeros(3), np.zeros(3), 0.01),
              ogf.ik_record(ogf.default_bone('zgo_gibs')))]
    geoms, frames = [], []
    for sec, s in pick(sites, n):
        made = piece(by_sec.get(sec, []), s)
        if made is None:
            continue
        parts_i, to_local = made
        j = len(bones)
        lut = np.full(max(len(skel.bones), 1), j, np.int64)
        local = [ogf.transform_geom(g, to_local, lut) for g in parts_i]
        P = np.concatenate([g.P for g in local]).astype(np.float64)
        name = 'gib_%d' % j
        bones.append((name, 'zgo_gibs', ogf.obb_bytes(P.min(0), P.max(0), 0.005),
                      ogf.ik_record(ogf.default_bone(name, 'zgo_gibs'))))
        geoms += local
        b = skel.bones[s['bone']]
        frames.append((b.name, ogf.rigid_inverse(b.world) @ ogf.rigid_inverse(to_local)))
    if not geoms:
        return None
    return ogf.build_skeleton_model(bones, geoms), frames


def encode_frames(frames):
    """'bone,0,qw,qx,qy,qz,cx,cy,cz;...' per piece: its source bone and the
    piece frame in that bone's frame, quaternion x10000, origin in 0.1 mm."""
    out = []
    for name, m in frames:
        q = np.round(wounds.quat(m[:3, :3]) * 10000).astype(int)
        c = np.round(m[:3, 3] * 10000).astype(int)
        out.append('%s,0,%s,%s' % (name, ','.join(map(str, q.tolist())), ','.join(map(str, c.tolist()))))
    return ';'.join(out)


def decode_frames(text):
    """[(bone name, 4x4)] from encode_frames (tests)."""
    return [(name, m) for name, _, m in wounds.decode_bind(text)]
