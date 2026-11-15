"""
(experimental, bake.py --experimental-damage) Damage meshes and gib chunks
(PLAN Phase C; docs/formats/damage.md).

D meshes: for every sub-mesh C of the baked model with wound sites in its
section, a copy D (shader zgo\\off, so it draws nothing until the runtime
switches it) whose triangles near the sites are split until no edge is longer
than MAX_EDGE, so a vertex shader can push craters into it. Splitting runs on
the welded surface, so UV seams never crack. Positions stay exactly on the
original surface; new vertices interpolate normals, tangents, UVs and
weights. The integer part of every UV carries a code for the shader:

    u' = u + 4 * code      code = site + 32 * rq
                           site = 1-based index into the section's site list
                           (1..31; 0 = outside every patch, or on the sub-mesh's
                           open border, where it meets the next section's
                           mesh: such vertices must never move)
                           rq = how far out in its patch the vertex lies,
                           1 (centre) .. 7 (rim); the shader makes a bowl of it
    v' = v + 4 * thick     local thickness under the vertex in 2 mm steps
                           (0..255 -> 0..510 mm)
    decode: code = floor((u' + 1.5) / 4), site = code & 31, rq = code >> 5,
            thick = floor((v' + 1.5) / 4) * 0.002
    texture lookup: unchanged with WRAP samplers (the shift is an integer)

which needs the original u, v inside [-1.5, 2.5): each sub-mesh is first moved
by a whole number of tiles to fit; a sub-mesh that can't fit gets no D mesh.

Gib chunks: per section one skeleton model with a root bone and bone
"site_<i>" for site i; site i's chunk is the skin patch around it plus the
crater volume below it (raw-flesh sides and bottom), weighted 100% to its bone,
in the victim's bone frame of that site's bone (docs/formats/damage.md).
"""
import numpy as np
import ogf
import caps as capmod
import parts as partsmod

MAX_EDGE = 0.015
SLIVER = 0.001                     # m, see subdivide
PATCH = 0.06                       # m around a site that gets split (crater r about 6 cm)
CODE_K = 4
SITE_BITS = 32                     # code = site + 32 * rq: sites 1..31, rq 1..7
RQ_STEPS = 7
MAX_VERTS = 65535                  # 16-bit indices in an OGF sub-mesh
CHUNK_DIR = 'zgo\\baked\\chunks'


def _blend(bw_a, bw_b, links):
    acc = {}
    for bones, ws in (bw_a, bw_b):
        for b, w in zip(bones, ws):
            if w > 0:
                acc[b] = acc.get(b, 0.0) + 0.5 * w
    top = sorted(acc.items(), key=lambda kv: -kv[1])[:links]
    s = sum(w for _, w in top) or 1.0
    return [b for b, _ in top], [w / s for _, w in top]


