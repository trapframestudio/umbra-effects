#!/usr/bin/env python3
"""
Build the release zip: ~/Desktop/"Umbra Gore & Effects <version>.zip".

  python3 dev/package.py [--out DIR]          build the zip
  python3 dev/package.py --dry-run [--list]   only say what would go in (and what not)

Ships the player's guide and notices at the top (README.md, CHANGELOG.md, CREDITS.txt,
LICENSE-PainterOfTheZone.txt) and refuses without them.

Leaves out what players don't need or must make themselves:
  * dev/ (dev tooling), tests/, docs/, native/ (the add-on's sources; players
    get bin/zgo_native.dll), CLAUDE.md, dotfiles (.git, .gitignore), __pycache__
  * developer-only generators: tools/zgo_world_assets, tools/zgo_wounds,
    tools/zgo_fracture/assets (their output ships, the generators don't)
  * everything a bake wrote on this machine, built per mod list on each
    player's machine by Umbra Effects Setup:
      - the body bake (tools/zgo_baker): files listed in zgo_bake_report.json,
        and in any case gamedata/meshes/actors/, monsters/, zgo/baked/ and
        every generated gamedata/scripts/zgo_bake_*.script (zgo_bake.script,
        the reader, ships)
      - the breakable-objects bake (tools/zgo_fracture): files listed in
        zgo_fracture_report.json, gamedata/meshes/zgo/props/fracture/ and
        zgo_props_fracture_index.script
      - kid mode particle copies of other mods' effects (tools/zgo_kidfx,
        kidfx_copies.json): Umbra Effects Setup makes them from the player's own mods

Packs the mod's own textures into one archive, db/mods/zgo_static.db0, instead of
shipping them loose (docs/formats/static.md): MO2 indexes every loose file at each
game start. Only textures whose names are ours alone go in; the archive is built from
them in sorted order (same files, same bytes), in a temporary folder.

  python3 dev/package.py --check-clashes [--game DIR] [--mods DIR]
      does any other source have a texture the archive holds? (the game's archives
      under DIR/db, and every other mod folder in the MO2 mods folder: loose or in
      its own archives; defaults: $ZGO_GAME, $ZGO_MO2/mods)
"""
import argparse, hashlib, json, os, re, sys, tempfile, zipfile, zlib

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
NAME = 'Umbra Gore & Effects'  # the zip's name and its top folder, whatever the repo folder is called
SKIP_DIRS = {'dev', 'tests', 'docs', 'native', '.git', '__pycache__'}
SKIP_TREES = ('tools/zgo_world_assets/', 'tools/zgo_wounds/', 'tools/zgo_fracture/assets/')
REPORTS = ('zgo_bake_report.json', 'zgo_fracture_report.json')
# generated even when a report is missing or half-written (defence in depth)
BAKED = ('gamedata/meshes/actors/', 'gamedata/meshes/monsters/', 'gamedata/meshes/zgo/baked/',
         'gamedata/meshes/zgo/props/fracture/', 'db/mods/zgo_bake_')     # (the bake's archives, 1.8.2)
