#!/usr/bin/env python3
"""
Umbra Effects mesh baker: rebuilds every NPC / mutant model the game would load (MO2
priority, then the base archives) with one sub-mesh per severable section,
and writes them into this mod's own folder (gamedata/meshes/...) together
with the generated scripts zgo_bake_index / zgo_bake_parts / zgo_bake_wounds.
Since 1.7 it also writes fitted stump caps and limb pieces
(gamedata/meshes/zgo/baked/...) and wound sites, all used only when the
runtime asks for them (docs/formats/).

  python3 bake.py [--mo2 DIR] [--profile NAME] [--only SUBSTR] [--jobs N]
  python3 bake.py --remove        # delete everything a bake wrote

The many small parts (caps, limb pieces, gibs: ~80,000 files for G.A.M.M.A.) go
into a few engine archives, db/mods/zgo_bake_<part>_NN.db0 (xdb_write.py says why: the
game indexes every loose file at each start); the body models stay loose, since
they must win over other mods' loose copies, which the game prefers to archives.
`--pack` packs a bake made before 1.8.2 in place.

Every file it writes is listed in zgo_bake_report.json ("files"; "packed" lists
what each archive holds); a re-run or --remove deletes exactly those, nothing else. Re-run it after changing mods that add or
replace character models. Umbra Gore & Effects must sit above every model mod in
MO2's left pane (highest priority) for its baked copies to win.

Library use (the setup GUI):

    import bake
    opts = bake.default_options()            # MO2 folder / profile / game from MO2's config
    opts.experimental_caps = False
    report = bake.bake(opts, progress=fn, cancel=fn)
    bake.remove(opts.out)

progress(stage, done, total, message) is called from the calling thread;
stage is one of STAGES. cancel() returning True stops the bake before it
touches the output folder (raises Cancelled). Errors raise BakeError with a
message meant for players.
"""
import argparse, hashlib, json, os, re, shutil, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ogf, partition, limbs, resolve, unpack_base, caps, parts, wounds, luagen, gibs, xdb_write  # noqa: E402

MOD_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
OLD_OUT_NAME = 'Zone Gore Overhaul - Baked Models'   # 1.4.x wrote a separate mod; it's skipped as a source
VERSION = 2
# What the baked output looks like: bump it whenever a change to the baker
# changes what it writes, so the setup tool and the game ask for a new bake
# (1 = ZGO 1.4-1.6, 2 = 1.7, 3 = 1.7.1: body gibs). gamedata/scripts/zgo_setup_notice.script has
# the same number (BAKER); dev/build_setup/test_setup.py checks they match.
BAKER_VERSION = 3
REPORT = 'zgo_bake_report.json'
INDEX = 'gamedata/scripts/zgo_bake_index.script'
PARTS = 'gamedata/scripts/zgo_bake_parts.script'
WOUNDS = 'gamedata/scripts/zgo_bake_wounds.script'
SCRIPTS = (INDEX, PARTS, WOUNDS)
# what the bake was made from, in a form the game can read (zgo_setup_notice)
INPUTS = 'gamedata/scripts/zgo_bake_inputs.script'
INPUTS_VERSION = 1
GENERATED_SCRIPTS = SCRIPTS + (INPUTS,)
CAP_FILES = 'gamedata/meshes/zgo/baked/caps/'
PIECE_FILES = 'gamedata/meshes/zgo/baked/pieces/'
CHUNK_FILES = 'gamedata/meshes/zgo/baked/chunks/'
GIB_FILES = 'gamedata/meshes/zgo/baked/gibs/'
# packed into db/mods/zgo_bake_<caps|pieces|chunks|gibs>_NN.db0 (since 1.8.2)
PACKED = (CAP_FILES, PIECE_FILES, CHUNK_FILES, GIB_FILES)
ARCHIVE_PREFIX = 'db/mods/zgo_bake_'
_ARCHIVE = re.compile(r'^db/mods/zgo_bake_[a-z]+_\d{2}\.db0$')
STAGES = ('prepare', 'unpack', 'resolve', 'bake', 'scripts', 'pack', 'install', 'done')


def _cache_dir():
    # ZGO_BAKER_CACHE: another work folder (the bake is built there, then moved
    # in; it needs as much free space as the bake itself)
    if os.environ.get('ZGO_BAKER_CACHE'):
        return os.path.abspath(os.environ['ZGO_BAKER_CACHE'])
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], 'zgo_baker')
    return os.path.expanduser('~/.cache/zgo_baker')


CACHE = _cache_dir()


class BakeError(Exception):
    """A bake could not run or finish; the message is meant for the player."""


class Cancelled(BakeError):
    """cancel() asked to stop; nothing in the output folder was changed."""


class Options:
    """What to bake. Defaults: today's models plus caps, pieces, wound
    sites and body gibs (all at their own paths); the experimental parts are off."""

    def __init__(self, mo2=None, profile=None, anomaly=None, out=MOD_ROOT, only=None, jobs=None,
                 caps=True, pieces=True, wounds=True, experimental_caps=False, experimental_damage=False,
                 cache=CACHE, gibs=True, pack=True):
        self.mo2, self.profile, self.anomaly, self.out = mo2, profile, anomaly, out
        self.only = only
        self.jobs = jobs or max(1, (os.cpu_count() or 4) - 2)
        self.caps, self.pieces, self.wounds, self.gibs = caps, pieces, wounds, gibs
        self.experimental_caps, self.experimental_damage = experimental_caps, experimental_damage
        self.cache = cache
        self.pack = pack                    # the small parts into archives (False: loose, as before 1.8.2)

    def flags(self):
        return {'caps': bool(self.caps), 'pieces': bool(self.pieces), 'wounds': bool(self.wounds),
                'gibs': bool(self.gibs), 'experimental_caps': bool(self.experimental_caps),
                'experimental_damage': bool(self.experimental_damage)}

    def __repr__(self):
        return 'Options(%s)' % ', '.join('%s=%r' % kv for kv in sorted(vars(self).items()))


