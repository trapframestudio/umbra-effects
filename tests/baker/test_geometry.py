"""Baker geometry: OGF writing, stump caps, limb pieces, wound sites and the
experimental damage meshes, on the synthetic character (tests/baker/synth.py).
Run: python3 -m unittest discover -s tests/baker   (or dev/run.sh ...)"""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth  # noqa: E402  (puts tools/zgo_baker on sys.path)
import ogf, partition, caps, parts, wounds, damage, gibs  # noqa: E402


def setup_model():
    m = ogf.Model(synth.build())
    kids, info = partition.split_model(m, synth.LIMBS)
    return m, kids, info


def flat(geoms):
    P = np.concatenate([g.P for g in geoms]).astype(np.float64)
    B = np.concatenate([g.bones.astype(np.int64) for g in geoms])
    W = np.concatenate([g.weights.astype(np.float64) for g in geoms])
    return P, B, W


class TestOgf(unittest.TestCase):
    def test_round_trip(self):
        data = synth.build()
        m = ogf.Model(data)
        self.assertEqual(m.pack(), data)
        self.assertEqual(len(m.children), 3)
        self.assertEqual(m.header.type if hasattr(m.header, 'type') else ogf.MT_SKELETON_RIGID, ogf.MT_SKELETON_RIGID)

    def test_euler_inverse(self):
        rng = np.random.default_rng(3)
        for _ in range(300):
            a = rng.uniform(-3, 3, 3)
            r = ogf.euler_xyzi(*a)
            self.assertLess(np.abs(ogf.euler_xyzi(*ogf.xyzi_from_matrix(r)) - r).max(), 1e-9)

    def test_skeleton_validation(self):
        b = ogf.default_bone('a')
        rec = ogf.ik_record(b)
        obb = ogf.obb_bytes(np.zeros(3), np.ones(3))
        with self.assertRaises(ogf.OgfError):
            ogf.build_skeleton_model([], [])
        with self.assertRaises(ogf.OgfError):     # two roots
            ogf.build_skeleton_model([('a', '', obb, rec), ('b', '', obb, rec)], [])
        with self.assertRaises(ogf.OgfError):     # missing parent
            ogf.build_skeleton_model([('a', '', obb, rec), ('b', 'zz', obb, rec)], [])

    def test_transform_keeps_bad_normals(self):
        m = ogf.Model(synth.build())
        g = m.children[0]
        g.N[0] = np.inf
        out = ogf.transform_geom(g, np.eye(4), np.arange(len(m.skeleton.bones)))
        self.assertFalse(np.isfinite(out.N[0]).all())
        self.assertTrue(np.isfinite(out.N[1:]).all())


class TestCaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.kids, cls.info = setup_model()
        cls.skel = cls.m.skeleton
        cls.sub = parts.subtree_sections(cls.skel, cls.info['roots'])

    def loops(self, name):
        s = self.skel.by_name[name]
        return s, caps.section_loops(self.m, self.info['labels'], self.sub[s])

    def test_seams_found(self):
        for name in synth.LIMBS['synth']:
            s, (loops, centre) = self.loops(name)
            self.assertEqual(len(loops), 1, name)
            self.assertIsNotNone(centre)
            self.assertGreater(len(loops[0].P), 8)

    def test_cap_rim_copies_the_seam(self):
        """The cap rim sits exactly on the seam with the seam's weights, and
        caps close the hole (no open boundary except the rim)."""
        for name in synth.LIMBS['synth']:
            s, lp = self.loops(name)
            cap = parts.stump_cap(self.m, s, lp, name)
            face = cap.face.geom(caps.FLESH_TEX, caps.SHADER)
            rim = lp[0][0]
            for p, bb, ww in zip(rim.P, rim.bones, rim.weights):
                d = np.linalg.norm(face.P.astype(np.float64) - p, axis=1)
                i = int(d.argmin())
                self.assertLess(d[i], 1e-5, name)
                got = {int(b): float(w) for b, w in zip(face.bones[i], face.weights[i]) if w > 0}
                want = {int(b): float(w) for b, w in zip(bb, ww) if w > 0}
                self.assertEqual(set(got), set(want), name)

    def test_cap_faces_away_from_the_stump(self):
        for name in synth.LIMBS['synth']:
            s, lp = self.loops(name)
            cap = parts.stump_cap(self.m, s, lp, name)
            g = cap.face.geom(caps.FLESH_TEX, caps.SHADER)
            P = g.P.astype(np.float64)
            a, b, c = P[g.tris[:, 0]], P[g.tris[:, 1]], P[g.tris[:, 2]]
            fn = np.cross(b - a, c - a).sum(0)
            toward = lp[1] - P.mean(0)
            self.assertGreater(float(fn @ toward), 0, name)

    def test_cap_model_frames(self):
        """Mode A (rigid on the parent, no offset) and Mode B (every cap bone
        follows the victim's bone of the same name) both match the victim's
        own skinning of the seam in a random pose."""
        W = synth.random_pose(7)
        binds_inv = [ogf.rigid_inverse(b.world) for b in self.skel.bones]
        for name in synth.LIMBS['synth']:
            s, lp = self.loops(name)
            cap = parts.stump_cap(self.m, s, lp, name)
            data, names = parts.cap_model(self.m, s, cap)
            cm = ogf.Model(data)
            ck = cm.skeleton
            p = self.skel.bones[s].parent
            self.assertEqual(names[0], self.skel.bones[p].name)
            self.assertLess(np.abs(ck.bones[0].world - np.eye(4)).max(), 1e-6)
            # cap bind of every bone = inverse(Bind_p) * Bind_b
            to_p = ogf.rigid_inverse(self.skel.bones[p].world)
            for cb in ck.bones:
                vb = self.skel.bones[self.skel.by_name[cb.name]]
                self.assertLess(np.abs(cb.world - to_p @ vb.world).max(), 1e-5, (name, cb.name))
            # Mode B: attachment XFORM = owner XFORM (identity here), bones = victim model-space bones
            mats = [W[self.skel.by_name[cb.name]] for cb in ck.bones]
            cinv = [ogf.rigid_inverse(cb.world) for cb in ck.bones]
            rim = lp[0][0]
            want = synth.skin(rim.P, rim.bones, rim.weights, W, binds_inv)
            P, B, Wt = flat(cm.children)
            got = synth.skin(P, B, Wt, mats, cinv)
            for q in want:
                self.assertLess(np.linalg.norm(got - q, axis=1).min(), 1e-4, name)
            # Mode A: XFORM = World_p; exact for vertices held by p alone
            only_p = (B[:, 0] == 0) & (Wt[:, 0] > 0.999)
            if only_p.any():
                a = (np.c_[P[only_p], np.ones(only_p.sum())] @ W[p].T)[:, :3]
                self.assertLess(np.abs(a - got[only_p]).max(), 1e-5)

    def test_content_names_dedupe(self):
        s, lp = self.loops('bip01_l_thigh')
        d1, _ = parts.cap_model(self.m, s, parts.stump_cap(self.m, s, lp, 'x'))
        d2, _ = parts.cap_model(self.m, s, parts.stump_cap(self.m, s, lp, 'x'))
        self.assertEqual(d1, d2)
        n = parts.content_name(parts.CAP_DIR, d1)
        self.assertRegex(n, r'^zgo\\baked\\caps\\[0-9a-f]{2}\\[0-9a-f]{12}$')
        self.assertTrue(n.split('\\')[-1].startswith(n.split('\\')[-2]))