FRACTURE_INDEX = 'gamedata/scripts/zgo_props_fracture_index.script'
KIDFX_COPIES = 'tools/zgo_kidfx/kidfx_copies.json'
DEV_NOTES = ('CLAUDE.md',)  # notes for agents working in the repo
PLAYER_DOCS = ('README.md', 'CHANGELOG.md', 'CREDITS.txt', 'LICENSE-PainterOfTheZone.txt')
# the ready-made setup programs (dev/build_setup/build.sh linux|windows); they must be built
# and match SHA256SUMS.txt before a release
SETUP_DIR = 'tools/zgo_setup/'
SETUP_PROGRAMS = ('Umbra Effects Setup.exe', 'zgo-setup-linux')
OLD_SETUP = ('tools/zgo_setup/ZGO Setup.exe',)  # the Windows program's name before 1.8.0
# The mod's own textures, packed into one archive (docs/formats/static.md). A name goes in
# only when no other source has it: an archived file loses to every loose file of that name,
# and its order against other archives isn't ours to rely on. Our own names are textures\zgo\
# and the wm_blood_zgo_* wallmarks; every other texture we ship overrides the game's or
# another mod's (wm_blood_2, Painter of the Zone's, Cinematic VFX's) and stays loose.
# --check-clashes (and deploy, against the install it deploys into) checks this.
STATIC_ARCHIVE = 'db/mods/zgo_static.db0'
STATIC_PREFIXES = ('gamedata/textures/zgo/', 'gamedata/textures/wm/wm_blood_zgo_')
STATIC_EXT = '.dds'
STATIC_KEEP_LOOSE = ()       # exact paths that match the above but must stay loose (a clash found)
BAKER_DIR = os.path.join(ROOT, 'tools', 'zgo_baker')     # xdb_write.py / xdb.py (read and write archives)


def version():
    """VERSION in zgo_main.script (MO2 writes a date stamp into meta.ini, so not that)."""
    with open(os.path.join(ROOT, 'gamedata', 'scripts', 'zgo_main.script'), encoding='utf-8') as f:
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
    if not m:
        sys.exit('no VERSION in gamedata/scripts/zgo_main.script')
    return m.group(1)


def setup_problems():
    """Why the setup programs aren't fit to ship ([] when they are)."""
    sums_path = os.path.join(ROOT, SETUP_DIR, 'SHA256SUMS.txt')
    try:
        sums = {}
        with open(sums_path, encoding='utf-8') as f:
            for line in f:
                # sha256sum's format: the hash, a space, ' ' or '*', then the name (which may hold spaces)
                m = re.match(r'([0-9a-fA-F]{64}) [ *](.+)$', line.rstrip('\r\n'))
                if m:
                    sums[m.group(2)] = m.group(1).lower()
    except OSError:
        return ['%sSHA256SUMS.txt is missing: build with dev/build_setup/build.sh linux and windows' % SETUP_DIR]
    out = []
    for name in SETUP_PROGRAMS:
        p = os.path.join(ROOT, SETUP_DIR, name)
        if not os.path.isfile(p):
            out.append('%s%s is missing: build it with dev/build_setup/build.sh' % (SETUP_DIR, name))
        elif name not in sums:
            out.append('%s%s is not in SHA256SUMS.txt' % (SETUP_DIR, name))
        else:
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for b in iter(lambda: f.read(1 << 20), b''):
                    h.update(b)
            if h.hexdigest() != sums[name]:
                out.append('%s%s does not match SHA256SUMS.txt (rebuild it)' % (SETUP_DIR, name))
    for name in sorted(set(sums) - set(SETUP_PROGRAMS)):
        out.append('SHA256SUMS.txt lists %s, which is not shipped (rebuild with build.sh)' % name)
    return out


def generated():
    """Paths a bake on this machine wrote (from the reports)."""
    out = set(REPORTS)
    for rep in REPORTS:
        try:
            with open(os.path.join(ROOT, rep)) as f:
                out |= {p.replace('\\', '/') for p in json.load(f).get('files', [])}
        except (OSError, ValueError):
            pass
    return out


def kidfx_copies():
    """The other mods' particle files kidfx copied (gamedata/particles/<rel>)."""
    try:
        with open(os.path.join(ROOT, KIDFX_COPIES)) as f:
            return {'gamedata/particles/' + r.replace('\\', '/') for r in json.load(f).get('copies', {})}
    except (OSError, ValueError):
        return set()


