"""
The game's virtual file system, rebuilt offline (read only).

X-Ray (xrCore CLocatorAPI, xray-monolith b86d733f4a) registers files in the
order fsgame.ltx lists its paths, and a later registration of the same name
replaces the earlier one (CLocatorAPI::Register):

  1. the archives (*.db*, *.xdb*) under the $arch_dir...$ entries, in fsgame
     order, each directory sorted by name (Recurse / ProcessOne);
  2. the loose files under $game_data$ (gamedata\\). Under MO2 that folder is
     usvfs' merged view: the game's real gamedata folder, then every enabled
     mod from the bottom of modlist.txt to the top, then MO2's overwrite folder.

Names are case-insensitive (the engine lower-cases them). Every path here is
lower-case with '/' separators, relative to gamedata.

This module only reads the game, MO2 and the mods. The one thing it writes is
the materialised tree in the cache (~/.cache/zgo_shadercheck/tree by default).
"""
import fnmatch
import hashlib
import json
import os
import re
import struct
import sys

sys.dont_write_bytecode = True          # never leave __pycache__ in tools/zgo_baker
HERE = os.path.dirname(os.path.abspath(__file__))
MOD_ROOT = os.path.dirname(os.path.dirname(HERE))
BAKER = os.path.join(MOD_ROOT, 'tools', 'zgo_baker')
if BAKER not in sys.path:
    sys.path.insert(0, BAKER)
import xdb        # noqa: E402  (tools/zgo_baker, read only)
import resolve    # noqa: E402

CACHE = os.environ.get('ZGO_SHADERCHECK_CACHE') or os.path.join(os.path.expanduser('~'), '.cache', 'zgo_shadercheck')
ZGO_LABEL = 'zgo'