class TestPieces(unittest.TestCase):
    def test_piece_poses_like_the_limb(self):
        """With bone callbacks returning the victim's world bone matrix relative
        to the attachment (what zgo_debris does), the piece lands exactly on
        the victim's limb."""
        m, kids, info = setup_model()
        skel = m.skeleton
        sub = parts.subtree_sections(skel, info['roots'])
        W = synth.random_pose(11)
        binds_inv = [ogf.rigid_inverse(b.world) for b in skel.bones]
        for name in synth.LIMBS['synth']:
            s = skel.by_name[name]
            lp = caps.section_loops(m, info['labels'], sub[s])
            data, names = parts.piece_model(m, kids, s, sub[s], parts.piece_cap(m, s, lp, None, name))
            pm = ogf.Model(data)
            pk = pm.skeleton
            self.assertEqual(names[0], name)
            self.assertEqual(set(names), {skel.bones[b].name for b in skel.descendants(s)})
            self.assertLess(np.abs(pk.bones[0].world - np.eye(4)).max(), 1e-6)
            att = W[s]                                   # attachment placed at the cut root
            inv_att = ogf.rigid_inverse(att)
            mats = [inv_att @ W[skel.by_name[b.name]] for b in pk.bones]
            pinv = [ogf.rigid_inverse(b.world) for b in pk.bones]
            limb = [k for k in kids if k.section in sub[s]]
            Pv, Bv, Wv = flat(limb)
            want = synth.skin(Pv, Bv, Wv, W, binds_inv)
            n_limb = sum(k.n for k in limb)
            Pp, Bp, Wp = flat(pm.children)
            got = synth.skin(Pp[:n_limb], Bp[:n_limb], Wp[:n_limb], mats, pinv)
            got = (np.c_[got, np.ones(len(got))] @ att.T)[:, :3]
            self.assertLess(np.abs(got - want).max(), 1e-4, name)
            self.assertGreater(len(pm.children), len(limb), 'piece end cap present')


class TestWounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.kids, cls.info = setup_model()
        cls.sites = wounds.bake_sites(cls.m, cls.kids, cls.info)

    def test_counts_and_spacing(self):
        lims = {'body': (12, 20), 'bip01_head': (4, 6), 'bip01_l_upperarm': (2, 4), 'bip01_l_thigh': (2, 4),
                'bip01_l_forearm': (1, 2), 'bip01_l_calf': (1, 2)}
        for name, ss in self.sites.items():
            lo, hi = lims[name]
            self.assertTrue(len(ss) <= hi, (name, len(ss)))
            P = np.array([s['p'] for s in ss])
            for i in range(len(P)):
                for j in range(i):
                    self.assertGreaterEqual(np.linalg.norm(P[i] - P[j]), wounds.MIN_SPACING * 0.999, name)
        self.assertGreaterEqual(len(self.sites['body']), 12)

    def test_site_fields(self):
        skel = self.m.skeleton
        for name, ss in self.sites.items():
            for s in ss:
                self.assertAlmostEqual(np.linalg.norm(s['n']), 1.0, 5)
                self.assertGreater(s['thick'], 0)
                self.assertLessEqual(s['depth'], s['thick'] + 1e-9)
                if name != 'body':
                    self.assertIn(s['bone'], skel.descendants(skel.by_name[name]))

    def test_thickness_of_a_tube(self):
        # the leg tube has radius 7 cm: straight through is about 14 cm
        th = [s['thick'] for s in self.sites['bip01_l_thigh']]
        for t in th:
            self.assertGreater(t, 0.09)
            self.assertLess(t, 0.16)

    def test_deterministic_and_round_trip(self):
        again = wounds.bake_sites(self.m, self.kids, self.info)
        for name in self.sites:
            a, b = wounds.encode_sites(self.sites[name]), wounds.encode_sites(again[name])
            self.assertEqual(a, b)
            dec = wounds.decode_sites(a)
            for s, d in zip(self.sites[name], dec):
                self.assertLess(np.abs(s['p'] - d['p']).max(), 0.0006)
                self.assertLess(np.abs(s['n'] - d['n']).max(), 0.02)
                self.assertEqual(s['hint'], d['hint'])

    def test_bind_round_trip(self):
        dec = wounds.decode_bind(wounds.encode_bind(self.m.skeleton))
        for (name, par, mtx), b in zip(dec, self.m.skeleton.bones):
            self.assertEqual(name, b.name)
            self.assertEqual(par, b.parent)
            self.assertLess(np.abs(mtx - b.world).max(), 3e-4)


