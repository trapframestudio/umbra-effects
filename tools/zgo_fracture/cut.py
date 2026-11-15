"""
Mesh cutting for the Umbra Effects fracture baker: clip a prop's triangles into pieces.

A mesh here is a list of "parts" (one per source sub-mesh / texture), each
{ 'texture', 'shader', 'V': (n,14) float64 rows [P N T B uv], 'tris': (m,3) }.
All positions are in the source model's space, so a piece model drawn at the
source object's transform sits exactly where that part of the object was.

  voronoi_cells(mesh, k, rng)      shells: k cells around seeds on the surface
                                   (barrels, cans, bottles, glass)
  plank_cells(mesh, width, rng)    wood: each face direction cut into strips
                                   along its long side (crates, chairs)
  thicken(piece, t)                closes a shell piece: a copy offset inward
                                   along the normals with flipped winding

Pure numpy / Python; no engine knowledge beyond the vertex layout.
"""
import numpy as np

P_, N_, T_, B_, UV_ = slice(0, 3), slice(3, 6), slice(6, 9), slice(9, 12), slice(12, 14)
EPS = 1e-7


def mesh_from_model(model):
    """Parts of an ogf.Model (zgo_baker.ogf) in model space."""
    parts = []
    for g in model.children:
        V = np.concatenate([g.P, g.N, g.T, g.B, g.uv], 1).astype(np.float64)
        parts.append({'texture': g.texture, 'shader': g.shader, 'V': V, 'tris': g.tris.astype(np.int64)})
    return parts


def bounds(mesh):
    P = np.concatenate([p['V'][:, P_] for p in mesh if len(p['V'])])
    return P.min(0), P.max(0)


def area_weights(mesh):
    """(part index, triangle index, area) for every triangle."""
    out = []
    for pi, p in enumerate(mesh):
        P = p['V'][:, P_]
        t = p['tris']
        if not len(t):
            continue
        a = np.linalg.norm(np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]]), axis=1) / 2
        for ti in range(len(t)):
            out.append((pi, ti, float(a[ti])))
    return out


def clip_poly(poly, n, d):
    """Sutherland-Hodgman: the part of poly (list of rows) with dot(n, P) <= d."""
    out = []
    m = len(poly)
    if m == 0:
        return out
    dist = [float(np.dot(n, v[P_])) - d for v in poly]
    for i in range(m):
        a, b = poly[i], poly[(i + 1) % m]
        da, db = dist[i], dist[(i + 1) % m]
        if da <= 0:
            out.append(a)
        if (da <= 0) != (db <= 0):
            t = da / (da - db)
            out.append(a + (b - a) * t)
    return out


def _finish(rows):
    """Renormalise the interpolated vectors of new vertices."""
    V = np.array(rows, np.float64)
    for s in (N_, T_, B_):
        L = np.linalg.norm(V[:, s], axis=1, keepdims=True)
        V[:, s] = np.where(L > 1e-9, V[:, s] / np.where(L > 1e-9, L, 1), V[:, s])
    return V


