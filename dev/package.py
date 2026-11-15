#!/usr/bin/env python3
"""
Build the release zip: ~/Desktop/"Umbra Gore & Effects <version>.zip".

  python3 dev/package.py [--out DIR]          build the zip
  python3 dev/package.py --dry-run [--list]   only say what would go in (and what not)

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
"""
import argparse, hashlib, json, os, re, sys, zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
NAME = 'Umbra Gore & Effects'  # the zip's name and its top folder, whatever the repo folder is called
SKIP_DIRS = {'dev', 'tests', 'docs', 'native', '.git', '__pycache__'}
SKIP_TREES = ('tools/zgo_world_assets/', 'tools/zgo_wounds/', 'tools/zgo_fracture/assets/')
REPORTS = ('zgo_bake_report.json', 'zgo_fracture_report.json')
# generated even when a report is missing or half-written (defence in depth)
BAKED = ('gamedata/meshes/actors/', 'gamedata/meshes/monsters/', 'gamedata/meshes/zgo/baked/',
         'gamedata/meshes/zgo/props/fracture/')
FRACTURE_INDEX = 'gamedata/scripts/zgo_props_fracture_index.script'
KIDFX_COPIES = 'tools/zgo_kidfx/kidfx_copies.json'
DEV_NOTES = ('CLAUDE.md',)  # notes for agents working in the repo
# the ready-made setup programs (dev/build_setup/build.sh linux|windows); they must be built
# and match SHA256SUMS.txt before a release
SETUP_DIR = 'tools/zgo_setup/'
SETUP_PROGRAMS = ('Umbra Effects Setup.exe', 'zgo-setup-linux')
OLD_SETUP = ('tools/zgo_setup/ZGO Setup.exe',)  # the Windows program's name before 1.8.0


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
    if fn.startswith('.') or fn.endswith(('.pyc', '.part')):
        return 'dotfile / build leftover'
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


def mb(n):
    return '%.1f MB' % (n / 1e6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.expanduser('~/Desktop'))
    ap.add_argument('--dry-run', action='store_true', help='build nothing, say what would go in')
    ap.add_argument('--list', action='store_true', help='with --dry-run: every file that goes in')
    a = ap.parse_args()
    kept, out = walk()
    problems = setup_problems()
    if a.dry_run:
        for p in problems:
            print('NOT READY: ' + p)
        tops = {}
        for rel, size in kept:
            parts = rel.split('/')
            key = '/'.join(parts[:2]) if parts[0] in ('gamedata', 'tools') and len(parts) > 2 else parts[0]
            n, s = tops.get(key, (0, 0))
            tops[key] = (n + 1, s + size)
        print('Would go in (%d files, %s before compression):' % (len(kept), mb(sum(s for _, s in kept))))
        for k in sorted(tops):
            print('  %-40s %6d files  %10s' % (k, tops[k][0], mb(tops[k][1])))
        if a.list:
            for rel, _ in kept:
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
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, _ in kept:
            z.write(os.path.join(ROOT, rel), NAME + '/' + rel)
    os.replace(tmp, dst)
    print('%s: %d files, %s' % (dst, len(kept), mb(os.path.getsize(dst))))


if __name__ == '__main__':
    main()
