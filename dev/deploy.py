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
    (both rewritten by ZGO Setup for that mod list);
  * meta.ini (MO2's file).
It never deletes anything. Files in the mod folder that the repo no longer has
are listed so you can remove them yourself.

It refuses to run while the game, ZGO Setup, the baker or kidfx is running.
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
DEFAULT_TO = os.path.join('~', 'gamma', 'gamma', 'mods', 'Zone Gore Overhaul')
MARKER = 'gamedata/scripts/zgo_main.script'
KIDFX_STATE = ('tools/zgo_kidfx/kidfx_copies.json', 'tools/zgo_kidfx/kidfx_snapshot.txt')
MO2_OWNED = ('meta.ini',)
BUSY = re.compile(r'anomalydx[0-9a-z]*\.exe|xrengine\.exe|zgo_baker[/\\]bake\.py|zgo_fracture'
                  r'|kidfx_pe\.py|zgo[-_ ]setup', re.I)


def busy():
    """Names of running programs that must not see the mod folder change."""
    found = set()
    if os.path.isdir('/proc'):
        me = {str(os.getpid()), str(os.getppid())}
        for pid in os.listdir('/proc'):
            if not pid.isdigit() or pid in me:
                continue
            try:
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    cmd = f.read().replace(b'\0', b' ').decode('utf-8', 'replace')
            except OSError:
                continue
            if 'dev/deploy.py' in cmd or 'dev\\deploy.py' in cmd:
                continue
            m = BUSY.search(cmd)
            if m:
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
    kept, _ = package.walk()
    prot = protected(dst)
    new, changed, same, kept_live = [], [], 0, []
    for rel, size in kept:
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
    ours = {rel for rel, _ in kept}
    extra = []
    for dp, dns, fns in os.walk(dst):
        dns[:] = [d for d in dns if d != '__pycache__']
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), dst).replace(os.sep, '/')
            if rel not in ours and not is_protected(rel, prot) and not fn.endswith(('.pyc', '.part')):
                extra.append(rel)
    return new, changed, same, kept_live, sorted(extra)


def copy(rel, dst):
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
    running = busy()
    if running and not a.dry_run:
        sys.exit('deploy: close these first: %s' % ', '.join(running))

    new, changed, same, kept_live, extra = plan(dst)
    print('deploy %s -> %s%s' % (root, dst, ' (dry run)' if a.dry_run else ''))
    if running:
        print('note: running now: %s (a real deploy would refuse)' % ', '.join(running))
    show('new', new)
    show('changed', changed)
    print('unchanged: %d' % same)
    if kept_live:
        show('left alone (made on that machine)', kept_live, 6)
    if extra:
        show('only in the mod folder (not in the repo; remove by hand if stale)', extra)
    if a.dry_run or not (new or changed):
        if not (new or changed):
            print('nothing to copy')
        return
    for rel in new + changed:
        copy(rel, dst)
    print('copied %d file(s)' % (len(new) + len(changed)))
    if any(r.startswith('gamedata/particles/') for r in new + changed):
        print('particles changed: run ZGO Setup (or tools/zgo_kidfx/kidfx_pe.py apply in the mod folder) '
              'to refresh kid mode for them')
    if any(r.startswith(('tools/zgo_baker/', 'gamedata/scripts/zgo_bake')) for r in new + changed):
        print('baker changed: ZGO Setup will say if the bake needs redoing')


if __name__ == '__main__':
    main()