def why_not(rel, fn, gen, copies):
    """Why rel stays out of the zip, or None."""
    if any(part.startswith('.') for part in rel.split('/')) or fn.endswith(('.pyc', '.part')):
        return 'dotfile / build leftover'     # (also what is in a dot-folder: .github/)
    if rel in DEV_NOTES:
        return 'dev notes'
    if rel.startswith(SKIP_TREES):
        return 'developer generator'
    if rel in REPORTS:
        return 'bake report'
    if rel in gen or rel.startswith(BAKED):
        return 'baked on this machine'
    if rel.startswith('gamedata/scripts/zgo_bake_') and rel.endswith('.script'):
        return 'baked on this machine'
    if rel == FRACTURE_INDEX:
        return 'baked on this machine'
    if rel in copies:
        return "copy of another mod's file (made by Umbra Effects Setup)"
    if rel in OLD_SETUP:
        return 'setup program under its old name'
    if rel == STATIC_ARCHIVE:
        return 'built from the textures at package time'
    return None


def walk():
    """(kept [(rel, size)], left out {reason: [(rel, size)]})."""
    gen, copies = generated(), kidfx_copies()
    kept, out = [], {}
    for dp, dns, fns in os.walk(ROOT):
        rel_dir = os.path.relpath(dp, ROOT).replace(os.sep, '/')
        if rel_dir.split('/')[0] in SKIP_DIRS:
            dns[:] = []
            continue
        for d in sorted(dns):
            if d in SKIP_DIRS:
                rd = d if rel_dir == '.' else rel_dir + '/' + d
                size = sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(os.path.join(dp, d)) for f in fs)
                out.setdefault('dev / tests / docs / native sources', []).append((rd + '/', size))
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            rel = fn if rel_dir == '.' else rel_dir + '/' + fn
            size = os.path.getsize(os.path.join(dp, fn))
            r = why_not(rel, fn, gen, copies)
            if r:
                out.setdefault(r, []).append((rel, size))
            else:
                kept.append((rel, size))
    return kept, out


def is_static(rel):
    """Does this shipped file go into the archive instead of the mod folder?"""
    return (rel.startswith(STATIC_PREFIXES) and rel.lower().endswith(STATIC_EXT)
            and rel not in STATIC_KEEP_LOOSE)


def split_static(kept):
    """walk()'s kept files -> (the loose ones, the archive's [(rel, size)] sorted by rel)."""
    loose = [(rel, size) for rel, size in kept if not is_static(rel)]
    return loose, sorted((rel, size) for rel, size in kept if is_static(rel))


def release():
    """(loose [(rel, size)], archived [(rel, size)], left out {reason: [(rel, size)]})."""
    kept, out = walk()
    loose, static = split_static(kept)
    return loose, static, out


def _xdb():
    """tools/zgo_baker's archive modules (read only; no __pycache__ left there)."""
    if BAKER_DIR not in sys.path:
        sys.path.insert(0, BAKER_DIR)
    was, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        import xdb_write
    finally:
        sys.dont_write_bytecode = was
    return xdb_write


def build_static(dest, static, root=ROOT):
    """Write the archive at dest (atomically: dest.part, then renamed) from [(rel, size)], in
    sorted order: the same files give the same bytes. Returns its size."""
    xw = _xdb()
    total = sum(size for _, size in static)
    if total > xw.LIMIT:
        sys.exit('package: %s would hold %s, over the %s an archive may have; split it'
                 % (STATIC_ARCHIVE, mb(total), mb(xw.LIMIT)))
    return xw.write_archive(dest, [(rel, os.path.join(root, rel)) for rel, _ in sorted(static)])


def static_matches(path, static, root=ROOT):
    """Is the archive at path exactly what build_static would write? (its header, and each
    file's name, size and CRC in order; the writer is deterministic, so the bytes are too)"""
    xw = _xdb()
    try:
        header, entries = xw.read_table(path)
    except (OSError, xw.BadArchive, ValueError):
        return False
    if header != xw.HEADER:
        return False
    have = [(name, real, comp, crc) for name, _, real, comp, crc in entries if not name.endswith('\\')]
    want = []
    for rel, _ in sorted(static):
        with open(os.path.join(root, rel), 'rb') as f:
            b = f.read()
        want.append((xw.archive_name(rel), len(b), len(b), zlib.crc32(b) & 0xFFFFFFFF))
    return have == want


