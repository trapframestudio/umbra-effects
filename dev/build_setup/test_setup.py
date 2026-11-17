"""
Tests of Umbra Effects Setup (tools/zgo_setup) and the parts of the baker it relies on
(the pure-Python Lua reader, fingerprints, zgo_bake_inputs.script).

    python3 -m unittest discover -s dev/build_setup -p 'test_*.py'      (from the ZGO folder)

  - the logic layer in this process, against a fake MO2 + game (fakezgo.py)
  - zgo_setup.py as a player runs it (subprocesses, a fake install with its
    own copy of tools/), --plan / --bake / --check / --remove / --selftest
  - the window, driven by gui_driver.py, when tkinter and a display (or
    xvfb-run) are there; otherwise skipped
  - the ready-made Linux program when it is built (tools/zgo_setup/zgo-setup-linux,
    or ZGO_SETUP_BIN=path); the Windows one under Wine with ZGO_TEST_WINE=1
Nothing outside temporary folders is written (the baker's work folder is
redirected too).
"""
import contextlib
import errno
import hashlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..'))
SETUP_DIR = os.path.join(MOD, 'tools', 'zgo_setup')
sys.path.insert(0, HERE)
sys.path.insert(0, SETUP_DIR)
sys.path.insert(0, os.path.join(MOD, 'tools', 'zgo_baker'))

import fakezgo  # noqa: E402
import bake  # noqa: E402
import limbs  # noqa: E402
import setup_core as core  # noqa: E402

LUAJIT = shutil.which('luajit')
NOTICE = os.path.join(MOD, 'gamedata', 'scripts', 'zgo_setup_notice.script')
TABLES = os.path.join(MOD, 'gamedata', 'scripts', 'zgo_tables.script')
# the baker's work folder of every test run goes to a temporary folder
TMP_CACHE = tempfile.mkdtemp(prefix='zgo_setup_test_cache_')
os.environ['ZGO_BAKER_CACHE'] = TMP_CACHE
# no test asks Umbra's bucket for a ready-made bake; TestPrebaked serves its own
os.environ['ZGO_PREBAKED_SOURCE'] = 'off'


def tearDownModule():
    shutil.rmtree(TMP_CACHE, ignore_errors=True)


def fake_kinds():
    with tempfile.NamedTemporaryFile('w', suffix='.script', delete=False) as f:
        f.write(fakezgo.TABLES)
    try:
        return limbs.roots_from_limb_map(limbs.read_tables(f.name, wanted={'limb_map'})['limb_map'])
    finally:
        os.remove(f.name)


@contextlib.contextmanager
def fake_tables(kinds=None):
    """The real ZGO folder's tools, the fake creature kinds."""
    k = kinds or fake_kinds()
    with mock.patch.object(limbs, 'load', lambda root: k):
        yield k


def lua(code):
    out = subprocess.run([LUAJIT, '-e', code], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr)
    return out.stdout


# ===================================================================== the Lua reader

class TestLuaReader(unittest.TestCase):
    def read(self, text, wanted=None):
        with tempfile.NamedTemporaryFile('w', suffix='.script', delete=False, encoding='utf-8') as f:
            f.write(text)
        try:
            return limbs.read_tables(f.name, wanted)
        finally:
            os.remove(f.name)

    def test_values(self):
        g = self.read(r'''
-- a comment { not a table
--[[ a long
comment ]]  --[==[ another ]==]
a = { 1, 2.5, -3, 0x10, 1e3, "s", 's\'q', "tab\tnl\n\"", [[long
string]], true, false, nil, x = 1, ["y z"] = { k = "v" }, [7] = "seven"; last = "semi" }
local helper = function(t) if t then for i = 1, 2 do t[i] = i end end return t end
b = "x" .. "y"
c = { nested = { deeper = { "ok" } } }
function f(x) local q = { 1 } repeat x = x - 1 until x < 0 return q end
d = { "after a function" }
''')
        a = g['a']
        self.assertEqual([a[i] for i in range(1, 11)], [1, 2.5, -3, 16, 1000.0, 's', "s'q", 'tab\tnl\n"', 'long\nstring', True])
        self.assertIs(a[11], False)
        self.assertEqual((a['x'], a['y z'], a[7], a['last']), (1, {'k': 'v'}, 'seven', 'semi'))
        self.assertEqual(g['c']['nested']['deeper'][1], 'ok')
        self.assertEqual(g['d'][1], 'after a function')
        self.assertNotIn('helper', g)

    def test_wanted_and_errors(self):
        g = self.read('a = { 1 }\nb = { 2 }\n', wanted={'b'})
        self.assertEqual(list(g), ['b'])
        with self.assertRaises(limbs.LuaReadError):
            self.read('a = { 1, 2')
        with self.assertRaises(limbs.LuaReadError):
            self.read('a = "unterminated')
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'gamedata', 'scripts'))
            with open(os.path.join(d, 'gamedata', 'scripts', 'zgo_tables.script'), 'w') as f:
                f.write('other = {}\n')
            with self.assertRaises(limbs.LuaReadError):
                limbs.load(d)
            with self.assertRaises(limbs.LuaReadError):
                limbs.load(os.path.join(d, 'nowhere'))

    def test_roots_and_canonical(self):
        r = limbs.roots_from_limb_map({'dog': {'a': {1: 'Bip01_Head'}, 'b': {1: 'bip01_head'}, 'c': {2: 'x'}},
                                       'cat': {}, 'ant': {'x': {1: 'z'}, 'y': {1: 'a'}}, 'bad': 5})
        self.assertEqual(r, {'dog': ['bip01_head'], 'cat': [], 'ant': ['a', 'z']})
        self.assertEqual(limbs.canonical(r), 'ant=a,z;dog=bip01_head')

    def test_shipped_tables(self):
        k = limbs.load(MOD)
        self.assertGreaterEqual(len(k), 5)
        self.assertIn('bip01_head', k.get('human', []))

    @unittest.skipUnless(LUAJIT, 'luajit is not installed')
    def test_same_line_as_the_game(self):
        """The in-game check builds the same line from zgo_tables.limb_map."""
        code = ('setmetatable(_G, { __index = function() return setmetatable({}, { __index = function() return 0 end }) end }) '
                'zgo_util = {} dofile(%r) dofile(%r) io.write(canonical_tables(limb_map))' % (TABLES, NOTICE))
        self.assertEqual(lua(code), limbs.canonical(limbs.load(MOD)))

    @unittest.skipUnless(LUAJIT, 'luajit is not installed')
    def test_same_as_luajit(self):
        """The reader agrees with LuaJIT on the real tables (the baker no longer needs LuaJIT)."""
        code = ('setmetatable(_G, { __index = function() return setmetatable({}, { __index = function() return 0 end }) end }) '
                'dofile(%r) local ks = {} for k in pairs(limb_map) do ks[#ks + 1] = k end table.sort(ks) '
                'for _, k in ipairs(ks) do local n = 0 for _ in pairs(limb_map[k]) do n = n + 1 end '
                'io.write(k, "=", n, ";") end' % TABLES)
        g = limbs.read_tables(TABLES, wanted={'limb_map'})['limb_map']
        mine = ''.join('%s=%d;' % (k, len(g[k])) for k in sorted(g))
        self.assertEqual(lua(code), mine)


# ===================================================================== versions and the inputs file

class TestVersions(unittest.TestCase):
    def test_baker_version_matches_the_game(self):
        with open(NOTICE, encoding='utf-8') as f:
            m = re.search(r'^BAKER = (\d+)', f.read(), re.M)
        self.assertTrue(m, 'BAKER = n in zgo_setup_notice.script')
        self.assertEqual(int(m.group(1)), bake.BAKER_VERSION,
                         'tools/zgo_baker/bake.py BAKER_VERSION and zgo_setup_notice.script BAKER must match')

    def test_zgo_version(self):
        with tempfile.TemporaryDirectory() as d:
            inst = fakezgo.make(d, version='9.8.7')
            self.assertEqual(bake.zgo_version(inst.mod), '9.8.7')
            os.remove(os.path.join(inst.mod, 'meta.ini'))
            self.assertEqual(bake.zgo_version(inst.mod), '9.8.7')       # from zgo_main.script
        self.assertTrue(re.match(r'^\d+\.\d+', bake.zgo_version(MOD)))

    def test_game_path(self):
        if os.name == 'nt':
            self.assertEqual(bake.game_path('C:\\x'), 'C:\\x')
        else:
            self.assertEqual(bake.game_path('/home/a b/mo2'), 'Z:\\home\\a b\\mo2')

    def test_fingerprint(self):
        res = [{'key': 'a', 'src_md5': '1', 'status': 'ok'}, {'key': 'b', 'src_md5': '2', 'status': 'ok'}]
        f = bake.fingerprint(res, {'caps': True}, 't')
        self.assertEqual(f, bake.fingerprint(list(reversed(res)), {'caps': True}, 't'), 'order does not matter')
        self.assertNotEqual(f, bake.fingerprint(res, {'caps': False}, 't'))
        self.assertNotEqual(f, bake.fingerprint(res, {'caps': True}, 'u'))
        self.assertNotEqual(f, bake.fingerprint(res[:1], {'caps': True}, 't'))


# ===================================================================== small parts of the logic layer

class TestCoreParts(unittest.TestCase):
    def test_human(self):
        self.assertEqual(core.human_bytes(0), '0 bytes')
        self.assertEqual(core.human_bytes(999), '999 bytes')
        self.assertEqual(core.human_bytes(1500), '1.5 KB')
        self.assertEqual(core.human_bytes(6.4e9), '6.4 GB')
        self.assertEqual(core.human_bytes(250e6), '250 MB')
        self.assertEqual(core.human_seconds(0), '1 seconds')
        self.assertEqual(core.human_seconds(80), '80 seconds')
        self.assertEqual(core.human_seconds(600), '10 minutes')
        self.assertEqual(core.human_seconds(4 * 3600), '4.0 hours')

    def test_choices(self):
        c = core.Choices()
        self.assertTrue(c.caps and c.pieces and c.wounds and c.props)
        self.assertTrue(c.kid_particles, 'kid mode for particles starts on')
        self.assertFalse(c.experimental_caps or c.experimental_damage or c.experimental_props, 'experimental parts start off')
        c2 = core.Choices.from_dict(dict(c.as_dict(), pieces=False, experimental_caps=True, jobs=3))
        self.assertEqual((c2.pieces, c2.experimental_caps, c2.jobs, c2.kid_particles), (False, True, 3, True))
        self.assertIn('kid_particles', c.as_dict())
        c3 = core.Choices.from_dict(json.loads(json.dumps(core.Choices(kid_particles=False, jobs=2).as_dict())))
        self.assertEqual((c3.kid_particles, c3.caps, c3.jobs), (False, True, 2), 'saved and read back (job.json)')
        self.assertTrue(core.Choices.from_dict({'caps': False}).kid_particles, 'an older job file: the default')
        self.assertGreaterEqual(core.default_jobs(), 1)

    def test_progress_is_monotonic(self):
        for props, particles in ((False, False), (True, False), (False, True), (True, True)):
            seen = []
            for stage in bake.STAGES:
                for d in (0, 5, 10):
                    seen.append(core.overall_fraction('models', stage, d, 10, props, particles))
            if props:
                for d in (0, 3, 6):
                    seen.append(core.overall_fraction('props', 'cut', d, 6, props, particles))
            if particles:
                for d in (0, 1):
                    seen.append(core.overall_fraction('particles', 'particles', d, 1, props, particles))
            self.assertEqual(seen, sorted(seen), (props, particles))
            self.assertGreaterEqual(seen[0], 0.0)
            self.assertAlmostEqual(seen[-1], 1.0)
        self.assertEqual(core.overall_fraction('models', 'nonsense', 1, 2, False), 0.0)
        self.assertTrue(all(s in core.STAGE_WEIGHT and s in core.STAGE_TEXT for s in bake.STAGES))
        self.assertIn('particles', core.STAGE_TEXT)

    def test_source_name(self):
        t = None
        self.assertEqual(core.source_name(t, None, '/a/mo2/mods/Some Mod/gamedata/meshes/actors/x.ogf'), 'Some Mod')
        self.assertEqual(core.source_name(t, None, 'Z:\\a\\MO2\\mods\\Mod B\\gamedata\\meshes\\actors\\x.ogf'), 'Mod B')
        self.assertEqual(core.source_name(t, None, '/cache/base/gamedata/meshes/actors/x.ogf'), '')
        self.assertEqual(core.source_name(t, None, None), '')

    def test_friendly(self):
        f = core.friendly
        self.assertIn('disk is full', f(OSError(errno.ENOSPC, 'No space', '/x')))
        self.assertIn('not allowed to change /x', f(PermissionError(errno.EACCES, 'denied', '/x')))
        self.assertIn('missing: /x', f(FileNotFoundError(errno.ENOENT, 'no', '/x')))
        self.assertIn('ran out of memory', f(MemoryError()))
        self.assertEqual(f(core.SetupError('Do this.')), 'Do this.')
        self.assertEqual(f(bake.BakeError('the baker says so')), 'The baker says so')
        self.assertIn('Wait for it', f(bake.BakeError('another bake into this folder is running (pid 5)')))
        self.assertIn('bug report', f(ValueError('odd')))

    def test_mod_root(self):
        self.assertEqual(core.find_mod_root(SETUP_DIR), MOD)
        self.assertTrue(core.is_mod_root(MOD))
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(core.find_mod_root(d))
            with self.assertRaises(core.SetupError):
                core.Tools(d)

    def test_status_text(self):
        st = core.Status('stale', 'Out of date.', ['a', 'b'], 'Bake.', ['info'])
        self.assertEqual(st.text(), 'Out of date.\n  - a\n  - b\nBake.\n  (info)')
        self.assertEqual(st.as_dict()['state'], 'stale')

    def test_space(self):
        p = core.Plan()
        p.free = {'/a': 100e9, '/b': 1e9}
        p.needed = {'/a': 6e9, '/b': 6e9}
        out = core.space_problems(p)
        self.assertEqual(len(out), 1)
        self.assertIn('/b', out[0])

    def test_log(self):
        with tempfile.TemporaryDirectory() as d:
            got = []
            log = core.Log(path=os.path.join(d, 'x.log'), echo=got.append)
            seen = []
            log.listeners.append(lambda lv, line: seen.append(lv))
            log('hello')
            log('careful', 'warn')
            with open(os.path.join(d, 'x.log')) as f:
                text = f.read()
            self.assertIn('hello', text)
            self.assertIn('WARN: careful', text)
            self.assertEqual(seen, ['info', 'warn'])
            self.assertEqual(len(got), 2)
            log.f.close()

    def test_environment(self):
        lines = core.environment_lines(core.Tools(MOD))
        self.assertIn('Umbra Effects Setup', lines[0])
        self.assertTrue(any('baker %d' % bake.BAKER_VERSION in l for l in lines))
        self.assertIn('Kid mode for particles: found', lines)

    def test_kidfx_loads_from_the_zgo_folder(self):
        """Only loading and reading here: the real ZGO folder's kidfx never
        runs a step that writes (TestKidfx works on a copy)."""
        t = core.Tools(MOD)
        self.assertIsNone(t.kidfx_problem)
        self.assertTrue(core._same_dir(t.kidfx.MOD_ROOT, MOD))
        self.assertIs(core.kidfx_for(t, core.Paths(MOD)), t.kidfx, 'the bake goes into the ZGO folder: kidfx acts')
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(core.kidfx_for(t, core.Paths(MOD, out=d)), 'a bake elsewhere leaves it alone')
            self.assertIn('left alone', core.kidfx_unavailable(t, core.Paths(MOD, out=d)))
            self.assertEqual(core.check_kidfx(t, core.Paths(MOD, out=d)), ('none', ''))
            self.assertEqual(core.load_kidfx(d), (None, None), 'a ZGO without it')
            # another folder's copy while this one is loaded: refused, never mixed
            kd = os.path.join(d, 'tools', 'zgo_kidfx')
            os.makedirs(kd)
            open(os.path.join(kd, 'kidfx_pe.py'), 'w').close()
            try:
                k, why = core.load_kidfx(d)
            finally:
                while kd in sys.path:
                    sys.path.remove(kd)
            self.assertIsNone(k)
            self.assertIn('another copy', why)
        t2 = types.SimpleNamespace(kidfx=None, kidfx_problem='ImportError: x', mod=MOD)
        self.assertIn('could not be loaded (ImportError: x)', core.kidfx_unavailable(t2, core.Paths(MOD)))
        self.assertEqual(core.kidfx_summary({}), {'shaders': 0, 'shaders_written': 0, 'copied': 0, 'copies': 0,
                                                  'skipped': 0, 'applied': 0, 'problems': 0})
        self.assertIn('Particles\\set is not', core.kidfx_friendly(RuntimeError('particles\\set is not a blender')))
        self.assertIn('disk is full', core.kidfx_friendly(OSError(errno.ENOSPC, 'No space', '/x')))