def is_archive(rel):
    return bool(_ARCHIVE.match(rel))


def packable(rel):
    return rel.startswith(PACKED)


def output_files(rep):
    """Every file a bake made: the loose ones and those inside its archives (once each, also
    while a pack that stopped half-way lists both)."""
    out = {f for f in rep.get('files') or [] if not is_archive(f)}
    for rels in (rep.get('packed') or {}).values():
        out.update(rels)
    return sorted(out)


def orphan_archives(root, known=()):
    """Archives of ours (by their name) in root/db/mods that no report lists, and .part files
    of them: left by a pack or bake that was killed between writing them and its report."""
    d = os.path.join(root, 'db', 'mods')
    try:
        names = os.listdir(d)
    except OSError:
        return []
    known = set(known)
    out = []
    for fn in sorted(names):
        rel = 'db/mods/' + fn
        base = rel[:-len('.part')] if rel.endswith('.part') else rel
        if _ARCHIVE.match(base) and rel not in known:
            out.append(rel)
    return out


def archive_sizes(root, archives):
    """{archive rel: its size} for the report: check() compares them (a cut-off archive
    crashes the game at its start)."""
    out = {}
    for a in archives:
        try:
            out[a] = os.path.getsize(os.path.join(root, *a.split('/')))
        except OSError:
            pass
    return out


def check_replaceable(root, rels):
    """Raise BakeError when one of these archives can't be replaced: on Windows the running
    game holds every archive it loaded (no delete sharing), so a bake or remove would stop
    half-way. A file is renamed away and back to find out."""
    for rel in rels:
        if not is_archive(rel):
            continue
        p = os.path.join(root, *rel.split('/'))
        if not os.path.isfile(p):
            continue
        probe = p + '.zgo-check'
        try:
            os.replace(p, probe)
        except PermissionError:
            raise BakeError('%s is in use: close the game (and anything else that has it open), then try again'
                            % rel.split('/')[-1])
        os.replace(probe, p)


def loose_files(rep):
    """A bake's files that belong in its archives but are loose (bakes made before 1.8.2)."""
    return [f for f in rep.get('files') or [] if packable(f)]


# ---------------------------------------------------------------- per model (worker processes)

_L = None
_F = None


def _init(limb_roots, flags):
    global _L, _F
    _L, _F = limb_roots, flags


def check(model, kids, n_base=None):
    """Structural checks on the rebuilt model (re-read from bytes). The first
    n_base children must hold every source triangle; the rest are extras
    (experimental K_s / D_s) that must still stay inside their section."""
    data = model.pack(kids)
    m2 = ogf.Model(data)
    if len(m2.children) != len(kids):
        raise ogf.OgfError('children lost on re-read')
    sk = m2.skeleton
    for g, k in zip(m2.children, kids):
        used = partition.bones_used(g)
        if k.section != partition.BODY and not used <= set(sk.descendants(k.section)):
            raise ogf.OgfError('section %s leaks bones' % sk.bones[k.section].name)
        if len(g.tris) and g.tris.max() >= g.n:
            raise ogf.OgfError('index out of range')
    n_base = len(kids) if n_base is None else n_base
    a = sum(len(g.tris) for g in model.children)
    b = sum(len(g.tris) for g in m2.children[:n_base])
    if a != b:
        raise ogf.OgfError('triangle count %d -> %d' % (a, b))
    return data


def _write_once(root, name, data):
    """Write a content-named model once (several workers may make the same)."""
    dst = os.path.join(root, *parts.model_path(name).split('/'))
    if os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = '%s.%d.part' % (dst, os.getpid())
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, dst)


def _sec_name(skel, s):
    return 'body' if s == partition.BODY else skel.bones[s].name