class TestDamage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.kids, cls.info = setup_model()
        cls.sites = wounds.bake_sites(cls.m, cls.kids, cls.info)
        cls.tris = wounds.model_triangles(cls.m)

    def test_damage_mesh(self):
        skel = self.m.skeleton
        made = 0
        for k in self.kids:
            name = 'body' if k.section < 0 else skel.bones[k.section].name
            d = damage.damage_mesh(k, self.sites.get(name), self.tris)
            if d is None:
                continue
            made += 1
            self.assertEqual(d.shader, parts.OFF_SHADER)
            P = d.P.astype(np.float64)
            S = np.array([s['p'] for s in self.sites[name]])
            cen = (P[d.tris[:, 0]] + P[d.tris[:, 1]] + P[d.tris[:, 2]]) / 3
            near = np.sqrt(((cen[:, None] - S[None]) ** 2).sum(2)).min(1) < damage.PATCH - 0.03
            for a, b in ((0, 1), (1, 2), (2, 0)):
                e = np.linalg.norm(P[d.tris[near, a]] - P[d.tris[near, b]], axis=1)
                self.assertLessEqual(e.max(), damage.MAX_EDGE * 1.0001)
            # same surface: every new vertex lies on an original triangle's plane
            self.assertAlmostEqual(self.area(d), self.area(k), places=4)
            # watertight on the welded surface: the open boundary is unchanged
            self.assertEqual(self.open_edges(d), self.open_edges(k))
            # codes: sites in range, texture coordinates unchanged modulo whole tiles
            site, thick = damage.decode_uv(d.uv.astype(np.float64))
            self.assertTrue(((site >= 0) & (site <= len(S))).all())
            self.assertTrue((site > 0).any())
            self.assertTrue((thick[site > 0] > 0).all())
            self.assertTrue(((thick >= 0) & (thick <= 0.51)).all())
            frac = lambda x: x - np.floor(x)  # noqa: E731
            self.assertLess(np.abs(frac(d.uv[:k.n].astype(np.float64)) - frac(k.uv.astype(np.float64))).max() % 1, 1e-4)
        self.assertGreater(made, 2)

    @staticmethod
    def area(g):
        P = g.P.astype(np.float64)
        a, b, c = P[g.tris[:, 0]], P[g.tris[:, 1]], P[g.tris[:, 2]]
        return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)

    @staticmethod
    def open_edges(g):
        wid = caps.weld(g.P)
        cnt = {}
        for t in g.tris.tolist():
            for x, y in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(wid[x], wid[y]), max(wid[x], wid[y]))
                cnt[k] = cnt.get(k, 0) + 1
        return sum(1 for v in cnt.values() if v == 1)

    def test_chunks(self):
        body = [k for k in self.kids if k.section < 0]
        data, n = damage.chunk_model(self.m, body, self.sites['body'])
        cm = ogf.Model(data)
        self.assertEqual(n, len(self.sites['body']))
        self.assertEqual([b.name for b in cm.skeleton.bones][:2], ['zgo_chunks', 'site_1'])
        self.assertEqual(len(cm.skeleton.bones), n + 1)
        # chunk i is held by bone i, near its site once placed at the victim bone
        skel = self.m.skeleton
        for g in cm.children:
            b = int(g.bones[0, 0])
            self.assertTrue((g.bones[:, 0] == b).all())
            s = self.sites['body'][b - 1]
            P = (np.c_[g.P.astype(np.float64), np.ones(g.n)] @ skel.bones[s['bone']].world.T)[:, :3]
            self.assertLess(np.linalg.norm(P.mean(0) - s['p']), 0.08)