# ===================================================================== the logic layer on a fake install

class FakeInstallCase(unittest.TestCase):
    """The real ZGO folder's tools, a fake MO2 + game; the bake goes into the
    fake MO2's mods/Out (as if that were the ZGO folder)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='zgo_setup_test_')
        self.inst = fakezgo.make(self.tmp, tools=False, zgo='Out')
        self.tools = core.Tools(MOD)
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=self.inst.mod, cache=self.inst.cache)
        self.choices = core.Choices(jobs=2, props=False)
        self.patch = fake_tables()
        self.patch.__enter__()

    def tearDown(self):
        self.patch.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def worker(self, action='bake', choices=None, cancel=False):
        d = tempfile.mkdtemp(dir=self.tmp)
        job = {'action': action, 'paths': self.paths.as_dict(), 'choices': (choices or self.choices).as_dict(),
               'status': os.path.join(d, 'status.jsonl'), 'cancel': os.path.join(d, 'cancel')}
        if cancel:
            open(job['cancel'], 'w').close()
        with open(os.path.join(d, 'job.json'), 'w') as f:
            json.dump(job, f)
        code = core.run_worker(os.path.join(d, 'job.json'))
        with open(job['status']) as f:
            events = [json.loads(line) for line in f]
        return code, events

    def bake(self, **kw):
        code, ev = self.worker(**kw)
        self.assertEqual(code, 0, ev[-1])
        return ev

    def check(self, **kw):
        return core.check(self.tools, self.paths, **kw)


class TestFindingThings(FakeInstallCase):
    def test_detect(self):
        t = types.SimpleNamespace(mod=self.inst.mod, bake=bake)
        p = core.detect(t)
        self.assertEqual((p.mo2, p.profile, p.game), (self.inst.mo2, 'P', self.inst.game))
        self.assertEqual(core.profiles(self.inst.mo2), ['Other', 'P'])
        # a profile MO2 does not have any more: none chosen (two to choose from)
        with open(os.path.join(self.inst.mo2, 'ModOrganizer.ini'), 'a') as f:
            f.write('selected_profile=@ByteArray(Gone)\n')
        ini = os.path.join(self.inst.mo2, 'ModOrganizer.ini')
        with open(ini) as f:
            text = f.read().replace('selected_profile=@ByteArray(P)\n', '')
        with open(ini, 'w') as f:
            f.write(text)
        self.assertIsNone(core.detect(t).profile)

    def test_problems_and_warnings(self):
        self.assertEqual(core.problems(self.tools, self.paths), [])
        self.assertEqual(core.warnings(self.tools, self.paths), [])
        self.assertEqual(len(core.problems(self.tools, core.Paths(MOD))), 2)
        bad = core.Paths(MOD, self.inst.mo2, 'Nope', self.inst.game)
        self.assertIn('profile', core.problems(self.tools, bad)[0])
        bad = core.Paths(MOD, self.inst.mo2, 'P', self.tmp)
        self.assertIn('game folder', core.problems(self.tools, bad)[0])
        # another copy of ZGO enabled
        os.makedirs(os.path.join(self.inst.mo2, 'mods', 'ZGO Old', 'gamedata', 'scripts'))
        open(os.path.join(self.inst.mo2, 'mods', 'ZGO Old', 'gamedata', 'scripts', 'zgo_main.script'), 'w').close()
        fakezgo.write_model(self.inst.mo2, 'ZGO Old', 'actors\\synth\\synth_old')
        fakezgo.set_modlist(self.inst.mo2, 'P', ['+Out', '+ZGO Old', '+Synth Models'])
        w = core.warnings(self.tools, self.paths)
        self.assertEqual(len(w), 1)
        self.assertIn('"ZGO Old"', w[0])
        self.assertNotIn('actors\\synth\\synth_old', core.winners(self.tools, self.paths), 'never a bake source')


class TestPlan(FakeInstallCase):
    def test_plan(self):
        p = core.plan(self.tools, self.paths, self.choices)
        self.assertEqual(p.models, 3, 'before the first bake only the mods are counted')
        self.assertTrue(p.notes)
        self.assertEqual(p.by_source, [('Synth Models', 3)])
        self.assertEqual(set(p.estimate), {'models', 'scripts', 'caps', 'pieces', 'gibs'})
        self.choices.gibs = False
        self.assertNotIn('gibs', core.plan(self.tools, self.paths, self.choices).estimate)
        self.choices.gibs = True
        self.assertIn(self.inst.cache, p.needed)
        self.assertGreater(p.total, 0)
        self.bake()
        p = core.plan(self.tools, self.paths, self.choices)
        self.assertEqual(p.models, 4, 'the game model counts once the archives are unpacked')
        self.assertEqual(p.by_source, [('Synth Models', 3), ('', 1)])
        self.assertFalse(p.notes)
        less = core.plan(self.tools, self.paths, core.Choices(caps=False, pieces=False, props=False))
        more = core.plan(self.tools, self.paths, core.Choices(experimental_caps=True, experimental_damage=True, props=False,
                                                             jobs=self.choices.jobs))
        self.assertLess(less.total, p.total)
        self.assertGreater(more.total, p.total)
        self.assertGreater(more.seconds, p.seconds)
        bad = core.Paths(MOD)
        self.assertEqual(core.plan(self.tools, bad, self.choices).models, 0)

    def test_estimate_is_close(self):
        """The estimate is within a factor of 2.5 of the real size (synthetic
        models are tiny, so the fixed per-model parts weigh more here)."""
        p0 = core.plan(self.tools, self.paths, self.choices)
        ev = self.bake()
        real = ev[-1]['summary']['bytes']
        p = core.plan(self.tools, self.paths, self.choices)
        self.assertGreater(real, 0)
        self.assertLess(max(p.total, real) / min(p.total, real), 2.5, (p.estimate, real))
        self.assertLess(p0.models, p.models)


class TestBakeAndCheck(FakeInstallCase):
    def test_bake_writes_inputs_the_game_can_check(self):
        ev = self.bake()
        kinds = [e['t'] for e in ev]
        self.assertEqual(kinds[-1], 'done')
        stages = [e['stage'] for e in ev if e['t'] == 'progress']
        self.assertEqual([s for s in bake.STAGES if s in stages], list(bake.STAGES))
        s = ev[-1]['summary']
        self.assertEqual((s['baked'], s['errors']), (4, 0))
        self.assertTrue(re.match(r'^[0-9a-f]{32}$', s['fingerprint']))
        out = self.inst.mod
        rep = bake.read_report(out)
        self.assertEqual(rep['inputs']['fingerprint'], s['fingerprint'])
        self.assertIn(bake.INPUTS, rep['files'])
        path = os.path.join(out, *bake.INPUTS.split('/'))
        g = limbs.read_tables(path)
        with open(path, 'rb') as f:
            raw = f.read()
        self.assertIn(b'\r\n', raw, 'generated scripts are CRLF like the others')
        idx = limbs.read_tables(os.path.join(out, *bake.INDEX.split('/')), wanted={'bake_id'})
        with open(path, encoding='utf-8') as f:
            text = f.read()
        for key in ('version', 'bake_id', 'baker', 'zgo', 'flags', 'fingerprint', 'tables', 'profile', 'mo2',
                    'zgo_mod', 'index_bytes'):
            self.assertRegex(text, r'(?m)^%s = ' % key)
        self.assertIn('bake_id = "%s"' % rep['bake_id'], text)
        self.assertEqual(len(idx), 0, 'the index keeps bake_id in its own form')  # wanted= only reads tables
        self.assertEqual(g['mods'], {1: 'Synth Models'})
        models = g['models']
        self.assertEqual(len(models), 4)
        for key, v in models.items():
            out_bytes, src, in_bytes = map(int, v.split())
            f = os.path.join(out, 'gamedata', 'meshes', *key.split('\\')) + '.ogf'
            self.assertEqual(os.path.getsize(f), out_bytes, 'the game compares this size: ' + key)
            self.assertEqual(src, 0 if key in fakezgo.GAME_MODELS else 1, key)
            self.assertGreater(in_bytes, 0)
        self.assertEqual(int(re.search(r'index_bytes = (\d+)', text).group(1)),
                         os.path.getsize(os.path.join(out, *bake.INDEX.split('/'))))
        self.assertIn('tables = "%s"' % limbs.canonical(fake_kinds()), text)
        self.assertIn('mo2 = "%s"' % bake.game_path(self.inst.mo2).replace('\\', '\\\\'), text)
        if LUAJIT:
            got = lua('dofile(%r) local n = 0 for k, v in pairs(models) do n = n + 1 end '
                      'io.write(n, " ", bake_id, " ", baker, " ", mods[1])' % path)
            self.assertEqual(got, '4 %s %d Synth Models' % (rep['bake_id'], bake.BAKER_VERSION))

    def test_up_to_date_then_each_kind_of_change(self):
        self.bake()
        st = self.check()
        self.assertEqual(st.state, 'ok', st.text())
        self.assertIn('Baked ', st.info[-1])
        mo2 = self.inst.mo2
        # the same size, another date and other bytes: found by the hash
        a = self.inst.model('Synth Models', 'actors\\synth\\synth_a')
        when = os.stat(a).st_mtime
        with open(a, 'r+b') as f:
            f.seek(-1, 2)
            last = f.read(1)
            f.seek(-1, 2)
            f.write(bytes([last[0] ^ 1]))
        os.utime(a, (when + 10, when + 10))     # another date even when the edit lands in the bake's second
        st = self.check()
        self.assertEqual(st.state, 'stale')
        self.assertIn('Mod "Synth Models" changed 1 model', st.reasons[0])
        with open(a, 'r+b') as f:
            f.seek(-1, 2)
            f.write(last)
        self.assertEqual(self.check().state, 'ok')
        # same bytes, a new date: still fine; other bytes, the old date: only --deep sees it
        rec = {r['key']: r for r in bake.read_report(self.inst.mod)['results']}['actors\\synth\\synth_a']
        os.utime(a, (time.time(), time.time() + 100))
        self.assertEqual(self.check().state, 'ok')
        with open(a, 'r+b') as f:
            f.seek(-1, 2)
            f.write(bytes([last[0] ^ 1]))
        os.utime(a, (rec['src_mtime'], rec['src_mtime']))
        self.assertEqual(self.check().state, 'ok', 'same size and date: not hashed')
        self.assertEqual(self.check(deep=True).state, 'stale')
        with open(a, 'r+b') as f:
            f.seek(-1, 2)
            f.write(last)
        # a new mod with a model
        fakezgo.write_model(mo2, 'New Models', 'actors\\synth\\synth_c')
        fakezgo.set_modlist(mo2, 'P', ['+Out', '+New Models', '+Synth Models'])
        st = self.check()
        self.assertEqual(st.state, 'stale')
        self.assertTrue(any('Mod "New Models" adds 1 model' in r for r in st.reasons), st.reasons)
        # it now provides synth_b too (wins over Synth Models)
        fakezgo.write_model(mo2, 'New Models', 'actors\\synth\\synth_b')
        st = self.check()
        self.assertTrue(any('now comes from mod "New Models" instead of mod "Synth Models"' in r for r in st.reasons), st.reasons)
        # disabled again; Synth Models disabled: its models are gone
        fakezgo.set_modlist(mo2, 'P', ['+Out', '-New Models', '-Synth Models'])
        st = self.check()
        self.assertTrue(any('3 baked models came from mod "Synth Models", which no longer provides them' in r
                            for r in st.reasons), st.reasons)
        fakezgo.set_modlist(mo2, 'P', ['+Out', '+Synth Models'])
        self.assertEqual(self.check().state, 'ok')
        # another profile than the bake's
        other = core.Paths(MOD, mo2, 'Other', self.inst.game, out=self.inst.mod, cache=self.inst.cache)
        st = core.check(self.tools, other)
        self.assertTrue(any('profile "P"; you chose "Other"' in r for r in st.reasons), st.reasons)
        # ZGO's tables changed (an update of ZGO)
        k = dict(fake_kinds(), synth=['bip01_head'])
        with fake_tables(k):
            st = self.check()
        self.assertTrue(any('tables changed' in r for r in st.reasons), st.reasons)
        # the game's archives changed
        db = os.path.join(self.inst.game, 'db', 'meshes', 'meshes_actors.db0')
        with open(db, 'ab') as f:
            f.write(b'\0' * 8)
        st = self.check()
        self.assertTrue(any("model archives changed" in r for r in st.reasons), st.reasons)

    @unittest.skipUnless(hasattr(os, 'symlink') and os.name != 'nt', 'needs symlinks')
    def test_props_same_file_another_path(self):
        # a props bake that recorded its sources through a symlinked folder (/home -> /var/home)
        # is up to date when Setup finds the same files by the real path
        if not self.tools.fracture:
            self.skipTest('no props tool')
        key = 'dynamics\\balon\\bidon'
        fakezgo.write_model(self.inst.mo2, 'Synth Models', key, b'a prop')
        link = os.path.join(self.tmp, 'linked')
        os.symlink(self.tmp, link)
        src = os.path.join(link, os.path.relpath(self.inst.model('Synth Models', key), self.tmp))
        rep = {'options': {}, 'files': [], 'results': [{'visual': key, 'status': 'ok', 'source': src}]}
        with open(os.path.join(self.inst.mod, 'zgo_fracture_report.json'), 'w') as f:
            json.dump(rep, f)
        state, text = core.check_props(self.tools, self.paths)
        self.assertEqual(state, 'ok', text)
        # baked from another file than the one that wins now: out of date
        rep['results'][0]['source'] = fakezgo.write_model(self.inst.mo2, 'Elsewhere', key, b'a prop')
        with open(os.path.join(self.inst.mod, 'zgo_fracture_report.json'), 'w') as f:
            json.dump(rep, f)
        state, text = core.check_props(self.tools, self.paths)
        self.assertEqual(state, 'stale', text)
        self.assertIn('1 prop model changed', text)

    def test_load_order(self):
        """A mod above ZGO that has baked models: fix the order, no new bake."""
        fakezgo.write_model(self.inst.mo2, 'Hider', 'actors\\synth\\synth_a')
        fakezgo.set_modlist(self.inst.mo2, 'P', ['+Hider', '+Out', '+Synth Models'])
        self.bake()
        st = self.check()
        self.assertEqual(st.state, 'order', st.text())
        self.assertIn('"Hider" (1 models) loads after Umbra Gore & Effects', st.advice)
        self.assertIn('drag "Out" below it', st.advice)
        p = core.plan(self.tools, self.paths, self.choices)
        self.assertEqual(p.overrides, [('Hider', 1)])
        fakezgo.set_modlist(self.inst.mo2, 'P', ['+Out', '+Hider', '+Synth Models'])
        self.assertEqual(self.check().state, 'ok')

    def test_broken_and_old_bakes(self):
        self.assertEqual(self.check().state, 'none')
        self.bake()
        out = self.inst.mod
        rp = os.path.join(out, bake.REPORT)
        with open(rp) as f:
            rep = json.load(f)
        # made by an older baker
        old = dict(rep, inputs=dict(rep['inputs'], baker=bake.BAKER_VERSION - 1))
        with open(rp, 'w') as f:
            json.dump(old, f)
        st = self.check()
        self.assertEqual(st.state, 'stale')
        self.assertIn('older Umbra Gore & Effects', st.reasons[0])
        # a 1.6 bake (no inputs at all)
        old = {k: v for k, v in rep.items() if k != 'inputs'}
        old['version'] = 1
        with open(rp, 'w') as f:
            json.dump(old, f)
        self.assertIn('older', self.check().reasons[0])
        # stopped while installing
        with open(rp, 'w') as f:
            json.dump(dict(rep, status='installing'), f)
        self.assertEqual(self.check().state, 'broken')
        with open(rp, 'w') as f:
            json.dump(rep, f)
        # a baked file deleted by hand
        os.remove(os.path.join(out, *rep['files'][0].split('/')))
        st = self.check()
        self.assertEqual(st.state, 'broken')
        self.assertIn('missing', st.headline)

    def test_last_choices_and_remove(self):
        ch = core.Choices(caps=False, wounds=False, jobs=2, props=False)
        self.bake(choices=ch)
        last = core.last_choices(self.tools, self.inst.mod)
        self.assertEqual((last.caps, last.pieces, last.wounds), (False, True, False))
        files = bake.read_report(self.inst.mod)['files']
        code, ev = self.worker('remove')
        self.assertEqual(code, 0)
        self.assertEqual(ev[-1]['removed'], len(files))
        for rel in files:
            self.assertFalse(os.path.exists(os.path.join(self.inst.mod, *rel.split('/'))), rel)
        self.assertFalse(os.path.exists(os.path.join(self.inst.mod, bake.REPORT)))
        self.assertEqual(self.check().state, 'none')

    def test_cancel_changes_nothing(self):
        code, ev = self.worker(cancel=True)
        self.assertEqual(code, 3)
        self.assertTrue(ev[-1]['cancelled'])
        self.assertIn('Nothing in the Umbra Effects folder was changed', ev[-1]['msg'])
        self.assertEqual(os.listdir(self.inst.mod), [])

    def test_failures_are_explained(self):
        bad = core.Paths(MOD, self.inst.mo2, 'P', None, out=self.inst.mod, cache=self.inst.cache)
        self.paths = bad
        code, ev = self.worker()
        self.assertEqual(code, 2)
        self.assertIn('game folder is not set', ev[-1]['msg'])
        # a file the baker did not write is in the way
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=self.inst.mod, cache=self.inst.cache)
        self.bake()
        rep = bake.read_report(self.inst.mod)
        os.remove(os.path.join(self.inst.mod, bake.REPORT))
        code, ev = self.worker()
        self.assertEqual(code, 2, ev[-1])
        self.assertEqual(ev[-1]['kind'], 'bake')
        self.assertTrue(ev[-1]['msg'][0].isupper())
        self.assertTrue(rep['files'])


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """A static server that answers Range requests (as B2 does); records them."""
    ranges = []

    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        start = int(re.match(r'bytes=(\d+)-', rng).group(1))
        type(self).ranges.append((self.path, start))
        size = os.path.getsize(path)
        f = open(path, 'rb')
        f.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, size - 1, size))
        self.send_header('Content-Length', str(size - start))
        self.end_headers()
        return f


class TestUnused(FakeInstallCase):
    """A bake that is right but that the game doesn't load: check says so (state 'unused')."""

    def test_unticked(self):
        self.bake()
        self.assertEqual(self.check().state, 'ok')
        fakezgo.set_modlist(self.inst.mo2, 'P', ['-Out', '+Synth Models'])
        st = self.check()
        self.assertEqual(st.state, 'unused', st.text())
        self.assertIn('not ticked', st.advice)

    def test_a_bake_the_game_would_never_load_is_refused(self):
        """A co-op player baked from the unpacked zip, then installed the zip through MO2: the game
        read a copy without the bake (no cuts, stumps or body gibs on their side). Setup now refuses
        such a bake (and download) before it starts."""
        # run from a copy outside MO2's mods (MOD: this repo), MO2 chosen by hand
        unpacked = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, cache=self.inst.cache)
        bad = core.problems(self.tools, unpacked)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn('not installed in MO2', bad[0])
        self.assertIn('Press "Install into MO2"', bad[0])
        # before MO2 is chosen, that is what it says first
        self.assertIn('Choose your Mod Organizer 2 folder above', core.problems(self.tools, core.Paths(MOD))[0])
        # the installed copy, ticked: ready
        installed = core.Paths(self.inst.mod, self.inst.mo2, 'P', self.inst.game, cache=self.inst.cache)
        self.assertEqual(core.problems(self.tools, installed), [])
        # unticked while MO2 ticks another copy: the bake would land in the copy the game skips
        new = os.path.join(self.inst.mo2, 'mods', 'Umbra Gore & Effects 1.8.2', 'gamedata', 'scripts')
        os.makedirs(new)
        open(os.path.join(new, 'zgo_main.script'), 'w').close()
        fakezgo.set_modlist(self.inst.mo2, 'P', ['-Out', '+Umbra Gore & Effects 1.8.2', '+Synth Models'])
        bad = core.problems(self.tools, installed)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn('is not the copy MO2 loads in the profile "P": the game loads "Umbra Gore & Effects 1.8.2"', bad[0])
        # unticked with no other copy: only a warning (the bake is right once it is ticked)
        fakezgo.set_modlist(self.inst.mo2, 'P', ['-Out', '-Umbra Gore & Effects 1.8.2', '+Synth Models'])
        self.assertEqual(core.problems(self.tools, installed), [])
        self.assertTrue(any('not enabled' in w for w in core.warnings(self.tools, installed)))

    # ---- Repair: Umbra Gore & Effects and its bake where the game loads them

    def copy_of_zgo(self, folder, version='1.8.3'):
        os.makedirs(os.path.join(folder, 'gamedata', 'scripts'), exist_ok=True)
        with open(os.path.join(folder, 'gamedata', 'scripts', 'zgo_main.script'), 'w') as f:
            f.write('VERSION = "%s"\n' % version)
        with open(os.path.join(folder, 'meta.ini'), 'w') as f:
            f.write('[General]\nversion=%s\n' % version)
        return folder

    def bake_into(self, folder):
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=folder, cache=self.inst.cache)
        self.bake()
        self.assertTrue(os.path.isfile(os.path.join(folder, 'zgo_bake_report.json')))

    def at(self, folder):
        return core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=folder, cache=self.inst.cache)

    def baked_files(self, folder):
        return [os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs
                if f.startswith('zgo_bake') or os.sep + 'zgo' + os.sep in dp + os.sep and 'meshes' in dp]

    def test_repair_installs_a_copy_baked_before_the_mod_was_installed(self):
        """The co-op player's case: Setup run from the unpacked zip, the bake made there; MO2 had no copy."""
        unpacked = self.copy_of_zgo(os.path.join(self.tmp, 'Downloads', 'Umbra Gore & Effects'))
        shutil.rmtree(self.inst.mod)
        fakezgo.set_modlist(self.inst.mo2, 'P', ['+Synth Models'])
        self.bake_into(unpacked)
        fix = core.repair_needed(self.tools, self.at(unpacked))
        self.assertTrue(any('not installed in MO2' in f for f in fix), fix)
        with mock.patch.object(core, 'mo2_running', lambda: False):
            done = core.repair(self.tools, self.at(unpacked), lambda **ev: None)
        installed = os.path.join(self.inst.mo2, 'mods', 'Umbra Gore & Effects')
        self.assertEqual((done['installed'], done['moved_from']), (installed, unpacked))
        self.assertTrue(os.path.isfile(os.path.join(installed, 'gamedata', 'scripts', 'zgo_main.script')))
        self.assertTrue(os.path.isfile(os.path.join(installed, 'zgo_bake_report.json')))
        self.assertEqual(self.baked_files(unpacked), [], 'baked files only in the copy the game loads')
        # set up in MO2: ticked, on top of the load order; the game uses the bake now
        self.assertEqual(done['tick'], 'added')
        self.assertEqual(fakezgo_enabled(self.inst.mo2, 'P')[0], 'Umbra Gore & Effects')
        self.assertEqual(self.check_at(installed).state, 'ok')
        text = ' '.join(core.repair_text(done, 'P'))
        self.assertIn('Ticked "Umbra Gore & Effects" in the MO2 profile "P"', text)
        self.assertEqual(core.repair_needed(self.tools, self.at(installed)), [])
        self.assertEqual(core.problems(self.tools, core.Paths(installed, self.inst.mo2, 'P', self.inst.game)), [])

    def test_repair_ticks_the_copy_only_while_mo2_is_closed(self):
        self.copy_of_zgo(self.inst.mod)
        self.bake_into(self.inst.mod)
        fakezgo.set_modlist(self.inst.mo2, 'P', ['-Out', '+Synth Models'])
        fix = core.repair_needed(self.tools, self.at(self.inst.mod))
        self.assertEqual(fix, ['"Out" is not ticked in the profile "P": tick it.'])
        modlist = os.path.join(self.inst.mo2, 'profiles', 'P', 'modlist.txt')
        before = open(modlist, 'rb').read()
        with mock.patch.object(core, 'mo2_running', lambda: True):
            done = core.repair(self.tools, self.at(self.inst.mod), lambda **ev: None)
        self.assertEqual(done['tick'], 'mo2_open')
        self.assertEqual(open(modlist, 'rb').read(), before, 'MO2 open: its list is left alone')
        self.assertIn('Close MO2 and press "Repair" again', ' '.join(core.repair_text(done, 'P')))
        with mock.patch.object(core, 'mo2_running', lambda: False):
            done = core.repair(self.tools, self.at(self.inst.mod), lambda **ev: None)
        self.assertEqual(done['tick'], 'ticked')
        self.assertEqual(fakezgo_enabled(self.inst.mo2, 'P'), ['Out', 'Synth Models'])
        self.assertEqual(self.check_at(self.inst.mod).state, 'ok')
        self.assertEqual(core.repair_needed(self.tools, self.at(self.inst.mod)), [])
        # not ticking on request (the window's "No" with MO2 open)
        fakezgo.set_modlist(self.inst.mo2, 'P', ['-Out', '+Synth Models'])
        with mock.patch.object(core, 'mo2_running', lambda: False):
            done = core.repair(self.tools, self.at(self.inst.mod), lambda **ev: None, tick=False)
        self.assertEqual(done['tick'], 'skipped')
        self.assertEqual(fakezgo_enabled(self.inst.mo2, 'P'), ['Synth Models'])

    def check_at(self, folder):
        return core.check(self.tools, self.at(folder))

    def test_repair_moves_a_bake_from_the_unpacked_copy_into_the_installed_one(self):
        unpacked = self.copy_of_zgo(os.path.join(self.tmp, 'Downloads', 'Umbra Gore & Effects'))
        self.copy_of_zgo(self.inst.mod)                         # installed, ticked, no bake
        self.bake_into(unpacked)
        self.assertIn('the game loads "Out"', core.problems(self.tools, core.Paths(unpacked, self.inst.mo2, 'P',
                                                                                   self.inst.game))[0])
        done = core.repair(self.tools, self.at(unpacked), lambda **ev: None)
        self.assertIsNone(done['installed'])
        self.assertEqual(done['moved_from'], unpacked)
        self.assertEqual(self.check_at(self.inst.mod).state, 'ok')
        self.assertEqual(self.baked_files(unpacked), [])
        self.assertIn('run Umbra Effects Setup from', ' '.join(core.repair_text(done, 'P')))

    def test_repair_keeps_a_bake_made_for_another_version(self):
        """An update half-way: the new zip unpacked and baked, the old version still installed."""
        unpacked = self.copy_of_zgo(os.path.join(self.tmp, 'Downloads', 'Umbra Gore & Effects'), '1.8.3')
        self.copy_of_zgo(self.inst.mod, '1.8.2')
        self.bake_into(unpacked)
        bad = core.problems(self.tools, core.Paths(unpacked, self.inst.mo2, 'P', self.inst.game))
        self.assertIn('version 1.8.3', bad[0])
        self.assertIn('Replace', bad[0])
        done = core.repair(self.tools, self.at(unpacked), lambda **ev: None)
        self.assertEqual(done['kept'], [unpacked])
        self.assertTrue(os.path.isfile(os.path.join(unpacked, 'zgo_bake_report.json')))
        self.assertFalse(os.path.isfile(os.path.join(self.inst.mod, 'zgo_bake_report.json')))

    def test_repair_removes_bakes_nobody_loads(self):
        self.copy_of_zgo(self.inst.mod)
        self.bake_into(self.inst.mod)                           # the loaded copy's bake fits
        old = self.copy_of_zgo(os.path.join(self.inst.mo2, 'mods', 'Umbra Gore & Effects 1.8.1'))
        self.bake_into(old)                                     # an unticked copy kept around
        left = os.path.join(self.inst.mod, '.zgo-prebaked', 'gamedata')
        os.makedirs(left)
        fix = core.repair_needed(self.tools, self.at(self.inst.mod))
        self.assertTrue(any('"Umbra Gore & Effects 1.8.1" holds a bake the game never loads' in f for f in fix), fix)
        self.assertTrue(any('.zgo-prebaked' in f for f in fix), fix)
        done = core.repair(self.tools, self.at(self.inst.mod), lambda **ev: None)
        self.assertEqual(done['removed'], [old])
        self.assertIsNone(done['moved_from'])
        self.assertFalse(os.path.isfile(os.path.join(old, 'zgo_bake_report.json')))
        self.assertEqual(self.baked_files(old), [])
        self.assertFalse(os.path.exists(os.path.join(self.inst.mod, '.zgo-prebaked')))
        self.assertEqual(self.check_at(self.inst.mod).state, 'ok')
        self.assertEqual(core.repair_needed(self.tools, self.at(self.inst.mod)), [])

    def test_tick_in_profile(self):
        d = os.path.join(self.inst.mo2, 'profiles', 'T')
        os.makedirs(d)
        path = os.path.join(d, 'modlist.txt')
        with open(path, 'wb') as f:
            f.write(b'# This file was automatically generated by Mod Organizer.\r\n+xrRazom Co-op\r\n-Old\r\n'
                    b'+Models\r\n+Base_separator\r\n')
        self.assertEqual(core.tick_in_profile(self.inst.mo2, 'T', 'Umbra Gore & Effects'), 'added')
        self.assertEqual(open(path, 'rb').read(), b'# This file was automatically generated by Mod Organizer.\r\n'
                         b'+xrRazom Co-op\r\n+Umbra Gore & Effects\r\n-Old\r\n+Models\r\n+Base_separator\r\n',
                         'under xrRazom (its fomod asks for the top), above everything else; CRLF kept')
        self.assertTrue(os.path.isfile(path + '.zgo-bak'))
        self.assertEqual(core.tick_in_profile(self.inst.mo2, 'T', 'Old'), 'ticked')
        self.assertIn(b'\r\n+Old\r\n+Models', open(path, 'rb').read(), 'ticked where it was')
        self.assertEqual(core.tick_in_profile(self.inst.mo2, 'T', 'Old'), 'already')
        with open(path, 'wb') as f:
            f.write(b'+Models\n')
        core.tick_in_profile(self.inst.mo2, 'T', 'Umbra Gore & Effects')
        self.assertEqual(open(path, 'rb').read(), b'+Umbra Gore & Effects\n+Models\n')

    def test_setup_program_in(self):
        self.assertEqual(core.setup_program_in(MOD), [sys.executable, os.path.join(MOD, 'tools', 'zgo_setup', 'zgo_setup.py')])
        self.assertIsNone(core.setup_program_in(self.tmp))

    def test_repair_through_the_worker(self):
        unpacked = self.copy_of_zgo(os.path.join(self.tmp, 'Downloads', 'Umbra Gore & Effects'))
        self.copy_of_zgo(self.inst.mod)
        self.bake_into(unpacked)
        self.paths = self.at(unpacked)
        with mock.patch.object(core, 'mo2_running', lambda: False):
            code, ev = self.worker('repair')
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue(ev[-1]['ok'])
        self.assertIn('Moved the bake', ev[-1]['msg'])
        self.assertEqual(self.check_at(self.inst.mod).state, 'ok')

    def test_outside_mo2(self):
        self.bake()
        elsewhere = os.path.join(self.tmp, 'Umbra Gore & Effects')
        shutil.copytree(self.inst.mod, elsewhere)
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=elsewhere, cache=self.inst.cache)
        st = self.check()
        self.assertEqual(st.state, 'unused', st.text())
        self.assertIn("not one of MO2's mods", st.advice)

    def test_baked_models_off_in_mcm(self):
        self.bake()
        cfg = os.path.join(self.inst.mo2, 'overwrite', 'gamedata', 'configs')
        os.makedirs(cfg)
        with open(os.path.join(cfg, 'axr_options.ltx'), 'w') as f:
            f.write('[mcm]\n        zgo/dismember/baked_models               = false\n')
        st = self.check()
        self.assertEqual(st.state, 'unused', st.text())
        self.assertIn('Use baked models', st.advice)
        with open(os.path.join(cfg, 'axr_options.ltx'), 'w') as f:
            f.write('[mcm]\n        zgo/dismember/baked_models               = true\n')
        self.assertEqual(self.check().state, 'ok')

    def test_a_cut_off_downloads_folder_is_named_and_cleared(self):
        self.bake()
        left = os.path.join(self.inst.mod, '.zgo-prebaked', 'gamedata', 'meshes')
        os.makedirs(left)
        st = self.check()
        self.assertTrue(any('.zgo-prebaked' in r for r in st.reasons), st.text())
        self.bake()
        self.assertFalse(os.path.exists(os.path.join(self.inst.mod, '.zgo-prebaked')))

    def test_pack_alone_has_its_own_bar(self):
        self.assertEqual(core.overall_fraction('pack', 'pack', 0, 10, False), 0.0)
        self.assertEqual(core.overall_fraction('pack', 'pack', 10, 10, False), 1.0)