def bake_model(raw, limb_roots, flags, out_root):
    """Bake one model (bytes). Returns (stock model bytes or None, result dict);
    attachment files are written into out_root as they are made."""
    model = ogf.Model(raw)
    tri_in = sum(len(g.tris) for g in model.children)
    r = partition.split_model(model, limb_roots)
    if r is None:
        return None, {'status': 'skipped', 'why': 'no cut roots in skeleton'}
    kids, info = r
    if not info['sections']:
        return None, {'status': 'skipped', 'why': 'nothing to split'}
    skel = model.skeleton
    roots, labels, sec_of = info['roots'], info['labels'], info['section_of_bone']
    sub = parts.subtree_sections(skel, roots)
    out_kids = list(kids)
    res = {'status': 'ok', 'sections': info['sections'], 'kids_in': info['children_in'],
           'kids_out': info['children_out'], 'tris': tri_in}
    secs = {}                              # section name -> parts entry
    for i, k in enumerate(kids):
        secs.setdefault(_sec_name(skel, k.section), {'ids': []})['ids'].append(i + 1)

    seams = {}
    if flags['caps'] or flags['pieces'] or flags['experimental_caps']:
        for s in roots:
            seams[s] = caps.section_loops(model, labels, sub[s])
    stumps = {}
    n_caps = n_pieces = 0
    for s in roots:
        name = skel.bones[s].name
        e = secs.setdefault(name, {'ids': []})
        loops = seams.get(s, ([], None))
        if (flags['caps'] or flags['experimental_caps']) and loops[0] and skel.bones[s].parent >= 0:
            stumps[s] = parts.stump_cap(model, s, loops, name)
        if flags['caps'] and s in stumps:
            made = parts.cap_model(model, s, stumps[s])
            if made:
                data, bones = made
                cname = parts.content_name(parts.CAP_DIR, data)
                _write_once(out_root, cname, data)
                e['cap'] = cname.rsplit('\\', 1)[1]
                e['cap_bones'] = ' '.join(bones)
                n_caps += 1
        if flags['pieces']:
            pcap = parts.piece_cap(model, s, loops, None, name) if loops[0] and skel.bones[s].parent >= 0 else None
            made = parts.piece_model(model, kids, s, sub[s], pcap)
            if made:
                data, _ = made
                pname = parts.content_name(parts.PIECE_DIR, data)
                _write_once(out_root, pname, data)
                e['piece'] = pname.rsplit('\\', 1)[1]
                n_pieces += 1
    if flags['experimental_caps']:
        for s, cap in sorted(stumps.items()):
            p = skel.bones[s].parent
            ids = []
            for g in parts.kcap_geoms(cap, s):
                g.section = int(sec_of[p])
                g.source_child = -1
                out_kids.append(g)
                ids.append(len(out_kids))
            if ids:
                secs[skel.bones[s].name]['k'] = ids
    sites = None
    if flags['wounds'] or flags['experimental_damage'] or flags.get('gibs'):
        sites = wounds.bake_sites(model, kids, info)
    n_gibs = 0
    if flags.get('gibs') and sites:
        made = gibs.gib_model(model, kids, sites)
        if made:
            data, frames = made
            gname = parts.content_name(gibs.GIB_DIR, data)
            _write_once(out_root, gname, data)
            secs.setdefault('body', {'ids': []})['b'] = (gname.rsplit('\\', 1)[1], gibs.encode_frames(frames))
            n_gibs = len(frames)
    if flags['experimental_damage']:
        import damage
        extra = damage.bake(model, kids, info, out_root, flags, sites, _write_once)
        for i, g in extra['dmeshes']:
            out_kids.append(g)
            secs[_sec_name(skel, kids[i].section)].setdefault('d', []).append((i + 1, len(out_kids)))
        for name, chunk in extra['chunks'].items():
            secs.setdefault(name, {'ids': []})['g'] = chunk
    if flags['wounds']:
        res['_sites'] = {name: wounds.encode_sites(ss) for name, ss in sites.items()}
        res['_bind'] = wounds.encode_bind(skel)
        res['sites'] = sum(len(ss) for ss in sites.values())
    data = check(model, out_kids, n_base=len(kids))
    res['kids_out'] = len(out_kids)
    res['caps'], res['pieces'], res['gibs'] = n_caps, n_pieces, n_gibs
    res['_parts'] = secs
    return data, res


def _src_info(src, raw):
    """The source fingerprint of one model: what it was baked from."""
    try:
        mtime = int(os.path.getmtime(src))
    except OSError:
        mtime = 0
    return {'src': src, 'src_md5': hashlib.md5(raw).hexdigest(), 'bytes_in': len(raw), 'src_mtime': mtime}


def work(job):
    key, src, out_root = job
    info = {'src': src}
    try:
        with open(src, 'rb') as f:
            raw = f.read()
        info = _src_info(src, raw)
        data, res = bake_model(raw, _L, _F, out_root)
        res['key'] = key
        res.update(info)
        if data is None:
            return res
        dst = os.path.join(out_root, 'gamedata', 'meshes', *key.split('\\')) + '.ogf'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst + '.part', 'wb') as f:
            f.write(data)
        os.replace(dst + '.part', dst)
        res['bytes_out'] = len(data)
        return res
    except Exception as e:  # noqa: BLE001
        return dict(info, key=key, status='error', why='%s: %s' % (type(e).__name__, e))


# ---------------------------------------------------------------- scripts

def parts_line(secs, names, bonesets, gibsets=None):
    """The zgo_bake_parts.models entry of one model (docs/formats/parts.md)."""
    out = []
    for name in sorted(secs, key=lambda n: (n != 'body', n)):
        e = secs[name]
        cap = '%s.%d' % (e['cap'], bonesets(e['cap_bones'])) if e.get('cap') else '-'
        tok = '%d:%s/%s/%s' % (names(name), ','.join(map(str, e.get('ids', []))), cap, e.get('piece', '-'))
        if e.get('k'):
            tok += '/k:' + ','.join(map(str, e['k']))
        if e.get('d'):
            tok += '/d:' + ','.join('%d=%d' % ab for ab in e['d'])
        if e.get('g'):
            tok += '/g:' + e['g']
        if e.get('b') and gibsets is not None:
            tok += '/b:%s.%d' % (e['b'][0], gibsets(e['b'][1]))
        out.append(tok)
    return ' '.join(out)


def write_scripts(out_root, results, bake_id, flags):
    """The three generated scripts; returns counts for the report. Takes the
    private '_parts' / '_sites' / '_bind' fields out of the results."""
    ok = sorted((r for r in results if r['status'] == 'ok'), key=lambda r: r['key'])
    features = {'caps': flags['caps'], 'pieces': flags['pieces'], 'wounds': flags['wounds'],
                'gibs': flags.get('gibs', False),
                'kcaps': flags['experimental_caps'], 'damage': flags['experimental_damage']}
    luagen.write_lines(out_root, INDEX, luagen.index_lines(ok, bake_id, features))
    names, bonesets, gibsets = luagen.Interner(), luagen.Interner(), luagen.Interner()
    entries = []
    for r in ok:
        line = parts_line(r.pop('_parts', {}), names, bonesets, gibsets)
        if line:
            entries.append((r['key'], line))
    luagen.write_lines(out_root, PARTS, luagen.parts_lines(bake_id, names.items, bonesets.items, entries,
                                                           gibsets.items))
    wnames, skels, sites = luagen.Interner(), luagen.Interner(), luagen.Interner()
    entries = []
    for r in ok:
        bind, secs = r.pop('_bind', None), r.pop('_sites', None)
        if bind is None or secs is None:
            continue
        toks = ['%d=%d' % (wnames(name), sites(text)) for name, text in sorted(secs.items()) if text]
        entries.append((r['key'], ' '.join(['%d' % skels(bind)] + toks)))
    luagen.write_lines(out_root, WOUNDS, luagen.wounds_lines(bake_id, wnames.items, skels.items, sites.items, entries))
    return {'bonesets': len(bonesets.items), 'gibsets': len(gibsets.items), 'skeletons': len(skels.items),
            'site_tables': len(sites.items)}


