#!/usr/bin/env python3
"""Writing the bake's engine archives (tools/zgo_baker/xdb_write.py) and packing a loose bake (bake.pack)."""
import glob
import json
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakemo2  # noqa: E402
import bake, xdb, xdb_write  # noqa: E402


class TestLzhuf(unittest.TestCase):
    def test_round_trip(self):
        rnd = random.Random(3)
        for n in (0, 1, 2, 59, 60, 61, 4095, 4096, 16383, 16384, 16385, 100000):
            for data in (b'a' * n, bytes(rnd.getrandbits(8) for _ in range(n)),
                         (b'meshes\\zgo\\baked\\pieces\\' * (n // 24 + 1))[:n]):
                self.assertEqual(xdb.lzhuf_decode(xdb_write.encode(data)), data, n)

    def test_reads_the_games_archives(self):
        """read_table reads the engine's own archives (folder entries, compressed tables). Uses
        the game's archives when ZGO_TEST_ANOMALY points at an Anomaly folder."""
        game = os.environ.get('ZGO_TEST_ANOMALY')
        if not game or not os.path.isdir(os.path.join(game, 'db')):
            self.skipTest('set ZGO_TEST_ANOMALY to an Anomaly folder')
        n = 0
        for p in sorted(glob.glob(os.path.join(game, 'db', '**', '*.db*'), recursive=True)):
            header, entries = xdb_write.read_table(p)
            self.assertIn('[header]', header or '')
            self.assertTrue(entries, p)
            n += 1
        self.assertGreater(n, 10)


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='zgo_xdb_')
        self.addCleanup(shutil.rmtree, self.root, True)

    def _files(self, n=40):
        rnd = random.Random(5)
        out = []
        for i in range(n):
            rel = 'gamedata/meshes/zgo/baked/pieces/%02x/%012x.ogf' % (i % 7, rnd.getrandbits(48))
            p = os.path.join(self.root, 'src', *rel.split('/'))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(bytes(rnd.getrandbits(8) for _ in range(rnd.randrange(0, 3000))))
            out.append((rel, p))
        return out

    def test_write_and_read(self):
        files = self._files()
        dest = os.path.join(self.root, 'db', 'mods', 'zgo_bake_pieces_00.db0')
        size = xdb_write.write_archive(dest, files)
        self.assertEqual(size, os.path.getsize(dest))
        self.assertFalse(os.path.exists(dest + '.part'))
        header, entries = xdb_write.read_table(dest)
        self.assertIn('auto_load = true', header)
        self.assertIn('entry_point = $fs_root$\\gamedata\\', header)
        with open(dest, 'rb') as f:
            cid, n = struct.unpack('<II', f.read(8))
        self.assertEqual(cid, xdb_write.HEADER_CHUNK)
        dirs = [e for e in entries if e[0].endswith('\\')]
        got = {e[0]: e for e in entries if not e[0].endswith('\\')}
        self.assertIn('meshes\\', [d[0] for d in dirs])
        self.assertIn('meshes\\zgo\\baked\\pieces\\00\\', [d[0] for d in dirs])
        self.assertTrue(all(d[1:] == (0, 0, 0, 0) for d in dirs))
        self.assertEqual(entries[:len(dirs)], dirs, 'folders first, as in the game\'s archives')
        for rel, src in files:
            e = got[xdb_write.archive_name(rel)]
            with open(src, 'rb') as f:
                b = f.read()
            self.assertEqual(e[2], e[3])
            self.assertEqual(e[4], zlib.crc32(b) & 0xFFFFFFFF)
            self.assertEqual(xdb_write.read_file(dest, e), b)
            self.assertEqual(xdb.Archive(dest).read(xdb_write.archive_name(rel)), b)   # the baker's own reader

    def test_split(self):
        its = [('gamedata/x/%d' % i, 'p', 100) for i in range(10)]
        self.assertEqual([len(g) for g in xdb_write.plan_archives(its, limit=250)], [2, 2, 2, 2, 2])
        self.assertEqual([len(g) for g in xdb_write.plan_archives([('gamedata/big', 'p', 999)], limit=10)], [1])

    def test_cancel(self):
        files = self._files(5)
        dest = os.path.join(self.root, 'a.db0')
        self.assertIsNone(xdb_write.write_archive(dest, files, stop=lambda: True))
        self.assertEqual(os.listdir(self.root), ['src'])

    def test_an_error_leaves_no_part_file(self):
        files = self._files(5)
        files[3] = (files[3][0], os.path.join(self.root, 'gone.ogf'))
        dest = os.path.join(self.root, 'a.db0')
        with self.assertRaises(OSError):
            xdb_write.write_archive(dest, files)
        self.assertEqual(os.listdir(self.root), ['src'])

    def test_consume_deletes_each_source_once_it_is_in(self):
        files = self._files(6)
        want = {}
        for rel, p in files:
            with open(p, 'rb') as f:
                want[xdb_write.archive_name(rel)] = f.read()
        dest = os.path.join(self.root, 'a.db0')
        xdb_write.write_archive(dest, files, consume=True)
        self.assertFalse(any(os.path.exists(p) for _, p in files))
        got = {e[0]: xdb_write.read_file(dest, e) for e in xdb_write.read_table(dest)[1] if not e[0].endswith('\\')}
        self.assertEqual(got, want)

    def test_the_engines_2_gb_limit(self):
        files = self._files(2)
        with mock.patch.object(xdb_write, 'DATA_MAX', 100):
            with self.assertRaisesRegex(xdb_write.BadArchive, '2 GB'):
                xdb_write.write_archive(os.path.join(self.root, 'a.db0'), files)
        self.assertEqual(os.listdir(self.root), ['src'])

    def test_limit_is_read_when_called(self):
        its = [('gamedata/x/%d' % i, 'p', 100) for i in range(4)]
        with mock.patch.object(xdb_write, 'LIMIT', 150):
            self.assertEqual(len(xdb_write.plan_archives(its)), 4)


class TestPackABake(unittest.TestCase):
    """A bake made loose (as before 1.8.2) packs in place; Remove deletes the archives."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='zgo_pack_')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.o = fakemo2.make(self.root)
        p = fakemo2.patched()
        p.__enter__()
        self.addCleanup(p.__exit__, None, None, None)
        self.o.pack = False
        self.loose = bake.bake(self.o)

    def _contents(self, rep):
        """{rel: bytes} of every output, read from the archives or the loose files."""
        out = {}
        for rel in rep['files']:
            p = os.path.join(self.o.out, *rel.split('/'))
            if bake.is_archive(rel):
                for e in xdb_write.read_table(p)[1]:
                    if not e[0].endswith('\\'):
                        out['gamedata/' + e[0].replace('\\', '/')] = xdb_write.read_file(p, e)
            else:
                with open(p, 'rb') as f:
                    out[rel] = f.read()
        return out

    def test_pack_in_place(self):
        before = self._contents(self.loose)
        n_loose = len(bake.loose_files(self.loose))
        self.assertGreater(n_loose, 10)
        self.assertEqual(bake.pack(self.o.out), n_loose)
        rep = bake.read_report(self.o.out)
        self.assertNotIn('status', rep)
        self.assertFalse(bake.loose_files(rep))
        self.assertEqual(sorted(bake.output_files(rep)), sorted(before))
        self.assertEqual(self._contents(rep), before)
        self.assertFalse(os.path.isdir(os.path.join(self.o.out, 'gamedata', 'meshes', 'zgo')))
        self.assertEqual(bake.pack(self.o.out), 0, 'nothing left to pack')
        # Remove: archives, folders and all
        bake.remove(self.o.out)
        self.assertFalse(os.path.exists(os.path.join(self.o.out, 'db')))

    def test_a_pack_that_stopped_while_deleting_is_finished(self):
        before = self._contents(self.loose)
        real = bake.remove_files
        calls = []

        def dies(root, files, progress=None):
            calls.append(1)
            real(root, files[:len(files) // 2], progress)
            raise OSError('power cut')
        bake.remove_files = dies
        try:
            with self.assertRaises(OSError):
                bake.pack(self.o.out)
        finally:
            bake.remove_files = real
        self.assertEqual(bake.read_report(self.o.out)['status'], 'packing')
        bake.pack(self.o.out)
        rep = bake.read_report(self.o.out)
        self.assertNotIn('status', rep)
        self.assertEqual(self._contents(rep), before)

    def test_cancel_leaves_it_loose(self):
        before = self._contents(self.loose)
        with self.assertRaises(bake.Cancelled):
            bake.pack(self.o.out, cancel=lambda: True)
        rep = bake.read_report(self.o.out)
        self.assertEqual(rep['files'], self.loose['files'])
        self.assertEqual(self._contents(rep), before)
        self.assertFalse(os.path.exists(os.path.join(self.o.out, 'db', 'mods')) and
                         os.listdir(os.path.join(self.o.out, 'db', 'mods')))

    def test_archives_a_killed_pack_left_dont_block_anything(self):
        """A pack killed after writing its archives but before its report: the next bake
        replaces them, the next pack writes them again, and Remove deletes them."""
        mods = os.path.join(self.o.out, 'db', 'mods')
        os.makedirs(mods)
        for fn in ('zgo_bake_caps_00.db0', 'zgo_bake_pieces_07.db0', 'zgo_bake_gibs_00.db0.part'):
            with open(os.path.join(mods, fn), 'wb') as f:
                f.write(b'half')
        with open(os.path.join(mods, 'someone_elses.db0'), 'wb') as f:
            f.write(b'theirs')
        before = self._contents(self.loose)
        bake.pack(self.o.out)
        rep = bake.read_report(self.o.out)
        self.assertEqual(self._contents(rep), before)
        self.assertEqual(sorted(os.listdir(mods)), sorted([a.split('/')[-1] for a in rep['packed']] + ['someone_elses.db0']))
        self.assertEqual(rep['counts']['archives'], len(rep['packed']))
        self.assertEqual(rep['archive_bytes'], {a: os.path.getsize(os.path.join(self.o.out, *a.split('/')))
                                                for a in rep['packed']})
        with open(os.path.join(mods, 'zgo_bake_pieces_09.db0'), 'wb') as f:      # another orphan
            f.write(b'half')
        self.o.pack = True
        bake.bake(self.o)
        self.assertNotIn('zgo_bake_pieces_09.db0', os.listdir(mods))
        with open(os.path.join(mods, 'zgo_bake_chunks_05.db0'), 'wb') as f:
            f.write(b'half')
        bake.remove(self.o.out)
        self.assertEqual(os.listdir(mods), ['someone_elses.db0'])

    def test_an_archive_in_use_stops_before_anything_changes(self):
        bake.pack(self.o.out)
        rep = bake.read_report(self.o.out)
        real = os.replace

        def locked(src, dst):
            if dst.endswith('.zgo-check'):
                raise PermissionError(13, 'in use')
            return real(src, dst)
        with mock.patch.object(bake.os, 'replace', locked):
            with self.assertRaisesRegex(bake.BakeError, 'close the game'):
                bake.remove(self.o.out)
            self.o.pack = True
            with self.assertRaisesRegex(bake.BakeError, 'close the game'):
                bake.bake(self.o)
        self.assertEqual(bake.read_report(self.o.out), rep, 'nothing changed')

    def test_no_room_to_pack(self):
        class Usage:
            free = 1000
        with mock.patch.object(bake.shutil, 'disk_usage', lambda p: Usage):
            with self.assertRaisesRegex(bake.BakeError, 'GB free'):
                bake.pack(self.o.out)
        self.assertEqual(bake.read_report(self.o.out)['files'], self.loose['files'])

    def test_rebake_replaces_a_loose_bake(self):
        self.o.pack = True
        rep = bake.bake(self.o)
        self.assertFalse(bake.loose_files(rep))
        self.assertFalse(os.path.isdir(os.path.join(self.o.out, 'gamedata', 'meshes', 'zgo')))
        self.assertEqual(sorted(bake.output_files(rep)), sorted(self._contents(rep)))


if __name__ == '__main__':
    unittest.main()