def fakezgo_enabled(mo2, profile):
    import resolve
    return resolve.enabled_mods(mo2, profile)


class TestPacking(FakeInstallCase):
    """Bakes made before 1.8.2 left their small parts (~80,000 files for G.A.M.M.A.) loose, and the
    game reads every loose file through MO2 at each start: Bake packs them into archives without
    baking again; a new bake is packed from the start."""

    def loose_bake(self):
        o = core.bake_options(self.tools, self.paths, self.choices)
        o.pack = False
        rep = bake.bake(o)
        self.assertTrue(bake.loose_files(rep))
        return rep

    def test_a_new_bake_is_packed(self):
        self.bake()
        rep = bake.read_report(self.inst.mod)
        self.assertFalse(bake.loose_files(rep))
        self.assertTrue([f for f in rep['files'] if bake.is_archive(f)])
        self.assertFalse(os.path.isdir(os.path.join(self.inst.mod, 'gamedata', 'meshes', 'zgo')))
        st = self.check()
        self.assertEqual((st.state, st.loose), ('ok', 0), st.text())

    def test_a_loose_bake_is_packed_not_baked_again(self):
        rep = self.loose_bake()
        n = len(bake.loose_files(rep))
        st = self.check()
        self.assertEqual((st.state, st.loose), ('ok', n), st.text())
        self.assertIn('needs packing', st.headline)
        self.assertIn('%d loose files' % n, st.advice)
        code, ev = self.worker()
        self.assertEqual(code, 0, ev[-1])
        s = ev[-1]['summary']
        self.assertEqual((s.get('packed_only'), s.get('packed')), (True, n))
        stages = {e.get('stage') for e in ev if e['t'] == 'progress'}
        self.assertNotIn('bake', stages, 'nothing was baked again')
        self.assertIn('pack', stages)
        rep2 = bake.read_report(self.inst.mod)
        self.assertEqual(rep2['bake_id'], rep['bake_id'])
        self.assertEqual(bake.output_files(rep2), sorted(rep['files']))
        st = self.check()
        self.assertEqual((st.state, st.loose), ('ok', 0), st.text())

    def test_a_loose_bake_with_other_settings_is_baked_again(self):
        """Bake with settings that differ from the loose bake's: a new bake, not just a pack."""
        rep = self.loose_bake()
        self.assertTrue(rep['options'].get('gibs'))
        code, ev = self.worker(choices=core.Choices(jobs=2, props=False, gibs=False, download=False))
        self.assertEqual(code, 0, ev[-1])
        self.assertFalse(ev[-1]['summary'].get('packed_only'), ev[-1])
        rep2 = bake.read_report(self.inst.mod)
        self.assertFalse(rep2['options'].get('gibs'))
        self.assertFalse(bake.loose_files(rep2))

    def test_a_damaged_archive_is_found(self):
        self.bake()
        rep = bake.read_report(self.inst.mod)
        self.assertEqual(set(rep['archive_bytes']), set(rep['packed']))
        a = sorted(rep['packed'])[0]
        with open(os.path.join(self.inst.mod, *a.split('/')), 'r+b') as f:
            f.truncate(100)
        st = self.check()
        self.assertEqual(st.state, 'broken', st.text())
        self.assertIn('damaged', st.headline)
        self.assertIn(a, st.details)

    def test_a_stale_loose_bake_is_baked_again_packed(self):
        self.loose_bake()
        with open(self.inst.model('Synth Models', fakezgo.MOD_MODELS[0]), 'ab') as f:
            f.write(b'\0')                                  # a mod changed a model
        self.assertEqual(self.check().state, 'stale')
        code, ev = self.worker()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('bake', {e.get('stage') for e in ev if e['t'] == 'progress'})
        rep = bake.read_report(self.inst.mod)
        self.assertFalse(bake.loose_files(rep))
        self.assertFalse(os.path.isdir(os.path.join(self.inst.mod, 'gamedata', 'meshes', 'zgo')))

    def test_pack_action_and_remove(self):
        rep = self.loose_bake()
        code, ev = self.worker(action='pack')
        self.assertEqual(code, 0, ev[-1])
        self.assertEqual(ev[-1]['msg'], 'Packed %d loose files into archives.' % len(bake.loose_files(rep)))
        code, ev = self.worker(action='pack')
        self.assertEqual(ev[-1]['msg'], 'Nothing to pack.')
        code, ev = self.worker(action='remove')
        self.assertEqual(code, 0, ev[-1])
        self.assertEqual(sorted(os.listdir(self.inst.mod)), ['gamedata'] if os.path.isdir(
            os.path.join(self.inst.mod, 'gamedata')) else [])


