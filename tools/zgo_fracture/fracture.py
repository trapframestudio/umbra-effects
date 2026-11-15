#!/usr/bin/env python3
"""
ZGO fracture baker: cuts the physics props the player's mod list actually
loads (MO2 priority, then the game's archives) into pieces that zgo_props
throws when one of them breaks (Phase E3).

  * barrels, canisters, bottles: Voronoi shells (cells around seeds on the
    surface), each closed with a thin inner face;
  * crates and stools: each face cut into planks across its long side.

Writes, into this mod's own folder:
  gamedata/meshes/zgo/props/fracture/<model>_<n>.ogf   one-bone piece models
                                                       (in the source model's space)
  gamedata/scripts/zgo_props_fracture_index.script     which pieces belong to which model
  zgo_fracture_report.json                             every file written
A re-run or --remove deletes exactly the files the report lists and refuses
to overwrite anything else. The runtime uses the pieces only when the index
exists; without a bake, objects break into the game's own parts (kit-bash).

Experimental, off by default (--experimental-native): also writes copies of
the source models with model data that makes the game break them itself
([destroyed] = the baked pieces), at their own paths under gamedata/meshes/.
Unverified in co-op (the game spawns the parts as objects); see
docs/integration/props.md.

  python3 fracture.py [--mo2 DIR] [--profile NAME] [--anomaly DIR] [--only SUBSTR]
  python3 fracture.py --remove

Library use (the setup GUI):

    import fracture
    opts = fracture.default_options()
    report = fracture.bake(opts, progress=fn, cancel=fn)
    fracture.remove(opts.out)

progress(stage, done, total, message) is called from the calling thread;
stage is one of STAGES. cancel() returning True stops before the output
folder changes (raises Cancelled). Errors raise FractureError with a
message meant for players.

Reads tools/zgo_baker (ogf, xdb, resolve, bake.mo2_defaults); never changes it.
"""
import argparse, copy, glob, hashlib, json, os, shutil, struct, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(MOD_ROOT, 'tools', 'zgo_baker'))
import numpy as np  # noqa: E402
import cut  # noqa: E402
import ogf, xdb, resolve  # noqa: E402  (zgo_baker, read only)

VERSION = 1
REPORT = 'zgo_fracture_report.json'
INDEX = 'gamedata/scripts/zgo_props_fracture_index.script'
PIECES = 'gamedata/meshes/zgo/props/fracture/'
NATIVE_TEMPLATES = 'gamedata/configs/models/objects/'
STAGES = ('prepare', 'resolve', 'cut', 'install', 'done')

# visual: (method, amount, inner face thickness m, seed salt)
#   shell: amount = cells; planks: amount = plank width (m)
TARGETS = {
    'dynamics\\balon\\bochka_close_1': ('shell', 9, 0.004),
    'dynamics\\balon\\bochka_close_2': ('shell', 9, 0.004),
    'dynamics\\balon\\bochka_close_3': ('shell', 9, 0.004),
    'dynamics\\balon\\bochka_close_4': ('shell', 9, 0.004),
    'dynamics\\balon\\bochka_fuel': ('shell', 9, 0.004),
    'dynamics\\balon\\bidon': ('shell', 8, 0.003),
    'dynamics\\box\\box_1a': ('planks', 0.16, 0.012),
    'dynamics\\box\\box_1b': ('planks', 0.16, 0.012),
    'dynamics\\box\\box_1c': ('planks', 0.16, 0.012),
    'dynamics\\box\\box_wood_02': ('planks', 0.17, 0.012),
    'dynamics\\stul\\taburet_wood_01': ('planks', 0.12, 0.012),
    'dynamics\\stul\\taburet_village': ('planks', 0.12, 0.012),
    'dynamics\\devices\\dev_vodka\\dev_vodka': ('shell', 7, 0.002),
    'dynamics\\devices\\dev_vodka\\dev_vodka2': ('shell', 7, 0.002),
    'dynamics\\decor\\butilka_vodka_01': ('shell', 7, 0.002),
}
# experimental native breaking: model data templates (shipped, inert) per visual
NATIVE = {
    'dynamics\\box\\box_1a': 'zgo_props_crate_small.ltx',
    'dynamics\\box\\box_1b': 'zgo_props_crate_small.ltx',
    'dynamics\\box\\box_1c': 'zgo_props_crate_small.ltx',
    'dynamics\\box\\box_wood_02': 'zgo_props_crate_small.ltx',
    'dynamics\\stul\\taburet_wood_01': 'zgo_props_stool.ltx',
    'dynamics\\stul\\taburet_village': 'zgo_props_stool.ltx',
}


