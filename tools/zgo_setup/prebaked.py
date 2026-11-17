"""
Ready-made bakes: Umbra publishes the bake it made for G.A.M.M.A.'s own mod list in its
public bucket. Before baking, Umbra Effects Setup looks there for one that fits this mod
list and these settings (setup_core.check(prebaked=True), the same test as --match),
downloads it and puts it in place. When none fits, or anything goes wrong on the way,
it bakes here as before; the Umbra Effects folder only changes once every file is
downloaded and checked.

The bucket (Umbra's dev/b2_upload.py writes it; its installer's packdef.py has the
bake manifest's format, the same one Umbra Setup reads):

    umbra-effects/index.json                     the bakes there:
        {"format": 1, "kind": "umbra-effects-bakes",
         "bakes": [{"path": "umbra-effects/<fingerprint>/<sha256>.json", "sha256", "size",
                    "fingerprint", "format", "baker", "zgo", "made", "models",
                    "download": <bytes of its volumes>, "bytes": <unpacked>}, ...]}
    umbra-effects/<fingerprint>/<sha256>.json    a bake's manifest
    umbra-effects/<fingerprint>/<sha256>.zip     its report volume (the two reports), its volumes

A bake comes in two formats (an entry's "format", none = 1). Format 1 has the small
parts loose (deflate volumes), so they are packed here once in place. Format 2
(1.8.3) is the same bake with its small parts already in the game archives
(db/mods/zgo_bake_*.db0) and LZMA volumes, about a quarter smaller: some 5,000 files
to unpack instead of 84,000, and no packing. candidates() takes a fingerprint's
format-2 bake when the list has one. The list puts the format-1 bakes first, because
Setup before 1.8.3 tries the first entries in turn and gives up at a manifest it
cannot read.

The volumes download PARALLEL at a time, each checked against its sha256 as it
arrives, and each is unpacked as soon as it is in, while the others still download
(fetch_and_unpack).

Every file is named by its sha256 and checked against it. The reports carry
@@UMBRA_*@@ tokens where the bake recorded its machine's paths and names; they get
this machine's (tokens(), relocate()), as Umbra Setup does.

ZGO_PREBAKED_SOURCE (a URL or a folder) replaces the bucket; ZGO_PREBAKED_SOURCE=off
turns the download off.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

DEFAULT_SOURCE = 'https://f005.backblazeb2.com/file/umbra-mod'
DIR = 'umbra-effects'
INDEX = DIR + '/index.json'
INDEX_FORMAT = 1
BAKE_FORMAT = 1                         # small parts loose
BAKE_FORMAT_PACKED = 2                  # small parts in game archives, LZMA volumes
BAKE_FORMATS = (BAKE_FORMAT, BAKE_FORMAT_PACKED)
PARALLEL = 3                            # volumes downloading at once
UNPACKERS = 2                           # volumes unpacking at once
USER_AGENT = 'UmbraEffectsSetup'
TMP = '.zgo-prebaked'                   # in the Umbra Effects folder while it is unpacked
CANDIDATES = 3                          # bakes compared at most (newest first)
_PATH = re.compile(r'^%s/([0-9a-f]{32})/([0-9a-f]{64})\.(json|zip)$' % DIR)
_FP = re.compile(r'^[0-9a-f]{32}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_TOKEN = re.compile(r'@@UMBRA_[A-Z0-9_]+@@')
ESCAPED_FORMATS = ('.json', '.script', '.lua')
# where Linux keeps its CA certificates, for a ready-made program whose OpenSSL looks elsewhere
CA_FILES = ('/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt',
            '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem', '/etc/ssl/ca-bundle.pem', '/etc/ssl/cert.pem',
            '/usr/local/share/certs/ca-root-nss.crt')
CA_DIRS = ('/etc/ssl/certs', '/etc/pki/tls/certs')


class Unavailable(Exception):
    """No ready-made bake is used (the reason is the message); bake here instead."""


def source():
    """Where the ready-made bakes are: the bucket, or ZGO_PREBAKED_SOURCE. None: turned off."""
    s = os.environ.get('ZGO_PREBAKED_SOURCE', '').strip()
    if s.lower() in ('off', 'no', '0', 'none'):
        return None
    return s or DEFAULT_SOURCE


def is_url(s):
    return s.startswith(('https://', 'http://'))


def human(n):
    n = float(n)
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return ('%d %s' % (n, unit)) if unit == 'bytes' else ('%.1f %s' % (n, unit))
        n /= 1000.0


# ---------------------------------------------------------------- fetching

_ctx = None


def ssl_context():
    """The default context; on Linux, also the system's certificates when this Python's
    OpenSSL looks for them where this distribution has none (a ready-made program built
    on another distribution)."""
    global _ctx
    if _ctx is not None:
        return _ctx
    ctx = ssl.create_default_context()
    if os.name != 'nt' and sys.platform != 'darwin':
        d = ssl.get_default_verify_paths()
        have = (d.cafile and os.path.isfile(d.cafile)) or (d.capath and os.path.isdir(d.capath) and
                                                            any(n.endswith(('.0', '.pem', '.crt'))
                                                                for n in os.listdir(d.capath)))
        if not have:
            for f in CA_FILES:
                if os.path.isfile(f):
                    ctx.load_verify_locations(cafile=f)
                    break
            else:
                for p in CA_DIRS:
                    if os.path.isdir(p):
                        ctx.load_verify_locations(capath=p)
                        break
    _ctx = ctx
    return ctx


def _url(src, rel):
    return src.rstrip('/') + '/' + rel


def _local(src, rel):
    return os.path.join(src, *rel.split('/'))


def _open(src, rel, start=0, timeout=60):
    """(stream, total size or None, offset it starts at) for rel under src."""
    if not is_url(src):
        f = open(_local(src, rel), 'rb')
        size = os.fstat(f.fileno()).st_size
        f.seek(min(start, size))
        return f, size, min(start, size)
    headers = {'User-Agent': USER_AGENT}
    if start:
        headers['Range'] = 'bytes=%d-' % start
    req = urllib.request.Request(_url(src, rel), headers=headers)
    r = urllib.request.urlopen(req, timeout=timeout, context=ssl_context() if src.startswith('https:') else None)
    length = r.headers.get('Content-Length')
    if start and r.status == 206:
        m = re.match(r'bytes (\d+)-\d+/(\d+)', r.headers.get('Content-Range', ''))
        if m and int(m.group(1)) == start:
            return r, int(m.group(2)), start
        r.close()
        raise OSError('the server answered a part that was not asked for')
    return r, (int(length) if length and length.isdigit() else None), 0    # (a server that ignores Range)


def _retrying(what, fn, stop=None, tries=4):
    delay = 2.0
    for n in range(tries):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise Unavailable('%s: the server says %d %s' % (what, e.code, e.reason))
            err = e
        except (OSError, ValueError) as e:      # URLError, timeouts, cut connections
            err = e
        if n + 1 < tries:
            for _ in range(int(delay * 10)):
                if stop and stop():
                    raise Cancelled()
                time.sleep(0.1)
            delay *= 2
    raise Unavailable('%s: %s' % (what, getattr(err, 'reason', None) or err))


def get_small(src, rel, limit, sha=None, size=None, stop=None):
    """A small file's bytes (an index, a manifest), checked against sha / size when given."""
    def go():
        f, total, _ = _open(src, rel)
        with f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise Unavailable('%s is larger than expected' % rel)
        return data
    data = _retrying(rel, go, stop)
    if size is not None and len(data) != size:
        raise Unavailable('%s has %d bytes, %d expected' % (rel, len(data), size))
    if sha is not None and hashlib.sha256(data).hexdigest() != sha:
        raise Unavailable('%s is not the file its name says (damaged on the way?)' % rel)
    return data


