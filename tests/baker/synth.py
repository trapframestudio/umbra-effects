"""
A small synthetic character for the baker tests: a torso / head tube, a left
arm and a left leg, closed and watertight, skinned like the stock models
(rings 100% to their bone, a 50/50 ring at each joint, so the seam of every
severable section is weighted only to that section's bones). Some bones are
rotated so that frames are really tested.
"""
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(MOD, 'tools', 'zgo_baker'))
import ogf  # noqa: E402

LIMBS = {'synth': ['bip01_head', 'bip01_l_calf', 'bip01_l_forearm', 'bip01_l_thigh', 'bip01_l_upperarm']}

# name, parent, local position, local rotation (x, y, z for euler_xyzi)
BONES = [
    ('root', '', (0, 0, 0), (0, 0, 0)),
    ('bip01_pelvis', 'root', (0, 1.0, 0), (0, 0, 0)),
    ('bip01_spine', 'bip01_pelvis', (0, 0.2, 0), (0.05, 0, 0)),
    ('bip01_neck', 'bip01_spine', (0, 0.42, 0), (-0.05, 0, 0)),
    ('bip01_head', 'bip01_neck', (0, 0.1, 0), (0.1, 0.2, 0)),
    ('bip01_l_upperarm', 'bip01_spine', (0.22, 0.35, 0), (0.3, 0.2, -1.2)),
    ('bip01_l_forearm', 'bip01_l_upperarm', (0, 0.3, 0), (0.0, 0.4, 0.2)),
    ('bip01_l_hand', 'bip01_l_forearm', (0, 0.25, 0), (0, 0, 0)),
    ('bip01_l_thigh', 'bip01_pelvis', (0.12, -0.05, 0), (0, 0, np.pi)),
    ('bip01_l_calf', 'bip01_l_thigh', (0, 0.45, 0), (0.1, 0, 0)),
    ('bip01_l_foot', 'bip01_l_calf', (0, 0.45, 0), (0, 0, 0)),
]


def skeleton_worlds():
    ids = {b[0]: i for i, b in enumerate(BONES)}
    W = []
    for name, par, pos, rot in BONES:
        m = np.eye(4)
        m[:3, :3] = ogf.euler_xyzi(*rot)
        m[:3, 3] = pos
        W.append(m if not par else W[ids[par]] @ m)
    return W, ids


def _frame(t):
    t = t / np.linalg.norm(t)
    a = np.array([1.0, 0, 0]) if abs(t[0]) < 0.9 else np.array([0, 0, 1.0])
    u = np.cross(a, t)
    u /= np.linalg.norm(u)
    v = np.cross(t, u)
    return u, v


def tube(points, radii, ring_bones, sides=16):
    """Closed tube through points; ring k is skinned by ring_bones[k] =
    [(bone, weight), ...]. Returns arrays for ogf.Geom.new."""
    P, N, bones, w, uv, tris = [], [], [], [], [], []
    pts = [np.asarray(p, np.float64) for p in points]
    rings = []
    for k, c in enumerate(pts):
        t = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
        u, v = _frame(t)
        ring = []
        for i in range(sides):
            th = 2 * np.pi * i / sides
            d = np.cos(th) * u + np.sin(th) * v
            ring.append(len(P))
            P.append(c + radii[k] * d)
            N.append(d)
            bb = ring_bones[k]
            bones.append([b for b, _ in bb] + [bb[0][0]] * (4 - len(bb)))
            w.append([x for _, x in bb] + [0.0] * (4 - len(bb)))
            uv.append((i / sides, 0.3 * k))
        rings.append(ring)
    for k in range(len(rings) - 1):
        A, B = rings[k], rings[k + 1]
        for i in range(sides):
            j = (i + 1) % sides
            tris.append((A[i], A[j], B[i]))
            tris.append((A[j], B[j], B[i]))
    for end, ring in ((0, rings[0]), (1, rings[-1])):
        c = pts[0] if end == 0 else pts[-1]
        t = (pts[1] - pts[0]) if end == 0 else (pts[-1] - pts[-2])
        t = t / np.linalg.norm(t)
        ci = len(P)
        P.append(c + (-0.3 if end == 0 else 0.3) * radii[0 if end == 0 else -1] * t)
        N.append(-t if end == 0 else t)
        bb = ring_bones[0 if end == 0 else -1]
        bones.append([b for b, _ in bb] + [bb[0][0]] * (4 - len(bb)))
        w.append([x for _, x in bb] + [0.0] * (4 - len(bb)))
        uv.append((0.5, 0.5))
        for i in range(sides):
            j = (i + 1) % sides
            tris.append((ci, ring[j], ring[i]) if end == 0 else (ci, ring[i], ring[j]))
    P, N = np.array(P), np.array(N)
    T = np.cross(N, [0, 0, 1.0])
    T[np.linalg.norm(T, axis=1) < 1e-6] = (1, 0, 0)
    B = np.cross(N, T)
    return P, N, T, B, np.array(uv), np.array(bones, np.uint16), np.array(w), np.array(tris, np.int64)


