"""A throw-away MO2 install with the synthetic character, for bake() tests,
plus the fixture generator for tests/zgo_test_baker2.lua:

    python3 tests/baker/fakemo2.py --fixtures     # rewrite tests/baker/fixtures/
"""
import contextlib
import os
import re
import shutil
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth  # noqa: E402
import bake  # noqa: E402

FIXTURES = os.path.join(synth.HERE, 'fixtures')
MODELS = ('actors\\synth\\synth_a', 'actors\\synth\\synth_b', 'monsters\\synth\\synth_m')
FIXTURE_ID = 'fixture-1'


def make(root):
    """MO2 folder layout under root; returns bake.Options for it."""
    mo2 = os.path.join(root, 'mo2')
    src = os.path.join(mo2, 'mods', 'Synth Models', 'gamedata', 'meshes')
    data = synth.build()
    for k in MODELS:
        p = os.path.join(src, *k.split('\\')) + '.ogf'
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # synth_m differs (another texture): a second set of caps / pieces
        with open(p, 'wb') as f:
            f.write(synth.build(texture='test\\other') if k.startswith('monsters') else data)
    os.makedirs(os.path.join(mo2, 'profiles', 'P'))
    with open(os.path.join(mo2, 'profiles', 'P', 'modlist.txt'), 'w') as f:
        f.write('# test\n+Out\n+Synth Models\n')
    out = os.path.join(mo2, 'mods', 'Out')
    os.makedirs(out)
    game = os.path.join(root, 'game')
    os.makedirs(os.path.join(game, 'db'))
    return bake.Options(mo2=mo2, profile='P', anomaly=game, out=out, jobs=2, cache=os.path.join(root, 'cache'))


@contextlib.contextmanager
def patched():
    """No base archives, the synthetic creature's cut roots."""
    with mock.patch.object(bake.unpack_base, 'unpack', lambda *a, **k: (0, 0)), \
            mock.patch.object(bake.limbs, 'load', lambda root: synth.LIMBS):
        yield


def fixed_id(text):
    return re.sub(r'bake_id = "[^"]*"', 'bake_id = "%s"' % FIXTURE_ID, text)


def fixture_scripts(experimental=True):
    """{name: text} of the generated scripts for the synthetic models."""
    with tempfile.TemporaryDirectory() as root:
        o = make(root)
        o.experimental_caps = o.experimental_damage = experimental
        with patched():
            bake.bake(o)
        out = {}
        for rel in bake.SCRIPTS:
            with open(os.path.join(o.out, *rel.split('/')), encoding='utf-8', newline='') as f:
                out[os.path.basename(rel)] = fixed_id(f.read())
        return out


if __name__ == '__main__':
    if '--fixtures' in sys.argv:
        os.makedirs(FIXTURES, exist_ok=True)
        for name, text in fixture_scripts().items():
            with open(os.path.join(FIXTURES, name), 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            print('wrote', os.path.join(FIXTURES, name))
    else:
        root = tempfile.mkdtemp()
        print(make(root))
        shutil.rmtree(root)