class TestPrebaked(FakeInstallCase):
    """Umbra's ready-made bake (tools/zgo_setup/prebaked.py, setup_core.get_prebaked): install A
    bakes, its bake goes into a fake bucket the way Umbra's packer puts it there, and install B
    (another MO2 folder, another machine's file dates) presses Bake."""

    def setUp(self):
        super().setUp()
        self.bake()
        self.a = self.inst
        self.bucket = os.path.join(self.tmp, 'bucket')
        self.man, self.entry = fakezgo.publish_bake(self.a.mod, self.bucket, self.a.mo2, self.a.game,
                                                    [self.a.cache, TMP_CACHE], 'P', 'Out')
        self.b = fakezgo.make(os.path.join(self.tmp, 'b'), tools=False, zgo='Out')
        for k in fakezgo.MOD_MODELS:
            os.utime(self.b.model('Synth Models', k), (1600000000, 1600000000))
        for db in ('meshes_actors.db0', 'meshes.db0'):
            os.utime(os.path.join(self.b.game, 'db', 'meshes', db), (1600000000, 1600000000))
        self.paths = core.Paths(MOD, self.b.mo2, 'P', self.b.game, out=self.b.mod, cache=self.b.cache)
        self.env = mock.patch.dict(os.environ, {'ZGO_PREBAKED_SOURCE': self.bucket})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def run_bake(self, **kw):
        code, ev = self.worker(**kw)
        logs = ' | '.join(e.get('msg', '') for e in ev if e['t'] == 'log')
        tasks = {e.get('task') for e in ev if e['t'] == 'progress'}
        return code, ev, logs, tasks

    def test_a_loose_ready_made_bake_is_packed_here(self):
        """A ready-made bake made before 1.8.2 (its small parts loose) is packed once it is in."""
        a = core.Paths(MOD, self.a.mo2, 'P', self.a.game, out=self.a.mod, cache=self.a.cache)
        o = core.bake_options(self.tools, a, self.choices)
        o.pack = False
        self.assertTrue(bake.loose_files(bake.bake(o)))
        bucket = os.path.join(self.tmp, 'bucket-loose')
        fakezgo.publish_bake(self.a.mod, bucket, self.a.mo2, self.a.game, [self.a.cache, TMP_CACHE], 'P', 'Out')
        with mock.patch.dict(os.environ, {'ZGO_PREBAKED_SOURCE': bucket}):
            code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue(ev[-1]['summary'].get('prebaked'), logs)
        self.assertIn('pack', {e.get('stage') for e in ev if e['t'] == 'progress' and e.get('task') == 'download'})
        rep = bake.read_report(self.b.mod)
        self.assertFalse(bake.loose_files(rep))
        self.assertTrue(rep['packed'])
        self.assertFalse(os.path.isdir(os.path.join(self.b.mod, 'gamedata', 'meshes', 'zgo')))
        st = self.check()
        self.assertEqual((st.state, st.loose), ('ok', 0), st.text())

    def test_downloads_when_it_fits(self):
        import zipfile
        self.assertEqual(self.man['format'], 2, 'a 1.8.2 bake goes up with its parts in archives')
        v = os.path.join(self.bucket, *self.man['volumes'][0]['path'].split('/'))
        with zipfile.ZipFile(v) as z:
            self.assertEqual({i.compress_type for i in z.infolist()}, {zipfile.ZIP_LZMA})
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        s = ev[-1]['summary']
        self.assertTrue(s.get('prebaked'), logs)
        self.assertIn('its small parts already in archives', logs)
        self.assertEqual((s['baked'], s['download']), (4, sum(v['size'] for v in self.man['volumes'])))
        self.assertNotIn('models', tasks, 'nothing was baked here')
        self.assertIn('download', tasks)
        self.assertNotIn('pack', {e.get('stage') for e in ev if e['t'] == 'progress'}, 'nothing to pack here')
        self.assertFalse(bake.loose_files(bake.read_report(self.b.mod)))
        st = self.check()
        self.assertEqual(st.state, 'ok', st.text())
        rep_a, rep_b = bake.read_report(self.a.mod), bake.read_report(self.b.mod)
        self.assertEqual(sorted(rep_a['files']), sorted(rep_b['files']))
        for rel in rep_a['files']:
            if rel == bake.INPUTS:
                continue
            with open(os.path.join(self.a.mod, *rel.split('/')), 'rb') as f1, \
                    open(os.path.join(self.b.mod, *rel.split('/')), 'rb') as f2:
                self.assertEqual(f1.read(), f2.read(), rel)
        # this machine's paths and names, and this machine's dates
        text = json.dumps(rep_b)
        self.assertNotIn('@@UMBRA_', text)
        for a_path in (self.a.mo2, self.a.game, self.a.cache):     # (B is inside A's folder: its paths start alike)
            self.assertNotIn(a_path + '/', text)
        self.assertIn(self.b.mo2, text)
        self.assertEqual(rep_b['profile'], 'P')
        r = [x for x in rep_b['results'] if x.get('src_mod')][0]
        self.assertEqual(r['src_mtime'], 1600000000)
        self.assertEqual(rep_b['inputs']['archives']['meshes/meshes_actors.db0'][1], 1600000000)
        with open(os.path.join(self.b.mod, *bake.INPUTS.split('/')), encoding='utf-8') as f:
            inp = f.read()
        self.assertNotIn('@@UMBRA_', inp)
        self.assertIn('mo2 = "%s"' % bake.game_path(self.b.mo2).replace('\\', '\\\\'), inp)
        self.assertEqual(sorted(os.listdir(self.b.mod)), ['db', 'gamedata', bake.REPORT], 'no work files left')
        self.assertFalse(os.path.exists(os.path.join(self.b.cache, 'prebaked', self.man['fingerprint'])))
        # Bake again: it is already there
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('already in place', logs)
        self.assertEqual(ev[-1]['summary']['download'], 0)

    def test_takes_the_packed_bake_of_a_fingerprint(self):
        """The bucket has the same bake loose (format 1, listed first for older Setups) and
        packed (format 2): this Setup takes the packed one."""
        a = core.Paths(MOD, self.a.mo2, 'P', self.a.game, out=self.a.mod, cache=self.a.cache)
        o = core.bake_options(self.tools, a, self.choices)
        o.pack = False
        bake.bake(o)
        loose_man, loose = fakezgo.publish_bake(self.a.mod, self.bucket, self.a.mo2, self.a.game,
                                                [self.a.cache, TMP_CACHE], 'P', 'Out', index=False)
        self.assertEqual((loose_man['format'], loose['fingerprint']), (1, self.entry['fingerprint']))
        fakezgo.write_index(self.bucket, [loose, self.entry])
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue(ev[-1]['summary'].get('prebaked'), logs)
        self.assertEqual(ev[-1]['summary']['download'], sum(v['size'] for v in self.man['volumes']))
        self.assertIn('already in archives', logs)
        self.assertNotIn('pack', {e.get('stage') for e in ev if e['t'] == 'progress'})
        self.assertEqual(self.check().state, 'ok')

    def test_an_up_to_date_bake_of_the_same_mod_list_downloads_nothing(self):
        o = core.bake_options(self.tools, self.paths, self.choices)
        bake.bake(o)                                    # B bakes for itself: the same fingerprint
        self.assertEqual(bake.read_report(self.b.mod)['inputs']['fingerprint'], self.man['fingerprint'])
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue('nothing to download' in logs or 'already in place' in logs, logs)
        self.assertNotIn('downloading', logs)
        self.assertEqual(ev[-1]['summary']['download'], 0)

    def test_an_install_that_fails_half_way_is_baked_over(self):
        """A file move fails (a virus scanner on Windows): the folder lists what came, so the
        bake that follows replaces it instead of refusing."""
        import prebaked as pb
        real, n = pb.move, [0]

        def flaky(src, dst):
            if dst.startswith(self.b.mod + os.sep):      # (moving into the Umbra Effects folder)
                n[0] += 1
                if n[0] == 3:
                    raise PermissionError(13, 'in use')
            return real(src, dst)
        with mock.patch.object(pb, 'move', flaky):
            code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('could not be used', logs)
        self.assertIn('models', tasks, 'baked here instead')
        self.assertEqual(self.check().state, 'ok', self.check().text())

    def test_a_complete_part_file_is_checked_not_fetched(self):
        v = self.man['volumes'][0]
        part = os.path.join(self.b.cache, 'prebaked', self.man['fingerprint'], os.path.basename(v['path']) + '.part')
        os.makedirs(os.path.dirname(part))
        shutil.copyfile(os.path.join(self.bucket, *v['path'].split('/')), part)
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue(ev[-1]['summary'].get('prebaked'), logs)

    def test_an_unreadable_manifest_is_skipped(self):
        """A newer bake whose manifest is damaged doesn't stop the download of the next one."""
        fp, sha = 'f' * 32, 'e' * 64
        d = os.path.join(self.bucket, 'umbra-effects', fp)
        os.makedirs(d)
        with open(os.path.join(d, sha + '.json'), 'wb') as f:
            f.write(b'{"not": "it"}')
        bad = dict(self.entry, path='umbra-effects/%s/%s.json' % (fp, sha), sha256=sha, size=13, fingerprint=fp,
                   made='2999-01-01 00:00:00')
        fakezgo.write_index(self.bucket, [bad, self.entry])
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('made 2999-01-01 00:00:00 cannot be read', logs)
        self.assertTrue(ev[-1]['summary'].get('prebaked'), logs)

    def test_bakes_when_it_does_not_fit(self):
        fakezgo.write_model(self.b.mo2, 'New Models', 'actors\\synth\\synth_c')
        fakezgo.set_modlist(self.b.mo2, 'P', ['+Out', '+New Models', '+Synth Models'])
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertFalse(ev[-1]['summary'].get('prebaked'))
        self.assertIn("doesn't fit", logs)
        self.assertIn('adds 1 model', logs)
        self.assertIn('models', tasks)
        self.assertEqual(ev[-1]['summary']['baked'], 5)
        self.assertEqual(self.check().state, 'ok')
        # the report it compared is not left in the Umbra Effects folder (1.8.3 named that folder a
        # cut-off download after every such bake)
        self.assertFalse(os.path.exists(os.path.join(self.b.mod, '.zgo-prebaked')))
        self.assertFalse(any('.zgo-prebaked' in r for r in self.check().reasons))

    def test_bakes_with_other_settings(self):
        code, ev, logs, tasks = self.run_bake(choices=core.Choices(jobs=2, props=False, gibs=False))
        self.assertEqual(code, 0, ev[-1])
        self.assertFalse(ev[-1]['summary'].get('prebaked'))
        self.assertIn('other settings than yours', logs)
        self.assertIn('"Body gibs" on there, off in yours', logs)

    def test_download_off(self):
        code, ev, logs, tasks = self.run_bake(choices=core.Choices(jobs=2, props=False, download=False))
        self.assertEqual(code, 0, ev[-1])
        self.assertEqual(tasks & {'download'}, set())
        self.assertFalse(ev[-1]['summary'].get('prebaked'))
        with mock.patch.dict(os.environ, {'ZGO_PREBAKED_SOURCE': 'off'}):
            code, ev, logs, tasks = self.run_bake()
        self.assertEqual(tasks & {'download'}, set())

    def test_a_damaged_volume_or_no_bucket_means_baking_here(self):
        v = os.path.join(self.bucket, *self.man['volumes'][0]['path'].split('/'))
        with open(v, 'r+b') as f:
            f.seek(10)
            f.write(b'XXXX')
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertFalse(ev[-1]['summary'].get('prebaked'))
        self.assertIn('could not be used', logs)
        self.assertIn('damaged on the way', logs)
        self.assertEqual(self.check().state, 'ok')
        self.assertFalse(os.path.exists(os.path.join(self.b.mod, '.zgo-prebaked')))
        with mock.patch.dict(os.environ, {'ZGO_PREBAKED_SOURCE': os.path.join(self.tmp, 'nowhere')}):
            code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('could not be used', logs)

    def test_another_baker_version_is_not_tried(self):
        fakezgo.write_index(self.bucket, [dict(self.entry, baker=bake.BAKER_VERSION + 1)])
        code, ev, logs, tasks = self.run_bake()
        self.assertEqual(code, 0, ev[-1])
        self.assertIn('No ready-made bake for this version', logs)
        self.assertFalse(ev[-1]['summary'].get('prebaked'))

    def test_cancel_changes_nothing(self):
        code, ev, logs, tasks = self.run_bake(cancel=True)
        self.assertEqual(code, 3, ev[-1])
        self.assertIn('Nothing in the Umbra Effects folder was changed', ev[-1]['msg'])
        self.assertEqual(os.listdir(self.b.mod), [])

    def test_over_http_resuming_a_cut_download(self):
        import functools
        import threading as th
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                                              functools.partial(_RangeHandler, directory=self.bucket))
        t = th.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            v = self.man['volumes'][0]
            part = os.path.join(self.b.cache, 'prebaked', self.man['fingerprint'], os.path.basename(v['path']) + '.part')
            os.makedirs(os.path.dirname(part))
            with open(os.path.join(self.bucket, *v['path'].split('/')), 'rb') as f:
                half = f.read(v['size'] // 2)
            with open(part, 'wb') as f:
                f.write(half)
            _RangeHandler.ranges = []
            with mock.patch.dict(os.environ, {'ZGO_PREBAKED_SOURCE': 'http://127.0.0.1:%d' % srv.server_address[1]}):
                code, ev, logs, tasks = self.run_bake()
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(code, 0, ev[-1])
        self.assertTrue(ev[-1]['summary'].get('prebaked'), logs)
        self.assertEqual(_RangeHandler.ranges, [('/' + v['path'], len(half))])
        self.assertEqual(self.check().state, 'ok')


class TestPrebakedParts(unittest.TestCase):

    def test_adopt_dates_records_the_archive_sizes(self):
        """A packed bake from Umbra's build records no archive sizes: putting it in place
        records them, so check() finds an archive cut short later."""
        import prebaked as pb
        d = tempfile.mkdtemp(prefix='zgo_adopt_')
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, 'db', 'mods'))
        with open(os.path.join(d, 'db', 'mods', 'zgo_bake_caps_00.db0'), 'wb') as f:
            f.write(b'x' * 1234)
        with open(os.path.join(d, bake.REPORT), 'w') as f:
            json.dump({'packed': {'db/mods/zgo_bake_caps_00.db0': ['a'], 'db/mods/zgo_bake_gone_00.db0': ['b']},
                       'results': []}, f)
        pb.adopt_dates(d, bake.REPORT, None, lambda g: {})
        self.assertEqual(bake.read_report(d)['archive_bytes'], {'db/mods/zgo_bake_caps_00.db0': 1234})
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='zgo_prebaked_test_')
        import prebaked
        self.pb = prebaked
        self.tools = core.Tools(MOD)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_relocate(self):
        pb = self.pb
        p = os.path.join(self.tmp, 'r.json')
        with open(p, 'w') as f:
            f.write('{"a": "@@UMBRA_MO2@@/mods/x", "b": "@@UMBRA_MO2_WIN_ESC@@\\\\mods", "c": "@@UMBRA_PROFILE@@"}')
        toks = pb.tokens('/m o2', '/game', '/cache', 'Prof', 'Out')
        pb.relocate(self.tmp, ['r.json', 'missing.json'], toks)
        with open(p) as f:
            d = json.load(f)
        want = 'Z:\\m o2' if os.name != 'nt' else '/m o2'
        self.assertEqual(d, {'a': '/m o2/mods/x', 'b': want + '\\mods', 'c': 'Prof'})
        with open(p, 'w') as f:
            f.write('"@@UMBRA_SOMETHING_NEW@@"')
        with self.assertRaises(pb.Unavailable):
            pb.relocate(self.tmp, ['r.json'], toks)

    def test_only_what_a_bake_writes_is_unpacked(self):
        import zipfile
        z = os.path.join(self.tmp, 'v.zip')
        for bad in ('gamedata/scripts/other.script', '../x.ogf', 'gamedata/configs/system.ltx', 'C:/x'):
            with zipfile.ZipFile(z, 'w') as zf:
                zf.writestr('gamedata/meshes/a.ogf', b'x')
                zf.writestr(bad, b'y')
            with self.assertRaises(self.pb.Unavailable, msg=bad):
                self.pb.unpack(self.tools, [z], os.path.join(self.tmp, 'out'))
        with zipfile.ZipFile(z, 'w') as zf:
            for rel in ('gamedata/meshes/a.ogf', bake.INDEX, bake.INPUTS, bake.REPORT):
                zf.writestr(rel, b'x')
        self.assertEqual(len(self.pb.unpack(self.tools, [z], os.path.join(self.tmp, 'out'))), 4)

    def test_formats(self):
        pb = self.pb
        fp, sha = 'a' * 32, 'b' * 64
        e = {'path': 'umbra-effects/%s/%s.json' % (fp, sha), 'sha256': sha, 'size': 10, 'fingerprint': fp, 'baker': 3}
        idx = {'format': 1, 'kind': 'umbra-effects-bakes', 'bakes': [e, dict(e, path='elsewhere/x.json'), 'junk']}
        self.assertEqual(pb.read_index(json.dumps(idx).encode()), [e])
        for bad in (dict(idx, format=2), dict(idx, kind='x'), []):
            with self.assertRaises(pb.Unavailable):
                pb.read_index(json.dumps(bad).encode())
        vol = {'path': 'umbra-effects/%s/%s.zip' % (fp, 'c' * 64), 'sha256': 'c' * 64, 'size': 5}
        man = {'format': 1, 'kind': 'umbra-effects-bake', 'fingerprint': fp, 'report': vol, 'volumes': [vol],
               'relocate': ['zgo_bake_report.json']}
        self.assertEqual(pb.read_manifest(json.dumps(man).encode(), e)['fingerprint'], fp)
        for bad in (dict(man, fingerprint='d' * 32), dict(man, volumes=[]), dict(man, relocate=['../x']),
                    dict(man, report=dict(vol, sha256='e' * 64)), dict(man, format=2)):
            with self.assertRaises(pb.Unavailable):
                pb.read_manifest(json.dumps(bad).encode(), e)

    def test_candidates(self):
        pb = self.pb
        def e(fp, made, fmt=None, baker=3):
            x = {'fingerprint': fp * 32, 'made': made, 'baker': baker, 'path': fp + str(fmt)}
            if fmt is not None:
                x['format'] = fmt
            return x
        old_loose, new_loose, new_packed = e('a', '2026-01-01'), e('b', '2026-02-01', 1), e('b', '2026-02-01', 2)
        other = e('c', '2026-03-01', baker=4)
        # the list's order (format 1 first) doesn't matter: newest first, packed preferred
        self.assertEqual(pb.candidates([old_loose, new_loose, other, new_packed], 3), [new_packed, old_loose])
        self.assertEqual(pb.candidates([new_packed, new_loose], 3), [new_packed])
        self.assertEqual(pb.candidates([old_loose, new_loose], 3, n=1), [new_loose])
        self.assertEqual(pb.candidates([other], 3), [])
        # a format this Setup doesn't know is left out of the list; a bool is no format
        sha = 'b' * 64
        ok = {'path': 'umbra-effects/%s/%s.json' % ('a' * 32, sha), 'sha256': sha, 'size': 10,
              'fingerprint': 'a' * 32, 'baker': 3}
        idx = {'format': 1, 'kind': 'umbra-effects-bakes',
               'bakes': [dict(ok, format=3), dict(ok, format=True), dict(ok, format=2), ok]}
        self.assertEqual(pb.read_index(json.dumps(idx).encode()), [dict(ok, format=2), ok])

    def _object(self, data, name='v.zip'):
        import hashlib
        src = os.path.join(self.tmp, 'src')
        sha = hashlib.sha256(data).hexdigest()
        rel = 'umbra-effects/%s/%s.zip' % ('a' * 32, sha)
        os.makedirs(os.path.join(src, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(src, *rel.split('/')), 'wb') as f:
            f.write(data)
        return src, {'path': rel, 'sha256': sha, 'size': len(data)}

    def test_download_checks_as_it_arrives(self):
        pb = self.pb
        data = os.urandom(3 << 20)
        src, obj = self._object(data)
        dest = os.path.join(self.tmp, 'cache', 'v.zip')
        os.makedirs(os.path.dirname(dest))
        with open(dest + '.part', 'wb') as f:          # an earlier try's part: resumed, not fetched again
            f.write(data[:1 << 20])
        got = []
        with mock.patch.object(pb, 'sha256_file', side_effect=AssertionError('read again')):
            pb.download(src, obj, dest, got.append)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), data)
        self.assertEqual(sum(got), len(data))
        os.remove(dest)
        with open(dest + '.part', 'wb') as f:          # a damaged part: fetched again
            f.write(b'X' * (1 << 20))
        got = []
        pb.download(src, obj, dest, got.append)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), data)
        self.assertEqual(sum(got), len(data), 'counted once')
        os.remove(dest)
        bad = dict(obj, sha256='0' * 64)               # damaged at the source: refused after a second try
        with self.assertRaises(pb.Unavailable):
            pb.download(src, bad, dest)
        self.assertFalse(os.path.exists(dest + '.part'))
        self.assertFalse(os.path.exists(dest))

    def test_fetch_and_unpack(self):
        import io
        import zipfile
        pb = self.pb

        def vol(names):
            b = io.BytesIO()
            with zipfile.ZipFile(b, 'w', zipfile.ZIP_LZMA) as z:
                for n in names:
                    z.writestr(n, n.encode() * 1000)
            return b.getvalue()
        src = os.path.join(self.tmp, 'src')
        objs = []
        for k in range(5):
            s, o = self._object(vol(['gamedata/meshes/zgo/baked/v%d_%d.ogf' % (k, i) for i in range(7)]))
            objs.append(o)
        cache, out = os.path.join(self.tmp, 'cache'), os.path.join(self.tmp, 'out')
        got, files = [], []
        paths, names = pb.fetch_and_unpack(self.tools, src, objs, cache, out, got.append,
                                           lambda i, rel: files.append(i))
        self.assertEqual(names, ['gamedata/meshes/zgo/baked/v%d_%d.ogf' % (k, i) for k in range(5) for i in range(7)])
        self.assertEqual(sum(got), sum(o['size'] for o in objs))
        self.assertEqual(sorted(files), list(range(1, 36)))
        for n in names:
            with open(os.path.join(out, *n.split('/')), 'rb') as f:
                self.assertEqual(f.read(), n.encode() * 1000)
        self.assertTrue(all(os.path.isfile(p) for p in paths))
        # one volume with a file a bake never writes: refused, the rest stopped
        _, bad = self._object(vol(['gamedata/scripts/evil.script']))
        with self.assertRaises(pb.Unavailable):
            pb.fetch_and_unpack(self.tools, src, objs[:2] + [bad] + objs[2:], os.path.join(self.tmp, 'c2'),
                                os.path.join(self.tmp, 'o2'))
        with self.assertRaises(pb.Cancelled):
            pb.fetch_and_unpack(self.tools, src, objs, os.path.join(self.tmp, 'c3'), os.path.join(self.tmp, 'o3'),
                                stop=lambda: True)

    def test_ssl_context(self):
        import ssl
        self.assertIsInstance(self.pb.ssl_context(), ssl.SSLContext)