class FractureError(Exception):
    """A bake could not run or finish; the message is meant for the player."""


class Cancelled(FractureError):
    """cancel() asked to stop; nothing in the output folder was changed."""


class Options:
    def __init__(self, mo2=None, profile=None, anomaly=None, out=MOD_ROOT, only=None, seed=1717,
                 experimental_native=False):
        self.mo2, self.profile, self.anomaly, self.out = mo2, profile, anomaly, out
        self.only, self.seed = only, seed
        self.experimental_native = experimental_native

    def __repr__(self):
        return 'Options(%s)' % ', '.join('%s=%r' % kv for kv in sorted(vars(self).items()))


def default_options(mod_root=MOD_ROOT):
    """MO2 folder / profile / game from MO2's config (same rules as the mesh baker)."""
    try:
        import bake as _baker   # zgo_baker.bake (read only)
        mo2, profile, game = _baker.mo2_defaults(mod_root)
    except Exception:  # noqa: BLE001
        mo2 = profile = game = None
    return Options(mo2=mo2, profile=profile, anomaly=game, out=mod_root)


# ---------------------------------------------------------------- report / removal

def read_report(root):
    try:
        with open(os.path.join(root, REPORT)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _safe(rel):
    rel = rel.replace('\\', '/')
    if '..' in rel.split('/') or rel.startswith('/') or ':' in rel:
        return None
    if rel == INDEX or rel.startswith(PIECES) or (rel.startswith('gamedata/meshes/') and rel.endswith('.ogf')):
        return rel
    return None


def previous_files(root):
    rep = read_report(root)
    if not rep:
        return []
    return [r for r in (_safe(x) for x in rep.get('files', [])) if r]


def remove(out=MOD_ROOT, progress=None):
    """Delete everything the last fracture bake wrote into out, and its report."""
    files = previous_files(out)
    n = 0
    for rel in files:
        p = os.path.join(out, *rel.split('/'))
        if os.path.isfile(p):
            os.remove(p)
            n += 1
    for d in sorted({os.path.dirname(os.path.join(out, *r.split('/'))) for r in files}, key=len, reverse=True):
        while d.startswith(os.path.join(out, 'gamedata', 'meshes')) and d != os.path.join(out, 'gamedata', 'meshes'):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    try:
        os.remove(os.path.join(out, REPORT))
    except OSError:
        pass
    if progress:
        progress('install', n, n, 'removed %d files' % n)
    return n


# ---------------------------------------------------------------- sources

def _archive_index(anomaly, wanted):
    """visual -> (archive path, member name) for the wanted visuals."""
    found = {}
    dbs = sorted(glob.glob(os.path.join(anomaly, 'db', 'meshes', '*.db*'))) + \
        sorted(glob.glob(os.path.join(anomaly, 'db', 'patches', '*.db*')))
    for db in dbs:
        try:
            a = xdb.Archive(db)
        except Exception:  # noqa: BLE001
            continue
        for name in a.files:
            low = name.lower()
            if low.startswith('meshes\\') and low.endswith('.ogf'):
                key = low[len('meshes\\'):-4]
                if key in wanted:
                    found[key] = (db, name)        # later archives win
    return found


def sources(opts, wanted, progress=None):
    """visual -> ('file', path) | ('db', archive, member): what the game loads."""
    out = {}
    if opts.mo2 and opts.profile:
        own = os.path.basename(os.path.normpath(opts.out))
        try:
            w = resolve.winners(opts.mo2, opts.profile, subdirs=('meshes/dynamics',), skip=(own,),
                                progress=(lambda d, t: progress('resolve', d, t, 'mods scanned')) if progress else None)
        except OSError as e:
            raise FractureError("can't read the MO2 mod list (%s): %s" % (opts.profile, e))
        for v in wanted:
            if v in w:
                out[v] = ('file', w[v])
    missing = [v for v in wanted if v not in out]
    if missing:
        if not (opts.anomaly and os.path.isdir(os.path.join(opts.anomaly, 'db'))):
            raise FractureError("the game's folder is not set or has no db/ folder: %s" % opts.anomaly)
        for v, (db, name) in _archive_index(opts.anomaly, set(missing)).items():
            out[v] = ('db', db, name)
    return out


def _read(src):
    if src[0] == 'file':
        with open(src[1], 'rb') as f:
            return f.read()
    return xdb.Archive(src[1]).read(src[2])


# ---------------------------------------------------------------- piece models

def box_shape(lo, hi):
    """SBoneShape (bone.h): type stBox, no flags, the box; empty sphere / cylinder."""
    return struct.pack('<HH', 1, 0) + ogf.obb_bytes(lo, hi)[:60] + b'\0' * 16 + b'\0' * 32


def piece_ogf(piece, src_bone, mass):
    lo, hi = cut.piece_bounds(piece)
    b = copy.copy(src_bone)
    b.mass = float(max(0.05, mass))
    b.com = tuple(((lo + hi) / 2).tolist())
    ik = ogf.ik_record(b, bind_rot=(0.0, 0.0, 0.0), bind_pos=(0.0, 0.0, 0.0), shape=box_shape(lo, hi))
    geoms = []
    for part in piece:
        V = part['V']
        n = len(V)
        geoms.append(ogf.Geom.new(part['texture'], part['shader'], V[:, cut.P_], V[:, cut.N_], V[:, cut.T_], V[:, cut.B_],
                                  V[:, cut.UV_], np.zeros((n, 1), np.uint16), np.ones((n, 1), np.float32), part['tris'], 1))
    return ogf.build_skeleton_model([('link', '', ogf.obb_bytes(lo, hi), ik)], geoms), lo, hi


def flat_name(visual):
    v = visual.replace('\\', '_')
    return v[len('dynamics_'):] if v.startswith('dynamics_') else v


def fracture_model(visual, data, spec, seed):
    """Pieces of one model: list of (ogf bytes, lo, hi)."""
    model = ogf.Model(data)
    mesh = cut.mesh_from_model(model)
    method, amount, thick = spec
    rng = np.random.default_rng(seed)
    cut.reset_cuts()
    if method == 'shell':
        pieces = cut.voronoi_cells(mesh, int(amount), rng)
    else:
        pieces = cut.plank_cells(mesh, float(amount), rng)
    pieces = [p for p in pieces if cut.piece_area(p) > 1e-4]
    if len(pieces) < 2:
        raise FractureError('%s did not split' % visual)
    total_mass = sum(b.mass for b in model.skeleton.bones) or 10.0
    areas = [cut.piece_area(p) for p in pieces]
    tot = sum(areas)
    root = model.skeleton.bones[model.skeleton.root]
    out = []
    for p, a in zip(pieces, areas):
        out.append(piece_ogf(cut.thicken(p, thick), root, total_mass * a / tot))
    return model, out


def native_userdata(template_text, piece_names):
    lines = [template_text.rstrip(), '', '[destroyed]'] + piece_names
    return ('\n'.join(lines) + '\n').encode('cp1251', 'replace')


def native_copy(model, userdata):
    """The source model with its model data (OGF_S_USERDATA) replaced."""
    chunks = [c for c in model.chunks if c[0] & 0x7FFFFFFF != ogf.S_USERDATA]
    chunks.append([ogf.S_USERDATA, userdata + b'\0'])
    return ogf.write_chunks(chunks) + model.tail


def write_index(path, rigs, bake_id, native=()):
    def s(x):
        return '"' + x.replace('\\', '\\\\') + '"'
    lines = ['-- Written by tools/zgo_fracture/fracture.py on this machine (bake %s). Do not edit;' % bake_id,
             '-- re-run the fracture bake (or the setup tool) after changing prop model mods.',
             '-- bake: a content id (the source models, options and this tool\'s version), so two',
             '-- machines with the same props bake have the same id (the co-op handshake compares it).',
             '-- rigs[visual] = { pieces = { { model, centre x, y, z, half size x, y, z }, ... } } (model space)',
             'version = %d' % VERSION, 'bake = "%s"' % bake_id, '', 'rigs = {']
    for v in sorted(rigs):
        lines.append('\t[%s] = { pieces = {' % s(v))
        for name, lo, hi in rigs[v]:
            c, h = (lo + hi) / 2, (hi - lo) / 2
            lines.append('\t\t{ %s, %.4f, %.4f, %.4f, %.4f, %.4f, %.4f },' % (s(name), *c.tolist(), *h.tolist()))
        lines.append('\t} },')
    lines.append('}')
    lines += ['', '-- (experimental) models this bake made the game break itself', 'native = {']
    lines += ['\t[%s] = true,' % s(v) for v in sorted(native)]
    lines.append('}')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


# ---------------------------------------------------------------- the bake

def bake(options=None, progress=None, cancel=None):
    opts = options or default_options()
    say = progress or (lambda *a: None)
    stop = cancel or (lambda: False)

    def check_cancel():
        if stop():
            raise Cancelled('fracture bake cancelled; the output folder was not changed')

    out = os.path.abspath(opts.out)
    if not os.path.isdir(os.path.join(out, 'gamedata')):
        raise FractureError('%s is not the Zone Gore Overhaul folder (no gamedata/)' % out)
    say('prepare', 0, 1, 'reading the last report')
    prev = set(previous_files(out))
    wanted = {v: s for v, s in TARGETS.items() if not opts.only or opts.only.lower() in v}
    if not wanted:
        raise FractureError('nothing matches --only %s' % opts.only)
    check_cancel()
    srcs = sources(opts, set(wanted), say)
    check_cancel()
    made = time.strftime('%Y%m%d-%H%M%S')
    # the bake id is a content id, comparable between machines (zgo_handshake)
    idh = hashlib.md5(('%d|%d|%d|%s' % (VERSION, opts.seed, bool(opts.experimental_native), opts.only or '')).encode())
    build = tempfile.mkdtemp(prefix='zgo_fracture_')
    files, results, rigs = [], [], {}
    try:
        names = sorted(wanted)
        for i, v in enumerate(names):
            say('cut', i, len(names), v)
            check_cancel()
            src = srcs.get(v)
            if not src:
                results.append({'visual': v, 'status': 'not in this mod list'})
                continue
            data = _read(src)
            src_md5 = hashlib.md5(data).hexdigest()
            idh.update(('|%s=%s' % (v, src_md5)).encode())
            try:
                model, pieces = fracture_model(v, data, wanted[v], opts.seed + sum(map(ord, v)))
            except (ogf.OgfError, FractureError, ValueError, IndexError) as e:
                results.append({'visual': v, 'status': 'skipped: %s' % e})
                continue
            entries = []
            for n, (data, lo, hi) in enumerate(pieces, 1):
                rel = '%s%s_%d.ogf' % (PIECES, flat_name(v), n)
                dst = os.path.join(build, *rel.split('/'))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(data)
                files.append(rel)
                entries.append(('zgo\\props\\fracture\\%s_%d' % (flat_name(v), n), lo, hi))
            rigs[v] = entries
            res = {'visual': v, 'status': 'ok', 'pieces': len(entries),
                   'source': src[1] if src[0] == 'file' else '%s:%s' % (os.path.basename(src[1]), src[2]),
                   'bytes_in': len(data), 'src_md5': src_md5}
            if opts.experimental_native and v in NATIVE:
                tpl = os.path.join(out, *NATIVE_TEMPLATES.split('/'), NATIVE[v])
                try:
                    with open(tpl, encoding='cp1251') as f:
                        text = f.read()
                    rel = 'gamedata/meshes/%s.ogf' % v.replace('\\', '/')
                    dst = os.path.join(build, *rel.split('/'))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, 'wb') as f:
                        f.write(native_copy(model, native_userdata(text, [e[0] for e in entries])))
                    files.append(rel)
                    res['native'] = rel
                except OSError as e:
                    res['native'] = 'skipped: %s' % e
            results.append(res)
        bake_id = idh.hexdigest()[:16]
        if rigs:
            rel = INDEX
            dst = os.path.join(build, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_index(dst, rigs, bake_id, [r['visual'] for r in results
                                             if str(r.get('native', '')).startswith('gamedata/')])
            files.append(rel)
        check_cancel()
        # ---- from here on the output folder changes
        for rel in files:
            p = os.path.join(out, *rel.split('/'))
            if os.path.exists(p) and rel not in prev:
                raise FractureError('%s exists and was not written by a fracture bake; not overwriting it' % rel)
        say('install', 0, len(files), 'removing the last bake')
        remove(out)
        for i, rel in enumerate(files):
            src = os.path.join(build, *rel.split('/'))
            dst = os.path.join(out, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst + '.part')
            os.replace(dst + '.part', dst)
            if (i + 1) % 20 == 0:
                say('install', i + 1, len(files), 'writing pieces')
        report = {'version': VERSION, 'bake': bake_id, 'made': made, 'files': files, 'results': results,
                  'options': {'only': opts.only, 'seed': opts.seed, 'experimental_native': bool(opts.experimental_native),
                              'profile': opts.profile}}
        p = os.path.join(out, REPORT)
        with open(p + '.part', 'w') as f:
            json.dump(report, f, indent=1)
        os.replace(p + '.part', p)
        say('done', len(files), len(files), '%d models cut into %d pieces' % (len(rigs), sum(len(e) for e in rigs.values())))
        return report
    finally:
        shutil.rmtree(build, ignore_errors=True)


def main(argv=None):
    o = default_options()
    ap = argparse.ArgumentParser(description='Cut ZGO prop pieces for this MO2 mod list.')
    ap.add_argument('--mo2', default=o.mo2, help='MO2 folder (default: the one this mod is installed in)')
    ap.add_argument('--profile', default=o.profile, help="MO2 profile (default: MO2's selected profile)")
    ap.add_argument('--anomaly', default=o.anomaly, help="the game's folder (default: MO2's game path)")
    ap.add_argument('--out', default=o.out, help='folder to write into (default: this mod)')
    ap.add_argument('--only', default=None, help='only models whose path contains this')
    ap.add_argument('--seed', type=int, default=o.seed)
    ap.add_argument('--remove', action='store_true', help='delete the files the last fracture bake wrote')
    ap.add_argument('--experimental-native', action='store_true',
                    help='(experimental) also make the game break crates and stools itself, into these pieces')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)

    def progress(stage, done, total, msg):
        if not a.quiet:
            print('[%s] %s/%s %s' % (stage, done, total, msg), flush=True)

    try:
        if a.remove:
            print('removed %d files' % remove(a.out, progress))
            return 0
        opts = Options(mo2=a.mo2, profile=a.profile, anomaly=a.anomaly, out=a.out, only=a.only, seed=a.seed,
                       experimental_native=a.experimental_native)
        rep = bake(opts, progress)
        bad = [r for r in rep['results'] if r['status'] != 'ok']
        for r in bad:
            print('  %s: %s' % (r['visual'], r['status']))
        return 0
    except FractureError as e:
        print('error: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
