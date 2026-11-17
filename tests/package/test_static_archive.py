#!/usr/bin/env python3
"""The textures' archive, db/mods/zgo_static.db0 (dev/package.py, dev/deploy.py;
docs/formats/static.md): what goes in, its bytes, the clash check, and the dry runs.

Set ZGO_TEST_ANOMALY (an Anomaly folder) and ZGO_TEST_MO2 (an MO2 folder: its mods/) to
also check the archive's textures against a real install."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'dev'))
sys.dont_write_bytecode = True       # (dev/ and tools/zgo_baker stay free of __pycache__)
import package  # noqa: E402
import deploy  # noqa: E402

package._xdb()
import xdb  # noqa: E402  (tools/zgo_baker, put on the path by package._xdb)
import xdb_write  # noqa: E402

RUN_TIMEOUT = 300


def repo_bytes(rel):
    with open(os.path.join(ROOT, rel), 'rb') as f:
        return f.read()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loose, cls.static, _ = package.release()
        cls.tmp = tempfile.mkdtemp(prefix='zgo_static_test_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestSelection(Base):
    def test_only_our_own_textures(self):
        self.assertTrue(self.static, 'no textures to archive')
        for rel, _ in self.static:
            self.assertTrue(rel.startswith(package.STATIC_PREFIXES), rel)
            self.assertTrue(rel.endswith('.dds'), rel)
        rels = {rel for rel, _ in self.static}
        self.assertIn('gamedata/textures/zgo/wounds/stump.dds', rels)
        self.assertIn('gamedata/textures/zgo/wounds/n/000.dds', rels)

    def test_overrides_stay_loose(self):
        """A texture that replaces the game's or another mod's stays a loose file (a loose
        file wins over every archive; ours would lose to theirs)."""
        loose = {rel for rel, _ in self.loose}
        for rel in ('gamedata/textures/wm/wm_blood_2.dds',            # the game's (textures.db4)
                    'gamedata/textures/pfx/pfx_distortion.dds',       # the game's
                    'gamedata/textures/jdude/BloodSquirt1.dds'):      # Painter of the Zone's, Cinematic VFX's
            if os.path.isfile(os.path.join(ROOT, rel)):
                self.assertIn(rel, loose)
                self.assertFalse(package.is_static(rel), rel)
        self.assertFalse(package.is_static('gamedata/particles/zgo/blood/spray.pe'))
        self.assertFalse(package.is_static('gamedata/textures/zgo/wounds/stump.thm'))
        for rel, _ in self.loose:
            self.assertFalse(rel.startswith('gamedata/textures/zgo/'), rel)

    def test_keep_loose_list(self):
        rel = self.static[0][0]
        with mock.patch.object(package, 'STATIC_KEEP_LOOSE', (rel,)):
            loose, static, _ = package.release()
        self.assertIn(rel, {r for r, _ in loose})
        self.assertNotIn(rel, {r for r, _ in static})

    def test_every_file_once(self):
        kept, _ = package.walk()
        self.assertEqual(sorted(kept), sorted(self.loose + self.static))


class TestArchive(Base):
    def test_holds_exactly_the_textures(self):
        dest = os.path.join(self.tmp, 'a', 'zgo_static.db0')
        size = package.build_static(dest, self.static)
        self.assertEqual(size, os.path.getsize(dest))
        self.assertFalse(os.path.exists(dest + '.part'))
        a = xdb.Archive(dest)
        self.assertIn(b'entry_point = $fs_root$\\gamedata\\', a.header)
        names = {n for n in a.files if not n.endswith('\\')}
        want = {xdb_write.archive_name(rel).lower(): rel for rel, _ in self.static}
        self.assertEqual(names, set(want))
        for name, rel in want.items():
            self.assertEqual(a.read(name), repo_bytes(rel), rel)
        self.assertTrue(package.static_matches(dest, self.static))

    def test_same_files_same_bytes(self):
        one, two = os.path.join(self.tmp, 'one.db0'), os.path.join(self.tmp, 'two.db0')
        package.build_static(one, self.static)
        package.build_static(two, list(reversed(self.static)))
        with open(one, 'rb') as f1, open(two, 'rb') as f2:
            self.assertTrue(f1.read() == f2.read(), 'two builds differ')

    def test_matches_spots_a_stale_archive(self):
        dest = os.path.join(self.tmp, 'stale.db0')
        package.build_static(dest, self.static[:-1])
        self.assertFalse(package.static_matches(dest, self.static))
        self.assertFalse(package.static_matches(os.path.join(self.tmp, 'missing.db0'), self.static))


class TestClashes(Base):
    def test_finds_other_sources(self):
        """The game's archives and loose gamedata, other mods' loose files and archives, and
        MO2's overwrite count; this mod's own folders don't."""
        rels = [rel for rel, _ in self.static]
        t = os.path.join(self.tmp, 'install')
        game, mods = os.path.join(t, 'anomaly'), os.path.join(t, 'mo2', 'mods')
        xdb_write.write_archive(os.path.join(game, 'db', 'textures_x.db0'),
                                [(rels[0], os.path.join(ROOT, rels[0]))])
        other = os.path.join(mods, 'Other Mod', *rels[1].split('/'))
        upper = os.path.join(mods, 'Other Mod', 'gamedata', *rels[2][9:].upper().split('/'))   # names: any case
        ours = os.path.join(mods, 'Umbra Gore & Effects')
        for p in (other, upper, os.path.join(ours, *rels[3].split('/')),
                  os.path.join(ours, 'gamedata', 'scripts', 'zgo_main.script'),
                  os.path.join(t, 'mo2', 'overwrite', *rels[4].split('/')),
                  os.path.join(mods, 'Unrelated', 'gamedata', 'textures', 'wm', 'wm_blood_2.dds')):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'wb').close()
        xdb_write.write_archive(os.path.join(mods, 'Archived Mod', 'db', 'mods', 'x.db0'),
                                [(rels[5], os.path.join(ROOT, rels[5]))])
        found = package.clashes(rels, game, mods)
        self.assertEqual(sorted(found), sorted(rels[i] for i in (0, 1, 2, 4, 5)))
        self.assertIn('game: db/textures_x.db0', found[rels[0]])
        self.assertIn('mod: Other Mod', found[rels[1]])
        self.assertIn('MO2 overwrite', found[rels[4]])

    def test_real_install(self):
        game, mo2 = os.environ.get('ZGO_TEST_ANOMALY'), os.environ.get('ZGO_TEST_MO2')
        if not (game and mo2 and os.path.isdir(os.path.join(game, 'db')) and os.path.isdir(os.path.join(mo2, 'mods'))):
            self.skipTest('set ZGO_TEST_ANOMALY and ZGO_TEST_MO2 to check against a real install')
        found = package.clashes([rel for rel, _ in self.static], game, os.path.join(mo2, 'mods'))
        self.assertEqual(found, {})
        # and the textures that stay loose do clash (that's why they stay loose)
        wm = [rel for rel, _ in self.loose if rel.startswith('gamedata/textures/wm/')]
        if wm:
            self.assertTrue(package.clashes(wm, game, os.path.join(mo2, 'mods')))