class TestKidfx(FakeInstallCase):
    """Kid mode for particles through the worker, for real: a copy of
    tools/zgo_kidfx in the fake ZGO folder (mods/Out, which the bake goes
    into, as for a player) against the fake game (fakezgo.add_kidfx). The real
    ZGO folder's kidfx is never run; Tools gets the copy instead."""

    def setUp(self):
        super().setUp()
        # the copy under test imports particles_xr from its own folder: set aside one another
        # suite imported (dev/ci_tests.py loads every suite first)
        self.preloaded = sys.modules.pop('particles_xr', None)
        self.kd = fakezgo.add_kidfx(self.inst)
        self.part = os.path.join(self.inst.mod, 'gamedata', 'particles')
        spec = importlib.util.spec_from_file_location('kidfx_pe_under_test', os.path.join(self.kd, 'kidfx_pe.py'))
        self.kidfx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.kidfx)
        self.assertTrue(core._same_dir(self.kidfx.MOD_ROOT, self.inst.mod))
        self.loader = mock.patch.object(core, 'load_kidfx', lambda mod_root: (self.kidfx, None))
        self.loader.start()
        self.tools = core.Tools(MOD)
        self.assertIs(self.tools.kidfx, self.kidfx)

    def tearDown(self):
        self.loader.stop()
        sys.path[:] = [p for p in sys.path if not p.startswith(self.tmp)]
        for name in ('sc_tree', 'sc_blenders', 'particles_xr'):
            m = sys.modules.get(name)
            if m is not None and (getattr(m, '__file__', '') or '').startswith(self.tmp):
                del sys.modules[name]          # later tests import the real ones again
        if self.preloaded is not None:
            sys.modules['particles_xr'] = self.preloaded
        super().tearDown()

    def shader(self, rel):
        with open(os.path.join(self.part, *rel.split('/')), 'rb') as f:
            return self.kidfx.read_sprite(f.read())[0]

    def tree(self):
        """Everything kidfx may change in the fake ZGO folder: {path: bytes}."""
        out = {}
        for sub in (('gamedata', 'particles'), ('gamedata', 'shaders'), ('tools', 'zgo_kidfx')):
            for dp, dns, fns in os.walk(os.path.join(self.inst.mod, *sub)):
                dns[:] = [d for d in dns if d != '__pycache__']
                for fn in fns:
                    with open(os.path.join(dp, fn), 'rb') as f:
                        out[os.path.relpath(os.path.join(dp, fn), self.inst.mod)] = f.read()
        return out

    def test_bake_undo_apply_remove(self):
        self.assertIs(core.kidfx_for(self.tools, self.paths), self.kidfx)
        self.assertIn('kid_particles', core.plan(self.tools, self.paths, self.choices).estimate)
        self.assertNotIn('kid_particles', core.plan(self.tools, self.paths,
                                                    core.Choices(jobs=2, props=False, kid_particles=False)).estimate)
        self.assertEqual(core.check_kidfx(self.tools, self.paths)[0], 'ok', 'ZGO ships its own effects switched')
        # ---- the bake: models first, then kid mode for particles
        ev = self.bake()
        s = ev[-1]['summary']
        self.assertEqual(s['baked'], 4)
        self.assertNotIn('kidfx_error', s)
        self.assertEqual(s['kidfx'], {'shaders': 14, 'shaders_written': 14, 'copied': 2, 'copies': 2, 'skipped': 1,
                                      'applied': 0, 'problems': 0})
        logs = [e['msg'] for e in ev if e['t'] == 'log']
        self.assertIn('Kid mode for particles: 14 particle shaders rebuilt for your mod list; 2 gory effects other '
                      'mods play copied into Umbra Effects (2 new).', logs)
        tasks = [e.get('task') for e in ev if e['t'] == 'progress']
        self.assertEqual(tasks[-1], 'particles', 'the last step')
        for rel in fakezgo.KIDFX_COPIES:
            self.assertTrue(self.shader(rel).startswith('zgo\\particle_'), rel)
        self.assertFalse(os.path.exists(os.path.join(self.part, 'hit_fx', 'knife_sparks_00.pe')), 'sparks stay theirs')
        sh = os.path.join(self.inst.mod, 'gamedata', 'shaders')
        for r in ('r1', 'r2', 'r3'):
            for n in ('blend', 'add', 'aadd', 'set'):
                self.assertTrue(os.path.isfile(os.path.join(sh, r, 'zgo_particle_%s.s' % n)), (r, n))
        with open(os.path.join(sh, 'r3', 'zgo_particle_kid.ps')) as f:
            self.assertIn('bus_zgo_view', f.read())
        with open(self.kidfx.COPIES) as f:
            self.assertEqual(sorted(json.load(f)['copies']), sorted(fakezgo.KIDFX_COPIES))
        st, text = core.check_kidfx(self.tools, self.paths)
        self.assertEqual(st, 'ok', text)
        self.assertIn("on (4 gory effects use Umbra Effects' particle shaders, 2 of them copied from your other mods)", text)
        self.assertTrue(core.last_choices(self.tools, self.inst.mod).kid_particles)
        baked = self.tree()
        # ---- undo: every effect back to the game's own shaders, only the shader lines change
        code, ev = self.worker('kidfx_revert')
        self.assertEqual(code, 0, ev[-1])
        self.assertEqual(ev[-1]['changed'], 4)
        self.assertIn("4 effects use the game's own particle shaders again", ev[-1]['msg'])
        for rel in fakezgo.ZGO_GORY + fakezgo.KIDFX_COPIES:
            self.assertTrue(self.shader(rel).startswith('particles\\'), rel)
        now = self.tree()
        self.assertEqual(set(now), set(baked))
        changed = sorted(p for p in now if now[p] != baked[p])
        self.assertEqual(len(changed), 4, changed)
        for p in changed:
            self.assertEqual(self.kidfx.normalized(now[p]), self.kidfx.normalized(baked[p]), p)
        st, text = core.check_kidfx(self.tools, self.paths)
        self.assertEqual(st, 'off', text)
        self.assertFalse(core.last_choices(self.tools, self.inst.mod).kid_particles, 'a re-bake keeps the undo')
        # ---- apply: back to the bake, byte for byte
        code, ev = self.worker('kidfx_apply')
        self.assertEqual((code, ev[-1]['changed']), (0, 4), ev[-1])
        self.assertIn('Kid mode for particles is on', ev[-1]['msg'])
        self.assertEqual(self.tree(), baked)
        code, ev = self.worker('kidfx_apply')
        self.assertEqual((code, ev[-1]['changed']), (0, 0))
        self.assertIn('already on', ev[-1]['msg'])
        self.assertTrue(core.last_choices(self.tools, self.inst.mod).kid_particles)
        # ---- a second bake keeps the copies as they are
        ev = self.bake()
        self.assertEqual((ev[-1]['summary']['kidfx']['copied'], ev[-1]['summary']['kidfx']['copies']), (0, 2))
        self.assertEqual(self.tree(), baked)
        # ---- remove: the bake and the copies go; what ZGO ships stays switched
        code, ev = self.worker('remove')
        self.assertEqual(code, 0, ev[-1])
        self.assertEqual(ev[-1]['kidfx_removed'], 2)
        self.assertIn("and 2 copies of other mods' particle effects.", ev[-1]['msg'])
        for rel in fakezgo.KIDFX_COPIES:
            self.assertFalse(os.path.exists(os.path.join(self.part, *rel.split('/'))), rel)
        self.assertFalse(os.path.isdir(os.path.join(self.part, 'anomaly2')), 'the folders the copies made go too')
        for rel in fakezgo.ZGO_GORY:
            self.assertTrue(self.shader(rel).startswith('zgo\\particle_'), rel)
        self.assertTrue(os.path.isfile(os.path.join(sh, 'r3', 'zgo_particle_blend.s')))
        with open(self.kidfx.COPIES) as f:
            self.assertEqual(json.load(f)['copies'], {})
        self.assertEqual(self.check().state, 'none')
        self.assertEqual(core.check_kidfx(self.tools, self.paths), (
            'ok', "Kid mode for particles: on (2 gory effects use Umbra Effects' particle shaders)."))

    def test_copies_from_particles_xr(self):
        """A gory effect that only a particles.xr has (no mod ships it loose) is copied too,
        written out as the loose file the game would take, with only the shader changed."""
        gp = os.path.join(self.inst.game, 'gamedata', 'particles')
        for rel in ('hit_fx/knife_blood_00.pe', 'hit_fx/hit_knife_flesh_00.pg'):
            os.unlink(os.path.join(gp, *rel.split('/')))
        effects = {'hit_fx\\knife_blood_00': fakezgo.GAME_EFFECTS['hit_fx/knife_blood_00.pe']}
        groups = {'hit_fx\\hit_knife_flesh_00': fakezgo.GAME_GROUPS['hit_fx/hit_knife_flesh_00.pg']}
        with open(os.path.join(self.inst.game, 'gamedata', 'particles.xr'), 'wb') as f:
            f.write(fakezgo.particles_xr_bytes(effects, groups))
        ev = self.bake()
        s = ev[-1]['summary']
        self.assertNotIn('kidfx_error', s)
        self.assertEqual((s['kidfx']['copied'], s['kidfx']['copies'], s['kidfx']['skipped']), (2, 2, 1))
        rel = 'hit_fx/knife_blood_00.pe'
        self.assertEqual(self.shader(rel), 'zgo\\particle_add')
        with open(self.kidfx.COPIES) as f:
            self.assertEqual(json.load(f)['copies'][rel]['source'], 'game:gamedata particles.xr')
        px = sys.modules['particles_xr']
        self.assertTrue(px.__file__.startswith(self.tmp), 'the copy in the fake ZGO folder')
        with open(os.path.join(self.part, *rel.split('/')), 'rb') as f:
            copy = px.parse_pe(f.read())
        self.assertEqual((copy.shader, copy.texture, copy.max_particles, copy.time_limit), (
            'zgo\\particle_add', 'fx\\fx_blood_mist', 10, 0.5))
        self.assertEqual([(a.name, a.floats, a.bools) for a in copy.actions], [('killold', [0.75], [0])])
        self.assertFalse(os.path.exists(os.path.join(self.part, 'hit_fx', 'knife_sparks_00.pe')), 'sparks stay theirs')
        # a second bake finds its copy current (the source is still particles.xr's entry)
        ev = self.bake()
        self.assertEqual((ev[-1]['summary']['kidfx']['copied'], ev[-1]['summary']['kidfx']['copies']), (0, 2))

    def test_a_kidfx_failure_is_a_warning(self):
        before = self.tree()
        with open(os.path.join(self.inst.game, 'gamedata', 'shaders.xr'), 'wb') as f:
            f.write(struct.pack('<II', 2, 0))            # no particle blenders in it
        ev = self.bake()
        s = ev[-1]['summary']
        self.assertTrue(ev[-1]['ok'])
        self.assertEqual(s['baked'], 4, 'the models are baked all the same')
        self.assertIn('Particles\\blend is not a C++ particle blender', s['kidfx_error'])
        self.assertNotIn('kidfx', s)
        warn = [e for e in ev if e['t'] == 'log' and e.get('level') == 'warn']
        self.assertTrue(any(e['msg'].startswith('Kid mode for particles was not updated for your mod list') and
                            e.get('trace') for e in warn), warn)
        self.assertEqual(self.tree(), before, 'nothing half-done')

    def test_cancel_before_the_particles(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        job = {'action': 'bake', 'paths': self.paths.as_dict(), 'choices': self.choices.as_dict(),
               'status': os.path.join(d, 'status.jsonl'), 'cancel': os.path.join(d, 'cancel')}
        with open(os.path.join(d, 'job.json'), 'w') as f:
            json.dump(job, f)
        real = bake.bake

        def bake_then_cancel(*a, **kw):
            r = real(*a, **kw)
            open(job['cancel'], 'w').close()           # Cancel pressed while the models installed
            return r
        before = self.tree()
        with mock.patch.object(bake, 'bake', bake_then_cancel):
            code = core.run_worker(os.path.join(d, 'job.json'))
        with open(job['status']) as f:
            ev = [json.loads(line) for line in f]
        self.assertEqual(code, 3, ev[-1])
        self.assertTrue(ev[-1]['cancelled'])
        self.assertEqual(ev[-1]['msg'], 'Cancelled before kid mode for particles: the body models are baked and '
                                        'installed; the particle effects were not changed.')
        self.assertEqual(ev[-1]['summary']['baked'], 4)
        self.assertEqual(self.tree(), before)

    def test_unticked_elsewhere_or_missing(self):
        before = self.tree()
        # a bake into another folder (as the tests and the self-test do) leaves kidfx alone
        other = os.path.join(self.tmp, 'elsewhere')
        os.makedirs(other)
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=other, cache=self.inst.cache)
        self.assertIsNone(core.kidfx_for(self.tools, self.paths))
        self.assertNotIn('kid_particles', core.plan(self.tools, self.paths, self.choices).estimate)
        ev = self.bake()
        self.assertTrue(any('so it was left alone' in e.get('msg', '') for e in ev if e['t'] == 'log'))
        code, ev = self.worker('kidfx_revert')
        self.assertEqual(code, 2)
        self.assertIn('left alone', ev[-1]['msg'])
        code, ev = self.worker('remove')
        self.assertEqual((code, ev[-1]['kidfx_removed']), (0, 0))
        self.assertEqual(self.tree(), before)
        # into the ZGO folder, unticked
        self.paths = core.Paths(MOD, self.inst.mo2, 'P', self.inst.game, out=self.inst.mod, cache=self.inst.cache)
        ev = self.bake(choices=core.Choices(jobs=2, props=False, kid_particles=False))
        self.assertNotIn('kidfx', ev[-1]['summary'])
        self.assertFalse(any('Kid mode for particles' in e.get('msg', '') for e in ev if e['t'] == 'log'))
        self.assertEqual(self.tree(), before)
        # a ZGO whose kidfx cannot be loaded: the actions say so, the box is off
        with mock.patch.object(core, 'load_kidfx', lambda mod_root: (None, 'ImportError: no sc_tree')):
            code, ev = self.worker('kidfx_apply')
            tools = core.Tools(MOD)
            self.assertFalse(core.last_choices(tools, self.inst.mod).kid_particles)
            self.assertEqual(core.check_kidfx(tools, self.paths), ('none', ''))
            ev2 = self.bake()
        self.assertEqual(code, 2)
        self.assertIn('could not be loaded (ImportError: no sc_tree)', ev[-1]['msg'])
        self.assertTrue(any('could not be loaded' in e.get('msg', '') and e.get('level') == 'warn' for e in ev2))
        self.assertTrue(ev2[-1]['ok'])
        self.assertEqual(self.tree(), before)


