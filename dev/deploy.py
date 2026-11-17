#!/usr/bin/env python3
"""
Deploy the mod from this repo into the MO2 mod folder the game loads.

  python3 dev/deploy.py --dry-run     say what would change, change nothing
  python3 dev/deploy.py               copy new and changed files
  python3 dev/deploy.py --to DIR      another mod folder (or set ZGO_MOD_DIR)

Edit here and deploy; never edit the live folder. (Installing a release zip
through MO2 under the same mod name once replaced the dev folder outright, and
the dev tree was lost. The repo lives outside mods/ so that can't happen again.)

What it copies: the same files dev/package.py puts in the release zip.

What it never touches in the mod folder:
  * anything a bake on that machine wrote: the files listed in its
    zgo_bake_report.json and zgo_fracture_report.json, the reports themselves,
    and the baked folders and index scripts (in case a report is missing);
  * kid mode's per-player state: the particle copies listed in its
    tools/zgo_kidfx/kidfx_copies.json, that file, and kidfx_snapshot.txt
    (both rewritten by Umbra Effects Setup for that mod list);
  * meta.ini (MO2's file).

The mod's own textures go in as one archive, db/mods/zgo_static.db0 (dev/package.py
builds it; docs/formats/static.md), not as loose files. Before writing it, deploy checks
that nothing else in that MO2 install (the game's archives and gamedata, the other mods,
overwrite) has a texture of the same name, and refuses if something does.
The only files it deletes are the loose copies of those textures that an earlier deploy
put in the mod folder (a loose file would win over the archive's), after the archive is
written. Other files in the mod folder that the repo no longer has are listed so you can
remove them yourself.

It refuses to run while the game, Umbra Effects Setup, the baker or kidfx is running. A game
started from another install (its exe and -fsltx outside this MO2 and its game folder, as
test harnesses run them) doesn't count; one that links into this mod folder must be closed
by hand.
"""
import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package  # noqa: E402  (the release file list)

ROOT = package.ROOT
# the Umbra install kept for development (Umbra's pack is built from it); a release-test
# install or a plain G.A.M.M.A. takes --to
DEFAULT_TO = os.path.join('~', 'development', 'umbra-dev', 'gamma', 'mods', 'Umbra Gore & Effects')
MARKER = 'gamedata/scripts/zgo_main.script'
KIDFX_STATE = ('tools/zgo_kidfx/kidfx_copies.json', 'tools/zgo_kidfx/kidfx_snapshot.txt')
# Umbra Effects Setup programs: build output (dev/build_setup/build.sh), not in a fresh checkout,
# so their absence from the repo doesn't make the mod folder's copies stale
SETUP_BUILDS = ('tools/zgo_setup/Umbra Effects Setup.exe', 'tools/zgo_setup/zgo-setup-linux', 'tools/zgo_setup/SHA256SUMS.txt')
MO2_OWNED = ('meta.ini',)
BUSY = re.compile(r'anomalydx[0-9a-z]*\.exe|xrengine\.exe|zgo_baker[/\\]bake\.py|zgo_fracture'
                  r'|kidfx_pe\.py|zgo[-_ ]setup|umbra effects setup', re.I)


GAME = re.compile(r'anomalydx[0-9a-z]*\.exe|xrengine\.exe', re.I)
GAME_PATH = re.compile(r'''[^\s'";|&<>()]*(?:anomalydx[0-9a-z]*\.exe|xrengine\.exe)''', re.I)