def sha256_file(path, stop=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            if stop and stop():
                raise Cancelled()
    return h.hexdigest()


class Cancelled(Exception):
    pass


def download(src, obj, dest, on_bytes=None, stop=None, tries=6):
    """obj ({"path", "sha256", "size"}) into dest, resuming a .part file left by an earlier
    try; checked against its sha256 as it arrives (a damaged one is fetched once more). on_bytes(n)
    for each block, never more than the file's size in all. A dest already there with the right
    sha256 is kept."""
    if os.path.isfile(dest) and os.path.getsize(dest) == obj['size']:
        if sha256_file(dest, stop) == obj['sha256']:
            if on_bytes:
                on_bytes(obj['size'])
            return dest
        os.remove(dest)
    part = dest + '.part'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    reported = [0]

    def count(upto):
        if upto > reported[0]:
            if on_bytes:
                on_bytes(upto - reported[0])
            reported[0] = upto

    delay = 2.0
    damaged = 0
    err = None
    for n in range(tries):
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        if have > obj['size']:
            os.remove(part)
            have = 0
        if have == obj['size']:         # (complete but not checked: cut off while it was checked)
            if sha256_file(part, stop) == obj['sha256']:
                count(have)
                move(part, dest)
                return dest
            os.remove(part)
            have = 0
        try:
            f, total, at = _open(src, obj['path'], have)
            with f:
                if total is not None and total != obj['size']:
                    raise Unavailable('%s has %d bytes, %d expected' % (obj['path'], total, obj['size']))
                with open(part, 'r+b' if at else 'wb') as out:
                    # hashed as it arrives (the part kept from an earlier try first), so the
                    # volume is not read a second time to check it
                    h = hashlib.sha256()
                    left = at
                    while left:
                        b = out.read(min(left, 1 << 20))
                        if not b:
                            raise OSError('the part file shrank')
                        h.update(b)
                        left -= len(b)
                    out.seek(at)
                    out.truncate()
                    got = at
                    count(got)
                    while True:
                        if stop and stop():
                            raise Cancelled()
                        b = f.read(1 << 20)
                        if not b:
                            break
                        out.write(b)
                        h.update(b)
                        got += len(b)
                        count(got)
            if os.path.getsize(part) != obj['size']:
                raise OSError('the download stopped at %s of %s' % (human(os.path.getsize(part)), human(obj['size'])))
            if h.hexdigest() != obj['sha256']:
                os.remove(part)
                damaged += 1
                if damaged > 1:
                    raise Unavailable('%s is not the file its name says (damaged on the way?)' % obj['path'])
                err = OSError('%s arrived damaged; fetching it again' % obj['path'])
                continue
            move(part, dest)
            return dest
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise Unavailable('%s: the server says %d %s' % (obj['path'], e.code, e.reason))
            if e.code == 416:           # (a part the server says is past the end: start again)
                try:
                    os.remove(part)
                except OSError:
                    pass
            err = e
        except (OSError, ValueError) as e:
            err = e
        if n + 1 < tries:
            for _ in range(int(delay * 10)):
                if stop and stop():
                    raise Cancelled()
                time.sleep(0.1)
            delay = min(delay * 2, 30.0)
    raise Unavailable('%s: %s' % (obj['path'], getattr(err, 'reason', None) or err))


def move(src, dst, tries=20):
    """os.replace, retried for a few seconds on Windows while a virus scanner or the search
    indexer holds the file."""
    for n in range(tries):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if os.name != 'nt' or n + 1 == tries:
                raise
            time.sleep(0.25)


# ---------------------------------------------------------------- formats

def safe_rel(r):
    return isinstance(r, str) and r and not r.startswith('/') and '\\' not in r and ':' not in r and \
        '..' not in r.split('/')


def _obj(v, fp, what, ext):
    if not isinstance(v, dict):
        raise Unavailable('%s is missing' % what)
    m = _PATH.match(str(v.get('path', '')))
    if not m or m.group(1) != fp or m.group(2) != v.get('sha256') or m.group(3) != ext:
        raise Unavailable('%s has a bad path (%r)' % (what, v.get('path')))
    if not isinstance(v.get('size'), int) or v['size'] < 0:
        raise Unavailable('%s has a bad size' % what)
    return v


def entry_format(e):
    """A list entry's manifest format (an entry without one is format 1)."""
    f = e.get('format', BAKE_FORMAT)
    return f if isinstance(f, int) and not isinstance(f, bool) else None


def read_index(data):
    """The bucket's list of bakes -> [entry] (entries this program cannot use are left out)."""
    try:
        d = json.loads(data.decode('utf-8'))
    except ValueError:
        raise Unavailable('the list of ready-made bakes is not readable')
    if not isinstance(d, dict) or d.get('kind') != 'umbra-effects-bakes':
        raise Unavailable('the list of ready-made bakes is not one')
    if d.get('format') != INDEX_FORMAT:
        raise Unavailable('the list of ready-made bakes is in format %r; this Umbra Effects Setup reads %d '
                          '(a newer Umbra Gore & Effects reads it)' % (d.get('format'), INDEX_FORMAT))
    out = []
    for e in d.get('bakes') or []:
        if not isinstance(e, dict) or not _FP.match(str(e.get('fingerprint', ''))):
            continue
        if entry_format(e) not in BAKE_FORMATS:
            continue
        try:
            _obj(e, e['fingerprint'], 'a bake', 'json')
        except Unavailable:
            continue
        out.append(e)
    return out


def candidates(entries, baker, n=CANDIDATES):
    """The bakes to compare with this mod list, newest first, at most n: per fingerprint the
    one with its parts in archives (format 2) when the list has it, else the loose one."""
    usable = sorted((e for e in entries if e.get('baker') == baker),
                    key=lambda e: str(e.get('made', '')), reverse=True)
    best, order = {}, []
    for e in usable:
        fp = e['fingerprint']
        if fp not in best:
            order.append(fp)
            best[fp] = e
        elif entry_format(e) > entry_format(best[fp]):
            best[fp] = e
    return [best[fp] for fp in order[:n]]


def read_manifest(data, entry):
    try:
        b = json.loads(data.decode('utf-8'))
    except ValueError:
        raise Unavailable('the bake manifest is not readable')
    if not isinstance(b, dict) or b.get('kind') != 'umbra-effects-bake':
        raise Unavailable('the bake manifest is not one')
    if b.get('format') not in BAKE_FORMATS:
        raise Unavailable('the bake is in format %r; this Umbra Effects Setup reads %s'
                          % (b.get('format'), ' and '.join(str(f) for f in BAKE_FORMATS)))
    if b.get('format') != entry_format(entry):
        raise Unavailable('the bake manifest is not the one the list names (format %r, the list says %r)'
                          % (b.get('format'), entry_format(entry)))
    fp = str(b.get('fingerprint', ''))
    if not _FP.match(fp) or fp != entry['fingerprint']:
        raise Unavailable('the bake manifest is not the one the list names')
    _obj(b.get('report'), fp, 'the bake report', 'zip')
    vols = b.get('volumes')
    if not isinstance(vols, list) or not vols:
        raise Unavailable('the bake has no volumes')
    for i, v in enumerate(vols):
        _obj(v, fp, 'bake volume %d' % (i + 1), 'zip')
    rel = b.get('relocate', [])
    if not isinstance(rel, list) or not all(safe_rel(r) for r in rel):
        raise Unavailable("the bake's list of files with tokens is bad")
    for k in ('baker', 'models', 'files', 'bytes'):
        if not isinstance(b.get(k, 0), int):
            raise Unavailable("the bake's %s is not a number" % k)
    return b


# ---------------------------------------------------------------- unpacking

def allowed(tools, rel):
    """Only what a bake writes: its reports, gamedata/meshes, its archives, the generated scripts."""
    if not safe_rel(rel):
        return False
    b, f = tools.bake, tools.fracture
    if rel == b.REPORT or rel in b.GENERATED_SCRIPTS or rel.startswith('gamedata/meshes/'):
        return True
    if hasattr(b, 'is_archive') and b.is_archive(rel):          # db/mods/zgo_bake_*.db0 (1.8.2)
        return True
    return bool(f) and rel in (f.REPORT, f.INDEX)


def unpack(tools, zips, dest, on_file=None, stop=None):
    """Unpack the volumes into dest; returns the names. Refuses a name a bake does not write."""
    names = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for i in zf.infolist():
                if i.is_dir():
                    continue
                if not allowed(tools, i.filename):
                    raise Unavailable('the bake has a file it should not have: %s' % i.filename)
                if stop and stop():
                    raise Cancelled()
                p = os.path.join(dest, *i.filename.split('/'))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with zf.open(i) as s, open(p, 'wb') as o:
                    shutil.copyfileobj(s, o, 1 << 20)
                names.append(i.filename)
                if on_file:
                    on_file(len(names), i.filename)
    return names


def fetch_and_unpack(tools, src, objs, cache, dest, on_bytes=None, on_file=None, stop=None,
                     parallel=PARALLEL, unpackers=UNPACKERS):
    """Download objs (volumes) into the folder cache, parallel at a time, and unpack each into
    dest as soon as it is in, while the others still download. on_bytes(n) and on_file(i,
    rel) are called from those threads, one at a time. Returns (the volumes' paths, the
    names unpacked, in objs' order). Anything going wrong stops the rest and is raised."""
    paths = [os.path.join(cache, os.path.basename(o['path'])) for o in objs]
    names = [None] * len(objs)
    halt = threading.Event()
    lock = threading.Lock()
    count = [0]

    def stopped():
        return halt.is_set() or bool(stop and stop())

    def got(n):
        if on_bytes:
            with lock:
                on_bytes(n)

    def placed(_i, rel):
        with lock:
            count[0] += 1
            if on_file:
                on_file(count[0], rel)

    def fetch(i):
        return download(src, objs[i], paths[i], got, stopped)

    def place(i):
        names[i] = unpack(tools, [paths[i]], dest, placed, stopped)

    dl = cf.ThreadPoolExecutor(max(1, parallel))
    up = cf.ThreadPoolExecutor(max(1, unpackers))
    try:
        fetching = {dl.submit(fetch, i): i for i in range(len(objs))}
        placing = []
        for f in cf.as_completed(fetching):
            f.result()
            placing.append(up.submit(place, fetching[f]))
        for f in cf.as_completed(placing):
            f.result()
    except BaseException:
        halt.set()
        raise
    finally:
        dl.shutdown(wait=True, cancel_futures=True)
        up.shutdown(wait=True, cancel_futures=True)
    return paths, [n for ns in names for n in ns]


def win_path(p):
    """How the game (a Windows program) sees a path: as it is on Windows, Z:\\... under Wine."""
    if os.name == 'nt':
        return p
    return 'Z:' + os.path.abspath(p).replace('/', '\\')


def tokens(mo2, anomaly, zgo_cache, profile, zgo_folder):
    """Token -> this machine's value (relocate() escapes where the file format needs it)."""
    out = {}
    for name, p in (('MO2', mo2), ('ANOMALY', anomaly), ('ZGO_CACHE', zgo_cache)):
        if p:
            out['@@UMBRA_%s@@' % name] = p
            out['@@UMBRA_%s_WIN@@' % name] = win_path(p)
            out['@@UMBRA_%s_WIN_ESC@@' % name] = win_path(p)
    for name, v in (('PROFILE', profile), ('ZGO_FOLDER', zgo_folder)):
        if v is not None:
            out['@@UMBRA_%s@@' % name] = v
    return out


def relocate(folder, rels, toks):
    """Put this machine's paths and names into the files that have tokens. In JSON and Lua a
    backslash is written as two, and _ESC tokens always are. Raises Unavailable when a token
    is left that this machine has no value for."""
    for rel in rels:
        p = os.path.join(folder, *rel.split('/'))
        try:
            with open(p, 'rb') as f:
                text = f.read().decode('utf-8')
        except FileNotFoundError:
            continue
        except UnicodeDecodeError:
            raise Unavailable('%s is not text' % rel)
        escaped = rel.lower().endswith(ESCAPED_FORMATS)
        for k in sorted(toks, key=len, reverse=True):     # _WIN_ESC before _WIN
            v = toks[k]
            if escaped or k.endswith('_ESC@@'):
                v = v.replace('\\', '\\\\')
            text = text.replace(k, v)
        left = sorted(set(_TOKEN.findall(text)))
        if left:
            raise Unavailable('%s has paths this machine cannot fill in (%s)' % (rel, ', '.join(left)))
        with open(p, 'wb') as f:
            f.write(text.encode('utf-8'))


def adopt_dates(folder, report_name, game, archives_info):
    """The bake fits (its sources were compared byte for byte where their dates differ): record
    this machine's dates of the models and the game's archives, so the next check compares by
    date and size, as for a bake made here."""
    p = os.path.join(folder, report_name)
    with open(p, encoding='utf-8') as f:
        rep = json.load(f)
    for r in rep.get('results', []):
        src = r.get('src')
        if not src or r.get('src_mtime') is None:
            continue
        try:
            st = os.stat(src)
        except OSError:
            continue
        if r.get('bytes_in') is None or st.st_size == r['bytes_in']:
            r['src_mtime'] = int(st.st_mtime)
    # the bake's own archives (checked by sha256 as they arrived): their sizes, so check()
    # finds one cut short later (a bake packed by Umbra's build has none recorded)
    if rep.get('packed') and not rep.get('archive_bytes'):
        sizes = {}
        for a in rep['packed']:
            try:
                sizes[a] = os.path.getsize(os.path.join(folder, *a.split('/')))
            except OSError:
                pass
        if sizes:
            rep['archive_bytes'] = sizes
    arch = (rep.get('inputs') or {}).get('archives') or {}
    if arch and game:
        now = archives_info(game)
        for a, v in arch.items():
            if v and now.get(a) and list(now[a])[:1] == list(v)[:1]:
                arch[a] = list(now[a])
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rep, f, indent=1)
    os.replace(tmp, p)


def free_bytes(path):
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def same_drive(a, b):
    def dev(p):
        while p and not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        try:
            return os.stat(p).st_dev
        except OSError:
            return None
    da, db = dev(a), dev(b)
    return da is not None and da == db