class TestJob(unittest.TestCase):
    """The worker as a separate process, the way the window runs it."""

    def test_remove_in_a_worker_process(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'out')
            os.makedirs(out)
            tools = core.Tools(MOD)
            job = core.Job(tools, 'remove', core.Paths(MOD, out=out), core.Choices(), workdir=os.path.join(d, 'w'))
            os.makedirs(job.dir)
            res = job.start().wait(timeout=120)
            self.assertTrue(res['ok'], (res, job.worker_log()))
            self.assertIn('Removed 0 baked files', res['msg'])
            self.assertEqual(res['kidfx_removed'], 0, 'the real ZGO folder is not the target: kidfx left alone')
            self.assertEqual(job.proc.returncode, 0)

    def test_crash_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            tools = core.Tools(MOD)
            job = core.Job(tools, 'remove', core.Paths(MOD, out=d), core.Choices(), workdir=d,
                           command=[sys.executable, '-c', 'import sys; print("boom"); sys.exit(5)'])
            res = job.start().wait(timeout=60)
            self.assertFalse(res['ok'])
            self.assertEqual((res['kind'], res['code']), ('crash', 5))
            self.assertIn('boom', res['trace'])

    def test_bad_action(self):
        with self.assertRaises(ValueError):
            core.Job(None, 'format c:', None, None)