def _unix(p, cwd=None):
    """A path as a command line names it (Wine's Z:\\..., or Unix), resolved; a relative one
    against cwd; None when it can't be placed."""
    p = p.strip('"\'')
    if re.match(r'^[zZ]:\\', p):
        p = '/' + p[3:]
    elif re.match(r'^[A-Za-z]:\\', p):
        return None
    p = p.replace('\\', '/')
    if not p.startswith('/'):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def install_roots(dst):
    """The MO2 folder holding the mod folder, and its game folder (ModOrganizer.ini gamePath)."""
    mo2 = os.path.dirname(os.path.dirname(dst))
    roots = [mo2]
    try:
        with open(os.path.join(mo2, 'ModOrganizer.ini'), encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re.match(r'^gamePath=(?:@ByteArray\()?(.*?)\)?\s*$', line.strip())
                if m:
                    g = _unix(m.group(1).replace('\\\\', '\\'))
                    if g:
                        roots.append(g)
    except OSError:
        pass
    return [os.path.realpath(r) for r in roots]


def _inside(p, roots):
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def busy(dst=None):
    """Names of running programs that must not see the mod folder change. A game whose exe and
    -fsltx are both outside dst's install (another install, a test harness) is left out."""
    found = set()
    roots = install_roots(dst) if dst else None
    if os.path.isdir('/proc'):
        me = {str(os.getpid()), str(os.getppid())}
        for pid in os.listdir('/proc'):
            if not pid.isdigit() or pid in me:
                continue
            try:
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    args = [a.decode('utf-8', 'replace') for a in f.read().split(b'\0') if a]
            except OSError:
                continue
            cmd = ' '.join(args)
            if 'dev/deploy.py' in cmd or 'dev\\deploy.py' in cmd:
                continue
            m = BUSY.search(cmd)
            if not m:
                continue
            if roots and GAME.fullmatch(m.group(0)):
                # the game, or what starts it (a launcher script): every exe or -fsltx it names
                try:
                    cwd = os.readlink('/proc/%s/cwd' % pid)
                except OSError:
                    cwd = None
                named = [x for a in args for x in GAME_PATH.findall(a)]
                named += [args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() == '-fsltx']
                paths = [_unix(a, cwd) for a in named]
                if paths and all(paths) and not any(_inside(p, roots) for p in paths):
                    continue                    # another install's game
            found.add(m.group(0))
    elif os.name == 'nt':
        out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = BUSY.search(line.split(',')[0])
            if m:
                found.add(m.group(0))
    return sorted(found)


def protected(dst):
    """Paths (relative, '/') in the mod folder that deploy must leave alone."""
    out = set(package.REPORTS) | set(KIDFX_STATE) | set(MO2_OWNED)
    for rep in package.REPORTS:
        try:
            with open(os.path.join(dst, rep)) as f:
                out |= {p.replace('\\', '/') for p in json.load(f).get('files', [])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            sys.exit('deploy: %s in %s is unreadable (%s); fix or remove it first' % (rep, dst, e))
    try:
        with open(os.path.join(dst, package.KIDFX_COPIES)) as f:
            out |= {'gamedata/particles/' + r.replace('\\', '/') for r in json.load(f).get('copies', {})}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        sys.exit('deploy: %s in %s is unreadable (%s); fix or remove it first' % (package.KIDFX_COPIES, dst, e))
    return out


def is_protected(rel, prot):
    return (rel in prot or rel.startswith(package.BAKED) or rel == package.FRACTURE_INDEX
            or (rel.startswith('gamedata/scripts/zgo_bake_') and rel.endswith('.script')))


def plan(dst):
    """(new, changed, unchanged count, left alone, only in the mod folder, loose copies to remove).
    The archive (package.STATIC_ARCHIVE) counts as one file of new or changed."""
    loose, static, _ = package.release()
    prot = protected(dst)
    new, changed, same, kept_live = [], [], 0, []
    for rel, size in loose:
        if is_protected(rel, prot):
            kept_live.append(rel)
            continue
        d = os.path.join(dst, rel)
        if not os.path.exists(d):
            new.append(rel)
        elif os.path.getsize(d) != size or not filecmp.cmp(os.path.join(ROOT, rel), d, shallow=False):
            changed.append(rel)
        else:
            same += 1
    ours = {rel for rel, _ in loose}
    if static:
        ours.add(package.STATIC_ARCHIVE)
        d = os.path.join(dst, package.STATIC_ARCHIVE)
        if not os.path.exists(d):
            new.append(package.STATIC_ARCHIVE)
        elif not package.static_matches(d, static):
            changed.append(package.STATIC_ARCHIVE)
        else:
            same += 1
    archived = {rel for rel, _ in static}
    extra, retire = [], []
    for dp, dns, fns in os.walk(dst):
        dns[:] = [d for d in dns if d != '__pycache__']
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), dst).replace(os.sep, '/')
            if rel in archived and not is_protected(rel, prot):
                retire.append(rel)
            elif (rel not in ours and rel not in SETUP_BUILDS and not is_protected(rel, prot)
                    and not fn.endswith(('.pyc', '.part'))):
                extra.append(rel)
    return new, changed, same, kept_live, sorted(extra), sorted(retire)


def static_clashes(dst, static):
    """({archived rel: [who else has it]}, the game folder) in the MO2 install holding dst;
    (None, None) when dst isn't in one (no ModOrganizer.ini two folders up)."""
    roots = install_roots(dst)
    if not os.path.isfile(os.path.join(roots[0], 'ModOrganizer.ini')):
        return None, None
    game = roots[1] if len(roots) > 1 and os.path.isdir(os.path.join(roots[1], 'db')) else None
    return package.clashes([rel for rel, _ in static], game, os.path.dirname(dst)), game


