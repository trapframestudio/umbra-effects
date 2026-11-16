#!/usr/bin/env python3
"""
tools/zgo_kidfx/particles_xr.py (particles.xr <-> loose .pe / .pg) and kidfx_pe's colour rule.

    python3 tests/kidfx/test_particles_xr.py

ZGO_TEST_PARTICLES_XR=<particles.xr>[:<another>...] also round-trips real libraries
(the game's own, from db/files.db0, or a mod's); without it those tests are skipped.
"""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIDFX = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'tools', 'zgo_kidfx')
sys.path.insert(0, KIDFX)
import particles_xr as px  # noqa: E402
import kidfx_pe  # noqa: E402

AWKWARD = [0.1, 1e-7, -0.0, 3.4028234663852886e+38, 1.401298464324817e-45, -1.5707963267948966, 777777777.0,
           1e16, float('-inf'), 0.333333343267, 12345.678]


def chunk(cid, body):
    return struct.pack('<II', cid, len(body)) + body


def sz(s):
    return s.encode('latin1') + b'\0'


def effect_body(e, version=1, edata=True):
    """An effect's particles.xr entry, as CPEDef::Save writes it (chunk 4 a stand-in)."""
    b = chunk(1, struct.pack('<H', version)) + chunk(2, sz(e.name)) + chunk(3, struct.pack('<I', e.max_particles))
    b += chunk(4, b'\0' * 4) + chunk(5, struct.pack('<I', e.flags))
    if e.flags & px.DF_SPRITE:
        b += chunk(7, sz(e.shader) + sz(e.texture))
    if e.flags & px.DF_FRAMED:
        b += chunk(6, struct.pack('<4f2if', *e.frame))
    if e.flags & px.DF_TIMELIMIT:
        b += chunk(8, struct.pack('<f', e.time_limit))
    if e.flags & px.DF_COLLISION:
        b += chunk(0x21, struct.pack('<3f', *e.collision))
    if e.flags & px.DF_VELOCITY_SCALE:
        b += chunk(0x22, struct.pack('<3f', *e.velocity_scale))
    if e.flags & px.DF_ALIGN_TO_PATH:
        b += chunk(0x25, struct.pack('<3f', *e.align_rotation))
    if edata:
        b += chunk(0x24, px.effect_edata(e))
    return b


def group_body(name, effects, time_limit=None, version=3):
    ents = struct.pack('<I', len(effects)) + b''.join(
        sz(n) + sz(p) + sz(bi) + sz(d) + struct.pack('<ffI', t0, t1, fl) for n, p, bi, d, t0, t1, fl in effects)
    b = chunk(1, struct.pack('<H', version)) + chunk(2, sz(name)) + chunk(3, struct.pack('<I', 0)) + chunk(4, ents)
    if time_limit is not None:
        b += chunk(5, struct.pack('<f', time_limit))
    return b


def library(effects=(), groups=()):
    return chunk(1, struct.pack('<H', 1)) + chunk(3, b''.join(chunk(i, e) for i, e in enumerate(effects))) + \
        chunk(4, b''.join(chunk(i, g) for i, g in enumerate(groups)))


def every_action_effect():
    """One effect with every action type, every optional block and awkward floats."""
    e = px.Effect('test\\every_action')
    e.max_particles = 77
    e.flags = (px.DF_SPRITE | px.DF_FRAMED | px.DF_TIMELIMIT | px.DF_COLLISION | px.DF_VELOCITY_SCALE |
               px.DF_ALIGN_TO_PATH | (1 << 21))
    e.shader, e.texture = 'particles\\alpha_add', 'pfx\\pfx_smoke_a,pfx\\pfx_dist2'
    e.frame = (px.f32(0.125), px.f32(0.5), 0.0, 0.0, 8, 16, px.f32(24.0))
    e.time_limit = px.f32(1.75)
    e.collision = (px.f32(0.9), px.f32(0.1), px.f32(0.01))
    e.velocity_scale = (px.f32(0.1), 1e-07, 0.0)
    e.align_rotation = (px.f32(-1.5707963267948966), 0.0, 0.0)
    k = 0
    for t, (name, nf, nv, nd, nb, ni) in sorted(px.ACTIONS.items()):
        def nxt():
            nonlocal k
            k += 1
            return px.f32(AWKWARD[k % len(AWKWARD)])
        e.actions.append(px.Action(t, name=name, flags=3, floats=[nxt() for _ in range(nf)],
                                   vectors=[[nxt(), nxt(), nxt()] for _ in range(nv)],
                                   domains=[(k % 11, [[nxt(), nxt(), nxt()] for _ in range(3)]) for _ in range(nd)],
                                   bools=[(k + j) % 2 for j in range(nb)], ints=[-3 + k for _ in range(ni)]))
    return e