class Builder:
    """Collects polygons per (cell, part) and fans them into triangles."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.cells = {}

    def add(self, cell, pi, poly):
        if len(poly) < 3:
            return
        c = self.cells.setdefault(cell, {})
        rows, tris = c.setdefault(pi, ([], []))
        base = len(rows)
        rows.extend(poly)
        for k in range(1, len(poly) - 1):
            P0, P1, P2 = poly[0][P_], poly[k][P_], poly[k + 1][P_]
            if np.linalg.norm(np.cross(P1 - P0, P2 - P0)) > 1e-10:
                tris.append((base, base + k, base + k + 1))

    def pieces(self):
        out = []
        for cell in sorted(self.cells):
            piece = []
            for pi in sorted(self.cells[cell]):
                rows, tris = self.cells[cell][pi]
                if not tris:
                    continue
                V, T = weld(_finish(rows), np.array(tris, np.int64))
                src = self.mesh[pi]
                piece.append({'texture': src['texture'], 'shader': src['shader'], 'V': V, 'tris': T})
            if piece:
                out.append(piece)
        return out


def weld(V, T, tol=1e-6):
    """Merge identical vertices (same position and attributes)."""
    key = np.round(V / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    return V[first], inv[T]


def surface_seeds(mesh, k, rng):
    """k points on the surface, area weighted, spread by a few rejection rounds."""
    tw = area_weights(mesh)
    if not tw:
        return np.zeros((0, 3))
    areas = np.array([a for _, _, a in tw])
    prob = areas / areas.sum()
    lo, hi = bounds(mesh)
    min_d = 0.6 * np.linalg.norm(hi - lo) / max(1, k) ** 0.5
    seeds = []
    tries = 0
    while len(seeds) < k and tries < k * 200:
        tries += 1
        pi, ti, _ = tw[int(rng.choice(len(tw), p=prob))]
        p = mesh[pi]
        a, b, c = (p['V'][p['tris'][ti, j], P_] for j in range(3))
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        x = a + (b - a) * r1 + (c - a) * r2
        if all(np.linalg.norm(x - s) >= min_d for s in seeds) or tries > k * 150:
            seeds.append(x)
    return np.array(seeds)


def voronoi_cells(mesh, k, rng):
    """Pieces of the surface split by the Voronoi cells of k surface seeds."""
    S = surface_seeds(mesh, k, rng)
    if len(S) < 2:
        return [mesh]
    bld = Builder(mesh)
    for pi, p in enumerate(mesh):
        V, T = p['V'], p['tris']
        if not len(T):
            continue
        d = ((V[:, None, P_] - S[None, :, :]) ** 2).sum(-1)
        near = np.argsort(d, axis=1)[:, :3]
        for tri in T:
            cand = sorted(set(int(c) for c in near[tri].ravel()))
            poly0 = [V[i] for i in tri]
            owner = set(int(near[i, 0]) for i in tri)
            if len(owner) == 1 and len(cand) >= 1:
                c0 = owner.pop()
                # all three corners nearest the same seed: whole triangle (convex cells)
                bld.add(c0, pi, poly0)
                continue
            for c in cand:
                poly = poly0
                for j in cand:
                    if j == c:
                        continue
                    n = S[j] - S[c]
                    poly = clip_poly(poly, n, float(np.dot(n, (S[j] + S[c]) / 2)))
                    if len(poly) < 3:
                        break
                bld.add(c, pi, poly)
    return bld.pieces()


def plank_cells(mesh, width, rng, max_pieces=10):
    """Wood: triangles grouped by the way they face (6 directions), each group
    cut into strips across its longest side, width jittered."""
    lo, hi = bounds(mesh)
    size = hi - lo
    bld = Builder(mesh)
    for pi, p in enumerate(mesh):
        V, T = p['V'], p['tris']
        if not len(T):
            continue
        P = V[:, P_]
        fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
        for ti, tri in enumerate(T):
            n = fn[ti]
            ax = int(np.argmax(np.abs(n)))
            face = ax * 2 + (1 if n[ax] < 0 else 0)
            # strips run across the longest axis lying in this face
            inplane = [a for a in range(3) if a != ax]
            cut = max(inplane, key=lambda a: size[a])
            cuts = _cuts(lo[cut], hi[cut], width, face * 7 + cut, rng)
            poly0 = [V[i] for i in tri]
            for si in range(len(cuts) - 1):
                e = np.zeros(3)
                e[cut] = 1.0
                poly = clip_poly(poly0, e, cuts[si + 1])
                poly = clip_poly(poly, -e, -cuts[si])
                bld.add((face, si), pi, poly)
    pieces = bld.pieces()
    while len(pieces) > max_pieces:
        # merge the two smallest neighbours in the list
        sizes = [sum(len(x['tris']) for x in pc) for pc in pieces]
        i = int(np.argmin([sizes[j] + sizes[j + 1] for j in range(len(pieces) - 1)]))
        pieces[i:i + 2] = [merge(pieces[i], pieces[i + 1])]
    return pieces


_CUT_CACHE = {}


def _cuts(a, b, width, key, rng):
    """Strip boundaries from a to b (the same for every triangle of one face)."""
    k = (key, round(a, 5), round(b, 5))
    if k not in _CUT_CACHE:
        n = max(1, int(round((b - a) / width)))
        xs = np.linspace(a, b, n + 1)
        if n > 1:
            j = (rng.random(n - 1) - 0.5) * 0.35 * (b - a) / n
            xs[1:-1] += j
        xs[0], xs[-1] = a - 1e-4, b + 1e-4
        _CUT_CACHE[k] = list(xs)
    return _CUT_CACHE[k]


def reset_cuts():
    _CUT_CACHE.clear()


def merge(a, b):
    by = {}
    for part in a + b:
        key = (part['texture'], part['shader'])
        if key in by:
            o = by[key]
            n0 = len(o['V'])
            o['V'] = np.concatenate([o['V'], part['V']])
            o['tris'] = np.concatenate([o['tris'], part['tris'] + n0])
        else:
            by[key] = {'texture': part['texture'], 'shader': part['shader'], 'V': part['V'].copy(), 'tris': part['tris'].copy()}
    return list(by.values())


def thicken(piece, t):
    """The piece plus a back face: offset inward along the normals by t,
    flipped normals and winding (shell pieces seen from inside)."""
    out = []
    for part in piece:
        V, T = part['V'], part['tris']
        back = V.copy()
        back[:, P_] = V[:, P_] - V[:, N_] * t
        back[:, N_] = -V[:, N_]
        back[:, T_] = -V[:, T_]
        n = len(V)
        out.append({'texture': part['texture'], 'shader': part['shader'],
                    'V': np.concatenate([V, back]), 'tris': np.concatenate([T, T[:, ::-1] + n])})
    return out


def piece_bounds(piece):
    P = np.concatenate([p['V'][:, P_] for p in piece])
    return P.min(0), P.max(0)


def piece_area(piece):
    a = 0.0
    for p in piece:
        P = p['V'][:, P_]
        t = p['tris']
        if len(t):
            a += float(np.linalg.norm(np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]]), axis=1).sum() / 2)
    return a