def remove_loose(rels, dst):
    """Delete the mod folder's loose copies of archived textures, and the folders that empties
    (under gamedata/textures only)."""
    stop = os.path.join(dst, 'gamedata', 'textures')
    dirs = set()
    for rel in rels:
        p = os.path.join(dst, rel)
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        dirs.add(os.path.dirname(p))
    for d in sorted(dirs, key=len, reverse=True):
        while d.startswith(stop + os.sep):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


def copy(rel, dst, static=()):
    if rel == package.STATIC_ARCHIVE:
        package.build_static(os.path.join(dst, rel), static)    # (writes .part, then renames)
        return
    s, d = os.path.join(ROOT, rel), os.path.join(dst, rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(s, d + '.part')
    os.replace(d + '.part', d)


def show(title, items, limit=12):
    print('%s: %d' % (title, len(items)))
    for rel in items[:limit]:
        print('    ' + rel)
    if len(items) > limit:
        print('    ... %d more' % (len(items) - limit))


def main():
    ap = argparse.ArgumentParser(description='Deploy ZGO from this repo into an MO2 mod folder.')
    ap.add_argument('--to', default=os.environ.get('ZGO_MOD_DIR', DEFAULT_TO), help='mod folder (default: %(default)s)')
    ap.add_argument('--dry-run', action='store_true', help='say what would change, change nothing')
    a = ap.parse_args()
    dst = os.path.realpath(os.path.expanduser(a.to))
    if not os.path.isfile(os.path.join(dst, MARKER)):
        sys.exit("deploy: %s isn't a ZGO mod folder (no %s); pass --to" % (dst, MARKER))
    root = os.path.realpath(ROOT)
    if dst == root or dst.startswith(root + os.sep) or root.startswith(dst + os.sep):
        sys.exit('deploy: the mod folder and the repo overlap (%s)' % dst)
    if os.path.exists(os.path.join(dst, '.git')):
        sys.exit('deploy: %s is a git repo; deploy goes from the repo into a mod folder, not into another repo' % dst)
    running = busy(dst)
    if running and not a.dry_run:
        sys.exit('deploy: close these first: %s' % ', '.join(running))

    new, changed, same, kept_live, extra, retire = plan(dst)
    _, static, _ = package.release()
    found, game = static_clashes(dst, static) if static else ({}, None)
    print('deploy %s -> %s%s' % (root, dst, ' (dry run)' if a.dry_run else ''))
    if running:
        print('note: running now: %s (a real deploy would refuse)' % ', '.join(running))
    show('new', new)
    show('changed', changed)
    print('unchanged: %d' % same)
    if static:
        st = 'new' if package.STATIC_ARCHIVE in new else 'changed' if package.STATIC_ARCHIVE in changed else 'unchanged'
        print('archive %s: %s (%d textures, %s; they are not copied loose)'
              % (package.STATIC_ARCHIVE, st, len(static), package.mb(sum(s for _, s in static))))
        if found is None:
            print('    (not in an MO2 install: no check that other sources lack these textures)')
        elif game is None:
            print("    (the game folder isn't known: only the other mods were checked for these textures)")
    if retire:
        show('remove (loose copies of textures now in the archive)', retire, 6)
    if kept_live:
        show('left alone (made on that machine)', kept_live, 6)
    if extra:
        show('only in the mod folder (not in the repo; remove by hand if stale)', extra)
    if found:
        print('CLASH: %d textures the archive would hold are in other sources too (a loose file of the '
              'same name wins over an archive):' % len(found))
        for rel in sorted(found)[:12]:
            print('    %s: %s' % (rel, ', '.join(found[rel][:3])))
        if not a.dry_run:
            sys.exit('deploy: add them to STATIC_KEEP_LOOSE in dev/package.py (they stay loose), then deploy again')
        print('    (a real deploy would refuse: add them to STATIC_KEEP_LOOSE in dev/package.py)')
    if a.dry_run or not (new or changed or retire):
        if not (new or changed or retire):
            print('nothing to copy')
        return
    for rel in new + changed:
        copy(rel, dst, static)
    print('copied %d file(s)' % (len(new) + len(changed)))
    if retire:
        remove_loose(retire, dst)
        print('removed %d loose texture(s) now in %s' % (len(retire), package.STATIC_ARCHIVE))
    if any(r.startswith('gamedata/particles/') for r in new + changed):
        print('particles changed: run Umbra Effects Setup (or tools/zgo_kidfx/kidfx_pe.py apply in the mod folder) '
              'to refresh kid mode for them')
    if any(r.startswith(('tools/zgo_baker/', 'gamedata/scripts/zgo_bake')) for r in new + changed):
        print('baker changed: Umbra Effects Setup will say if the bake needs redoing')


if __name__ == '__main__':
    main()