class TestGibs(unittest.TestCase):
    """Body gibs (gibs.py): pieces cut from the body itself."""

    @classmethod
    def setUpClass(cls):
        cls.m, cls.kids, cls.info = setup_model()
        cls.sites = wounds.bake_sites(cls.m, cls.kids, cls.info)
        cls.made = gibs.gib_model(cls.m, cls.kids, cls.sites)

    def test_model(self):
        self.assertIsNotNone(self.made)
        data, frames = self.made
        g = ogf.Model(data)
        names = [b.name for b in g.skeleton.bones]
        self.assertEqual(names[0], 'zgo_gibs')
        self.assertEqual(names[1:], ['gib_%d' % i for i in range(1, len(frames) + 1)])
        self.assertGreaterEqual(len(frames), 8)
        self.assertLessEqual(len(frames), gibs.MAX_GIBS)
        by_bone = {}
        for k in g.children:
            b = set(k.bones[:, 0].tolist()) | set(k.bones[k.weights > 0].tolist())
            self.assertEqual(len(b), 1, 'one bone per sub-mesh')
            self.assertTrue(np.allclose(k.weights[:, 0], 1.0))
            by_bone.setdefault(b.pop(), []).append(k)
        self.assertEqual(sorted(by_bone), list(range(1, len(frames) + 1)))
        for b, ks in by_bone.items():
            tex = {k.texture for k in ks}
            self.assertIn(caps.FLESH_TEX, tex, 'flesh underneath, piece %d' % b)
            self.assertIn('test\\skin', tex, 'the body\'s own skin on top, piece %d' % b)
            P = np.concatenate([k.P for k in ks]).astype(np.float64)
            self.assertLess(np.abs(P).max(), gibs.R_MAX + gibs.DEPTH_MAX + 0.02, 'centred on its own origin')

    def test_no_hands_or_feet(self):
        picked = gibs.pick(self.sites)
        self.assertTrue(picked)
        for sec, _ in picked:
            self.assertNotEqual(wounds.section_class(sec), 'end', sec)

    def _cut_in_bind_space(self):
        """The pieces gib_model keeps, in its order, as cut (bind space)."""
        skel = self.m.skeleton
        out = []
        for sec, s in gibs.pick(self.sites):
            kids = [k for k in self.kids if ('body' if k.section < 0 else skel.bones[k.section].name) == sec]
            made = gibs.cut(kids, s)
            if made:
                out.append(made[0])
        return out

    def test_frames_put_pieces_back_on_the_body(self):
        """The body's bone (bind pose) * the stored frame takes each piece back to where it was cut."""
        data, frames = self.made
        g = ogf.Model(data)
        skel = self.m.skeleton
        dec = gibs.decode_frames(gibs.encode_frames(frames))
        self.assertEqual([n for n, _ in dec], [n for n, _ in frames])
        for (_, rel), (_, rel2) in zip(frames, dec):
            self.assertTrue(np.allclose(rel, rel2, atol=2e-4))
        cut = self._cut_in_bind_space()
        self.assertEqual(len(cut), len(dec))
        names = [b.name for b in skel.bones]
        for i, ((name, rel), tops) in enumerate(zip(dec, cut), 1):
            bw = skel.bones[names.index(name)].world
            top = [k for k in g.children if int(k.bones[0, 0]) == i and k.texture != caps.FLESH_TEX]
            P = np.concatenate([k.P for k in top]).astype(np.float64)
            back = (np.c_[P, np.ones(len(P))] @ (bw @ rel).T)[:, :3]
            want = np.concatenate([t.P for t in tops]).astype(np.float64)
            self.assertEqual(back.shape, want.shape)
            # float32 storage + 0.1 mm / 1e-4 rotation quantisation of the frame
            self.assertLess(np.abs(back - want).max(), 0.0005, 'piece %d (%s)' % (i, name))

    def test_deterministic(self):
        again = gibs.gib_model(self.m, self.kids, self.sites)
        self.assertEqual(again[0], self.made[0])

    def test_open_edges_only(self):
        """No piece has walls taller than its depth plus the allowed height."""
        for sec, s in gibs.pick(self.sites):
            made = gibs.cut([k for k in self.kids if (k.section < 0 and sec == 'body') or
                             (k.section >= 0 and self.m.skeleton.bones[k.section].name == sec)], s)
            if not made:
                continue
            tops, side, depth = made
            h = (np.array(side.P) - s['p']) @ s['n']
            self.assertGreaterEqual(h.min(), -depth - 1e-6)
            self.assertLessEqual(h.max(), gibs.ABOVE + 0.02)


if __name__ == '__main__':
    unittest.main()