class TestFloats(unittest.TestCase):
    def test_six_decimals_when_they_read_back(self):
        self.assertEqual(px.fmt_float(0.5), '0.500000')
        self.assertEqual(px.fmt_float(px.f32(0.1)), '0.100000')
        self.assertEqual(px.fmt_float(-0.0), '-0.000000')
        self.assertEqual(px.fmt_float(float('-inf')), '-inf')

    def test_more_when_six_lose_the_value(self):
        for v in (1e-07, 1.401298464324817e-45, px.f32(0.7137255), px.f32(1e16)):
            s = px.fmt_float(px.f32(v))
            self.assertNotIn('e', s)
            self.assertEqual(px.f32(float(s)), px.f32(v), s)          # atof, then the cast
            self.assertEqual(px._f32_exact(s), px.f32(v), s)          # strtof
        self.assertEqual(px.fmt_float(px.f32(0.7137255)), '0.7137255')

    def test_strtof_rounds_once(self):
        # halfway between two floats: ties go to the even one
        lo = px.f32(1.0)
        hi = px._from_bits(px._bits(lo) + 1)
        mid = (lo + hi) / 2                                 # exact in double
        self.assertEqual(px._f32_exact('%.30f' % mid), lo, 'exactly halfway: the even one')
        self.assertEqual(px._f32_exact(repr(mid)), hi, 'repr is a hair above halfway')
        self.assertEqual(px._f32_exact('1e-50'), 0.0)
        self.assertEqual(px._f32_exact('-1.5E+3'), -1500.0)
        with self.assertRaises(px.FormatError):
            px.fmt_float(float('nan'))


