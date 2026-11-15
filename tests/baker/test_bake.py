"""bake.bake() as the setup GUI uses it: progress, cancel, the manifest,
remove(), refusing to overwrite, default output identical to plain splitting,
the experimental flags, and the Lua fixtures being current."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakemo2  # noqa: E402
import synth  # noqa: E402
import bake, ogf, partition  # noqa: E402


def walk(root):
    out = set()
    for dp, _, fs in os.walk(root):
        for f in fs:
            out.add(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/'))
    return out


class TestBake(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.o = fakemo2.make(self.root)
        self.p = fakemo2.patched()
        self.p.__enter__()

    def tearDown(self):
        self.p.__exit__(None, None, None)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_progress_report_manifest_remove(self):
        seen = []
        rep = bake.bake(self.o, progress=lambda *a: seen.append(a))
        stages = [s[0] for s in seen]
        self.assertTrue(set(stages) <= set(bake.STAGES))
        self.assertEqual(stages[-1], 'done')
        order = [bake.STAGES.index(s) for s in stages]
        self.assertEqual(order, sorted(order), 'stages come in order')
        for s, done, total, msg in seen:
            self.assertTrue(0 <= done <= total and isinstance(msg, str))
        self.assertEqual((rep['baked'], rep['errors']), (3, 0))
        c = rep['counts']
        self.assertEqual(c['caps'], 15)
        self.assertEqual(c['cap_files'], 10)          # synth_a and synth_b share files, synth_m differs
        self.assertEqual(c['pieces'], 15)
        self.assertEqual(c['piece_files'], 10)
        self.assertGreater(c['sites'], 30)
        self.assertEqual(rep['options'], self.o.flags())
        # the manifest is exactly what is on disk (plus the report itself)
        self.assertEqual(walk(self.o.out), set(rep['files']) | {bake.REPORT})
        for f in bake.SCRIPTS:
            self.assertIn(f, rep['files'])
        self.assertEqual(sorted(rep['files']), rep['files'])
        with open(os.path.join(self.o.out, bake.REPORT)) as f:
            self.assertEqual(json.load(f)['files'], rep['files'])
        self.assertEqual(bake.previous_files(self.o.out), rep['files'])
        # a second bake replaces the first one exactly
        rep2 = bake.bake(self.o)
        self.assertEqual(rep2['files'], rep['files'])
        self.assertEqual(rep2['replaced'], len(rep['files']))
        # remove deletes those and nothing else
        keep = os.path.join(self.o.out, 'gamedata', 'meshes', 'mine.ogf')
        with open(keep, 'w') as f:
            f.write('x')
        n = bake.remove(self.o.out)
        self.assertEqual(n, len(rep['files']))
        self.assertEqual(walk(self.o.out), {'gamedata/meshes/mine.ogf'})

    def test_refuses_to_overwrite(self):
        mine = os.path.join(self.o.out, 'gamedata', 'meshes', 'actors', 'synth', 'synth_a.ogf')
        os.makedirs(os.path.dirname(mine))
        with open(mine, 'wb') as f:
            f.write(b'not mine')
        with self.assertRaises(bake.BakeError):
            bake.bake(self.o)
        with open(mine, 'rb') as f:
            self.assertEqual(f.read(), b'not mine')
        self.assertEqual(walk(self.o.out), {'gamedata/meshes/actors/synth/synth_a.ogf'})

    def test_cancel_leaves_the_folder_alone(self):
        bake.bake(self.o)
        before = {f: os.path.getmtime(os.path.join(self.o.out, f)) for f in walk(self.o.out)}
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 3
        with self.assertRaises(bake.Cancelled):
            bake.bake(self.o, cancel=cancel)
        after = {f: os.path.getmtime(os.path.join(self.o.out, f)) for f in walk(self.o.out)}
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(os.path.join(self.o.cache, 'building-x')))
        self.assertEqual([d for d in os.listdir(self.o.cache) if d.startswith('building')], [])

    def test_bad_options(self):
        for k, v in (('mo2', os.path.join(self.root, 'nope')), ('profile', 'nope'), ('anomaly', self.root)):
            o = fakemo2.make(tempfile.mkdtemp(dir=self.root))
            setattr(o, k, v)
            with self.assertRaises(bake.BakeError):
                bake.bake(o)

    def test_default_models_are_plain_splits(self):
        """Caps, pieces, wounds and gibs never change the baked models themselves."""
        rep = bake.bake(self.o)
        m = ogf.Model(synth.build())
        kids, _ = partition.split_model(m, synth.LIMBS)
        want = bake.check(m, kids)
        with open(os.path.join(self.o.out, 'gamedata/meshes/actors/synth/synth_a.ogf'), 'rb') as f:
            self.assertEqual(f.read(), want)
        o2 = fakemo2.make(tempfile.mkdtemp(dir=self.root))
        o2.caps = o2.pieces = o2.wounds = o2.gibs = False
        rep2 = bake.bake(o2)
        stock = [f for f in rep2['files'] if f.startswith('gamedata/meshes/actors') or f.startswith('gamedata/meshes/monsters')]
        self.assertEqual(len(stock), 3)
        for f in stock:
            with open(os.path.join(self.o.out, f), 'rb') as a, open(os.path.join(o2.out, f), 'rb') as b:
                self.assertEqual(a.read(), b.read(), f)
        self.assertFalse([f for f in rep2['files'] if f.startswith('gamedata/meshes/zgo/')])
        self.assertTrue([f for f in rep['files'] if f.startswith('gamedata/meshes/zgo/baked/caps/')])
        self.assertTrue([f for f in rep['files'] if f.startswith(bake.GIB_FILES)])
        self.assertEqual(rep['counts']['gib_files'], len([f for f in rep['files'] if f.startswith(bake.GIB_FILES)]))

    def test_experimental(self):
        self.o.experimental_caps = self.o.experimental_damage = True
        rep = bake.bake(self.o)
        self.assertEqual(rep['errors'], 0)
        self.assertGreater(rep['counts']['chunk_files'], 0)
        with open(os.path.join(self.o.out, 'gamedata/meshes/actors/synth/synth_a.ogf'), 'rb') as f:
            m = ogf.Model(f.read())
        base = ogf.Model(synth.build())
        kids, _ = partition.split_model(base, synth.LIMBS)
        n = len(kids)
        self.assertGreater(len(m.children), n)
        for g in m.children[n:]:
            self.assertEqual(g.shader, 'zgo\\off')
        for g, k in zip(m.children[:n], kids):
            self.assertEqual(g.shader, k.shader)
        for f in rep['files']:
            if f.startswith('gamedata/meshes/zgo/'):
                with open(os.path.join(self.o.out, f), 'rb') as fh:
                    ogf.Model(fh.read())

    def test_lua_fixtures_current(self):
        got = fakemo2.fixture_scripts()
        for name, text in got.items():
            with open(os.path.join(fakemo2.FIXTURES, name), encoding='utf-8', newline='') as f:
                self.assertEqual(f.read(), text, '%s is stale: python3 tests/baker/fakemo2.py --fixtures' % name)

    @unittest.skipUnless(shutil.which('luajit'), 'needs luajit')
    def test_scripts_load_in_luajit(self):
        bake.bake(self.o)
        for rel in bake.SCRIPTS:
            p = os.path.join(self.o.out, *rel.split('/'))
            # (the path goes inside the chunk: with "luajit -e chunk file" the file is
            # arg[0] and gets run itself, and loadfile(nil) would read stdin)
            chunk = ('local env = {}; local f = assert(loadfile([==[%s]==])); setfenv(f, env); f(); '
                     'assert(type(env.models) == "table" and env.bake_id, "models / bake_id")') % p
            r = subprocess.run(['luajit', '-e', chunk], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)


class TestOptions(unittest.TestCase):
    def test_mo2_defaults(self):
        root = tempfile.mkdtemp()
        try:
            mod = os.path.join(root, 'mods', 'ZGO')
            os.makedirs(mod)
            os.makedirs(os.path.join(root, 'profiles', 'Main'))
            with open(os.path.join(root, 'ModOrganizer.ini'), 'w') as f:
                f.write('[General]\nselected_profile=@ByteArray(Main)\ngamePath=@ByteArray(Z:\\\\home\\\\u\\\\anomaly)\n')
            mo2, prof, game = bake.mo2_defaults(mod)
            self.assertEqual((mo2, prof), (root, 'Main'))
            if os.name != 'nt':
                self.assertEqual(game, '/home/u/anomaly')
        finally:
            shutil.rmtree(root)

    def test_cli_flags(self):
        self.assertEqual(bake.Options().flags(), {'caps': True, 'pieces': True, 'wounds': True, 'gibs': True,
                                                  'experimental_caps': False, 'experimental_damage': False})
        self.assertFalse(bake.Options(gibs=False).flags()['gibs'])


if __name__ == '__main__':
    unittest.main()