def subdivide(g, centres, radius=PATCH, max_edge=MAX_EDGE):
    """Split every triangle of g that has a corner within radius of one of
    the centres (and its neighbours across split edges, so the mesh stays
    watertight) until such triangles have no edge longer than max_edge
    (slivers excepted, see SLIVER). Returns (parents (k,2) of the new
    vertices in creation order, tris)."""
    P = [tuple(p) for p in g.P.astype(np.float64)]
    C = np.asarray(centres, np.float64).reshape(-1, 3)
    near = (np.sqrt(((g.P.astype(np.float64)[:, None, :] - C[None]) ** 2).sum(2)).min(1) < radius).tolist() \
        if len(C) else [False] * g.n
    R2 = radius * radius
    Cl = [tuple(c) for c in C]

    def close(p):
        return any((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2 < R2 for c in Cl)

    wid = capmod.weld(g.P).tolist()
    nw = max(wid) + 1 if wid else 0
    tri = [list(t) for t in g.tris.tolist()]
    alive = [True] * len(tri)
    mark = [near[a] or near[b] or near[c] for a, b, c in tri]
    edges = {}

    def ek(a, b):
        x, y = wid[a], wid[b]
        return (x, y) if x < y else (y, x)

    def reg(t):
        a, b, c = tri[t]
        for u, v in ((a, b), (b, c), (c, a)):
            edges.setdefault(ek(u, v), set()).add(t)

    def unreg(t):
        a, b, c = tri[t]
        for u, v in ((a, b), (b, c), (c, a)):
            s = edges.get(ek(u, v))
            if s is not None:
                s.discard(t)

    # degenerate triangles (two corners welded together) keep their place but
    # never take part: splitting one would recreate the same edge forever
    for t in range(len(tri)):
        a, b, c = tri[t]
        if wid[a] == wid[b] or wid[b] == wid[c] or wid[c] == wid[a]:
            mark[t] = False
            continue
        reg(t)
    # open edges (where this sub-mesh meets the next section's) are never
    # split: the neighbour mesh would get a T-junction there
    border = {e for e, ts in edges.items() if len(ts) == 1}
    parents, mid, wmid = [], {}, {}
    L2 = max_edge * max_edge

    def d2(a, b):
        pa, pb = P[a], P[b]
        return (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2

    stack = [t for t in range(len(tri)) if mark[t]]
    while stack:
        t = stack.pop()
        if not alive[t]:
            continue
        a, b, c = tri[t]
        L = [(d2(a, b), 0), (d2(b, c), 1), (d2(c, a), 2)]
        if max(L)[0] <= L2:
            continue
        L = [x for x in L if ek(tri[t][x[1]], tri[t][(x[1] + 1) % 3]) not in border]
        if not L:
            continue
        l, i = max(L)
        if l <= L2:
            continue
        # slivers (height under SLIVER) never split on their own, only as a
        # neighbour of a real split; otherwise their far corner keeps
        # making long edges and the splitting never ends
        pa, pb, pc = P[a], P[b], P[c]
        e1 = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        e2 = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        cx = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        if cx[0] * cx[0] + cx[1] * cx[1] + cx[2] * cx[2] < (SLIVER * SLIVER) * l:
            continue
        u, v = tri[t][i], tri[t][(i + 1) % 3]
        e = ek(u, v)
        for t2 in sorted(edges.get(e, ())):
            if not alive[t2]:
                continue
            q = tri[t2]
            for j in range(3):
                if ek(q[j], q[(j + 1) % 3]) == e:
                    break
            else:
                continue
            p0, p1, p2 = q[j], q[(j + 1) % 3], q[(j + 2) % 3]
            key = (p0, p1) if p0 < p1 else (p1, p0)
            m = mid.get(key)
            if m is None:
                m = len(P)
                pa, pb = P[p0], P[p1]
                P.append(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2))
                near.append(close(P[m]))
                if e not in wmid:
                    wmid[e] = nw
                    nw += 1
                wid.append(wmid[e])
                parents.append(key)
                mid[key] = m
            unreg(t2)
            alive[t2] = False
            for nt in ([p0, m, p2], [m, p1, p2]):
                tri.append(nt)
                alive.append(True)
                mk = near[nt[0]] or near[nt[1]] or near[nt[2]]
                mark.append(mk)
                reg(len(tri) - 1)
                if mk:
                    stack.append(len(tri) - 1)
    tris = np.array([t for t, a in zip(tri, alive) if a], np.int64).reshape(-1, 3)
    bw = {w for e in border for w in e}
    bverts = np.array([w in bw for w in wid[:g.n]] + [False] * (len(P) - g.n), bool)
    return np.array(parents, np.int64).reshape(-1, 2), tris, bverts


def _interp(g, parents, links):
    """Attribute arrays of g plus the midpoints listed in parents."""
    n0 = g.n
    k = len(parents)
    out = {}
    for name in ('P', 'N', 'T', 'B', 'uv'):
        a = np.zeros((n0 + k,) + getattr(g, name).shape[1:], np.float64)
        a[:n0] = getattr(g, name)
        out[name] = a
    bw = [(g.bones[i, :g.links].tolist(), g.weights[i, :g.links].tolist()) for i in range(n0)]
    for j, (a, b) in enumerate(parents):
        i = n0 + j
        for name in ('P', 'N', 'T', 'B', 'uv'):
            out[name][i] = 0.5 * (out[name][a] + out[name][b])
        bw.append(_blend(bw[a], bw[b], links))
    nl = np.linalg.norm(out['N'], axis=1, keepdims=True)
    out['N'] = out['N'] / np.where(nl > 1e-9, nl, 1)
    bones = np.zeros((n0 + k, 4), np.int64)
    w = np.zeros((n0 + k, 4), np.float64)
    for i, (bb, ww) in enumerate(bw):
        bones[i, :len(bb)] = bb
        bones[i, len(bb):] = bb[0] if bb else 0
        w[i, :len(ww)] = ww
    return out, bones, w


def uv_shift(uv):
    """Whole-tile shift that puts uv inside [-1.5, 2.5), or None."""
    lo, hi = uv.min(0), uv.max(0)
    s = np.floor((lo + hi) / 2) - 0.0
    s = np.where((lo - s >= -1.5) & (hi - s < 2.5), s, np.nan)
    return None if np.isnan(s).any() else s


def damage_mesh(g, sites, tris_all):
    """D mesh for sub-mesh g (sites: its section's list), or None."""
    if not sites or not len(g.tris):
        return None
    shift = uv_shift(g.uv.astype(np.float64))
    if shift is None:
        return None
    S = np.array([s['p'] for s in sites])
    if np.sqrt(((g.P.astype(np.float64)[:, None, :] - S[None]) ** 2).sum(2)).min() >= PATCH:
        return None
    links = 4 if g.links > 1 else 2
    parents, tris, border = subdivide(g, S)
    if g.n + len(parents) > MAX_VERTS:
        return None             # too dense to subdivide this far: no D mesh (fail safe)
    a, bones, w = _interp(g, parents, links)
    D = np.sqrt(((a['P'][:, None, :] - S[None]) ** 2).sum(2))
    near = D.argmin(1)
    # border vertices (shared with the next section's mesh) stay put: code 0
    dist = D[np.arange(len(D)), near]
    inside = (dist < PATCH) & ~border & (near + 1 < SITE_BITS)
    rq = np.clip(1 + np.floor(RQ_STEPS * dist / PATCH), 1, RQ_STEPS).astype(int)
    code_u = np.where(inside, near + 1 + SITE_BITS * rq, 0)
    thick = np.zeros(len(D))
    # thickness under each original patch vertex (inward ray), midpoints interpolate
    from wounds import thickness
    n0 = g.n
    for i in np.nonzero(inside[:n0])[0]:
        n = a['N'][i]
        t = thickness(tris_all, a['P'][i] + 0.001 * n, -n) if tris_all is not None else None
        thick[i] = t if t is not None else sites[near[i]]['thick']
    for j, (p, q) in enumerate(parents):
        i = n0 + j
        if inside[i]:
            tp = thick[p] if inside[p] else sites[near[i]]['thick']
            tq = thick[q] if inside[q] else sites[near[i]]['thick']
            thick[i] = 0.5 * (tp + tq)
    code_v = np.where(inside, np.clip(np.round(thick / 0.002), 0, 255), 0)
    uv = a['uv'] - shift + CODE_K * np.stack([code_u, code_v], 1)
    out = ogf.Geom.new(g.texture, partsmod.OFF_SHADER, a['P'], a['N'], a['T'], a['B'], uv,
                       bones.astype(np.uint16), w, tris)
    return out


def decode_uv(uv, with_rq=False):
    """(site, thickness m) per vertex from coded UVs (tests, tools), as the
    vertex shader decodes them; with_rq: (site, thickness, rq)."""
    code = np.floor((uv[:, 0] + 1.5) / CODE_K).astype(int)
    site = code & (SITE_BITS - 1)
    thick = np.floor((uv[:, 1] + 1.5) / CODE_K) * 0.002
    if with_rq:
        return site, thick, code >> 5
    return site, thick


# ---------------------------------------------------------------- gib chunks

def _chunk(model, kids_sec, site, depth_max=0.04):
    """(top geoms grouped by texture, flesh Surface) of one site's chunk, in
    the bind space of the model; None if the patch is empty."""
    r = float(np.clip(0.6 * site['radius'], 0.025, 0.06))
    c, n = site['p'], site['n']
    depth = float(np.clip(0.6 * site['thick'], 0.01, depth_max))
    tops = []
    side = capmod.Surface()
    for g in kids_sec:
        P = g.P.astype(np.float64)
        cen = (P[g.tris[:, 0]] + P[g.tris[:, 1]] + P[g.tris[:, 2]]) / 3
        sel = np.nonzero(((cen - c) ** 2).sum(1) < r * r)[0]
        if not len(sel):
            continue
        T = g.tris[sel]
        used, inv = np.unique(T, return_inverse=True)
        T2 = inv.reshape(-1, 3)
        top = ogf.Geom.new(g.texture, g.shader, P[used], g.N[used], g.T[used], g.B[used], g.uv[used],
                           np.zeros((len(used), 4), np.uint16), np.c_[np.ones(len(used)), np.zeros((len(used), 3))],
                           T2, 1)
        tops.append(top)
        # boundary edges of the patch (welded) -> side walls down to the crater floor
        wid = capmod.weld(P[used])
        cnt = {}
        for t in T2.tolist():
            for x, y in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
                cnt[k] = cnt.get(k, 0) + 1
        U = np.cross(n, [0, 1, 0] if abs(n[1]) < 0.9 else [1, 0, 0])
        U /= np.linalg.norm(U)
        V = np.cross(n, U)

        def flesh_uv(p):
            d = p - c
            fx, fy, fX, fY = capmod.FLESH_BOX
            return (fx + (fX - fx) * (0.5 + 0.5 * float(d @ U) / r), fy + (fY - fy) * (0.5 + 0.5 * float(d @ V) / r))

        def floor_pt(p):
            d = p - c
            d = d - (d @ n) * n
            return c + 0.55 * d - depth * n

        for t in T2.tolist():
            for x, y in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
                if cnt[k] != 1:
                    continue
                pa, pb = P[used[x]], P[used[y]]
                fa, fb = floor_pt(pa), floor_pt(pb)
                ids = [side.add(q, flesh_uv(q), [0], [1.0]) for q in (pa, pb, fb, fa)]
                # outward-facing wall (the top runs a->b counter-clockwise seen from outside)
                side.tris += [[ids[0], ids[3], ids[2]], [ids[0], ids[2], ids[1]]]
                cid = side.add(c - depth * n, flesh_uv(c), [0], [1.0])
                side.tris.append([ids[3], cid, ids[2]])
    if not tops:
        return None
    return tops, side


def chunk_model(model, kids_sec, sites, tris_all=None):
    """(bytes, count) of the gib chunk model of one section, or None."""
    skel = model.skeleton
    geoms, bones = [], [('zgo_chunks', '', ogf.obb_bytes(np.zeros(3), np.zeros(3), 0.01), ogf.ik_record(
        ogf.default_bone('zgo_chunks')))]
    for i, s in enumerate(sites):
        made = _chunk(model, kids_sec, s)
        if made is None:
            # keep numbering: an empty bone
            bones.append(('site_%d' % (i + 1), 'zgo_chunks', ogf.obb_bytes(np.zeros(3), np.zeros(3), 0.01),
                          ogf.ik_record(ogf.default_bone('site_%d' % (i + 1), 'zgo_chunks'))))
            continue
        tops, side = made
        to_local = ogf.rigid_inverse(skel.bones[s['bone']].world)
        parts_i = tops + [g for g in [side.geom(capmod.FLESH_TEX, capmod.SHADER)] if g is not None]
        lut = np.full(max(len(skel.bones), 1), i + 1, np.int64)
        local = [ogf.transform_geom(g, to_local, lut) for g in parts_i]
        P = np.concatenate([g.P for g in local]).astype(np.float64)
        bones.append(('site_%d' % (i + 1), 'zgo_chunks', ogf.obb_bytes(P.min(0), P.max(0), 0.005),
                      ogf.ik_record(ogf.default_bone('site_%d' % (i + 1), 'zgo_chunks'))))
        geoms += local
    if not geoms or len(bones) > 64:
        return None
    return ogf.build_skeleton_model(bones, geoms), len(sites)


def bake(model, kids, info, out_root, flags, sites, write_once):
    """{'dmeshes': [(kid index, D geom)], 'chunks': {section: 'hashxN'}}"""
    from wounds import model_triangles
    skel = model.skeleton
    tris_all = model_triangles(model)
    out = {'dmeshes': [], 'chunks': {}}
    by_sec = {}
    for i, k in enumerate(kids):
        name = 'body' if k.section < 0 else skel.bones[k.section].name
        by_sec.setdefault(name, []).append((i, k))
        if name not in sites:
            continue
        d = damage_mesh(k, sites[name], tris_all)
        if d is not None:
            d.section, d.source_child = k.section, i
            out['dmeshes'].append((i, d))
    for name, ss in sorted(sites.items()):
        made = chunk_model(model, [k for _, k in by_sec.get(name, [])], ss)
        if made:
            data, n = made
            cname = partsmod.content_name(CHUNK_DIR, data)
            write_once(out_root, cname, data)
            out['chunks'][name] = '%sx%d' % (cname.rsplit('\\', 1)[1], n)
    return out