# ---------------------------------------------------------------- clash check

def _entry_prefix(header):
    """An archive's entry_point as a gamedata-relative prefix ('' or 'textures/'), or None when
    it mounts outside gamedata (as tools/zgo_kidfx/sc_tree.py reads it)."""
    m = re.search(r'entry_point\s*=\s*(\S+)', header or '')
    ep = (m.group(1) if m else '$fs_root$\\gamedata\\').lower().replace('/', '\\')
    for base in ('$fs_root$\\gamedata\\', '$game_data$\\', '$game_data$'):
        if ep.startswith(base):
            rest = ep[len(base):].strip('\\')
            return rest.replace('\\', '/') + '/' if rest else ''
    for alias, d in (('$game_textures$', 'textures'), ('$game_meshes$', 'meshes'), ('$game_particles$', 'particles'),
                     ('$game_shaders$', 'shaders'), ('$game_config$', 'configs'), ('$game_scripts$', 'scripts'),
                     ('$game_sounds$', 'sounds'), ('$game_levels$', 'levels')):
        if ep.startswith(alias):
            rest = ep[len(alias):].strip('\\')
            return d + '/' + (rest.replace('\\', '/') + '/' if rest else '')
    return None


def _archives(folder):
    for dp, dns, fns in os.walk(folder):
        dns.sort()
        for fn in sorted(fns):
            if re.search(r'\.x?db[^.]*$', fn, re.I):
                yield os.path.join(dp, fn)


def clashes(rels, game, mods, skip_zgo=True):
    """{rel: [who else has it]} for rels (gamedata/...): the game (its archives under game/db
    and its loose game/gamedata), and in the MO2 mods folder every other mod (its loose
    gamedata files and its own archives) plus MO2's overwrite folder. Folders holding this mod
    (its zgo_main.script) are ours, not another source. Names compare without case, as the
    engine's do. An archive that can't be read counts as a clash for everything."""
    xw = _xdb()
    want = {r[len('gamedata/'):].lower(): r for r in rels}
    tops = {k.split('/')[0] for k in want}
    found = {}

    def hit(key, who):
        if key in want:
            found.setdefault(want[key], []).append(who)

    def loose(gd, who):
        try:
            subs = [d for d in os.listdir(gd) if d.lower() in tops]
        except OSError:
            return
        for sub in subs:
            for dp, _, fns in os.walk(os.path.join(gd, sub)):
                for fn in fns:
                    hit(os.path.relpath(os.path.join(dp, fn), gd).replace(os.sep, '/').lower(), who)

    def archive(path, who):
        try:
            header, entries = xw.read_table(path)
        except (OSError, xw.BadArchive, ValueError) as e:
            for r in rels:
                found.setdefault(r, []).append('%s (unreadable: %s)' % (who, e))
            return
        pre = _entry_prefix(header)
        if pre is None:
            return
        for name, *_ in entries:
            hit(pre + name.lower().replace('\\', '/'), who)

    if game:
        for p in _archives(os.path.join(game, 'db')):
            archive(p, 'game: ' + os.path.relpath(p, game))
        loose(os.path.join(game, 'gamedata'), 'game: gamedata')
    folders = []
    if mods and os.path.isdir(mods):
        folders = [('mod: ' + m, os.path.join(mods, m)) for m in sorted(os.listdir(mods))]
        folders.append(('MO2 overwrite', os.path.join(os.path.dirname(os.path.abspath(mods)), 'overwrite')))
    for name, folder in folders:
        gd = os.path.join(folder, 'gamedata')
        if not os.path.isdir(folder) or (skip_zgo and os.path.isfile(os.path.join(gd, 'scripts', 'zgo_main.script'))):
            continue
        loose(gd, name)
        for p in _archives(os.path.join(folder, 'db')):
            archive(p, '%s (%s)' % (name, os.path.relpath(p, folder)))
    return found