# ---------------------------------------------------------------- manifest

def read_report(root):
    try:
        with open(os.path.join(root, REPORT)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def previous_files(root):
    """Files the last bake wrote into root (from its report), relative paths."""
    rep = read_report(root)
    if rep is None:
        return []
    files = rep.get('files')
    if files is None:   # 1.4.x reports: rebuild the list from the results
        files = ['gamedata/meshes/%s.ogf' % r['key'].replace('\\', '/') for r in rep.get('results', []) if r.get('status') == 'ok']
        files.append(INDEX)
    safe = []
    for rel in files:
        rel = rel.replace('\\', '/')
        # only ever generated paths: meshes and the generated scripts
        if rel.startswith('gamedata/meshes/') or rel in GENERATED_SCRIPTS or is_archive(rel):
            if '..' not in rel.split('/') and not rel.startswith('/'):
                safe.append(rel)
    return safe


def remove_files(root, files, progress=None):
    n = 0
    dirs = set()
    for i, rel in enumerate(files):
        p = os.path.join(root, *rel.split('/'))
        if os.path.isfile(p):
            os.remove(p)
            n += 1
        dirs.add(os.path.dirname(p))
        if progress and (i + 1) % 1000 == 0:
            progress('install', i + 1, len(files), 'removing the last bake')
    # prune emptied folders under gamedata/meshes, and db/mods, db when the archives were all
    stop = os.path.join(root, 'gamedata')
    for d in sorted(dirs, key=len, reverse=True):
        while d.startswith(os.path.join(stop, 'meshes')) and d != stop:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    if any(is_archive(rel) for rel in files):
        for d in (os.path.join(root, 'db', 'mods'), os.path.join(root, 'db')):
            try:
                os.rmdir(d)
            except OSError:
                break
    return n


def remove(out=MOD_ROOT, progress=None):
    """Delete everything the last bake wrote into out (and archives of ours no report lists),
    and its report. Returns the number of files removed."""
    files = previous_files(out)
    files += orphan_archives(out, files)
    check_replaceable(out, files)
    n = remove_files(out, files, progress)
    try:
        os.remove(os.path.join(out, REPORT))
    except OSError:
        pass
    return n


# ---------------------------------------------------------------- archives (xdb_write.py)

def write_archives(src_root, rels, dest_root, progress=None, cancel=None, consume=False):
    """Pack src_root/<rel> for rels into dest_root/db/mods/zgo_bake_<part>_NN.db0 (one series per
    part: caps, chunks, gibs, pieces). Returns {archive rel: [rels in it]}. On a cancel (raises
    Cancelled) or an error, the archives it wrote are deleted again. consume: delete each
    source once it is in an archive (the bake's temporary copies, never installed files)."""
    say = progress or (lambda *a: None)
    stop = cancel or (lambda: False)
    by_part = {}
    for rel in sorted(rels):
        by_part.setdefault(rel[len('gamedata/meshes/zgo/baked/'):].split('/')[0], []).append(rel)
    items = {part: [(rel, os.path.join(src_root, *rel.split('/')),
                     os.path.getsize(os.path.join(src_root, *rel.split('/')))) for rel in prels]
             for part, prels in by_part.items()}
    total = sum(s for its in items.values() for _, _, s in its) or 1
    done = [0, 0]
    out = {}
    written = []

    def on_file(rel, size):
        done[0] += size
        done[1] += 1
        if done[1] % 2000 == 0:
            say('pack', done[0], total, 'packing the small parts into archives')

    try:
        for part, its in sorted(items.items()):
            for n, group in enumerate(xdb_write.plan_archives(its)):
                arel = '%s%s_%02d.db0' % (ARCHIVE_PREFIX, part, n)
                dest = os.path.join(dest_root, *arel.split('/'))
                if xdb_write.write_archive(dest, group, on_file, stop, consume) is None:
                    raise Cancelled('bake cancelled; the output folder was not changed')
                written.append(dest)
                out[arel] = [rel for rel, _ in group]
    except BaseException:
        for p in written:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
    say('pack', total, total, 'packed %d files into %d archives' % (done[1], len(out)))
    return out


def pack(out=MOD_ROOT, progress=None, cancel=None):
    """Pack an installed bake's loose small parts into archives, in place (bakes made before 1.8.2
    left them loose: ~80,000 files for G.A.M.M.A.). Returns how many files it packed (0: nothing to
    do). Cancelling (raises Cancelled) leaves the bake as it was, until the loose files are deleted."""
    say = progress or (lambda *a: None)
    rep = read_report(out)
    if rep is None or rep.get('status') == 'installing':
        return 0
    if rep.get('status') != 'packing':
        loose = loose_files(rep)
        if not loose:
            return 0
        missing = [f for f in loose if not os.path.isfile(os.path.join(out, *f.split('/')))]
        if missing:
            raise BakeError('%d of the baked files are missing (e.g. %s); bake again' % (len(missing), missing[0]))
        # the archives are written before the loose copies go: room for both
        need = sum(os.path.getsize(os.path.join(out, *f.split('/'))) for f in loose) + (64 << 20)
        try:
            free = shutil.disk_usage(out).free
        except OSError:
            free = None
        if free is not None and free < need:
            raise BakeError('packing needs %.1f GB free on the drive of the Umbra Effects folder; it has %.1f GB'
                            % (need / 1e9, free / 1e9))
        orphans = orphan_archives(out, rep.get('files') or [])
        check_replaceable(out, orphans)
        for rel in orphans:             # (a pack killed before its report: its archives are written again)
            try:
                os.remove(os.path.join(out, *rel.split('/')))
            except OSError:
                pass
        packed = write_archives(out, loose, out, say, cancel)
        # the report lists both from here on, so a pack that dies while deleting is finished next time
        rep = dict(rep, status='packing', files=sorted(set(rep.get('files') or []) | set(packed)),
                   packed=dict(rep.get('packed') or {}, **packed))
        _write_report(out, rep)
    else:
        missing = [a for a in rep.get('packed') or {} if not os.path.isfile(os.path.join(out, *a.split('/')))]
        if missing:
            raise BakeError('the bake\'s archive %s is missing; bake again' % missing[0])
    loose = loose_files(rep)
    remove_files(out, loose, lambda s, d, t, m: say('pack', d, t, 'deleting the loose copies'))
    files = [f for f in rep['files'] if not packable(f)]
    size = 0
    for rel in files:
        try:
            size += os.path.getsize(os.path.join(out, *rel.split('/')))
        except OSError:
            pass
    counts = dict(rep.get('counts') or {}, archives=len(rep.get('packed') or {}))
    rep = dict(rep, files=files, bytes=size, counts=counts,
               archive_bytes=archive_sizes(out, rep.get('packed') or {}))
    rep.pop('status', None)
    _write_report(out, rep)
    return len(loose)


# ---------------------------------------------------------------- MO2

def _ini_value(text, key):
    m = re.search(r'^' + re.escape(key) + r'=(.*)$', text, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith('@ByteArray(') and v.endswith(')'):
        v = v[len('@ByteArray('):-1]
    return v.replace('\\\\', '\\')


def _from_windows_path(p):
    """MO2 stores Windows paths; under Wine/Proton drive Z: is the Linux root."""
    if os.name == 'nt' or not p:
        return p
    if re.match(r'^[Zz]:[\\/]', p):
        return '/' + p[3:].replace('\\', '/')
    return None


def mo2_defaults(mod_root=MOD_ROOT):
    """MO2 folder, profile and game folder for this mod, from MO2's own config:
    the mod sits in <MO2>/mods/<name>, and ModOrganizer.ini names the selected
    profile and the game's path."""
    base = os.path.dirname(os.path.dirname(mod_root))
    profile, game = None, None
    ini = os.path.join(base, 'ModOrganizer.ini')
    if os.path.isfile(ini):
        with open(ini, encoding='utf-8', errors='replace') as f:
            text = f.read()
        profile = _ini_value(text, 'selected_profile')
        game = _from_windows_path(_ini_value(text, 'gamePath'))
    if not profile:
        profs = os.path.join(base, 'profiles')
        names = sorted(os.listdir(profs)) if os.path.isdir(profs) else []
        profile = names[0] if len(names) == 1 else None
    return base, profile, game


def default_options(mod_root=MOD_ROOT):
    mo2, profile, game = mo2_defaults(mod_root)
    return Options(mo2=mo2, profile=profile, anomaly=game, out=mod_root)


# ---------------------------------------------------------------- fingerprints (inputs)

def zgo_version(mod_root=MOD_ROOT):
    """The Umbra Effects version this baker belongs to (zgo_main.VERSION, else meta.ini). MO2 rewrites
    meta.ini's version when it installs a zip (a date stamp such as d2026.11.14)."""
    for rel, pat in (('gamedata/scripts/zgo_main.script', r'^VERSION\s*=\s*"([^"]+)"'),
                     ('meta.ini', r'^version\s*=\s*(\S+)')):
        try:
            with open(os.path.join(mod_root, *rel.split('/')), encoding='utf-8', errors='replace') as f:
                m = re.search(pat, f.read(), re.M)
            if m:
                return m.group(1)
        except OSError:
            pass
    return '?'


def game_path(p):
    """A path as the game (a Windows program, under Wine / Proton too) sees
    it: Windows paths stay as they are, a Linux path goes through drive Z:."""
    if not p:
        return ''
    if os.name == 'nt' or re.match(r'^[A-Za-z]:[\\/]', p):
        return p.replace('/', '\\')
    return 'Z:' + os.path.abspath(p).replace('/', '\\')


def other_zgo_mods(mo2, profile, mod_root=MOD_ROOT):
    """Enabled mods that are other copies of Umbra Effects (they hold a bake report or
    Umbra Effects' main script), e.g. a release kept as a fallback. Their models are
    baked copies, never sources."""
    me = os.path.normcase(os.path.abspath(mod_root))
    out = []
    try:
        names = resolve.enabled_mods(mo2, profile)
    except OSError:
        return out
    for m in names:
        d = os.path.join(mo2, 'mods', m)
        if os.path.normcase(os.path.abspath(d)) == me:
            continue
        if os.path.isfile(os.path.join(d, REPORT)) or os.path.isfile(os.path.join(d, 'gamedata', 'scripts', 'zgo_main.script')):
            out.append(m)
    return out


def model_mods(mo2, profile, skip=()):
    """Enabled mods (highest priority first) that ship character or mutant
    models (gamedata/meshes/actors or monsters), skip excluded."""
    out = []
    for m in resolve.enabled_mods(mo2, profile):
        if m in skip:
            continue
        g = os.path.join(mo2, 'mods', m, 'gamedata', 'meshes')
        if os.path.isdir(os.path.join(g, 'actors')) or os.path.isdir(os.path.join(g, 'monsters')):
            out.append(m)
    return out


def source_mod(mo2, src):
    """The mod a source file came from, or '' for the game's own archives."""
    if not src:
        return ''
    top = os.path.join(mo2, 'mods', '')
    if src.startswith(top):
        return src[len(top):].replace('\\', '/').split('/', 1)[0]
    return ''


def archives_info(anomaly):
    """{archive: [size, mtime]} of the game archives the base models come from."""
    out = {}
    for rel in unpack_base.ARCHIVES:
        p = os.path.join(anomaly, 'db', *rel.split('/'))
        try:
            st = os.stat(p)
            out[rel] = [st.st_size, int(st.st_mtime)]
        except OSError:
            out[rel] = None
    return out


def fingerprint(results, flags, tables):
    """Same mod list content + options + baker -> the same value on every
    machine (no times, no paths): for co-op peers and support."""
    rows = sorted([r['key'], r.get('src_md5') or ''] for r in results)
    blob = json.dumps([BAKER_VERSION, tables, sorted(flags.items()), rows], separators=(',', ':'))
    return hashlib.md5(blob.encode()).hexdigest()


def inputs_record(o, results, flags, limb_roots, skip):
    """report['inputs']: what this bake was made from."""
    mods = model_mods(o.mo2, o.profile, skip)
    for r in results:
        r['src_mod'] = source_mod(o.mo2, r.get('src'))
    tables = limbs.canonical(limb_roots)
    return {'version': INPUTS_VERSION, 'baker': BAKER_VERSION, 'zgo': zgo_version(), 'tables': tables,
            'flags': flags, 'profile': o.profile, 'mo2': os.path.abspath(o.mo2), 'mo2_game': game_path(o.mo2),
            'anomaly': o.anomaly, 'zgo_mod': os.path.basename(os.path.normpath(o.out)),
            'archives': archives_info(o.anomaly), 'model_mods': mods,
            'fingerprint': fingerprint(results, flags, tables)}


def inputs_lines(inputs, results, bake_id, index_bytes):
    """zgo_bake_inputs.script: the compact, game-readable form of the inputs
    (format in docs/integration/setup.md and tools/zgo_setup/README.md)."""
    mods = list(inputs['model_mods'])
    pos = {m: i + 1 for i, m in enumerate(mods)}
    flags = ' '.join(k for k in ('caps', 'pieces', 'wounds', 'gibs', 'experimental_caps', 'experimental_damage')
                     if inputs['flags'].get(k))
    s = luagen.lua_str
    lines = [
        '-- Generated by the Umbra Effects mesh baker (tools/zgo_baker/bake.py). Do not edit.',
        '-- What this bake was made from: read by zgo_setup_notice (the in-game',
        '-- stale-bake check) and Umbra Effects Setup ("is my bake up to date?").',
        '--   models[visual] = "<bytes of the baked file> <source> <bytes of the source file>"',
        '--   source: position in mods (0 = the game\'s own archives)',
        '--   mods: enabled mods with character models, highest priority first',
        'version = %d' % INPUTS_VERSION,
        'bake_id = %s' % s(bake_id),
        'baker = %d' % BAKER_VERSION,
        'zgo = %s' % s(inputs['zgo']),
        'flags = %s' % s(flags),
        'fingerprint = %s' % s(inputs['fingerprint']),
        'tables = %s' % s(inputs['tables']),
        'profile = %s' % s(inputs['profile'] or ''),
        'mo2 = %s' % s(inputs['mo2_game']),
        'zgo_mod = %s' % s(inputs['zgo_mod']),
        'index_bytes = %d' % index_bytes,
        'mods = {',
    ]
    lines += ['\t%s,' % s(m) for m in mods]
    lines += ['}', 'models = {']
    for r in sorted(results, key=lambda r: r['key']):
        if r['status'] != 'ok':
            continue
        lines.append('\t[%s] = "%d %d %d",' % (s(r['key']), r['bytes_out'], pos.get(r.get('src_mod'), 0),
                                               r.get('bytes_in', 0)))
    lines.append('}')
    return lines


# ---------------------------------------------------------------- the bake

def _lock(path):
    """A lock file with our pid; a stale one (dead process) is taken over."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                with open(path) as f:
                    pid = int(f.read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _alive(pid):
                raise BakeError('another bake into this folder is running (pid %d); wait for it, '
                                'or delete %s if it is not' % (pid, path))
            try:
                os.remove(path)
            except OSError:
                pass
    raise BakeError("can't create the lock file %s" % path)


def _alive(pid):
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259                                     # STILL_ACTIVE
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_report(root, report):
    p = os.path.join(root, REPORT)
    with open(p + '.part', 'w') as f:
        json.dump(report, f, indent=1)
    os.replace(p + '.part', p)


def _move(src, dst):
    """Rename, or copy across file systems (cache on another drive)."""
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copyfile(src, dst + '.part')
        os.replace(dst + '.part', dst)
        os.remove(src)


def bake(options=None, progress=None, cancel=None):
    """Run a bake (see the module doc). Returns the report dict that is also
    written to <out>/zgo_bake_report.json."""
    o = options or default_options()
    say = progress or (lambda *a: None)
    stop = cancel or (lambda: False)

    def check_cancel():
        if stop():
            raise Cancelled('bake cancelled; the output folder was not changed')

    if not o.mo2 or not os.path.isdir(o.mo2):
        raise BakeError("can't find the MO2 folder (%s); pass it" % o.mo2)
    if not o.profile or not os.path.isdir(os.path.join(o.mo2, 'profiles', o.profile)):
        raise BakeError("can't tell the MO2 profile (%s); pass it, e.g. G.A.M.M.A" % o.profile)
    if not o.anomaly or not os.path.isdir(os.path.join(o.anomaly, 'db')):
        raise BakeError("can't find the game's folder (%s, it holds db/); pass it" % o.anomaly)
    if not os.path.isdir(o.out):
        raise BakeError('output folder %s does not exist' % o.out)
    t0 = time.time()
    flags = o.flags()
    tag = hashlib.md5(os.path.abspath(o.out).encode()).hexdigest()[:8]
    tmp = os.path.join(o.cache, 'building-' + tag)
    lock = tmp + '.lock'
    _lock(lock)
    try:
        say('prepare', 0, 1, 'reading the creature tables')
        L = limbs.load(MOD_ROOT)
        check_cancel()
        base = os.path.join(o.cache, 'base', 'gamedata')
        try:
            n_base, n_new = unpack_base.unpack(o.anomaly, base, o.jobs,
                                               progress=lambda d, t: say('unpack', d, t, 'base game models'),
                                               cancel=stop)
        except (OSError, ValueError) as e:
            raise BakeError("can't read the game's model archives: %s" % e)
        check_cancel()
        say('unpack', n_base, n_base, 'base game models: %d (%d newly extracted)' % (n_base, n_new))
        skip = (OLD_OUT_NAME, os.path.basename(os.path.normpath(o.out)), os.path.basename(MOD_ROOT)) + \
            tuple(other_zgo_mods(o.mo2, o.profile))
        win = resolve.winners(o.mo2, o.profile, skip=skip,
                              base_dirs=(base,), progress=lambda d, t: say('resolve', d, t, 'mods scanned'))
        items = sorted(win.items())
        if o.only:
            items = [kv for kv in items if o.only.lower() in kv[0]]
        say('resolve', 1, 1, 'models to bake: %d' % len(items))
        check_cancel()
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        results = []
        with Pool(o.jobs, initializer=_init, initargs=(L, flags)) as p:
            for i, r in enumerate(p.imap_unordered(work, [(k, s, tmp) for k, s in items], chunksize=4)):
                results.append(r)
                if (i + 1) % 25 == 0 or i + 1 == len(items):
                    say('bake', i + 1, len(items), 'models baked')
                if stop():
                    p.terminate()
                    break
        check_cancel()
        bake_id = '%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), hashlib.md5(
            json.dumps([[r['key'], r.get('src_md5')] for r in sorted(results, key=lambda r: r['key'])]).encode()
            + json.dumps(flags, sort_keys=True).encode()).hexdigest()[:8])
        say('scripts', 0, 1, 'writing the index scripts')
        counts = write_scripts(tmp, results, bake_id, flags)
        inputs = inputs_record(o, results, flags, L, skip)
        luagen.write_lines(tmp, INPUTS, inputs_lines(inputs, results, bake_id,
                                                     os.path.getsize(os.path.join(tmp, *INDEX.split('/')))))
        say('scripts', 1, 1, 'index scripts written')
        new_files = []
        for dp, _, fs in os.walk(os.path.join(tmp, 'gamedata')):
            for fn in fs:
                if fn.endswith('.part'):
                    os.remove(os.path.join(dp, fn))
                    continue
                new_files.append(os.path.relpath(os.path.join(dp, fn), tmp).replace(os.sep, '/'))
        new_files.sort()
        made = list(new_files)              # every output, packed or not
        packed = {}
        to_pack = [f for f in new_files if packable(f)] if o.pack else []
        if to_pack:
            # (each part is deleted once it is in: the cache never holds the parts twice)
            packed = write_archives(tmp, to_pack, tmp, say, stop, consume=True)
            new_files = sorted([f for f in new_files if not packable(f)] + list(packed))
        check_cancel()
        # never overwrite a file this baker didn't write (e.g. one the mod ships); archives
        # named like ours that no report lists are ours (a pack killed before its report)
        old = set(previous_files(o.out))
        old |= set(orphan_archives(o.out, old))
        clash = [f for f in new_files if f not in old and os.path.exists(os.path.join(o.out, *f.split('/')))]
        if clash:
            raise BakeError('refusing to overwrite files the baker did not write, e.g. %s' % clash[0])
        check_replaceable(o.out, sorted(old | set(new_files)))
        check_cancel()
        # ---- from here on the output folder changes; no more cancelling.
        # The manifest first lists old and new files, so an install that dies
        # half way can still be removed / replaced by the next run.
        _write_report(o.out, {'status': 'installing', 'version': VERSION, 'bake_id': bake_id,
                              'files': sorted(old | set(new_files))})
        new_set = set(new_files)
        removed = remove_files(o.out, sorted(old - new_set), say)
        for i, rel in enumerate(new_files):
            dst = os.path.join(o.out, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _move(os.path.join(tmp, *rel.split('/')), dst)
            if (i + 1) % 1000 == 0 or i + 1 == len(new_files):
                say('install', i + 1, len(new_files), 'files installed')
        removed += len(old & new_set)
        errs = [r for r in results if r['status'] == 'error']
        ok = [r for r in results if r['status'] == 'ok']
        size = 0
        for rel in new_files:
            try:
                size += os.path.getsize(os.path.join(o.out, *rel.split('/')))
            except OSError:
                pass
        report = {'baked': len(ok), 'skipped': sum(r['status'] == 'skipped' for r in results), 'errors': len(errs),
                  'profile': o.profile, 'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'version': VERSION,
                  'bake_id': bake_id, 'options': flags, 'seconds': round(time.time() - t0, 1),
                  'replaced': removed, 'bytes': size,
                  'counts': dict(counts, models=len(ok), files=len(made), archives=len(packed),
                                 caps=sum(r.get('caps', 0) for r in ok), pieces=sum(r.get('pieces', 0) for r in ok),
                                 cap_files=sum(1 for f in made if f.startswith(CAP_FILES)),
                                 piece_files=sum(1 for f in made if f.startswith(PIECE_FILES)),
                                 chunk_files=sum(1 for f in made if f.startswith(CHUNK_FILES)),
                                 gibs=sum(r.get('gibs', 0) for r in ok),
                                 gib_files=sum(1 for f in made if f.startswith(GIB_FILES)),
                                 sites=sum(r.get('sites', 0) for r in ok),
                                 kids_in=sum(r['kids_in'] for r in ok), kids_out=sum(r['kids_out'] for r in ok),
                                 bytes_in=sum(r['bytes_in'] for r in ok), bytes_out=sum(r['bytes_out'] for r in ok)),
                  'inputs': inputs, 'files': new_files, 'packed': packed,
                  'archive_bytes': archive_sizes(o.out, packed),
                  'results': sorted(results, key=lambda r: r['key'])}
        _write_report(o.out, report)
        say('done', 1, 1, 'baked %d models in %.0f s' % (len(ok), report['seconds']))
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(lock)
        except OSError:
            pass


# ---------------------------------------------------------------- command line

def main(argv=None):
    o = default_options()
    ap = argparse.ArgumentParser(description='Bake Umbra Effects body models for this MO2 mod list.')
    ap.add_argument('--mo2', default=o.mo2, help='MO2 folder (default: the one this mod is installed in)')
    ap.add_argument('--profile', default=o.profile, help="MO2 profile (default: MO2's selected profile)")
    ap.add_argument('--anomaly', default=o.anomaly, help="the game's folder (default: MO2's game path)")
    ap.add_argument('--out', default=o.out, help='folder to write into (default: this mod)')
    ap.add_argument('--only', default=None, help='bake only models whose path contains this')
    ap.add_argument('--jobs', type=int, default=o.jobs)
    ap.add_argument('--remove', action='store_true', help='delete the baked files from --out')
    ap.add_argument('--no-caps', action='store_true', help='no stump cap attachments (gamedata/meshes/zgo/baked/caps)')
    ap.add_argument('--no-pieces', action='store_true', help='no limb piece models (gamedata/meshes/zgo/baked/pieces)')
    ap.add_argument('--no-wounds', action='store_true', help='no wound sites (zgo_bake_wounds.script)')
    ap.add_argument('--no-gibs', action='store_true',
                    help='no body gibs (gamedata/meshes/zgo/baked/gibs): explosions throw meat models instead')
    ap.add_argument('--experimental-caps', action='store_true',
                    help='(experimental) also put the caps INSIDE every model as zgo\\off sub-meshes; '
                         'needs the in-game off-shader probe, shows on every NPC if that shader is missing')
    ap.add_argument('--experimental-damage', action='store_true',
                    help='(experimental) damage meshes (D_s, zgo\\off) inside every model and gib chunks; '
                         'needs the in-game probes, roughly doubles the bake size')
    ap.add_argument('--pack', action='store_true',
                    help="pack a bake's loose caps, pieces and gibs into archives (bakes made before 1.8.2)")
    ap.add_argument('--loose', action='store_true', help='leave the caps, pieces and gibs loose (no archives)')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    if a.remove:
        n = remove(a.out)
        print('removed %d baked files from %s' % (n, a.out))
        return 0
    if a.pack:
        n = pack(a.out, progress=None if a.quiet else (lambda s, d, t, m: print('[%s] %s' % (s, m))))
        print('packed %d loose files into archives in %s' % (n, a.out) if n else 'nothing to pack in %s' % a.out)
        return 0
    opts = Options(mo2=a.mo2, profile=a.profile, anomaly=a.anomaly, out=a.out, only=a.only, jobs=a.jobs,
                   caps=not a.no_caps, pieces=not a.no_pieces, wounds=not a.no_wounds, gibs=not a.no_gibs,
                   experimental_caps=a.experimental_caps, experimental_damage=a.experimental_damage,
                   pack=not a.loose)
    last = {}

    def progress(stage, done, total, msg):
        if a.quiet:
            return
        if stage in ('bake', 'install') and done != total and done % 500 >= 25:
            return
        if stage == 'pack' and done != total and msg == last.get('pack'):
            return
        if stage == 'unpack' and done != total:
            return
        if stage == 'pack':
            last['pack'] = msg
        if last.get('m') == (stage, msg, done):
            return
        last['m'] = (stage, msg, done)
        print('  %s %d / %d' % (msg, done, total) if stage in ('bake', 'install') else msg, flush=True)

    try:
        rep = bake(opts, progress)
    except BakeError as e:
        print('bake.py: %s' % e, file=sys.stderr)
        return 2
    c = rep['counts']
    print('baked %d, skipped %d, errors %d in %.0fs (replaced %d old files)' % (
        rep['baked'], rep['skipped'], rep['errors'], rep['seconds'], rep['replaced']))
    print('sub-meshes %d -> %d (x%.2f), models %.0f MB -> %.0f MB' % (
        c['kids_in'], c['kids_out'], c['kids_out'] / max(c['kids_in'], 1), c['bytes_in'] / 1e6, c['bytes_out'] / 1e6))
    print('stump caps %d (%d files), limb pieces %d (%d files), wound sites %d, body gibs %d (%d files); '
          '%d files, %.0f MB in all' % (c['caps'], c['cap_files'], c['pieces'], c['piece_files'], c['sites'],
                                         c.get('gibs', 0), c.get('gib_files', 0), c['files'], rep['bytes'] / 1e6))
    for r in [r for r in rep['results'] if r['status'] == 'error'][:10]:
        print('  error', r['key'], r['why'])
    print('output:', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