# ===================================================================== zgo_setup.py as a player runs it

def run(cmd, env=None, timeout=600, cwd=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, cwd=cwd,
                       stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout + p.stderr


def xvfb():
    return shutil.which('xvfb-run')


def has_tk(python):
    return run([python, '-c', 'import tkinter'])[0] == 0


class EndToEnd(unittest.TestCase):
    """A fake install whose ZGO folder has its own copy of tools/; the program
    finds the MO2 folder, profile and game by itself."""
    PROGRAM = None          # [command...]; None = python3 zgo_setup.py from the fake install

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='zgo_setup_e2e_')
        cls.inst = fakezgo.make(cls.tmp)
        cls.env = {'ZGO_BAKER_CACHE': cls.inst.cache, 'DISPLAY': '', 'WAYLAND_DISPLAY': ''}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def cmd(self, *args):
        prog = self.PROGRAM or [sys.executable, os.path.join(self.inst.mod, 'tools', 'zgo_setup', 'zgo_setup.py')]
        return run(prog + list(args), env=self.env)

    def test_adopt_dates(self):
        prog = self.PROGRAM or [sys.executable, os.path.join(self.inst.mod, 'tools', 'zgo_setup', 'zgo_setup.py')]
        code, out = run(prog + ['--adopt-dates', '--yes'], env=self.env)
        self.assertEqual(code, 1, out)
        self.assertIn('RESULT adopted=0', out)

    def test_a_loose_bake_and_pack(self):
        """--check says pack=needed for a bake made before 1.8.2; --pack packs it. (Runs before
        test_flow on the same install: its own work folder, and it removes its bake again.)"""
        env = dict(self.env, ZGO_BAKER_CACHE=tempfile.mkdtemp(dir=self.tmp))
        prog = self.PROGRAM or [sys.executable, os.path.join(self.inst.mod, 'tools', 'zgo_setup', 'zgo_setup.py')]

        def cmd(*args):
            return run(prog + list(args), env=env)
        bk = os.path.join(self.inst.mod, 'tools', 'zgo_baker', 'bake.py')
        code, out = run([sys.executable, bk, '--loose', '--quiet', '--jobs', '2', '--mo2', self.inst.mo2,
                         '--profile', 'P', '--anomaly', self.inst.game, '--out', self.inst.mod], env=env)
        try:
            self.assertEqual(code, 0, out)
            code, out = cmd('--check')
            self.assertIn('needs packing', out)
            self.assertTrue(out.strip().splitlines()[-1].endswith(' pack=needed'), out)
            self.assertEqual(code, 1, out)
            code, out = cmd('--pack', '--yes')
            self.assertEqual(code, 0, out)
            self.assertIn('loose files into archives', out)
            code, out = cmd('--check')
            self.assertTrue(out.strip().splitlines()[-1].endswith(' pack=ok'), out)
            self.assertFalse(os.path.isdir(os.path.join(self.inst.mod, 'gamedata', 'meshes', 'zgo')))
        finally:
            cmd('--remove', '--yes')
        self.assertFalse(os.path.exists(os.path.join(self.inst.mod, 'db')))

    def test_flow(self):
        code, out = self.cmd('--plan')
        self.assertEqual(code, 0, out)
        self.assertIn('profile: P', out)
        self.assertIn('Plan: 3 models', out)
        self.assertIn('Synth Models', out)
        code, out = self.cmd('--check')
        self.assertEqual(code, 1, out)
        self.assertIn('Not baked yet.', out)
        code, out = self.cmd('--bake', '--yes', '--jobs', '2')
        self.assertEqual(code, 0, out)
        self.assertIn('Baked 4 models (0 skipped, 0 could not be baked)', out)
        self.assertTrue(os.path.isfile(os.path.join(self.inst.mod, *bake.INPUTS.split('/'))))
        # kid mode for particles came along (the fake ZGO folder's own copy of tools/zgo_kidfx)
        self.assertIn('Kid mode for particles: 14 particle shaders rebuilt for your mod list; 2 gory effects other '
                      'mods play copied into Umbra Effects (2 new).', out)
        part = os.path.join(self.inst.mod, 'gamedata', 'particles')
        for rel in fakezgo.KIDFX_COPIES:
            self.assertTrue(os.path.isfile(os.path.join(part, *rel.split('/'))), rel)
        code, out = self.cmd('--check')
        self.assertIn('Your bake is up to date.', out)
        self.assertIn("Kid mode for particles: on (4 gory effects use Umbra Effects' particle shaders, 2 of them copied from "
                      'your other mods).', out)
        # the props tool came along: with no props in this mod list it says so, the models stay
        self.assertTrue('Breakable props' in out or code == 0, out)
        # kid mode for particles off and on again (the undo button of the window)
        spray = os.path.join(part, 'zgo', 'blood_spray.pe')
        with open(spray, 'rb') as f:
            shipped = f.read()
        code, out = self.cmd('--kid-particles-revert', '--yes')
        self.assertEqual(code, 0, out)
        self.assertIn("4 effects use the game's own particle shaders again", out)
        with open(spray, 'rb') as f:
            self.assertIn(b'= particles\\blend\r\n', f.read())
        code, out = self.cmd('--check')
        self.assertIn('Kid mode for particles: off.', out)
        code, out = self.cmd('--kid-particles-apply', '--yes')
        self.assertEqual(code, 0, out)
        self.assertIn("Kid mode for particles is on: 4 effects now use Umbra Effects' particle shaders again.", out)
        with open(spray, 'rb') as f:
            self.assertEqual(f.read(), shipped)
        code, out = self.cmd('--check')
        self.assertIn('RESULT body=ok ', out.strip().splitlines()[-1])
        # a prebaked bake (Umbra Setup): only its report is here, its files are not
        pre = os.path.join(self.tmp, 'prebaked')
        os.makedirs(pre, exist_ok=True)
        with open(os.path.join(self.inst.mod, bake.REPORT)) as f:
            rep = json.load(f)
        rep['profile'] = rep['inputs']['profile'] = 'Another profile'   # made on another machine
        for r in rep['results']:
            if r.get('src_mtime'):
                r['src_mtime'] -= 3600                                   # files from another download
        with open(os.path.join(pre, bake.REPORT), 'w') as f:
            json.dump(rep, f)
        code, out = self.cmd('--match', pre)
        self.assertEqual(code, 0, out)
        self.assertIn('The prebaked bake fits your mod list.', out)
        self.assertIn('RESULT match=yes fingerprint=%s' % rep['inputs']['fingerprint'], out)
        # made with other settings than this player's last bake: baked here instead, with theirs
        other = os.path.join(self.tmp, 'prebaked-other-settings')
        os.makedirs(other, exist_ok=True)
        rep2 = dict(rep, options=dict(rep.get('options') or {}, gibs=False, experimental_damage=True))
        with open(os.path.join(other, bake.REPORT), 'w') as f:
            json.dump(rep2, f)
        code, out = self.cmd('--match', other)
        self.assertEqual(code, 1, out)
        self.assertIn('It was made with other settings than yours: "Body gibs" off there, on in yours; '
                      '"Damage meshes and gib chunks (experimental)" on there, off in yours.', out)
        self.assertIn('RESULT match=no ', out)
        with open(os.path.join(other, bake.REPORT), 'w') as f:
            json.dump(rep, f)
        with open(os.path.join(other, 'zgo_fracture_report.json'), 'w') as f:
            json.dump({'options': {'experimental_native': True}, 'files': [], 'results': []}, f)
        code, out = self.cmd('--match', other)
        self.assertEqual(code, 1, out)
        self.assertIn('"Game breaks crates and stools itself (experimental)" on there, off in yours', out)
        code, out = self.cmd('--match', self.tmp)
        self.assertEqual(code, 2, out)
        self.assertIn('no bake report', out)
        fakezgo.write_model(self.inst.mo2, 'Synth Models', 'actors\\synth\\synth_b', b'not a model any more')
        code, out = self.cmd('--check')
        self.assertEqual(code, 1, out)
        self.assertIn('Mod "Synth Models" changed 1 model', out)
        self.assertIn('RESULT body=stale ', out)
        code, out = self.cmd('--match', pre)
        self.assertEqual(code, 1, out)
        self.assertIn('The prebaked bake does not fit your mod list.', out)
        self.assertIn('Mod "Synth Models" changed 1 model', out)
        self.assertIn('RESULT match=no ', out)
        code, out = self.cmd('--bake', '--yes', '--no-props', '--no-kid-particles')
        self.assertEqual(code, 0, out)
        self.assertIn('1 could not be baked', out)
        self.assertIn('Not baked: actors\\synth\\synth_b', out)
        self.assertNotIn('particle shaders rebuilt', out)
        fakezgo.write_model(self.inst.mo2, 'Synth Models', 'actors\\synth\\synth_b')
        code, out = self.cmd('--remove', '--yes')
        self.assertEqual(code, 0, out)
        self.assertIn("and 2 copies of other mods' particle effects.", out)
        self.assertFalse(os.path.exists(os.path.join(self.inst.mod, bake.REPORT)))
        for rel in fakezgo.KIDFX_COPIES:
            self.assertFalse(os.path.exists(os.path.join(part, *rel.split('/'))), rel)
        with open(spray, 'rb') as f:
            self.assertEqual(f.read(), shipped, 'what ZGO ships stays')
        code, out = self.cmd('--plan', '--profile', 'Nope')
        self.assertEqual(code, 2, out)
        self.assertIn('Problem: Choose the MO2 profile', out)

    def kidfx_files(self):
        """The fake ZGO folder's files kid mode for particles may change: {path: sha1}."""
        out = {}
        for sub in (('gamedata',), ('tools', 'zgo_kidfx')):
            for dp, dns, fns in os.walk(os.path.join(self.inst.mod, *sub)):
                dns[:] = [d for d in dns if d != '__pycache__']
                for fn in fns:
                    with open(os.path.join(dp, fn), 'rb') as f:
                        out[os.path.relpath(os.path.join(dp, fn), self.inst.mod)] = hashlib.sha1(f.read()).hexdigest()
        return out

    def test_selftest(self):
        before = self.kidfx_files()
        code, out = self.cmd('--selftest')
        self.assertEqual(code, 0, out)
        self.assertIn('SELFTEST PASSED', out)
        self.assertIn('PASS worker process', out)
        self.assertIn('PASS parallel workers', out)
        self.assertIn('kid mode for particles yes', out)
        self.assertEqual(self.kidfx_files(), before, 'the self-test changes nothing in the ZGO folder')

    def test_kid_particles_need_the_tool(self):
        if self.PROGRAM:
            self.skipTest('the source script only')
        with tempfile.TemporaryDirectory() as d:
            inst = fakezgo.make(d, kidfx=False)
            prog = [sys.executable, os.path.join(inst.mod, 'tools', 'zgo_setup', 'zgo_setup.py')]
            code, out = run(prog + ['--kid-particles-revert', '--yes'], env=dict(self.env, ZGO_BAKER_CACHE=inst.cache))
            self.assertEqual(code, 2, out)
            self.assertIn('Kid mode for particles (tools/zgo_kidfx) is not installed with this version of Umbra Effects.', out)
            code, out = run(prog + ['--plan'], env=dict(self.env, ZGO_BAKER_CACHE=inst.cache))
            self.assertEqual(code, 0, out)
            self.assertNotIn('kid_particles', out)

    def test_not_in_a_zgo_folder(self):
        if self.PROGRAM:
            self.skipTest('the source script only')
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'zgo_setup.py')
            shutil.copy(os.path.join(SETUP_DIR, 'zgo_setup.py'), src)
            code, out = run([sys.executable, src, '--check'], env=self.env)
            self.assertEqual(code, 2)
            self.assertIn('run it from the Umbra Gore & Effects folder', out)