def _chain(W, ids, names, extra_end):
    """Points along a bone chain (several rings per bone) and their skinning."""
    pts, rb = [], []
    for k, name in enumerate(names):
        a = W[ids[name]][:3, 3]
        b = W[ids[names[k + 1]]][:3, 3] if k + 1 < len(names) else a + extra_end(W[ids[name]])
        n = 4
        for i in range(n):
            f = i / n
            pts.append(a + f * (b - a))
            if i == 0 and k > 0:
                rb.append([(ids[names[k - 1]], 0.5), (ids[name], 0.5)])
            else:
                rb.append([(ids[name], 1.0)])
    pts.append(b)
    rb.append([(ids[names[-1]], 1.0)])
    return pts, rb


def build(texture='test\\skin', shader='models\\model'):
    """Bytes of the synthetic model (MT_SKELETON_RIGID, three sub-meshes)."""
    W, ids = skeleton_worlds()
    up = lambda m: m[:3, :3] @ np.array([0, 0.25, 0])  # noqa: E731
    kids = []
    # torso + head: pelvis .. spine .. neck .. head (+ top)
    pts, rb = _chain(W, ids, ['bip01_pelvis', 'bip01_spine', 'bip01_neck', 'bip01_head'], up)
    radii = [0.15 if p[1] < 1.6 else 0.1 for p in pts]
    kids.append(tube(pts, radii, rb))
    # left arm, starting inside the torso on the spine
    pts, rb = _chain(W, ids, ['bip01_spine', 'bip01_l_upperarm', 'bip01_l_forearm', 'bip01_l_hand'],
                     lambda m: m[:3, :3] @ np.array([0, 0.1, 0]))
    pts[0] = pts[0] + np.array([0.1, 0.3, 0])
    kids.append(tube(pts, [0.05] * len(pts), rb, sides=12))
    # left leg, starting at the pelvis
    pts, rb = _chain(W, ids, ['bip01_pelvis', 'bip01_l_thigh', 'bip01_l_calf', 'bip01_l_foot'],
                     lambda m: m[:3, :3] @ np.array([0, 0.1, 0]))
    pts[0] = pts[0] + np.array([0.08, -0.02, 0])
    kids.append(tube(pts, [0.07] * len(pts), rb, sides=12))
    geoms = [ogf.Geom.new(texture, shader, *k) for k in kids]
    bones = []
    for name, par, pos, rot in BONES:
        b = ogf.default_bone(name, par)
        bones.append((name, par, ogf.obb_bytes(np.full(3, -0.2), np.full(3, 0.2)),
                      ogf.ik_record(b, tuple(float(x) for x in rot), tuple(float(x) for x in pos))))
    return ogf.build_skeleton_model(bones, geoms)


def random_pose(seed=1, spread=0.6):
    """World matrices of the synthetic skeleton in a random pose (column vectors)."""
    rng = np.random.default_rng(seed)
    W = []
    ids = {b[0]: i for i, b in enumerate(BONES)}
    root = np.eye(4)
    root[:3, :3] = ogf.euler_xyzi(*rng.uniform(-np.pi, np.pi, 3))
    root[:3, 3] = rng.uniform(-5, 5, 3)
    for name, par, pos, rot in BONES:
        m = np.eye(4)
        m[:3, :3] = ogf.euler_xyzi(*(np.array(rot) + rng.uniform(-spread, spread, 3)))
        m[:3, 3] = pos
        W.append(root @ m if not par else W[ids[par]] @ m)
    return W


def skin(P, bones, weights, mats, binds_inv):
    """Linear blend skinning: sum_k w_k * mats[b_k] @ binds_inv[b_k] @ p."""
    out = np.zeros((len(P), 3))
    for i, p in enumerate(P):
        h = np.append(p, 1.0)
        for b, w in zip(bones[i], weights[i]):
            if w > 0:
                out[i] += w * (mats[b] @ binds_inv[b] @ h)[:3]
    return out


if __name__ == '__main__':
    data = build()
    out = sys.argv[1] if len(sys.argv) > 1 else 'synth.ogf'
    with open(out, 'wb') as f:
        f.write(data)
    print(out, len(data))