class TestDryRuns(Base):
    def run_py(self, *args):
        p = subprocess.run([sys.executable, '-B', *args], cwd=ROOT, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_package_dry_run(self):
        out = self.run_py('dev/package.py', '--dry-run', '--list')
        listed = [ln.strip() for ln in out.splitlines() if ln.startswith('    ') and not ln.startswith('      ')]
        self.assertIn(package.STATIC_ARCHIVE, listed)
        self.assertFalse([ln for ln in listed if package.is_static(ln)], 'archived textures listed loose')
        self.assertIn('gamedata/textures/wm/wm_blood_2.dds', listed)
        self.assertIn('an archive of %d textures' % len(self.static), out)

    def fake_mod_folder(self):
        dst = os.path.join(tempfile.mkdtemp(dir=self.tmp), 'mods', 'Umbra Gore & Effects')
        os.makedirs(os.path.join(dst, 'gamedata', 'scripts'))
        shutil.copy(os.path.join(ROOT, deploy.MARKER), os.path.join(dst, deploy.MARKER))
        return dst

    def test_deploy_plan(self):
        """Into a folder an earlier deploy filled with loose textures: the archive is new, the
        loose copies go (unless a bake report lists them), nothing archived is copied loose."""
        dst = self.fake_mod_folder()
        olds = [rel for rel, _ in self.static[:3]]
        for rel in olds + ['gamedata/textures/zgo/wounds/gone.dds']:
            d = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy(os.path.join(ROOT, olds[0]), d)
        new, changed, same, kept_live, extra, retire = deploy.plan(dst)
        self.assertIn(package.STATIC_ARCHIVE, new)
        self.assertFalse([r for r in new + changed if package.is_static(r)])
        self.assertEqual(retire, sorted(olds))
        self.assertIn('gamedata/textures/zgo/wounds/gone.dds', extra)     # not ours any more: listed, kept

        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['deploy.py', '--dry-run', '--to', dst]), redirect_stdout(out):
            deploy.main()
        text = out.getvalue()
        self.assertIn('archive %s: new (%d textures' % (package.STATIC_ARCHIVE, len(self.static)), text)
        self.assertIn('remove (loose copies of textures now in the archive): 3', text)
        for rel in olds:                                    # a dry run changes nothing
            self.assertTrue(os.path.isfile(os.path.join(dst, rel)))
        self.assertFalse(os.path.exists(os.path.join(dst, package.STATIC_ARCHIVE)))

        # the archive in place and current: unchanged, and no copy of it to make
        package.build_static(os.path.join(dst, package.STATIC_ARCHIVE), self.static)
        new, changed, *_ = deploy.plan(dst)
        self.assertNotIn(package.STATIC_ARCHIVE, new + changed)

    def test_remove_loose(self):
        dst = self.fake_mod_folder()
        rels = [rel for rel, _ in self.static if rel.startswith('gamedata/textures/zgo/wounds/n/')][:2]
        keep = os.path.join(dst, 'gamedata', 'textures', 'zgo', 'keep.dds')
        for p in [os.path.join(dst, r) for r in rels] + [keep]:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'wb').close()
        deploy.remove_loose(rels, dst)
        for r in rels:
            self.assertFalse(os.path.exists(os.path.join(dst, r)))
        self.assertFalse(os.path.exists(os.path.join(dst, 'gamedata', 'textures', 'zgo', 'wounds')))   # emptied
        self.assertTrue(os.path.isfile(keep))

    def test_bake_files_are_never_removed(self):
        """A path a bake report lists is left alone, even at an archived texture's name."""
        dst = self.fake_mod_folder()
        rel = self.static[0][0]
        os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
        open(os.path.join(dst, rel), 'wb').close()
        with open(os.path.join(dst, package.REPORTS[0]), 'w') as f:
            f.write('{"files": ["%s"]}' % rel)
        *_, retire = deploy.plan(dst)
        self.assertNotIn(rel, retire)


if __name__ == '__main__':
    unittest.main()
