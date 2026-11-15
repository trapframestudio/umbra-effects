#!/usr/bin/env python3
"""
Bring Umbra's look into Umbra Effects Setup: the icon, the typefaces (Tektur Narrow,
Play, with their OFL licences) and the font code that draws them where Tk can't
(typeface.py, ttf.py). They come from the Umbra repo (installer/umbra_installer) and
land in tools/zgo_setup, where they ship with the mod (the setup program runs the mod
folder's own copy of tools/zgo_setup) and get bundled into the built programs.

  python3 dev/build_setup/umbra_assets.py             copy them from the Umbra repo
  python3 dev/build_setup/umbra_assets.py --check     exit 1 if the copies differ from Umbra's
  python3 dev/build_setup/umbra_assets.py --if-found  copy when the Umbra repo is there, else
                                                      keep the committed copies (build.sh uses this)

The Umbra repo: $UMBRA_REPO, else a folder named "umbra" next to this repo.
Edit these files in Umbra, not here; this script overwrites them.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..'))
DEST = os.path.join(MOD, 'tools', 'zgo_setup')
SRC_PKG = os.path.join('installer', 'umbra_installer')

# (Umbra path under installer/umbra_installer, path under tools/zgo_setup)
FILES = [('assets/umbra-icon-256.png', 'assets/umbra-icon-256.png'),
         ('assets/umbra-icon-64.png', 'assets/umbra-icon-64.png'),
         ('assets/fonts/TekturNarrow-SemiBold.ttf', 'assets/fonts/TekturNarrow-SemiBold.ttf'),
         ('assets/fonts/Play-Regular.ttf', 'assets/fonts/Play-Regular.ttf'),
         ('assets/fonts/Play-Bold.ttf', 'assets/fonts/Play-Bold.ttf'),
         ('assets/fonts/OFL-Tektur.txt', 'assets/fonts/OFL-Tektur.txt'),
         ('assets/fonts/OFL-Play.txt', 'assets/fonts/OFL-Play.txt'),
         ('ttf.py', 'ttf.py'),
         ('typeface.py', 'typeface.py')]

NOTE = (b'# Copied from Umbra (installer/umbra_installer/%s) by dev/build_setup/umbra_assets.py:\n'
        b'# edit it there, then run that script. Umbra is MIT-licensed.\n')

# typeface.py lives in a package in Umbra and next to setup_gui.py here
TYPEFACE_EDITS = [
    (b'from . import ttf\n', b'import ttf\n'),
    (b'    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))\n'
     b'    for d in (os.path.join(base, "assets", "fonts"), os.path.join(base, "umbra_installer", "assets", "fonts")):\n',
     b'    here = os.path.dirname(os.path.abspath(__file__))\n'
     b'    base = getattr(sys, "_MEIPASS", None) or here\n'
     b'    for d in (os.path.join(here, "assets", "fonts"), os.path.join(base, "assets", "fonts")):\n'),
]


def umbra_repo():
    for p in (os.environ.get('UMBRA_REPO'), os.path.join(os.path.dirname(MOD), 'umbra')):
        if p and os.path.isfile(os.path.join(p, SRC_PKG, 'typeface.py')):
            return p
    return None


def wanted(repo, src):
    with open(os.path.join(repo, SRC_PKG, *src.split('/')), 'rb') as f:
        data = f.read()
    if src.endswith('.py'):
        if src == 'typeface.py':
            for old, new in TYPEFACE_EDITS:
                if data.count(old) != 1:
                    raise SystemExit('umbra_assets: Umbra\'s typeface.py changed shape (%r); update TYPEFACE_EDITS'
                                     % old[:50])
                data = data.replace(old, new)
        data = NOTE % src.encode() + data
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--check', action='store_true', help='only compare; exit 1 when a copy differs')
    ap.add_argument('--if-found', action='store_true', help='keep the committed copies when Umbra is not there')
    a = ap.parse_args()
    repo = umbra_repo()
    if repo is None:
        if a.if_found:
            print('umbra_assets: no Umbra repo found ($UMBRA_REPO or ../umbra); using the committed copies')
            return 0
        sys.exit('umbra_assets: no Umbra repo found: set UMBRA_REPO to its folder')
    stale = []
    for src, dst in FILES:
        data = wanted(repo, src)
        p = os.path.join(DEST, *dst.split('/'))
        try:
            with open(p, 'rb') as f:
                same = f.read() == data
        except OSError:
            same = False
        if same:
            continue
        stale.append(dst)
        if not a.check:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(data)
    if a.check:
        for d in stale:
            print('differs from Umbra: tools/zgo_setup/' + d)
        return 1 if stale else 0
    print('umbra_assets: %s' % ('updated ' + ', '.join(stale) if stale else 'all %d files match Umbra' % len(FILES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
