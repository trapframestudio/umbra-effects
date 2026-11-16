"""Writing X-Ray engine archives (.db0): what the bake packs its many small models into.
(xdb.py reads them; this module shares its LZHUF tree constants and decoder.)

The engine indexes every loose file of every MO2 mod at startup, through MO2's
virtual file system; on Linux (Proton) that costs about a millisecond per file
and more as the count grows, so a bake of ~80,000 loose files added a minute or
more to every game start. An archive is one file whose index the engine reads
in one go. Archives in db/mods/ (fsgame.ltx: $arch_dir_resource$) load at
startup like Anomaly's own, mounted at gamedata\\.

Format (as Anomaly's own archives and every G.A.M.M.A. mod archive):

    chunk 666   the [header] ltx: auto_load = true, entry_point = $fs_root$\\gamedata\\
    chunk 0     the files' bytes, one after another
    chunk 1     the file table, LZHUF-compressed (chunk id | 0x80000000):
                per file u16 n, then n bytes: u32 size_real, u32 size_compressed,
                u32 crc32, the name (gamedata-relative, backslashes), u32 offset
                (from the start of the archive file); each folder first has an
                entry of its own (name ending in a backslash, all zero)

A file with size_real == size_compressed is stored as it is (we store all of them
that way: the engine maps it straight from the archive). Chunks are u32 id, u32
size, then the bytes. Offsets are u32, and Anomaly keeps its archives under about
540 MB, so write_archives splits at LIMIT.

LZHUF is Haruhiko Okumura's 1989 LZSS + adaptive Huffman coder (public domain),
as the engine's xrCore uses it (MAX_FREQ 0x4000): a little-endian u32 of the
original size, then the bit stream. encode() writes literals only (no back
references), which every LZHUF decoder reads (xdb.lzhuf_decode reads it back in
the tests), at about 70% of the input: the tables are small.
"""
import os
import struct
import zlib

import xdb

HEADER_CHUNK = 666
DATA_CHUNK = 0
TABLE_CHUNK = 1
COMPRESSED = 0x80000000
LIMIT = 512 * 1024 * 1024        # bytes per archive (Anomaly's own stay under ~540 MB)
HEADER = ('[header]\r\nauto_load = true\r\ncreator = "Umbra Gore & Effects"\r\n'
          'entry_point = $fs_root$\\gamedata\\\r\nlevel_name = anomaly\r\nlevel_ver = 1.8\r\n'
          'link = "Umbra Gore & Effects bake"\r\n')


class BadArchive(Exception):
    pass


# ---------------------------------------------------------------- LZHUF

_N_CHAR, _T, _R, _MAX_FREQ = xdb.N_CHAR, xdb.T, xdb.R, xdb.MAX_FREQ


class _Huff:
    """The adaptive Huffman tree both directions share."""

    def __init__(self):
        T, N_CHAR = _T, _N_CHAR
        self.freq = freq = [0] * (T + 1)
        self.prnt = prnt = [0] * (T + N_CHAR)
        self.son = son = [0] * T
        for i in range(N_CHAR):
            freq[i] = 1
            son[i] = i + T
            prnt[i + T] = i
        i, j = 0, N_CHAR
        while j <= _R:
            freq[j] = freq[i] + freq[i + 1]
            son[j] = i
            prnt[i] = prnt[i + 1] = j
            i += 2
            j += 1
        freq[T] = 0xFFFF
        prnt[_R] = 0

    def reconst(self):
        freq, son, prnt, T = self.freq, self.son, self.prnt, _T
        j = 0
        for i in range(T):
            if son[i] >= T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, _N_CHAR
        while j < T:
            f = freq[j] = freq[i] + freq[i + 1]
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(T):
            k = son[i]
            if k >= T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(self, c):
        freq, son, prnt, T = self.freq, self.son, self.prnt, _T
        if freq[_R] == _MAX_FREQ:
            self.reconst()
        c = prnt[c + T]
        while True:
            freq[c] += 1
            k = freq[c]
            l = c + 1
            if k > freq[l]:
                l += 1
                while k > freq[l]:
                    l += 1
                l -= 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break


def encode(data):
    """Bytes -> LZHUF (literals only; any LZHUF decoder reads it)."""
    h = _Huff()
    prnt, T, R = h.prnt, _T, _R
    out = bytearray(struct.pack('<I', len(data)))
    putbuf = 0
    putlen = 0
    for c in data:
        code = 0
        n = 0
        k = prnt[c + T]
        while True:
            code >>= 1
            if k & 1:
                code |= 0x8000
            n += 1
            k = prnt[k]
            if k == R:
                break
        # Putcode(n, code)
        putbuf |= code >> putlen
        putlen += n
        if putlen >= 8:
            out.append((putbuf >> 8) & 0xFF)
            putlen -= 8
            if putlen >= 8:
                out.append(putbuf & 0xFF)
                putlen -= 8
                putbuf = (code << (n - putlen)) & 0xFFFF
            else:
                putbuf = (putbuf << 8) & 0xFFFF
        h.update(c)
    if putlen:
        out.append((putbuf >> 8) & 0xFF)
    return bytes(out)