def _frozen_linux():
    p = os.environ.get('ZGO_SETUP_BIN') or os.path.join(SETUP_DIR, 'zgo-setup-linux')
    return p if os.path.isfile(p) and os.name != 'nt' else None


@unittest.skipUnless(_frozen_linux(), 'the Linux program is not built (dev/build_setup/build.sh linux)')
class FrozenLinux(EndToEnd):
    """The ready-made Linux program, copied into the fake install, as shipped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        dst = os.path.join(cls.inst.mod, 'tools', 'zgo_setup', 'zgo-setup-linux')
        shutil.copy(_frozen_linux(), dst)
        os.chmod(dst, 0o755)
        cls.PROGRAM = [dst]

    def test_window_under_xvfb(self):
        if not xvfb():
            self.skipTest('xvfb-run is not installed')
        code, out = run(['xvfb-run', '-a', self.PROGRAM[0], '--selftest', '--smoke', '3'],
                        env={'ZGO_BAKER_CACHE': self.inst.cache})
        self.assertEqual(code, 0, out)
        self.assertIn('PASS window', out)


@unittest.skipUnless(xvfb() and has_tk(sys.executable), 'needs tkinter and xvfb-run')
class TestWindow(unittest.TestCase):
    """The window, driven like a player would (gui_driver.py), on a virtual display."""

    def test_drive(self):
        with tempfile.TemporaryDirectory() as d:
            inst = fakezgo.make(d)
            code, out = run(['xvfb-run', '-a', sys.executable, os.path.join(HERE, 'gui_driver.py'), inst.mod],
                            env={'ZGO_BAKER_CACHE': inst.cache}, timeout=900)
            self.assertEqual(code, 0, out)
            self.assertIn('GUI DRIVER PASSED', out)


def _windows_exe():
    p = os.environ.get('ZGO_SETUP_EXE') or os.path.join(SETUP_DIR, 'Umbra Effects Setup.exe')
    return p if os.path.isfile(p) else None


@unittest.skipUnless(os.environ.get('ZGO_TEST_WINE') == '1' and _windows_exe() and shutil.which('wine'),
                     'set ZGO_TEST_WINE=1 (needs wine and the built Umbra Effects Setup.exe)')
class WindowsUnderWine(unittest.TestCase):
    def test_selftest(self):
        with tempfile.TemporaryDirectory() as d:
            inst = fakezgo.make(d)
            exe = os.path.join(inst.mod, 'tools', 'zgo_setup', 'Umbra Effects Setup.exe')
            shutil.copy(_windows_exe(), exe)
            prefix = os.environ.get('WINEPREFIX') or os.path.expanduser('~/.cache/zgo-wine-setup')
            env = {'WINEPREFIX': prefix, 'WINEDEBUG': '-all', 'ZGO_BAKER_CACHE': ''}
            log = os.path.join(d, 'selftest.txt')
            cmd = (['xvfb-run', '-a'] if xvfb() else []) + ['wine', exe, '--selftest', '--log', log]
            code, out = run(cmd, env=env, timeout=900)
            with open(log, encoding='utf-8', errors='replace') as f:
                text = f.read()
            self.assertEqual(code, 0, text + out)
            self.assertIn('SELFTEST PASSED', text)
            code, out = run((['xvfb-run', '-a'] if xvfb() else []) +
                            ['wine', exe, '--bake', '--yes', '--no-props', '--jobs', '2', '--log', log], env=env, timeout=900)
            with open(log, encoding='utf-8', errors='replace') as f:
                text = f.read()
            self.assertEqual(code, 0, text)
            self.assertIn('Baked 4 models', text)
            self.assertIn('Running under Wine', text)


if __name__ == '__main__':
    unittest.main()
