#!/usr/bin/env python3
"""
Self-test of the fracture cutter on synthetic meshes (no game files needed):
  python3 selftest.py        -> prints PASSED
Checks that Voronoi shells and planks cover the whole surface exactly once
(piece areas add up to the source area), stay inside the source box, and
that a piece model written for the engine reads back as a one-bone rigid
model (tools/zgo_baker/ogf.py).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import cut, fracture  # noqa: E402
import ogf  # noqa: E402  (zgo_baker, on the path through fracture)


def box_mesh(lo, hi, n=4):
    """A closed box, each face an n x n grid (outward normals)."""
    lo, hi = np.array(lo, float), np.array(hi, float)
    rows, tris = [], []
    for ax in range(3):
        for sgn in (-1, 1):
            u, v = [a for a in range(3) if a != ax]
            base = len(rows)
            for i in range(n + 1):
                for j in range(n + 1):
                    p = np.zeros(3)
                    p[ax] = hi[ax] if sgn > 0 else lo[ax]
                    p[u] = lo[u] + (hi[u] - lo[u]) * i / n
                    p[v] = lo[v] + (hi[v] - lo[v]) * j / n
                    nrm = np.zeros(3)
                    nrm[ax] = sgn
                    t = np.zeros(3)
                    t[u] = 1
                    b = np.cross(nrm, t)
                    rows.append(np.concatenate([p, nrm, t, b, [i / n, j / n]]))
            for i in range(n):
                for j in range(n):
                    a, b2, c, d = base + i * (n + 1) + j, base + (i + 1) * (n + 1) + j, base + (i + 1) * (n + 1) + j + 1, base + i * (n + 1) + j + 1
                    if (sgn > 0) == ((ax + 1) % 3 == u and True):
                        tris += [(a, b2, c), (a, c, d)]
                    else:
                        tris += [(a, c, b2), (a, d, c)]
    return [{'texture': 'test\\tex', 'shader': 'models\\model', 'V': np.array(rows), 'tris': np.array(tris, np.int64)}]


def area(mesh):
    return cut.piece_area(mesh)


def main():
    src = box_mesh((-0.2, 0, -0.4), (0.2, 0.25, 0.4), 6)
    A = area(src)
    lo, hi = cut.bounds(src)
    rng = np.random.default_rng(3)
    shells = cut.voronoi_cells(src, 8, rng)
    a_sh = sum(area(p) for p in shells)
    assert 4 <= len(shells) <= 8, len(shells)
    assert abs(a_sh - A) < 1e-6 * max(1, A) + 1e-6, (a_sh, A)
    cut.reset_cuts()
    planks = cut.plank_cells(src, 0.12, np.random.default_rng(4))
    a_pl = sum(area(p) for p in planks)
    assert 4 <= len(planks) <= 10, len(planks)
    assert abs(a_pl - A) < 1e-6 * max(1, A) + 1e-6, (a_pl, A)
    for p in shells + planks:
        plo, phi = cut.piece_bounds(p)
        assert (plo >= lo - 1e-6).all() and (phi <= hi + 1e-6).all()
    # a written piece reads back as a rigid one-bone model, inside its box
    bone = ogf.default_bone('link')
    bone.mtl = 'objects\\large_furniture'
    data, plo, phi = fracture.piece_ogf(cut.thicken(planks[0], 0.01), bone, 3.0)
    m = ogf.Model(data)
    assert m.header.type == ogf.MT_SKELETON_RIGID and len(m.skeleton.bones) == 1
    assert abs(m.skeleton.bones[0].mass - 3.0) < 1e-6 and m.skeleton.bones[0].mtl == 'objects\\large_furniture'
    P = np.concatenate([g.P for g in m.children])
    assert (P.min(0) >= plo - 1e-5).all() and (P.max(0) <= phi + 1e-5).all()
    print('shells %d (area %.4f of %.4f), planks %d (area %.4f), piece model %d bytes'
          % (len(shells), a_sh, A, len(planks), a_pl, len(data)))
    print('PASSED')


if __name__ == '__main__':
    main()