# ------------------------------------------------------------------ locations
def _mo2_ini(mo2_root):
    out = {}
    p = os.path.join(mo2_root, 'ModOrganizer.ini')
    if not os.path.isfile(p):
        return out
    with open(p, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = re.match(r'^(\w+)=(.*)$', line.strip())
            if m:
                v = m.group(2)
                b = re.match(r'^@ByteArray\((.*)\)$', v)
                out[m.group(1)] = b.group(1) if b else v
    return out


def _win_to_unix(p):
    p = p.replace('\\\\', '\\')
    m = re.match(r'^[A-Za-z]:\\(.*)$', p)
    if m and p[0] in 'zZ':                 # Wine's Z: is the Unix root
        return '/' + m.group(1).replace('\\', '/')
    return p.replace('\\', '/')


class Paths:
    """Where the game, MO2 and this mod are. Environment overrides:
    ZGO_MO2, ZGO_PROFILE, ZGO_GAME, ZGO_MOD_ROOT."""

    def __init__(self, mo2=None, profile=None, game=None, mod_root=None):
        self.mod_root = os.path.abspath(mod_root or os.environ.get('ZGO_MOD_ROOT') or MOD_ROOT)
        self.mod_name = os.path.basename(self.mod_root)
        self.mo2 = os.path.abspath(mo2 or os.environ.get('ZGO_MO2') or os.path.dirname(os.path.dirname(self.mod_root)))
        ini = _mo2_ini(self.mo2)
        self.profile = profile or os.environ.get('ZGO_PROFILE') or ini.get('selected_profile') or 'Default'
        g = game or os.environ.get('ZGO_GAME') or (_win_to_unix(ini['gamePath']) if 'gamePath' in ini else None)
        self.game = os.path.abspath(g) if g else None
        self.mods_dir = os.path.join(self.mo2, 'mods')
        self.overwrite = os.path.join(self.mo2, 'overwrite')

    def check(self):
        missing = []
        if not os.path.isfile(os.path.join(self.mo2, 'profiles', self.profile, 'modlist.txt')):
            missing.append('MO2 profile %r under %s (set ZGO_MO2 / ZGO_PROFILE)' % (self.profile, self.mo2))
        if not self.game or not os.path.isdir(os.path.join(self.game, 'db')):
            missing.append('game folder with db/ (set ZGO_GAME), got %r' % self.game)
        return missing

    def describe(self):
        return {'mod_root': self.mod_root, 'mo2': self.mo2, 'profile': self.profile, 'game': self.game}


# ------------------------------------------------------------------ archives
class ArchiveIndex:
    """A .db archive's file list without reading the whole archive (the
    texture archives are 500 MB each). Same format as xdb.Archive."""

    def __init__(self, path):
        self.path = path
        self.header = b''
        lst = None
        with open(path, 'rb') as f:
            size = os.fstat(f.fileno()).st_size
            o = 0
            while o + 8 <= size:
                f.seek(o)
                cid, sz = struct.unpack('<II', f.read(8))
                if cid & 0x7FFFFFFF == 1:
                    body = f.read(sz)
                    lst = xdb.lzhuf_decode(body) if cid & 0x80000000 else body
                elif cid == 0x29A:
                    self.header = f.read(sz)
                o += 8 + sz
        if lst is None:
            raise ValueError('no file list in %s' % path)
        self.prefix = self._entry_prefix()
        self.files = {}
        o = 0
        while o < len(lst):
            bs, = struct.unpack_from('<H', lst, o)
            real, comp, crc = struct.unpack_from('<III', lst, o + 2)
            name = lst[o + 14:o + 2 + bs - 4].decode('latin1')
            ptr, = struct.unpack_from('<I', lst, o + 2 + bs - 4)
            o += 2 + bs
            if not real and not comp and name.endswith('\\'):
                continue                        # folder entry
            key = (self.prefix + name).replace('\\', '/').lower()
            self.files[key] = (ptr, real, comp)

    def _entry_prefix(self):
        """Archive names are relative to the header's entry_point; map it to gamedata."""
        txt = self.header.decode('latin1', 'replace')
        m = re.search(r'entry_point\s*=\s*(\S+)', txt)
        ep = (m.group(1) if m else '$fs_root$\\gamedata\\').lower().replace('/', '\\')
        for root in ('$fs_root$\\gamedata\\', '$game_data$\\', '$game_data$'):
            if ep.startswith(root):
                rest = ep[len(root):].strip('\\')
                return rest + '\\' if rest else ''
        aliases = {'$game_shaders$': 'shaders', '$game_particles$': 'particles', '$game_config$': 'configs',
                   '$game_scripts$': 'scripts', '$game_meshes$': 'meshes', '$game_textures$': 'textures',
                   '$game_levels$': 'levels', '$game_sounds$': 'sounds'}
        for a, d in aliases.items():
            if ep.startswith(a):
                rest = ep[len(a):].strip('\\')
                return d + '\\' + (rest + '\\' if rest else '')
        return '\x00unmapped\\'               # entry point outside gamedata: never matches

    def read(self, key):
        ptr, real, comp = self.files[key]
        with open(self.path, 'rb') as f:
            f.seek(ptr)
            raw = f.read(comp)
        return raw if real == comp else xdb.lzo1x_decompress(raw, real)


def _fsgame_archive_dirs(game):
    """[(dir, recursive)] for every fsgame.ltx path under db\\, in file order."""
    ltx = os.path.join(game, 'fsgame.ltx')
    roots = {'$fs_root$': game}
    out = []
    if not os.path.isfile(ltx):
        return [(os.path.join(game, 'db'), False)]
    with open(ltx, encoding='latin1') as f:
        for line in f:
            line = line.split(';', 1)[0].strip()
            if '=' not in line:
                continue
            pid, rest = [x.strip() for x in line.split('=', 1)]
            parts = [x.strip() for x in rest.split('|')]
            if len(parts) < 3:
                continue
            rec = parts[0].lower() in ('true', 'on', 'yes', '1')
            base = roots.get(parts[2].lower(), parts[2])
            add = parts[3] if len(parts) > 3 else ''
            path = os.path.join(base, *[x for x in add.replace('\\', '/').split('/') if x])
            roots[pid.lower()] = path
            if pid.lower().startswith('$arch_dir'):
                out.append((path, rec))
    return out


def _archives_in(d, recursive, seen):
    """ProcessOne order: entries sorted by name, sub-folders entered in place."""
    if not os.path.isdir(d) or os.path.exists(os.path.join(d, '.xrignore')):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isdir(p):
            if recursive:
                out += _archives_in(p, True, seen)
        else:
            ext = os.path.splitext(n)[1].lower()
            if (ext.startswith('.db') or ext.startswith('.xdb')) and p not in seen:
                seen.add(p)
                out.append(p)
    return out


# ------------------------------------------------------------------ layers
class Layer:
    """One source of files: an archive or a gamedata folder."""

    def __init__(self, label, kind, path, mo2_index=None):
        self.label = label          # 'base:shaders.db0', 'game:gamedata', 'mod:<name>', 'overwrite', 'zgo'
        self.kind = kind            # 'archive' | 'dir'
        self.path = path            # archive file, or the folder that holds gamedata's contents
        self.mo2_index = mo2_index  # modlist.txt position (0 = top = highest), mods only
        self._arch = None
        self._dir_index = None

    def archive(self):
        if self._arch is None:
            self._arch = ArchiveIndex(self.path)
        return self._arch

    def files(self, prefixes):
        """{relpath: source} for files under any of the prefixes ('shaders/', ...)."""
        if self.kind == 'archive':
            a = self.archive()
            return {k: k for k in a.files if k.startswith(prefixes)}
        out = {}
        for pre in prefixes:
            top = _ci_join(self.path, pre.rstrip('/'))
            if not top:
                continue
            if os.path.isfile(top):                     # a single file ('shaders.xr')
                out[pre.rstrip('/').lower()] = top
                continue
            for dp, dns, fns in os.walk(top):
                dns.sort()
                for fn in sorted(fns):
                    full = os.path.join(dp, fn)
                    rel = os.path.relpath(full, self.path).replace(os.sep, '/').lower()
                    out.setdefault(rel, full)
        return out

    def read(self, src):
        if self.kind == 'archive':
            return self.archive().read(src)
        with open(src, 'rb') as f:
            return f.read()

    def describe(self):
        if self.kind == 'archive':
            return '%s (%s)' % (self.label, os.path.relpath(self.path, os.path.dirname(os.path.dirname(self.path))))
        return self.label if self.mo2_index is None else '%s [MO2 #%d]' % (self.label, self.mo2_index)


def _ci_join(root, rel):
    """Case-insensitive path join (mods ship 'Gamedata/Shaders' and the like)."""
    cur = root
    for part in [p for p in rel.split('/') if p]:
        if not os.path.isdir(cur):
            return None
        hit = None
        for n in os.listdir(cur):
            if n.lower() == part.lower():
                hit = n
                break
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur


def layers(paths, zgo_on_top=True, include_zgo=True):
    """Every source in registration order (the last one wins)."""
    out = []
    seen = set()
    for d, rec in _fsgame_archive_dirs(paths.game):
        for a in _archives_in(d, rec, seen):
            out.append(Layer('base:' + os.path.basename(a), 'archive', a))
    gd = _ci_join(paths.game, 'gamedata')
    if gd:
        out.append(Layer('game:gamedata', 'dir', gd))
    mods = resolve.enabled_mods(paths.mo2, paths.profile)       # top = highest priority
    zgo_index = None
    for i in range(len(mods) - 1, -1, -1):
        name = mods[i]
        if name == paths.mod_name:
            zgo_index = i
            if not zgo_on_top and include_zgo:
                g = _ci_join(paths.mod_root, 'gamedata')
                if g:
                    out.append(Layer(ZGO_LABEL, 'dir', g, i))
            continue
        g = _ci_join(os.path.join(paths.mods_dir, name), 'gamedata')
        if g:
            out.append(Layer('mod:' + name, 'dir', g, i))
    g = _ci_join(paths.overwrite, 'gamedata')
    if g:
        out.append(Layer('overwrite', 'dir', g))
    if zgo_on_top and include_zgo:
        g = _ci_join(paths.mod_root, 'gamedata')
        if g:
            out.append(Layer(ZGO_LABEL, 'dir', g, zgo_index))
    return out


class Resolved:
    """Every relpath under the prefixes with its chain of providers."""

    def __init__(self, paths, prefixes=('shaders/',), zgo_on_top=True, include_zgo=True):
        self.paths = paths
        self.prefixes = tuple(p.lower() for p in prefixes)
        self.layers = layers(paths, zgo_on_top, include_zgo)
        self.chain = {}                 # relpath -> [(layer, src)], lowest first
        for L in self.layers:
            for rel, src in L.files(self.prefixes).items():
                self.chain.setdefault(rel, []).append((L, src))

    def winner(self, rel):
        c = self.chain.get(rel.lower())
        return c[-1] if c else None

    def read(self, rel):
        w = self.winner(rel)
        if not w:
            raise KeyError(rel)
        return w[0].read(w[1])

    def names(self, pattern='*'):
        return sorted(r for r in self.chain if fnmatch.fnmatch(r, pattern))

    def game_winner(self, rel):
        """The provider the game really loads: ZGO at its own MO2 position,
        not on top. Only differs from winner() for ZGO files."""
        c = self.chain.get(rel.lower()) or []
        zgo = [x for x in c if x[0].label == ZGO_LABEL]
        if not zgo:
            return c[-1] if c else None
        above = self.above_zgo(rel)
        return above[-1] if above else zgo[0]

    def below_zgo(self, rel):
        """The provider ZGO's copy replaces in the game (None for a new file)."""
        c = self.chain.get(rel.lower()) or []
        above = set(id(x) for x in self.above_zgo(rel))
        rest = [x for x in c if x[0].label != ZGO_LABEL and id(x) not in above]
        return rest[-1] if rest else None

    def above_zgo(self, rel):
        """Providers the game ranks above ZGO (MO2 overwrite, mods higher in
        modlist.txt), lowest first: in the game these beat ZGO's copy."""
        c = self.chain.get(rel.lower()) or []
        zgo = [x for x in c if x[0].label == ZGO_LABEL]
        if not zgo or zgo[0][0].mo2_index is None:
            return [x for x in c if x[0].label == 'overwrite']
        zi = zgo[0][0].mo2_index
        return [x for x in c if x[0].label == 'overwrite' or (
            x[0].label.startswith('mod:') and x[0].mo2_index is not None and x[0].mo2_index < zi)]


# ------------------------------------------------------------------ materialise
INCLUDE_RE = re.compile(rb'^[ \t]*#[ \t]*include[ \t]*["<]([^">]+)[">]', re.M)


def materialize(res, dest=None, prefix='shaders/'):
    """Write the winning file of every path under prefix into dest (the
    gamedata-relative layout, lower-case). Only changed files are rewritten;
    stale ones are removed. Mixed-case #include names get a symlink so
    case-sensitive tools (vkd3d-compiler) find them. Returns dest."""
    dest = dest or os.path.join(CACHE, 'tree')
    os.makedirs(dest, exist_ok=True)
    want = {}
    manifest = {}
    for rel, chain in res.chain.items():
        if not rel.startswith(prefix):
            continue
        L, src = chain[-1]
        data = L.read(src)
        want[rel] = data
        manifest[rel] = {
            'winner': L.label,
            'chain': [x[0].label for x in chain],
            'sha1': hashlib.sha1(data).hexdigest(),
        }
    # write
    for rel, data in want.items():
        p = os.path.join(dest, *rel.split('/'))
        if os.path.islink(p):
            os.unlink(p)
        try:
            with open(p, 'rb') as f:
                if f.read() == data:
                    continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.part'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
    # remove stale files (keep the manifest)
    keep = {os.path.join(dest, *r.split('/')) for r in want}
    for dp, dns, fns in os.walk(os.path.join(dest, *prefix.strip('/').split('/')), topdown=False):
        for fn in fns:
            p = os.path.join(dp, fn)
            if p not in keep:
                os.unlink(p)
        for dn in dns:
            q = os.path.join(dp, dn)
            if os.path.isdir(q) and not os.path.islink(q) and not os.listdir(q):
                os.rmdir(q)
    # case aliases for #include names
    aliases = 0
    lower = set(want)
    for rel, data in want.items():
        for m in INCLUDE_RE.finditer(data):
            inc = m.group(1).decode('latin1').replace('\\', '/')
            for base in (prefix + 'r3/', prefix):
                cand = (base + inc).lower()
                if cand in lower:
                    if inc != inc.lower():
                        ap = os.path.join(dest, *(base + inc).split('/'))
                        if not os.path.lexists(ap):
                            os.makedirs(os.path.dirname(ap), exist_ok=True)
                            os.symlink(os.path.join(dest, *cand.split('/')), ap)
                            aliases += 1
                    break
    with open(os.path.join(dest, '.manifest.json'), 'w') as f:
        json.dump({'paths': res.paths.describe(),
                   'layers': [L.describe() for L in res.layers],
                   'files': manifest}, f, indent=0, sort_keys=True)
    return dest


if __name__ == '__main__':
    P = Paths()
    bad = P.check()
    if bad:
        sys.exit('\n'.join(bad))
    R = Resolved(P)
    d = materialize(R)
    print('%d shader files from %d layers -> %s' % (len(R.chain), len(R.layers), d))