def mb(n):
    return '%.1f MB' % (n / 1e6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.expanduser('~/Desktop'))
    ap.add_argument('--dry-run', action='store_true', help='build nothing, say what would go in')
    ap.add_argument('--list', action='store_true', help='with --dry-run: every file that goes in')
    ap.add_argument('--check-clashes', action='store_true',
                    help="does the game or another mod have a texture the archive holds?")
    ap.add_argument('--game', default=os.environ.get('ZGO_GAME'), help='with --check-clashes: the game folder (holds db/)')
    ap.add_argument('--mods', default=os.path.join(os.environ['ZGO_MO2'], 'mods') if os.environ.get('ZGO_MO2') else None,
                    help="with --check-clashes: MO2's mods folder")
    a = ap.parse_args()
    loose, static, out = release()
    if a.check_clashes:
        if not (a.game and a.mods):
            sys.exit('package: --check-clashes needs --game and --mods (or ZGO_GAME and ZGO_MO2)')
        found = clashes([rel for rel, _ in static], a.game, a.mods)
        print('%s: %d textures checked against %s and %s' % (STATIC_ARCHIVE, len(static), a.game, a.mods))
        for rel in sorted(found):
            print('  CLASH %s: %s' % (rel, ', '.join(found[rel][:3])))
        if found:
            sys.exit('package: %d textures must stay loose: add them to STATIC_KEEP_LOOSE' % len(found))
        print('  none: no other source has any of them')
        return
    problems = setup_problems()
    shipped = {rel for rel, _ in loose}
    problems += ['%s is missing (the zip must hold it)' % d for d in PLAYER_DOCS if d not in shipped]
    zipped = loose + ([(STATIC_ARCHIVE, sum(s for _, s in static))] if static else [])
    if a.dry_run:
        for p in problems:
            print('NOT READY: ' + p)
        tops = {}
        for rel, size in zipped:
            parts = rel.split('/')
            key = '/'.join(parts[:2]) if parts[0] in ('gamedata', 'tools', 'db') and len(parts) > 2 else parts[0]
            n, s = tops.get(key, (0, 0))
            tops[key] = (n + 1, s + size)
        print('Would go in (%d files, %s before compression):' % (len(zipped), mb(sum(s for _, s in zipped))))
        for k in sorted(tops):
            print('  %-40s %6d files  %10s' % (k, tops[k][0], mb(tops[k][1])))
        if static:
            print('  (%s: an archive of %d textures, not loose files; docs/formats/static.md)'
                  % (STATIC_ARCHIVE, len(static)))
        if a.list:
            for rel, _ in zipped:
                print('    ' + rel)
        print('Left out:')
        for r in sorted(out):
            items = out[r]
            print('  %-45s %6d entries %10s' % (r, len(items), mb(sum(s for _, s in items))))
            for rel, _ in items[:6]:
                print('      ' + rel)
            if len(items) > 6:
                print('      ... %d more' % (len(items) - 6))
        return
    if problems:
        sys.exit('package: ' + '; '.join(problems))
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, '%s %s.zip' % (NAME, version()))
    tmp = dst + '.part'
    with tempfile.TemporaryDirectory(prefix='zgo_static_') as work:
        arch = os.path.join(work, os.path.basename(STATIC_ARCHIVE))
        if static:
            build_static(arch, static)
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel, _ in loose:
                z.write(os.path.join(ROOT, rel), NAME + '/' + rel)
            if static:
                z.write(arch, NAME + '/' + STATIC_ARCHIVE)
    os.replace(tmp, dst)
    print('%s: %d files (%d textures in %s), %s' % (dst, len(zipped), len(static), STATIC_ARCHIVE,
                                                   mb(os.path.getsize(dst))))


if __name__ == '__main__':
    main()