# ---------------------------------------------------------------- archives

def _chunks(f, size):
    """(id, offset of the bytes, length) of each chunk."""
    out = []
    o = 0
    while o + 8 <= size:
        f.seek(o)
        cid, n = struct.unpack('<II', f.read(8))
        if o + 8 + n > size:
            raise BadArchive('chunk %d runs past the end of the file' % (cid & ~COMPRESSED))
        out.append((cid, o + 8, n))
        o += 8 + n
    if o != size:
        raise BadArchive('trailing bytes after the last chunk')
    return out


def read_table(path):
    """(header text or None, [(name, offset, size_real, size_compressed, crc)]) of an archive."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        header = table = None
        for cid, at, n in _chunks(f, size):
            f.seek(at)
            if cid & ~COMPRESSED == HEADER_CHUNK:
                header = f.read(n).decode('latin-1')
            elif cid & ~COMPRESSED == TABLE_CHUNK:
                raw = f.read(n)
                table = xdb.lzhuf_decode(raw) if cid & COMPRESSED else raw
    if table is None:
        raise BadArchive('no file table')
    entries = []
    q = 0
    while q < len(table):
        if q + 2 > len(table):
            raise BadArchive('file table cut short')
        n, = struct.unpack_from('<H', table, q)
        q += 2
        if n < 16 or q + n > len(table):
            raise BadArchive('bad file table entry')
        real, comp, crc = struct.unpack_from('<III', table, q)
        name = table[q + 12:q + n - 4].decode('latin-1')
        off, = struct.unpack_from('<I', table, q + n - 4)
        q += n
        if off + comp > size:
            raise BadArchive('%s points past the end of the archive' % name)
        entries.append((name, off, real, comp, crc))
    return header, entries


def read_file(path, entry):
    """The bytes of one stored (uncompressed) file of an archive."""
    name, off, real, comp, crc = entry
    if real != comp:
        raise BadArchive('%s is compressed (not written by the bake)' % name)
    with open(path, 'rb') as f:
        f.seek(off)
        return f.read(real)


def archive_name(rel):
    """gamedata/meshes/a/b.ogf -> meshes\\a\\b.ogf (the name in the table)."""
    rel = rel.replace('\\', '/')
    if not rel.startswith('gamedata/'):
        raise ValueError('%s is not under gamedata/' % rel)
    return rel[len('gamedata/'):].replace('/', '\\')


def write_archive(dest, files, on_file=None, stop=None):
    """Write one archive at dest from files: [(rel under gamedata/, source path)].
    Written to dest + '.part', then renamed. Returns its size."""
    tmp = dest + '.part'
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    hdr = HEADER.encode('latin-1')
    table = bytearray()
    dirs = set()
    for rel, _ in files:
        parts = archive_name(rel).split('\\')[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add('\\'.join(parts[:i]) + '\\')
    for d in sorted(dirs):
        b = d.encode('latin-1')
        table += struct.pack('<HIII', 16 + len(b), 0, 0, 0) + b + struct.pack('<I', 0)
    with open(tmp, 'wb') as out:
        out.write(struct.pack('<II', HEADER_CHUNK, len(hdr)) + hdr)
        data_at = out.tell()
        out.write(struct.pack('<II', DATA_CHUNK, 0))           # its size is filled in below
        for rel, src in files:
            if stop is not None and stop():
                out.close()
                os.remove(tmp)
                return None
            with open(src, 'rb') as f:
                b = f.read()
            off = out.tell()
            if off + len(b) > 0xFFFFFFFF:
                raise BadArchive('archive over 4 GB')
            out.write(b)
            name = archive_name(rel).encode('latin-1')
            crc = zlib.crc32(b) & 0xFFFFFFFF
            table += struct.pack('<HIII', 16 + len(name), len(b), len(b), crc) + name + struct.pack('<I', off)
            if on_file is not None:
                on_file(rel, len(b))
        end = out.tell()
        out.seek(data_at)
        out.write(struct.pack('<II', DATA_CHUNK, end - data_at - 8))
        out.seek(end)
        packed = encode(bytes(table))
        out.write(struct.pack('<II', TABLE_CHUNK | COMPRESSED, len(packed)) + packed)
        size = out.tell()
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, dest)
    return size


def plan_archives(files, limit=LIMIT):
    """Split [(rel, source, size)] (in order) into lists for archives of at most limit bytes."""
    groups, cur, cur_size = [], [], 0
    for rel, src, size in files:
        if cur and cur_size + size > limit:
            groups.append(cur)
            cur, cur_size = [], 0
        cur.append((rel, src))
        cur_size += size
    if cur:
        groups.append(cur)
    return groups