class TestRoundTrip(unittest.TestCase):
    def test_every_action(self):
        e = every_action_effect()
        lib = px.loads(library([effect_body(e)]))
        self.assertEqual(lib.skipped, [])
        got = lib.effects['test\\every_action']
        self.assertIsNone(px.round_trip('pe', got))
        back = px.parse_pe(px.effect_ini(got), got.name)
        self.assertEqual(px.effect_edata(back), px.effect_edata(e))
        self.assertTrue(px.same(back, e))

    def test_loose_file_layout(self):
        e = every_action_effect()
        ini = px.read_ini(px.effect_ini(e))
        self.assertEqual(sorted(k for k in ini if not k.startswith(('action_', 'domain_'))),
                         ['_effect', 'align_to_path', 'collision', 'frame', 'sprite', 'timelimit', 'velocity_scale'])
        self.assertEqual(ini['_effect']['action_count'], str(len(px.ACTIONS)))
        src = next(i for i, a in enumerate(e.actions) if a.type == 21)
        self.assertEqual(ini['action_%04d' % src]['action_type'], '21')
        self.assertIn('domain_action_%04d_0004' % src, ini, 'source has five domains')
        self.assertEqual(ini['sprite']['texture'], 'pfx\\pfx_smoke_a,pfx\\pfx_dist2')
        text = px.effect_ini(e).decode('latin1')
        self.assertTrue(text.startswith('[_effect]\n        action_count                     = '), text[:80])

    def test_group_children_and_time_limit(self):
        g = group_body('test\\grp', [('test\\a', 'stale_play', 'test\\birth', '', 0.0, 0.25, 4 | px.FL_ON_BIRTH_CHILD),
                                     ('test\\b', '', '', 'stale_dead', 0.5, 2.5, 4)])
        lib = px.loads(library([], [g]))
        grp = lib.groups['test\\grp']
        self.assertEqual(grp.time_limit, 2.5, 'no time limit chunk: the longest time1')
        ini = px.read_ini(px.group_ini(grp))
        self.assertEqual(ini['effect_0000']['on_play_child'], '', 'its flag is not set: the SDK writes no name')
        self.assertEqual(ini['effect_0000']['on_birth_child'], 'test\\birth')
        self.assertEqual(ini['effect_0001']['on_death_child'], '')
        self.assertEqual(px.children(grp), ['test\\a', 'test\\birth', 'test\\b'])
        self.assertTrue(px.same(px.parse_pg(px.group_ini(grp)), grp))
        self.assertIsNone(px.round_trip('pg', grp))
        lib = px.loads(library([], [group_body('test\\fixed', [('test\\a', '', '', '', 0.0, 9.0, 4)], 1.0)]))
        self.assertEqual(lib.groups['test\\fixed'].time_limit, 1.0)

    def test_what_the_game_drops_is_skipped(self):
        e = every_action_effect()
        bad = [effect_body(e, version=2), effect_body(e, edata=False)]
        lib = px.loads(library(bad, [group_body('test\\g', [], version=2)]))
        self.assertEqual(lib.effects, {})
        self.assertEqual(lib.groups, {})
        self.assertEqual([s[0] for s in lib.skipped], ['effect', 'effect', 'group'])
        self.assertIn('chunk 0x24', lib.skipped[1][2])

    def test_find_and_export(self):
        e = every_action_effect()
        e.name = 'Test\\Mixed_Case'
        lib = px.loads(library([effect_body(e)], [group_body('test\\g', [('Test\\Mixed_Case', '', '', '', 0, 1, 4)])]))
        self.assertEqual(lib.find('test/mixed_case')[0], 'pe')
        self.assertEqual(lib.find('TEST\\G')[0], 'pg')
        self.assertIsNone(lib.find('test\\none'))
        with tempfile.TemporaryDirectory() as d:
            out = px.export(lib, d, ['test\\mixed_case', 'test\\g'])
            self.assertEqual(sorted(os.path.relpath(p, d) for _, _, p in out),
                             sorted([os.path.join('test', 'g.pg'), os.path.join('test', 'mixed_case.pe')]))
            with self.assertRaises(FileExistsError):
                px.export(lib, d, ['test\\g'])

    def test_texture_names_as_the_engine_reads_them(self):
        e = px.Effect('x')
        e.flags = px.DF_SPRITE
        e.texture = 'pfx\\pfx_ani-fire01.bmp, PFX/Smoke.dds,,crysis_3\\spark'
        self.assertEqual(px.texture_names(e), ['pfx\\pfx_ani-fire01', 'pfx\\smoke', 'crysis_3\\spark'])

    def test_strings_an_ini_line_cannot_hold(self):
        e = every_action_effect()
        e.shader = 'particles\\add;oops'
        with self.assertRaises(px.FormatError):
            px.effect_ini(e)

    @unittest.skipUnless(os.environ.get('ZGO_TEST_PARTICLES_XR'), 'set ZGO_TEST_PARTICLES_XR to real particles.xr files')
    def test_real_libraries(self):
        for path in os.environ['ZGO_TEST_PARTICLES_XR'].split(os.pathsep):
            lib = px.load(path)
            self.assertGreater(len(lib.effects), 0, path)
            fails = [n for n, e in lib.effects.items() if px.round_trip('pe', e)]
            fails += [n for n, g in lib.groups.items() if px.round_trip('pg', g)]
            self.assertEqual(fails, [], path)


class TestBloodRed(unittest.TestCase):
    def test_blood(self):
        for c in ((0.45, 0, 0), (0.27, 0.15, 0.15), (0.20, 0.06, 0.06), (0.13, 0.01, 0.01), (0.6, 0.05, 0.08)):
            self.assertTrue(kidfx_pe.blood_red(c), c)

    def test_fire_glow_and_others(self):
        for c in ((1.0, 0.49, 0.20), (0.82, 0.29, 0.0), (1.0, 0.62, 0.34), (0.58, 0.31, 0.14), (0.25, 0.01, 0.06),
                  (0.14, 0.06, 0.0), (1, 1, 1), (0.05, 0, 0), None):
            self.assertFalse(kidfx_pe.blood_red(c), c)

    def test_classify_uses_it(self):
        cls, why = kidfx_pe.classify('explosions/effects/expl_hd_x.pe', 'particles\\add', 'crysis_3\\spark_tiled_blue',
                                     (1.0, 0.49, 0.2))
        self.assertEqual(cls, 'clean', why)
        cls, why = kidfx_pe.classify('srbd/headshot/srbd_upsplash.pe', 'particles\\blend', 'farcry4\\water_splash_01',
                                     (0.13, 0.01, 0.01))
        self.assertEqual(cls, 'gore', why)


if __name__ == '__main__':
    unittest.main()
