"""
Umbra Effects Setup, the logic layer: everything the window does, without the window.

  * where things are: the Umbra Effects folder (this file sits in <Umbra Effects>/tools/zgo_setup),
    the MO2 instance (<MO2>/mods/<Umbra Effects>), its profiles, the game folder;
  * what a bake would make: the models the mod list loads, per source mod,
    and an estimate of time and disk use;
  * "is my bake up to date?": the bake's recorded inputs against the mod list
    as it is now (tools/zgo_baker/bake.py records them);
  * jobs: bake, remove, the props (fracture) bake and kid mode for particles
    (tools/zgo_kidfx: rebuilt with the bake, apply / undo on their own) run in
    a separate worker process (this program again, with --worker), which
    reports through a status file, so the window never blocks and a crash in a
    bake cannot take the window with it;
  * plain-language messages for everything that can go wrong.

Tested headless by dev/build_setup/test_setup.py. Python 3.8+, stdlib only;
the baker itself needs numpy.
"""
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
APP = 'Umbra Effects Setup'
ZGO_MAIN = ('gamedata', 'scripts', 'zgo_main.script')
BAKER = ('tools', 'zgo_baker', 'bake.py')
FRACTURE = ('tools', 'zgo_fracture', 'fracture.py')
KIDFX = ('tools', 'zgo_kidfx', 'kidfx_pe.py')

# Bake stages (bake.STAGES) and how much of the progress bar each one fills
STAGE_WEIGHT = {'prepare': 1, 'unpack': 6, 'resolve': 3, 'bake': 70, 'scripts': 4, 'pack': 10, 'install': 6, 'done': 0}
STAGE_TEXT = {'prepare': 'Getting ready', 'unpack': "Reading the game's own models", 'resolve': 'Reading your mod list',
              'bake': 'Baking models', 'scripts': 'Writing the index', 'install': 'Installing into the Umbra Effects folder',
              'done': 'Done', 'cut': 'Cutting props', 'particles': 'Kid mode for particles',
              'match': 'Looking for a ready-made bake', 'download': 'Downloading the ready-made bake',
              'place': 'Unpacking the ready-made bake', 'pack': 'Packing the small parts into archives'}
# a ready-made bake (task 'download'): each stage's share of the models' part of the bar
DOWNLOAD_SHARE = {'match': (0.0, 0.05), 'download': (0.05, 0.8), 'place': (0.8, 0.88), 'install': (0.88, 0.9),
                  'pack': (0.9, 1.0)}
# a bake made before 1.8.2 left its small parts loose: what the check says about that
LOOSE_TEXT = ('The bake is stored as %s loose files, and the game reads every one of them through MO2 each time it '
              'starts: that is slow. Press "Bake" to pack them into a few archives (a minute or two; nothing is baked '
              'again).')

# Per-model averages from the full G.A.M.M.A bake (docs/integration/baker2.md):
# 4790 models, 3.12 GB of sources -> 2.97 GB baked; caps 250 MB; pieces 3.2 GB;
# generated scripts 6.7 MB; about 100 s on 14 worker processes.
EST_MODEL_RATIO = 0.953          # baked model bytes per source byte
EST_PIECE_RATIO = 1.077          # limb piece bytes per baked model byte
EST_CAP_PER_MODEL = 52e3
EST_GIB_PER_MODEL = 137e3        # body gibs (1.7.1): 657 MB on the full G.A.M.M.A bake
EST_GIB_CPU_PER_MODEL = 0.17     # body gibs: 158 s instead of 100 s for the full bake
EST_KCAP_PER_MODEL = 135e3       # (experimental) caps inside the models
EST_DAMAGE_RATIO = 7.0           # (experimental) damage meshes + chunks per model byte
EST_SCRIPTS_PER_MODEL = 1.4e3
EST_BASE_MODEL = 650e3           # a game model whose size isn't known yet
EST_CPU_SECONDS_PER_MODEL = 0.30
EST_PROPS_BYTES = 6e6
# kid mode for particles on G.A.M.M.A: 14 shaders + 10 copied effects, 70 KB, about 4 s
EST_KIDFX_BYTES = 0.1e6
EST_KIDFX_SECONDS = 5


class SetupError(Exception):
    """Something the player has to fix; the message says what and how."""


# ---------------------------------------------------------------- finding things

def is_mod_root(path):
    return bool(path) and os.path.isfile(os.path.join(path, *ZGO_MAIN)) and os.path.isfile(os.path.join(path, *BAKER))


def find_mod_root(start=None):
    """The Umbra Effects folder: two levels above tools/zgo_setup, or any folder above
    start that looks like it (gamedata/scripts/zgo_main.script + the baker)."""
    start = os.path.abspath(start or HERE)
    d = start
    for _ in range(6):
        if is_mod_root(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _same_dir(a, b):
    """The same folder, however it is spelled (case on Windows, symlinks such
    as /home -> /var/home)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def load_kidfx(mod_root):
    """Kid mode for particles (tools/zgo_kidfx/kidfx_pe.py and its helpers
    sc_tree, sc_blenders) of this Umbra Effects folder: (kidfx_pe, None), (None, why it
    cannot be used) or (None, None) when this version of Umbra Effects does not have it. Its
    functions change files in the folder it is loaded from, so it must be
    this folder's own copy."""
    kdir = os.path.join(mod_root, *KIDFX[:-1])
    if not os.path.isfile(os.path.join(kdir, KIDFX[-1])):
        return None, None
    if kdir not in sys.path:
        sys.path.append(kdir)
    # kidfx_pe turns bytecode files off itself, but only once it runs (after its own
    # .pyc would be written): this way no __pycache__ is left in tools/zgo_kidfx
    sys.dont_write_bytecode = True
    try:
        import kidfx_pe
        import sc_tree  # noqa: F401  (kidfx_pe imports them when it runs; a missing one shows up now)
        import sc_blenders  # noqa: F401
        for need in ('bake', 'copies', 'apply', 'revert', 'status', 'MOD_ROOT', 'COPIES'):
            if not hasattr(kidfx_pe, need):
                raise AttributeError('kidfx_pe.%s is missing' % need)
        if not hasattr(sc_tree, 'Paths'):
            raise AttributeError('sc_tree.Paths is missing')
        if not _same_dir(kidfx_pe.MOD_ROOT, mod_root):
            raise ImportError('another copy of it is already loaded (%s)' % kidfx_pe.MOD_ROOT)
        return kidfx_pe, None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


class Tools:
    """The baker (and the props fracture tool and kid mode for particles when
    they are installed), imported from the Umbra Effects folder itself, so this program
    always runs the baker that came with the mod."""

    def __init__(self, mod_root):
        if not is_mod_root(mod_root):
            raise SetupError('%s is not the Umbra Gore & Effects folder (it needs gamedata/scripts/zgo_main.script '
                             'and tools/zgo_baker/bake.py). Choose the Umbra Effects folder inside your MO2 "mods" folder.'
                             % mod_root)
        self.mod = os.path.abspath(mod_root)
        baker_dir = os.path.join(self.mod, 'tools', 'zgo_baker')
        if baker_dir not in sys.path:
            sys.path.insert(0, baker_dir)
        try:
            import numpy  # noqa: F401
        except ImportError:
            raise SetupError('Python is missing numpy, which the baker needs. Install it with '
                             '"python3 -m pip install numpy" (or your system\'s python3-numpy package), '
                             'or use the ready-made Umbra Effects Setup program in tools/zgo_setup.')
        try:
            import bake
        except Exception as e:  # noqa: BLE001
            raise SetupError("The baker in %s could not be loaded (%s: %s). Reinstall Umbra Gore & Effects."
                             % (baker_dir, type(e).__name__, e))
        if os.path.normcase(os.path.abspath(bake.MOD_ROOT)) != os.path.normcase(self.mod):
            raise SetupError('Another copy of the baker is already loaded (%s); start Umbra Effects Setup again.' % bake.MOD_ROOT)
        self.bake = bake
        import limbs
        import resolve
        self.limbs, self.resolve = limbs, resolve
        self.fracture = None
        self.fracture_problem = None
        fdir = os.path.join(self.mod, 'tools', 'zgo_fracture')
        if os.path.isfile(os.path.join(fdir, 'fracture.py')):
            if fdir not in sys.path:
                sys.path.append(fdir)
            try:
                import fracture
                for need in ('bake', 'remove', 'Options', 'read_report', 'STAGES', 'REPORT'):
                    if not hasattr(fracture, need):
                        raise AttributeError('fracture.%s is missing' % need)
                self.fracture = fracture
            except Exception as e:  # noqa: BLE001
                self.fracture_problem = '%s: %s' % (type(e).__name__, e)
        self.kidfx, self.kidfx_problem = load_kidfx(self.mod)


def profiles(mo2):
    """MO2 profiles (folders with a modlist.txt), sorted."""
    d = os.path.join(mo2 or '', 'profiles')
    try:
        names = sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, 'modlist.txt')))
    except OSError:
        return []
    return names


def looks_like_mo2(path):
    return bool(path) and os.path.isdir(os.path.join(path, 'mods')) and os.path.isdir(os.path.join(path, 'profiles'))


def looks_like_game(path):
    return bool(path) and os.path.isfile(os.path.join(path, 'db', 'meshes', 'meshes_actors.db0'))


class Paths:
    """Where the bake reads from and writes to. Any of them may be None.
    out is where the bake goes: the Umbra Effects folder itself (tests use another)."""

    def __init__(self, mod, mo2=None, profile=None, game=None, out=None, cache=None):
        self.mod, self.mo2, self.profile, self.game = mod, mo2, profile, game
        self.out = out or mod
        self.cache = cache            # the baker's work folder (None = its default)

    def as_dict(self):
        return {'mod': self.mod, 'mo2': self.mo2, 'profile': self.profile, 'game': self.game, 'out': self.out,
                'cache': self.cache}

    def __repr__(self):
        return 'Paths(%r)' % self.as_dict()


def detect(tools):
    """MO2 folder, profile and game folder for this Umbra Effects folder, the way the
    baker finds them: <MO2>/mods/<Umbra Effects>, MO2's selected profile and game path
    from ModOrganizer.ini (a Wine Z:\\ path becomes a Linux path)."""
    mo2, profile, game = tools.bake.mo2_defaults(tools.mod)
    if not looks_like_mo2(mo2):
        mo2 = None
    if mo2 and profile not in profiles(mo2):
        names = profiles(mo2)
        profile = 'G.A.M.M.A' if 'G.A.M.M.A' in names else (names[0] if len(names) == 1 else None)
    if game and not looks_like_game(game):
        game = None
    return Paths(tools.mod, mo2, profile, game)


def problems(tools, paths):
    """What stops a bake, in plain words ([] = ready)."""
    out = []
    if not looks_like_mo2(paths.mo2):
        out.append("Mod Organizer 2's folder is not set. Choose the folder that holds MO2's \"mods\" and \"profiles\" "
                   "folders (normally the one Umbra Effects is installed in, two levels above the Umbra Effects folder).")
    elif not paths.profile or paths.profile not in profiles(paths.mo2):
        out.append('Choose the MO2 profile you play with (for G.A.M.M.A. it is usually "G.A.M.M.A").')
    if not looks_like_game(paths.game):
        out.append('The game folder is not set. Choose the Anomaly folder: the one that holds the "db" and "bin" '
                   'folders (the MO2 setting "Game folder" shows it).')
    return out


def zgo_folder(tools, paths):
    """The folder the bake goes into: the Umbra Effects folder (tests bake elsewhere)."""
    return os.path.normpath(paths.out or tools.mod)


def other_zgo_copies(tools, paths):
    """Enabled mods that are another copy of Umbra Effects (a release kept as a
    fallback, say). The baker never reads their models."""
    if not hasattr(tools.bake, 'other_zgo_mods'):
        return []
    own = os.path.basename(zgo_folder(tools, paths))
    return [m for m in tools.bake.other_zgo_mods(paths.mo2, paths.profile, tools.mod) if m != own]


def warnings(tools, paths):
    """Worth knowing before a bake, but not in the way of one."""
    out = []
    if problems(tools, paths):
        return out
    zgo = os.path.basename(zgo_folder(tools, paths))
    try:
        enabled = tools.resolve.enabled_mods(paths.mo2, paths.profile)
    except OSError:
        return out
    inside = os.path.normcase(os.path.dirname(zgo_folder(tools, paths))) == \
        os.path.normcase(os.path.normpath(os.path.join(paths.mo2, 'mods')))
    if inside and zgo not in enabled:
        out.append('"%s" is not enabled in the MO2 profile "%s". You can bake now, but the game only uses the '
                   'bake once Umbra Gore & Effects is ticked in MO2.' % (zgo, paths.profile))
    others = other_zgo_copies(tools, paths)
    if others:
        out.append('Another copy of Umbra Gore & Effects is enabled in this profile (%s). Enable only one copy of Umbra Effects; '
                   'the bake never uses models from the other copy.' % ', '.join('"%s"' % m for m in others))
    return out


# ---------------------------------------------------------------- choices

class Choices:
    """What the player ticked. Defaults: the baker's defaults (models, caps,
    pieces, wound sites, body gibs, props), kid mode for particles on, every
    experimental part off, a ready-made bake downloaded when one fits (download).
    (A report from before 1.7.1 has no 'gibs': ticked.)"""
    FIELDS = ('caps', 'pieces', 'wounds', 'gibs', 'experimental_caps', 'experimental_damage', 'props',
              'experimental_props', 'kid_particles', 'download')

    def __init__(self, caps=True, pieces=True, wounds=True, experimental_caps=False, experimental_damage=False,
                 props=True, experimental_props=False, jobs=None, kid_particles=True, gibs=True, download=True):
        self.caps, self.pieces, self.wounds, self.gibs = caps, pieces, wounds, gibs
        self.experimental_caps, self.experimental_damage = experimental_caps, experimental_damage
        self.props, self.experimental_props = props, experimental_props
        self.kid_particles = kid_particles
        self.download = download
        self.jobs = jobs or default_jobs()

    def as_dict(self):
        d = {k: bool(getattr(self, k)) for k in self.FIELDS}
        d['jobs'] = int(self.jobs)
        return d

    @classmethod
    def from_dict(cls, d):
        c = cls()
        for k in cls.FIELDS:
            if k in d:
                setattr(c, k, bool(d[k]))
        if d.get('jobs'):
            c.jobs = max(1, int(d['jobs']))
        return c

    def __repr__(self):
        return 'Choices(%r)' % self.as_dict()


def default_jobs():
    return max(1, (os.cpu_count() or 4) - 2)


def last_choices(tools, out=None):
    """The ticks of the last bake (so a re-bake makes the same thing). Kid
    mode for particles stays ticked unless the particle shaders were set back
    to the game's own (the undo button), so a re-bake does not undo the undo."""
    c = Choices()
    out = out or tools.mod
    rep = tools.bake.read_report(out) or {}
    for k, v in (rep.get('options') or {}).items():
        if k in Choices.FIELDS:
            setattr(c, k, bool(v))
    if tools.fracture:
        frep = tools.fracture.read_report(out)
        if frep:
            c.props = True
            c.experimental_props = bool((frep.get('options') or {}).get('experimental_native'))
    if not getattr(tools, 'kidfx', None):
        c.kid_particles = False
    else:
        k = kidfx_for(tools, Paths(tools.mod, out=out))
        if k is not None:
            try:
                c.kid_particles = k.status().get('state') != 'reverted'
            except Exception:  # noqa: BLE001  (unreadable: keep the default)
                pass
    return c


def bake_options(tools, paths, choices, only=None):
    o = tools.bake.Options(mo2=paths.mo2, profile=paths.profile, anomaly=paths.game, out=paths.out, only=only,
                           jobs=choices.jobs, caps=choices.caps, pieces=choices.pieces, wounds=choices.wounds,
                           gibs=choices.gibs,
                           experimental_caps=choices.experimental_caps,
                           experimental_damage=choices.experimental_damage)
    if paths.cache:
        o.cache = paths.cache
    return o


def fracture_options(tools, paths, choices):
    if not tools.fracture:
        return None
    return tools.fracture.Options(mo2=paths.mo2, profile=paths.profile, anomaly=paths.game, out=paths.out,
                                  experimental_native=choices.experimental_props)


# ---------------------------------------------------------------- kid mode for particles (tools/zgo_kidfx)

def kidfx_for(tools, paths):
    """The kid-mode particle tool when it may act for these paths, else None.
    It changes files in the Umbra Effects folder it came with (gamedata/particles,
    gamedata/shaders, its own list of copies), so only when the bake goes into
    that folder too; a bake into another folder (the tests, the self-test)
    leaves it alone."""
    k = getattr(tools, 'kidfx', None)
    if k is None:
        return None
    if not _same_dir(paths.out or tools.mod, k.MOD_ROOT):
        return None
    return k


def kidfx_unavailable(tools, paths):
    """Why kidfx_for() is None, in plain words."""
    if getattr(tools, 'kidfx', None) is None:
        if getattr(tools, 'kidfx_problem', None):
            return ('Kid mode for particles (tools/zgo_kidfx) could not be loaded (%s). Reinstall Umbra Gore & Effects.'
                    % tools.kidfx_problem)
        return 'Kid mode for particles (tools/zgo_kidfx) is not installed with this version of Umbra Effects.'
    return ('Kid mode for particles changes the Umbra Effects folder it came with (%s), and this run writes into %s, '
            'so it was left alone.' % (tools.kidfx.MOD_ROOT, paths.out))


def kidfx_paths(tools, paths):
    """The game / MO2 the player picked, the way kidfx reads them (sc_tree.Paths)."""
    import sc_tree      # next to kidfx_pe in tools/zgo_kidfx (load_kidfx put it on sys.path)
    return sc_tree.Paths(mo2=paths.mo2, profile=paths.profile, game=paths.game, mod_root=tools.kidfx.MOD_ROOT)


def kidfx_copy_count(k):
    """How many effects of other mods kidfx has copied into Umbra Effects (its kidfx_copies.json)."""
    try:
        with open(k.COPIES, encoding='utf-8') as f:
            return len(json.load(f).get('copies') or {})
    except (OSError, ValueError, AttributeError):
        return 0


def kidfx_summary(r):
    """Counts from kidfx.bake()'s report, for the log and the summary."""
    files = (r.get('shaders') or {}).get('files') or []
    copies = (r.get('copies') or {}).get('copies') or []
    st = [c.get('status') or '' for c in copies]
    return {'shaders': len(files), 'shaders_written': sum(1 for f in files if (f.get('status') or '').endswith('written')),
            'copied': sum(1 for s in st if s == 'copied'),
            'copies': sum(1 for s in st if s in ('copied', 'ours (copied earlier)') or s.startswith('refreshed')),
            'skipped': sum(1 for s in st if s.startswith('skipped')),
            'applied': len((r.get('apply') or {}).get('changed') or []),
            'problems': len((r.get('apply') or {}).get('problems') or [])}


def kidfx_friendly(exc):
    """A failed kidfx step in plain words (its own messages are short:
    'cannot find the game / MO2: ...')."""
    if isinstance(exc, (OSError, MemoryError, SetupError)):
        return friendly(exc)
    if isinstance(exc, (RuntimeError, ValueError)) and str(exc):
        m = str(exc)
        return '%s%s. The log has the details.' % (m[:1].upper(), m[1:])
    return friendly(exc)


def check_kidfx(tools, paths):
    """A short line about kid mode for particles: (state, text). state:
    'none' (no tool, or a bake elsewhere), 'ok' (on), 'off' (the game's own
    particle shaders: the undo button), 'stale' (only partly on). Reads only
    the Umbra Effects folder (about 0.1 s)."""
    k = kidfx_for(tools, paths)
    if k is None:
        return 'none', ''
    try:
        st = k.status()
    except Exception as e:  # noqa: BLE001
        return 'stale', 'Kid mode for particles: could not be read (%s).' % kidfx_friendly(e)
    on = sum(n for s, n in (st.get('shaders') or {}).items() if str(s or '').lower().startswith('zgo\\particle_'))
    if st.get('state') == 'reverted':
        return 'off', ("Kid mode for particles: off. Particles use the game's own shaders, so kid mode cannot hide "
                       'particles already flying ("Apply now" turns it on).')
    wrong = st.get('inconsistent') or []
    if st.get('state') == 'partial' or wrong:
        return 'stale', ('Kid mode for particles: only partly on (%d effect%s %s the wrong shader). Press "Apply now" '
                         'or bake again.' % (len(wrong), '' if len(wrong) == 1 else 's', 'uses' if len(wrong) == 1 else 'use'))
    n = kidfx_copy_count(k)
    return 'ok', ("Kid mode for particles: on (%d gory effects use Umbra Effects' particle shaders%s)."
                  % (on, (', %d of them copied from your other mods' % n) if n else ''))


# ---------------------------------------------------------------- what a bake would make

def human_bytes(n):
    n = float(n or 0)
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            if unit == 'bytes':
                return '%d bytes' % n
            return ('%.1f %s' if n < 10 else '%.0f %s') % (n, unit)
        n /= 1000.0


def human_seconds(s):
    s = max(0, int(round(s)))
    if s < 90:
        return '%d seconds' % max(s, 1)
    m = int(round(s / 60.0))
    if m < 90:
        return '%d minutes' % m
    return '%.1f hours' % (s / 3600.0)


class Plan:
    """What a bake would make for these paths and choices."""

    def __init__(self):
        self.models = 0                 # models to bake
        self.by_source = []             # [(source name, count)] most first; '' = the game's own archives
        self.source_bytes = 0
        self.estimate = {}              # part -> bytes
        self.total = 0
        self.seconds = 0
        self.free = {}                  # folder -> free bytes
        self.needed = {}                # folder -> bytes needed free while baking
        self.overrides = []             # [(mod, count)] mods above ZGO that replace baked models
        self.old_bytes = 0
        self.notes = []

    def short(self):
        return '%d models, about %s on disk, about %s' % (self.models, human_bytes(self.total), human_seconds(self.seconds))


def _skip_names(tools, paths=None):
    """Mods whose models are never bake sources: Umbra Effects itself, the 1.4 bake
    folder and other enabled copies of Umbra Effects (the baker skips the same)."""
    b = tools.bake
    out = (b.OLD_OUT_NAME, os.path.basename(os.path.normpath(tools.mod)))
    if paths is not None and paths.out:
        out += (os.path.basename(os.path.normpath(paths.out)),)
    if paths is not None and paths.mo2 and paths.profile:
        out += tuple(other_zgo_copies(tools, paths))
    return out


def cache_dir(tools, paths=None):
    return (paths.cache if paths is not None and paths.cache else None) or tools.bake.CACHE


def _base_dir(tools, paths=None):
    return os.path.join(cache_dir(tools, paths), 'base', 'gamedata')


def winners(tools, paths, progress=None):
    """{model key: source path} as the next bake would see it. Game models
    come from the baker's cache of the archives when it exists (else they are
    counted from the bake report, or not at all)."""
    base = _base_dir(tools, paths)
    return tools.resolve.winners(paths.mo2, paths.profile, skip=_skip_names(tools, paths),
                                 base_dirs=(base,) if os.path.isdir(base) else (),
                                 progress=progress)


def source_name(tools, paths, src):
    """The MO2 mod a model file comes from ('' = the game's own archives).
    Read from the path itself (.../mods/<mod>/gamedata/meshes/...), so it does
    not matter how the MO2 folder is spelled (Linux path, Z:\\ under Wine)."""
    if not src:
        return ''
    p = src.replace('\\', '/')
    i = p.lower().rfind('/gamedata/meshes/')
    if i < 0:
        return ''
    head = p[:i]
    j = head.rfind('/')
    if j < 0 or head[:j].lower().rsplit('/', 1)[-1] != 'mods':
        return ''
    return head[j + 1:]


def overriding_mods(tools, paths, keys):
    """[(mod, count)]: enabled mods with a HIGHER priority than Umbra Effects that ship
    some of these models; the game loads theirs instead of Umbra Effects' baked copy."""
    zgo = os.path.basename(zgo_folder(tools, paths))
    try:
        enabled = tools.resolve.enabled_mods(paths.mo2, paths.profile)
    except OSError:
        return []
    if zgo not in enabled:
        return []
    out = []
    keys = set(keys)
    for m in enabled[:enabled.index(zgo)]:
        root = os.path.join(paths.mo2, 'mods', m, 'gamedata', 'meshes')
        n = 0
        for sub in ('actors', 'monsters'):
            top = os.path.join(root, sub)
            if not os.path.isdir(top):
                continue
            for dp, _, fs in os.walk(top):
                for fn in fs:
                    if fn.lower().endswith('.ogf'):
                        rel = os.path.relpath(os.path.join(dp, fn), root)
                        if rel[:-4].replace('/', '\\').lower() in keys:
                            n += 1
        if n:
            out.append((m, n))
    return out


def _disk_free(path):
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    try:
        return shutil.disk_usage(p or '.').free
    except OSError:
        return None


def _same_drive(a, b):
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
    return dev(a) is not None and dev(a) == dev(b)


def plan(tools, paths, choices, progress=None):
    """What a bake with these choices would make (counts, sizes, time)."""
    p = Plan()
    if problems(tools, paths):
        return p
    win = winners(tools, paths, progress)
    rep = tools.bake.read_report(paths.out) or {}
    recorded = {r.get('key'): r for r in rep.get('results', [])}
    if not os.path.isdir(_base_dir(tools, paths)):
        # the game's models are not unpacked yet: count them from the last bake
        for k, r in recorded.items():
            if k and k not in win and not source_name(tools, paths, r.get('src')):
                win[k] = None
        if not recorded:
            p.notes.append("The game's own models are counted once the first bake has unpacked them; "
                           "the estimate covers the models from your mods only.")
    counts = {}
    for k, src in win.items():
        name = source_name(tools, paths, src) if src else ''
        counts[name] = counts.get(name, 0) + 1
        size = None
        if src:
            try:
                size = os.path.getsize(src)
            except OSError:
                size = None
        if size is None:
            size = (recorded.get(k) or {}).get('bytes_in') or EST_BASE_MODEL
        p.source_bytes += size
    p.models = len(win)
    p.by_source = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    models = p.source_bytes * EST_MODEL_RATIO
    est = {'models': models, 'scripts': p.models * EST_SCRIPTS_PER_MODEL}
    if choices.caps:
        est['caps'] = p.models * EST_CAP_PER_MODEL
    if choices.pieces:
        est['pieces'] = models * EST_PIECE_RATIO
    if choices.gibs:
        est['gibs'] = p.models * EST_GIB_PER_MODEL
    if choices.experimental_caps:
        est['experimental_caps'] = p.models * EST_KCAP_PER_MODEL
    if choices.experimental_damage:
        est['experimental_damage'] = models * EST_DAMAGE_RATIO
    if choices.props and tools.fracture:
        est['props'] = EST_PROPS_BYTES
    kid = getattr(choices, 'kid_particles', False) and kidfx_for(tools, paths) is not None
    if kid:
        est['kid_particles'] = EST_KIDFX_BYTES
    p.estimate = est
    p.total = sum(est.values())
    cpu = EST_CPU_SECONDS_PER_MODEL * (8 if choices.experimental_damage else 1) + \
        (EST_GIB_CPU_PER_MODEL if choices.gibs else 0)
    p.seconds = 20 + p.models * cpu / max(1, choices.jobs) + (EST_KIDFX_SECONDS if kid else 0)
    p.old_bytes = rep.get('bytes') or 0
    cache = cache_dir(tools, paths)
    # the bake is built in the cache folder, then moved into the ZGO folder;
    # the old bake is deleted only when the new one is complete
    p.free[cache] = _disk_free(cache)
    p.needed[cache] = p.total
    if not _same_drive(cache, paths.out):
        p.free[paths.out] = _disk_free(paths.out)
        p.needed[paths.out] = max(0, p.total - p.old_bytes)
    p.overrides = overriding_mods(tools, paths, win.keys())
    return p


def space_problems(p):
    out = []
    for folder, need in p.needed.items():
        free = p.free.get(folder)
        if free is not None and need > free * 0.95:
            out.append('The drive with %s has %s free, and the bake needs about %s there. Free some space, '
                       'or untick "Limb pieces" (the largest part). The work folder can be moved to another drive '
                       'with --cache DIR (or the ZGO_BAKER_CACHE environment variable).'
                       % (folder, human_bytes(free), human_bytes(need)))
    return out


# ---------------------------------------------------------------- is my bake up to date?

class Status:
    """The answer to "is my bake up to date?".
    state: 'none' (no bake), 'ok', 'stale' (bake again), 'order' (fix the
    load order in MO2), 'broken' (incomplete bake: bake again or remove)."""

    def __init__(self, state='none', headline='', reasons=None, advice='', info=None):
        self.state, self.headline, self.advice = state, headline, advice
        self.reasons = reasons or []        # why it is not up to date, one line each
        self.info = info or []              # worth knowing, not a reason to bake
        self.details = []                   # long lists for the log
        self.report = None
        self.loose = 0                      # loose small parts to pack (bakes made before 1.8.2)

    def text(self):
        lines = [self.headline]
        lines += ['  - ' + r for r in self.reasons]
        if self.advice:
            lines.append(self.advice)
        lines += ['  (' + i + ')' for i in self.info]
        return '\n'.join(lines)

    def as_dict(self):
        return {'state': self.state, 'headline': self.headline, 'reasons': self.reasons, 'advice': self.advice,
                'info': self.info, 'loose': self.loose}


def _norm(p):
    return os.path.normcase(os.path.normpath(p)) if p else p


def _same_file(a, b):
    """The same file, also when reached another way (a symlinked folder: /home and /var/home)."""
    if _norm(a) == _norm(b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _md5(path, cancel=None):
    import hashlib
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            if cancel and cancel():
                raise Cancelled()
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Cancelled(Exception):
    pass


def _group(items, n=3):
    """'a, b, c and 4 more'"""
    items = list(items)
    if len(items) <= n:
        return ', '.join(items)
    return '%s and %d more' % (', '.join(items[:n]), len(items) - n)


def _mod_label(m):
    return "the game's own archives" if not m else 'mod "%s"' % m


def _who(m):
    return 'The game itself' if not m else 'Mod "%s"' % m


# what a prebaked bake must have been made with: the player's own settings (setup_gui's LABEL)
PREBAKE_SETTINGS = (('caps', 'Stump caps'), ('pieces', 'Limb pieces'), ('wounds', 'Wound sites'), ('gibs', 'Body gibs'),
                    ('experimental_caps', 'Caps inside every model (experimental)'),
                    ('experimental_damage', 'Damage meshes and gib chunks (experimental)'),
                    ('experimental_props', 'Game breaks crates and stools itself (experimental)'))


def check(tools, paths, progress=None, cancel=None, deep=False, report=None, prebaked=False, props_report=None,
          choices=None):
    """Compare the last bake's recorded inputs with the mod list now.
    progress(done, total, message); deep=True hashes every source file even
    when its size and date match.
    prebaked=True: report is a bake made on another machine (Umbra Setup's prebaked
    bakes) whose files are not here yet: would it fit this mod list? Its files and
    profile name are not checked, the game's archives only by size, and a model
    whose source file has another date must have the recorded md5. It must also
    have been made with the player's settings: choices, else those of their last bake
    here (the defaults without one); props_report is its props report, if it has one."""
    say = progress or (lambda *a: None)
    b = tools.bake
    rep = report if (report is not None or prebaked) else b.read_report(paths.out)
    st = Status()
    st.report = rep
    if rep is None:
        st.state, st.headline = 'none', 'Not baked yet.'
        st.advice = 'Press "Bake" to bake the models for your mod list.'
        return st
    if rep.get('status') == 'installing':
        st.state, st.headline = 'broken', 'The last bake stopped half-way while it was installing.'
        st.advice = 'Press "Bake" to bake again (or "Remove bake" to remove what it left).'
        return st
    reasons, info = [], []
    # ---- the baked files are all there (a pack that stopped half-way: the archives are; the
    # loose copies it was deleting may not be, and "Bake" finishes it)
    packing = rep.get('status') == 'packing'
    files = [] if prebaked else [f for f in rep.get('files') or []
                                 if not (packing and hasattr(b, 'packable') and b.packable(f))]
    missing = []
    for i, rel in enumerate(files):
        if not os.path.isfile(os.path.join(paths.out, *rel.split('/'))):
            missing.append(rel)
        if (i + 1) % 5000 == 0:
            say(i + 1, len(files), 'checking the baked files')
            if cancel and cancel():
                raise Cancelled()
    if missing:
        st.state = 'broken'
        st.headline = '%d of the %d baked files are missing (for example %s).' % (len(missing), len(files), missing[0])
        st.advice = 'Press "Bake" to bake again.'
        st.details = missing[:200]
        return st
    inputs = rep.get('inputs') or {}
    rep_version = rep.get('version', 1)
    baker = inputs.get('baker') or (1 if rep_version < 2 else 2)
    if baker < b.BAKER_VERSION:
        reasons.append('This bake was made by an older Umbra Gore & Effects (baker version %d; this version needs %d).'
                       % (baker, b.BAKER_VERSION))
    elif baker > b.BAKER_VERSION:
        reasons.append('This bake was made by a newer Umbra Gore & Effects than the one installed (baker version %d, '
                       'installed %d).' % (baker, b.BAKER_VERSION))
    try:
        tables_now = tools.limbs.canonical(tools.limbs.load(tools.mod))
    except Exception as e:  # noqa: BLE001
        tables_now = None
        info.append("Umbra Effects' body-part tables could not be read (%s)" % e)
    if inputs.get('tables') and tables_now and inputs['tables'] != tables_now:
        reasons.append("Umbra Effects' body-part tables changed since this bake (an update of Umbra Effects).")
    if prebaked:
        want = choices if choices is not None else last_choices(tools, paths.out)
        got = Choices.from_dict(rep.get('options') or {})        # (a report without 'gibs' had them)
        got.experimental_props = (bool((props_report.get('options') or {}).get('experimental_native'))
                                  if props_report else want.experimental_props)
        diff = [(label, getattr(got, k)) for k, label in PREBAKE_SETTINGS if bool(getattr(got, k)) != bool(getattr(want, k))]
        if diff:
            reasons.append('It was made with other settings than yours: %s.' % '; '.join(
                '"%s" %s there, %s in yours' % (label, 'on' if on else 'off', 'off' if on else 'on') for label, on in diff))
    if not prebaked and rep.get('profile') and paths.profile and rep['profile'] != paths.profile:
        reasons.append('This bake was made for the MO2 profile "%s"; you chose "%s".' % (rep['profile'], paths.profile))
    arch = inputs.get('archives') or {}
    if arch and paths.game:
        now = b.archives_info(paths.game)
        # [size, mtime]; another machine's archives have their own dates
        n = 1 if prebaked else 2
        changed = [a for a, v in arch.items() if v and now.get(a) and list(now[a])[:n] != list(v)[:n]]
        if changed:
            reasons.append("The game's own model archives changed since this bake (%s)." % _group(changed))
    # ---- model by model: which mod wins now, and is it the same file
    say(0, 1, 'reading your mod list')
    win = winners(tools, paths)
    base_known = os.path.isdir(_base_dir(tools, paths))
    recorded = {r['key']: r for r in rep.get('results', []) if r.get('key')}
    added, gone, moved, changed = {}, {}, {}, {}
    keys = sorted(set(win) | set(recorded))
    todo = []
    for k in keys:
        r = recorded.get(k)
        src = win.get(k)
        if r is None:
            added.setdefault(source_name(tools, paths, src), []).append(k)
            continue
        was = r.get('src_mod')
        if was is None:
            was = source_name(tools, paths, r.get('src'))
        if src is None:
            if not was and not base_known:
                continue                    # a game model; its archives are checked above
            gone.setdefault(was, []).append(k)
            continue
        now_mod = source_name(tools, paths, src)
        if now_mod != was:
            moved.setdefault((was, now_mod), []).append(k)
            continue
        todo.append((k, src, r))
    for i, (k, src, r) in enumerate(todo):
        if (i + 1) % 200 == 0:
            say(i + 1, len(todo), 'comparing models')
        if cancel and cancel():
            raise Cancelled()
        try:
            stt = os.stat(src)
        except OSError:
            gone.setdefault(source_name(tools, paths, src), []).append(k)
            continue
        if r.get('bytes_in') is not None and stt.st_size != r['bytes_in']:
            changed.setdefault(source_name(tools, paths, src), []).append(k)
            continue
        same_time = r.get('src_mtime') and int(stt.st_mtime) == r['src_mtime']
        if (deep or not same_time) and r.get('src_md5'):
            if _md5(src, cancel) != r['src_md5']:
                changed.setdefault(source_name(tools, paths, src), []).append(k)
        elif prebaked and not same_time:
            changed.setdefault(source_name(tools, paths, src), []).append(k)    # nothing to compare it with
    for m, ks in sorted(added.items()):
        reasons.append('%s adds %d model%s the bake does not have (e.g. %s).'
                       % (_who(m), len(ks), 's' if len(ks) != 1 else '', ks[0]))
    for m, ks in sorted(gone.items()):
        reasons.append('%d baked model%s came from %s, which no longer provides %s (e.g. %s).'
                       % (len(ks), 's' if len(ks) != 1 else '', _mod_label(m), 'them' if len(ks) != 1 else 'it', ks[0]))
    for (a, c), ks in sorted(moved.items()):
        reasons.append('%d model%s now come%s from %s instead of %s (e.g. %s).'
                       % (len(ks), 's' if len(ks) != 1 else '', '' if len(ks) != 1 else 's', _mod_label(c), _mod_label(a), ks[0]))
    for m, ks in sorted(changed.items()):
        reasons.append('%s changed %d model%s since the bake (e.g. %s).'
                       % (_who(m), len(ks), 's' if len(ks) != 1 else '', ks[0]))
    st.details = ['%s: %s' % (kind, k) for kind, groups in (('added', added), ('gone', gone), ('changed', changed))
                  for ks in groups.values() for k in ks]
    st.details += ['moved: %s' % k for ks in moved.values() for k in ks]
    # ---- a mod above ZGO wins over the baked copies
    baked_keys = [r['key'] for r in rep.get('results', []) if r.get('status') == 'ok']
    over = overriding_mods(tools, paths, baked_keys)
    zgo = os.path.basename(zgo_folder(tools, paths))
    if recorded and not any(r.get('src_md5') for r in recorded.values()):
        info.append('This bake was made before Umbra Effects Setup recorded what each model was baked from, so a mod that '
                    'was updated in place cannot be noticed; bake once more to fix that')
    if rep.get('errors'):
        info.append('%d model%s could not be baked last time; the game uses %s unchanged.'
                    % (rep['errors'], 's' if rep['errors'] != 1 else '', 'them' if rep['errors'] != 1 else 'it'))
    if rep.get('time'):
        info.append('Baked %s, %d models, %s.' % (rep['time'], rep.get('baked', 0), human_bytes(rep.get('bytes', 0))))
    st.reasons, st.info = reasons, info
    if prebaked:
        st.state = 'stale' if reasons else ('order' if over else 'ok')
        st.headline = ('The prebaked bake does not fit your mod list.' if reasons else
                       'The prebaked bake fits your mod list.')
        st.advice = 'Bake for your own mod list instead.' if reasons else ''
        if over:
            st.info.append('Once it is in, %s load%s after Umbra Gore & Effects and hide%s some of it'
                           % (', '.join('"%s"' % m for m, _ in over), 's' if len(over) == 1 else '',
                              's' if len(over) == 1 else ''))
        return st
    if reasons:
        st.state = 'stale'
        st.headline = 'Your bake is out of date.'
        st.advice = 'Press "Bake" to bake again for your mod list as it is now.'     # (a new bake is packed)
    elif over:
        st.state = 'order'
        st.headline = 'Your bake is up to date, but another mod hides some of it.'
    else:
        st.state = 'ok'
        st.headline = 'Your bake is up to date.'
    if over:
        names = ', '.join('"%s" (%d models)' % mc for mc in over)
        line = ('%s load%s after Umbra Gore & Effects and replace%s baked models, so the game shows the unbaked ones. '
                'In MO2, drag "%s" below %s in the left pane (lower = wins), then start the game; '
                'no new bake is needed for that.' % (names, 's' if len(over) == 1 else '', 's' if len(over) == 1 else '',
                                                     zgo, 'it' if len(over) == 1 else 'them'))
        if st.state == 'order':
            st.advice = line
        else:
            st.reasons.append(line)
    if not reasons and hasattr(b, 'loose_files'):
        st.loose = len(b.loose_files(rep))
    if st.loose:
        st.headline += ' It needs packing, though.'
        st.advice = LOOSE_TEXT % '{:,}'.format(st.loose) + ((' ' + st.advice) if st.advice else '')
    return st


def check_props(tools, paths):
    """A short line about the props (fracture) bake: (state, text)."""
    f = tools.fracture
    if not f:
        return 'none', ''
    rep = f.read_report(paths.out)
    if not rep:
        return 'none', 'Breakable props: not baked yet.'
    changed = []
    try:
        w = tools.resolve.winners(paths.mo2, paths.profile, subdirs=('meshes/dynamics',), skip=_skip_names(tools, paths))
    except OSError:
        w = {}
    for r in rep.get('results', []):
        v, src = r.get('visual'), r.get('source')
        if not v or r.get('status') != 'ok':
            continue
        now = w.get(v)
        was_file = bool(src) and ':' not in os.path.basename(src) and os.path.isabs(src)
        if now and (not was_file or not _same_file(now, src)):
            changed.append(v)
        elif not now and was_file:
            changed.append(v)
    if changed:
        return 'stale', 'Breakable props: %d prop model%s changed since their bake (%s).' % (
            len(changed), 's' if len(changed) != 1 else '', _group(changed))
    return 'ok', 'Breakable props: up to date (%d models).' % sum(1 for r in rep.get('results', []) if r.get('status') == 'ok')


# ---------------------------------------------------------------- plain-language errors

def friendly(exc, where=None):
    """A message a player can act on, for any exception."""
    names = {}
    try:
        import bake
        names['bake'] = bake.BakeError
    except Exception:  # noqa: BLE001
        pass
    if isinstance(exc, SetupError):
        return str(exc)
    if 'bake' in names and isinstance(exc, names['bake']):
        return _baker_text(str(exc))
    if type(exc).__name__ in ('FractureError', 'Cancelled') and type(exc).__module__ == 'fracture':
        return 'Props: %s' % exc
    if isinstance(exc, MemoryError):
        return ('The computer ran out of memory. Close other programs, or lower "CPU cores to use" '
                '(each core needs about 300 MB), and try again.')
    if isinstance(exc, OSError):
        target = exc.filename or where or 'a file'
        if exc.errno == errno.ENOSPC:
            return 'The disk is full while writing %s. Free some space and try again.' % target
        if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM):
            return ('Umbra Effects Setup is not allowed to change %s. Close the game (and MO2 if it is running a program), '
                    'make sure the folder is not read-only, and try again.' % target)
        if isinstance(exc, FileNotFoundError):
            return 'A file or folder is missing: %s. Check the folders at the top and try again.' % target
        return 'Could not read or write %s (%s). Check the folders at the top and try again.' % (target, exc.strerror or exc)
    return 'Something unexpected went wrong (%s: %s). The log below has the details; please include it in a bug report.' % (
        type(exc).__name__, exc)


def _baker_text(msg):
    """The baker's own messages are meant for players already; a few get a
    clearer hint here."""
    low = msg.lower()
    if 'another bake into this folder is running' in low:
        return msg + '. Wait for it to finish (or close the other Umbra Effects Setup window) and try again.'
    if 'refusing to overwrite' in low:
        return ('The Umbra Effects folder already has a file the baker did not make (%s). This happens when a model mod was '
                'installed into the Umbra Effects folder by mistake. Move that file out, or reinstall Umbra Effects, then bake again.'
                % msg.split('e.g.', 1)[-1].strip())
    if "can't read the game's model archives" in low:
        return msg + ". Check that the game folder is right (it holds db\\meshes\\meshes_actors.db0)."
    return msg[:1].upper() + msg[1:]


# ---------------------------------------------------------------- jobs (worker process)

def worker_command(mod_root):
    """How to start this program again as a worker."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--mod', mod_root]
    return [sys.executable, '-u', os.path.join(HERE, 'zgo_setup.py'), '--mod', mod_root]


def overall_fraction(task, stage, done, total, with_props, with_particles=False):
    """Progress 0..1 over the whole job (models, then props, then kid mode
    for particles: a few seconds at the very end)."""
    tail = 0.02 if with_particles else 0.0
    end = 1.0 - tail                                    # the props end here
    share = (0.94 if with_props else 1.0) - tail        # the models end here
    f = min(1.0, (done / float(total)) if total else 0.0)
    if task == 'download':                              # a ready-made bake in place of the models' part
        lo, hi = DOWNLOAD_SHARE.get(stage, (0.0, 0.0))
        return share * (lo + (hi - lo) * f)
    if task == 'particles':
        return end + tail * f
    if task == 'props':
        return min(end, share + (end - share) * f)      # (min: no float drift past the next part)
    order = list(STAGE_WEIGHT)
    if stage not in STAGE_WEIGHT:
        return 0.0
    before = sum(STAGE_WEIGHT[s] for s in order[:order.index(stage)])
    w = STAGE_WEIGHT[stage]
    return min(share, share * (before + w * f) / float(sum(STAGE_WEIGHT.values())))


class Job:
    """One action in a worker process: bake (models, then props and kid mode
    for particles when ticked), remove, props (cut the props only),
    kidfx_apply / kidfx_revert (kid mode for particles on / the game's own
    particle shaders; only the Umbra Effects folder changes, in about a second).

        job = Job(tools, 'bake', paths, choices)
        job.start()
        while job.running(): events = job.poll(); ...
        job.cancel()           # asks the worker to stop (before it installs)
        job.result             # the final event: {'ok': bool, 'msg': ..., ...}
    """
    ACTIONS = ('bake', 'remove', 'props', 'pack', 'kidfx_apply', 'kidfx_revert')

    def __init__(self, tools, action, paths, choices, workdir=None, command=None):
        if action not in self.ACTIONS:
            raise ValueError(action)
        self.tools, self.action, self.paths, self.choices = tools, action, paths, choices
        self.dir = workdir or tempfile.mkdtemp(prefix='zgo_setup_')
        self.status_path = os.path.join(self.dir, 'status.jsonl')
        self.cancel_path = os.path.join(self.dir, 'cancel')
        self.stderr_path = os.path.join(self.dir, 'worker.log')
        self.job_path = os.path.join(self.dir, 'job.json')
        self.command = command or worker_command(tools.mod)
        self.proc = None
        self.result = None
        self.events = []
        self._pos = 0
        self._buf = b''
        self.started = None

    def start(self):
        job = {'action': self.action, 'paths': self.paths.as_dict(), 'choices': self.choices.as_dict(),
               'status': self.status_path, 'cancel': self.cancel_path}
        with open(self.job_path, 'w') as f:
            json.dump(job, f)
        open(self.status_path, 'wb').close()
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = 0x08000000          # CREATE_NO_WINDOW
        self._err = open(self.stderr_path, 'wb')
        self.proc = subprocess.Popen(self.command + ['--worker', self.job_path], stdin=subprocess.DEVNULL,
                                     stdout=self._err, stderr=subprocess.STDOUT, cwd=self.dir, **kw)
        self.started = time.time()
        return self

    def poll(self):
        """New events since the last call. Sets .result when the worker is done."""
        new = []
        try:
            with open(self.status_path, 'rb') as f:
                f.seek(self._pos)
                data = f.read()
                self._pos = f.tell()
        except OSError:
            data = b''
        self._buf += data
        while b'\n' in self._buf:
            line, self._buf = self._buf.split(b'\n', 1)
            try:
                ev = json.loads(line.decode('utf-8'))
            except ValueError:
                continue
            new.append(ev)
            if ev.get('t') == 'done':
                self.result = ev
        self.events += new
        if self.result is None and self.proc is not None and self.proc.poll() is not None:
            # the worker ended; read what is left, then call it
            if not new:
                self.result = {'t': 'done', 'ok': False, 'kind': 'crash', 'code': self.proc.returncode,
                               'msg': 'The baking process stopped unexpectedly (exit code %s). The log has the details; '
                                      'please include it in a bug report.' % self.proc.returncode,
                               'trace': self.worker_log()}
                new.append(self.result)
                self.events.append(self.result)
        return new

    def running(self):
        return self.result is None

    def cancel(self):
        try:
            open(self.cancel_path, 'w').close()
        except OSError:
            pass

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def worker_log(self, limit=4000):
        try:
            with open(self.stderr_path, 'rb') as f:
                data = f.read()
            return data[-limit:].decode('utf-8', 'replace')
        except OSError:
            return ''

    def wait(self, timeout=None, on_event=None, interval=0.1):
        t0 = time.time()
        while self.running():
            for ev in self.poll():
                if on_event:
                    on_event(ev)
            if not self.running():
                break
            if timeout is not None and time.time() - t0 > timeout:
                raise TimeoutError('job did not finish in %s s' % timeout)
            time.sleep(interval)
        self.close()
        return self.result

    def close(self):
        if self.proc is not None:
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        try:
            self._err.close()
        except Exception:  # noqa: BLE001
            pass


class _Writer:
    def __init__(self, path):
        self.f = open(path, 'a', encoding='utf-8')
        self.lock = threading.Lock()

    def __call__(self, **ev):
        with self.lock:
            self.f.write(json.dumps(ev) + '\n')
            self.f.flush()


def run_worker(job_path):
    """The worker side of Job: runs one action and reports through the
    status file. Returns the process exit code (0 done, 2 failed, 3 cancelled)."""
    with open(job_path) as f:
        job = json.load(f)
    emit = _Writer(job['status'])
    try:
        return _work(job, emit)
    finally:
        emit.f.close()


def _work(job, emit):
    cancel_path = job['cancel']

    def stop():
        return os.path.exists(cancel_path)

    p = job['paths']
    paths = Paths(p['mod'], p.get('mo2'), p.get('profile'), p.get('game'), p.get('out'), p.get('cache'))
    choices = Choices.from_dict(job.get('choices') or {})
    t0 = time.time()
    models_done = props_done = False
    step = 'models'
    summary = {}
    try:
        tools = Tools(paths.mod)
        emit(t='log', msg=' / '.join(environment_lines(tools)))
        if job['action'] in ('kidfx_apply', 'kidfx_revert'):
            return _work_kidfx(job['action'], tools, paths, emit, t0)
        if job['action'] == 'remove':
            emit(t='log', msg='Removing the baked files from %s' % paths.out)
            n = tools.bake.remove(paths.out, progress=lambda s, d, t, m: emit(t='progress', task='models', stage=s,
                                                                                  done=d, total=t, msg=m))
            fn = tools.fracture.remove(paths.out) if tools.fracture else 0
            kn, kerr = _remove_kidfx_copies(tools, paths, emit)
            what = ['%d baked files' % n] + (['%d prop pieces' % fn] if fn else []) + (
                ["%d copies of other mods' particle effects" % kn] if kn else [])
            what = what[0] if len(what) == 1 else '%s and %s' % (', '.join(what[:-1]), what[-1])
            emit(t='done', ok=True, msg='Removed %s.' % what, removed=n, props_removed=fn, kidfx_removed=kn,
                 kidfx_error=kerr, seconds=round(time.time() - t0, 1))
            return 0
        if job['action'] == 'pack':
            n = _pack(tools, paths, emit, stop)
            emit(t='done', ok=True, msg=('Packed %d loose files into archives.' % n) if n else 'Nothing to pack.',
                 packed=n, seconds=round(time.time() - t0, 1))
            return 0
        if job['action'] == 'bake':
            bad = problems(tools, paths)
            if bad:
                raise SetupError(bad[0])
            got = None
            rep0 = tools.bake.read_report(paths.out) if hasattr(tools.bake, 'loose_files') else None
            if rep0 and (tools.bake.loose_files(rep0) or rep0.get('status') == 'packing'):
                st0 = check(tools, paths, cancel=stop)
                if st0.state in ('ok', 'order') and st0.loose:
                    emit(t='log', msg='The bake is up to date; packing its %s loose files into archives.'
                         % '{:,}'.format(st0.loose))
                    n = _pack(tools, paths, emit, stop)
                    got = {'packed_only': True, 'packed': n, 'seconds': round(time.time() - t0, 1)}
            if got is None and choices.download:
                got = get_prebaked(tools, paths, choices, emit, stop)
            if got:
                models_done = True
                summary = got
            else:
                o = bake_options(tools, paths, choices)
                emit(t='log', msg='Baking with %r' % o)

                def progress(stage, done, total, msg):
                    emit(t='progress', task='models', stage=stage, done=done, total=total, msg=msg)
                rep = tools.bake.bake(o, progress=progress, cancel=stop)
                models_done = True
                summary = {'baked': rep['baked'], 'skipped': rep['skipped'], 'errors': rep['errors'],
                           'bytes': rep['bytes'], 'seconds': rep['seconds'], 'files': rep['counts']['files'],
                           'error_models': [[r['key'], r.get('why', '')] for r in rep['results']
                                            if r['status'] == 'error'][:50],
                           'fingerprint': (rep.get('inputs') or {}).get('fingerprint')}
                emit(t='log', msg='Baked %d models (%d skipped, %d could not be baked), %s, in %s.' % (
                    rep['baked'], rep['skipped'], rep['errors'], human_bytes(rep['bytes']),
                    human_seconds(rep['seconds'])))
                for key, why in summary['error_models'][:20]:
                    emit(t='log', level='warn', msg='Not baked: %s (%s); the game uses it unchanged.' % (key, why))
        do_props = job['action'] == 'props' or (job['action'] == 'bake' and choices.props and tools.fracture)
        if do_props and job['action'] == 'bake' and summary.get('packed_only') and check_props(tools, paths)[0] == 'ok':
            do_props = False                    # only packed: the props were fine
        if do_props and job['action'] == 'bake' and summary.get('prebaked') and check_props(tools, paths)[0] == 'ok':
            do_props = False                    # the ready-made bake's props fit this mod list
            emit(t='log', msg="Props: the ready-made bake's cut props fit your mod list.")
        if do_props:
            if not tools.fracture:
                raise SetupError('The props tool (tools/zgo_fracture) is not installed with this version of Umbra Effects.')
            step = 'props'
            if stop():
                raise tools.bake.Cancelled('cancelled before the props')
            fo = fracture_options(tools, paths, choices)
            emit(t='log', msg='Cutting props with %r' % fo)

            def fprogress(stage, done, total, msg):
                emit(t='progress', task='props', stage=stage, done=done, total=total, msg=msg)
            try:
                frep = tools.fracture.bake(fo, progress=fprogress, cancel=stop)
                ok = [r for r in frep.get('results', []) if r.get('status') == 'ok']
                summary['props'] = len(ok)
                emit(t='log', msg='Props: %d models cut into %d pieces.' % (len(ok), sum(r.get('pieces', 0) for r in ok)))
            except Exception as e:  # noqa: BLE001
                if job['action'] == 'props' or type(e).__name__ == 'Cancelled':
                    raise
                # the body models are in; a props problem must not hide that
                summary['props_error'] = friendly(e)
                emit(t='log', level='warn', msg='Props were not baked: %s' % friendly(e), trace=traceback.format_exc())
            props_done = True
        if job['action'] == 'bake' and choices.kid_particles:
            k = kidfx_for(tools, paths)
            if k is None:
                emit(t='log', msg=kidfx_unavailable(tools, paths), level='warn' if tools.kidfx_problem else 'info')
            else:
                step = 'particles'
                if stop():
                    raise tools.bake.Cancelled('cancelled before kid mode for particles')
                _bake_kidfx(k, tools, paths, emit, summary)
        emit(t='done', ok=True, msg='Done in %s.' % human_seconds(time.time() - t0), summary=summary,
             seconds=round(time.time() - t0, 1))
        return 0
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == 'Cancelled':
            if models_done and step == 'particles':
                msg = ('Cancelled before kid mode for particles: the body models%s are baked and installed; the '
                       'particle effects were not changed.' % (' and props' if props_done else ''))
            elif models_done:
                msg = 'Cancelled before the props: the body models are baked and installed; the props were not changed.'
            else:
                msg = 'Cancelled. Nothing in the Umbra Effects folder was changed.'
            emit(t='done', ok=False, cancelled=True, msg=msg, summary=summary)
            return 3
        emit(t='done', ok=False, kind='bake' if type(e).__name__ in ('BakeError', 'FractureError') else 'crash',
             msg=friendly(e), trace=traceback.format_exc(), summary=summary, models_done=models_done)
        return 2


# ---------------------------------------------------------------- ready-made bakes (prebaked.py)

def _pack(tools, paths, emit, stop):
    """Pack an installed bake's loose small parts (bake.pack). Returns how many files."""
    if not hasattr(tools.bake, 'pack'):
        raise SetupError('This version of Umbra Effects cannot pack a bake.')
    n = tools.bake.pack(paths.out, progress=lambda s, d, t, m: emit(t='progress', task='models', stage='pack',
                                                                     done=d, total=t, msg=m), cancel=stop)
    if n:
        emit(t='log', msg='Packed %s loose files into archives (db/mods/zgo_bake_*.db0).' % '{:,}'.format(n))
    return n


def get_prebaked(tools, paths, choices, emit, stop):
    """Umbra's ready-made bake, downloaded and put in place when one fits this mod list and
    these settings. Returns a summary (as a bake's, with prebaked=True), or None when none
    fits or it could not be used: the reason is logged and the caller bakes here instead.
    The Umbra Effects folder only changes once everything is downloaded and unpacked."""
    try:
        import prebaked as pb
    except ImportError as e:             # a ready-made program without the modules it needs
        emit(t='log', level='warn', msg='Ready-made bakes cannot be downloaded by this program (%s); baking here.' % e)
        return None
    src = pb.source()
    if src is None:
        return None
    t0 = time.time()
    out = zgo_folder(tools, paths)
    tmp = os.path.join(out, pb.TMP)
    cache = os.path.join(cache_dir(tools, paths), 'prebaked')
    b, fr = tools.bake, tools.fracture

    def prog(stage, done, total, msg=''):
        emit(t='progress', task='download', stage=stage, done=done, total=total, msg=msg)

    def fresh_tmp():
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)

    installing = False
    try:
        prog('match', 0, 1, 'asking %s' % (src if pb.is_url(src) else 'the folder given'))
        entries = pb.read_index(pb.get_small(src, pb.INDEX, 1 << 20, stop=stop))
        usable = [e for e in entries if e.get('baker') == b.BAKER_VERSION]
        if not usable:
            emit(t='log', msg='No ready-made bake for this version of Umbra Gore & Effects (%d listed); baking here.'
                 % len(entries))
            return None
        toks = pb.tokens(paths.mo2, paths.game, cache_dir(tools, paths), paths.profile, os.path.basename(out))
        man = None
        for e in usable[:pb.CANDIDATES]:
            m = pb.read_manifest(pb.get_small(src, e['path'], 4 << 20, e['sha256'], e['size'], stop), e)
            fcache = os.path.join(cache, m['fingerprint'])
            rz = pb.download(src, m['report'], os.path.join(fcache, os.path.basename(m['report']['path'])), stop=stop)
            fresh_tmp()
            names = pb.unpack(tools, [rz], tmp, stop=stop)
            if b.REPORT not in names:
                raise pb.Unavailable('its report is missing')
            pb.relocate(tmp, [r for r in m.get('relocate', []) if r in names], toks)
            rep = b.read_report(tmp)
            prep = fr.read_report(tmp) if fr else None
            st = check(tools, paths, progress=lambda d, n, msg: prog('match', d, n, msg), cancel=stop, report=rep,
                       prebaked=True, props_report=prep, choices=choices)
            if st.state in ('ok', 'order'):
                man = m
                break
            emit(t='log', msg="The ready-made bake made %s (%d models) doesn't fit: %s" % (
                m.get('made', '?'), m.get('models', 0), ' '.join(st.reasons[:3]) or st.headline))
        if man is None:
            emit(t='log', msg='No ready-made bake fits your mod list and settings; baking here.')
            return None
        here, theirs = b.read_report(out) or {}, b.read_report(tmp) or {}
        if here.get('bake_id') and here.get('bake_id') == theirs.get('bake_id') and \
                check(tools, paths, cancel=stop).state in ('ok', 'order'):
            shutil.rmtree(tmp, ignore_errors=True)
            emit(t='log', msg='The ready-made bake for your mod list is already in place (made %s).' % man.get('made', '?'))
            return {'prebaked': True, 'baked': here.get('baked', 0), 'skipped': here.get('skipped', 0),
                    'errors': here.get('errors', 0), 'bytes': man.get('bytes', 0), 'download': 0,
                    'seconds': round(time.time() - t0, 1), 'files': len(here.get('files') or []), 'error_models': [],
                    'fingerprint': man['fingerprint'], 'made': man.get('made', '')}
        vols = man['volumes']
        fcache = os.path.join(cache, man['fingerprint'])
        total = sum(v['size'] for v in vols)
        left = sum(v['size'] for v in vols if not os.path.isfile(os.path.join(fcache, os.path.basename(v['path']))))
        need_out = man.get('bytes', 0)
        if pb.same_drive(fcache, out):
            need = {out: left + need_out}
        else:
            need = {fcache: left, out: need_out}
        for where, n in need.items():
            free = pb.free_bytes(where)
            if free is not None and free < n + (200 << 20):
                raise pb.Unavailable('%s free on the drive of %s, %s needed' % (pb.human(free), where, pb.human(n)))
        emit(t='log', msg='A ready-made bake fits your mod list (made %s, %d models): downloading %s instead of baking.'
             % (man.get('made', '?'), man.get('models', 0), pb.human(total)))
        got = [0]
        last = [0.0, time.time(), 0]

        def on_bytes(n):
            got[0] += n
            now = time.time()
            if now - last[0] >= 0.5 or got[0] >= total:
                rate = (got[0] - last[2]) / max(now - last[1], 1e-3) if now - last[1] > 3 else 0
                if now - last[1] > 10:
                    last[1], last[2] = now, got[0]
                msg = '%s of %s' % (pb.human(got[0]), pb.human(total))
                if rate > 0:
                    msg += ', %s/s, about %s left' % (pb.human(rate), human_seconds((total - got[0]) / rate))
                last[0] = now
                prog('download', got[0], total, msg)
        prog('download', 0, total, '0 of %s' % pb.human(total))
        zips = [pb.download(src, man['report'], os.path.join(fcache, os.path.basename(man['report']['path'])), stop=stop)]
        for v in vols:
            zips.append(pb.download(src, v, os.path.join(fcache, os.path.basename(v['path'])), on_bytes, stop))
        fresh_tmp()
        nfiles = man.get('files') or 1
        names = pb.unpack(tools, zips, tmp, lambda i, rel: (i % 500 == 0) and prog('place', i, nfiles, rel), stop)
        if b.REPORT not in names:
            raise pb.Unavailable('its report is missing')
        pb.relocate(tmp, [r for r in man.get('relocate', []) if r in names], toks)
        if stop():
            raise b.Cancelled('cancelled before installing')
        # from here on the Umbra Effects folder changes: no cancelling
        installing = True
        prog('install', 0, len(names), 'removing the last bake')
        b.remove(out)
        if fr:
            fr.remove(out)
        reports = [r for r in (fr.REPORT if fr else None, b.REPORT) if r in names]
        for i, rel in enumerate([n for n in names if n not in reports] + reports):
            dst = os.path.join(out, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(tmp, *rel.split('/')), dst)
            if (i + 1) % 2000 == 0:
                prog('install', i + 1, len(names), 'moving the files in')
        pb.adopt_dates(out, b.REPORT, paths.game, b.archives_info)
        prog('install', len(names), len(names), 'done')
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(fcache, ignore_errors=True)
        if hasattr(b, 'pack'):
            try:
                b.pack(out, progress=lambda s, d, t, m: prog('pack', d, t, m))
            except Exception as e:  # noqa: BLE001  (the bake is in and works; packing is for the game's start)
                emit(t='log', level='warn', msg='The ready-made bake is in, but its small parts could not be packed '
                     'into archives (%s), so the game starts slower; press "Bake" to try again.' % friendly(e))
        st = check(tools, paths)
        if st.state not in ('ok', 'order'):
            emit(t='log', level='warn', msg="The ready-made bake is in place but doesn't check out (%s); baking here "
                 'instead.' % (' '.join(st.reasons[:2]) or st.headline))
            return None
        rep = b.read_report(out) or {}
        emit(t='log', msg='Put the ready-made bake in place: %d models, %s (downloaded %s in %s).' % (
            man.get('models', 0), human_bytes(man.get('bytes', 0)), pb.human(total), human_seconds(time.time() - t0)))
        return {'prebaked': True, 'baked': rep.get('baked', man.get('models', 0)), 'skipped': rep.get('skipped', 0),
                'errors': rep.get('errors', 0), 'bytes': man.get('bytes', 0), 'download': total,
                'seconds': round(time.time() - t0, 1), 'files': len(names), 'error_models': [],
                'fingerprint': man['fingerprint'], 'made': man.get('made', '')}
    except (pb.Cancelled, Cancelled):
        shutil.rmtree(tmp, ignore_errors=True)
        raise b.Cancelled('cancelled')
    except Exception as e:  # noqa: BLE001  (Unavailable, a damaged zip, the network, the disk)
        if type(e).__name__ == 'Cancelled':
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        why = str(e) if isinstance(e, pb.Unavailable) else friendly(e)
        emit(t='log', level='warn' if installing else 'info',
             msg='The ready-made bake could not be used (%s); baking here instead.' % why,
             trace=traceback.format_exc() if not isinstance(e, pb.Unavailable) else None)
        shutil.rmtree(tmp, ignore_errors=True)
        return None


def _bake_kidfx(k, tools, paths, emit, summary):
    """The bake's last step: kid mode for particles for this mod list. A
    failure is a warning in the summary (kidfx_error): the models are in."""
    emit(t='log', msg="Kid mode for particles: rebuilding Umbra Effects' particle shaders from your mod list and copying "
                      'the gory effects other mods play')
    emit(t='progress', task='particles', stage='particles', done=0, total=1, msg='particle shaders and effects')
    try:
        s = kidfx_summary(k.bake(kidfx_paths(tools, paths)))
    except Exception as e:  # noqa: BLE001
        summary['kidfx_error'] = kidfx_friendly(e)
        emit(t='log', level='warn', msg='Kid mode for particles was not updated for your mod list: %s'
             % summary['kidfx_error'], trace=traceback.format_exc())
        return
    summary['kidfx'] = s
    emit(t='progress', task='particles', stage='particles', done=1, total=1, msg='done')
    w, n = s['shaders_written'], s['shaders']
    parts = ['%d particle shaders rebuilt for your mod list' % w if w == n else
             '%d of %d particle shaders rebuilt (the others were already right)' % (w, n) if w else
             'the particle shaders were already right for your mod list']
    parts.append(('%d gory effect%s other mods play copied into Umbra Effects (%d new)'
                  % (s['copies'], '' if s['copies'] == 1 else 's', s['copied'])) if s['copies'] else
                 'no gory effects from other mods to copy')
    if s['applied']:
        parts.append("%d more effect%s switched to Umbra Effects' particle shaders" % (s['applied'], '' if s['applied'] == 1 else 's'))
    emit(t='log', msg='Kid mode for particles: %s.' % '; '.join(parts))
    if s['problems']:
        emit(t='log', msg="%d gory effect%s use%s a particle shader Umbra Effects has no kid-mode copy of; kid mode cannot "
                          'hide %s.' % (s['problems'], '' if s['problems'] == 1 else 's',
                                        's' if s['problems'] == 1 else '', 'it' if s['problems'] == 1 else 'them'))


def _remove_kidfx_copies(tools, paths, emit):
    """Remove: the copies of other mods' effects kidfx made (only those; the
    shader lines Umbra Effects ships stay). (removed, error text or None)"""
    k = kidfx_for(tools, paths)
    if k is None:
        return 0, None
    try:
        r = k.copies(remove=True)
    except Exception as e:  # noqa: BLE001
        emit(t='log', level='warn', msg="The copies of other mods' particle effects were not removed: %s"
             % kidfx_friendly(e), trace=traceback.format_exc())
        return 0, kidfx_friendly(e)
    for x in r.get('removed') or []:
        if not (x.get('status') or '').startswith('removed'):
            why = (x.get('status') or '').split(':', 1)[-1].strip()
            emit(t='log', level='warn', msg='Kept gamedata/particles/%s (%s).' % (x.get('file'), why))
    return sum(1 for x in r.get('removed') or [] if x.get('status') == 'removed'), None


def _work_kidfx(action, tools, paths, emit, t0):
    """kidfx_apply / kidfx_revert: only the Umbra Effects folder changes."""
    k = kidfx_for(tools, paths)
    if k is None:
        raise SetupError(kidfx_unavailable(tools, paths))
    if action == 'kidfx_apply':
        emit(t='log', msg="Pointing the gory particle effects at Umbra Effects' particle shaders")
        r = k.apply()
    else:
        emit(t='log', msg="Setting every particle effect back to the game's own particle shaders")
        r = k.revert()
    n = len(r.get('changed') or [])
    if action == 'kidfx_apply' and n:
        msg = ("Kid mode for particles is on: %d effect%s now use%s Umbra Effects' particle shaders again."
               % (n, '' if n == 1 else 's', 's' if n == 1 else ''))
    elif action == 'kidfx_apply':
        msg = 'Kid mode for particles was already on; nothing needed changing.'
    elif n:
        msg = ("%d effect%s use%s the game's own particle shaders again. Kid mode cannot hide particles already "
               'flying now; "Apply now" turns it back on.' % (n, '' if n == 1 else 's', 's' if n == 1 else ''))
    else:
        msg = "Every particle effect already used the game's own particle shaders; nothing needed changing."
    emit(t='done', ok=True, msg=msg, changed=n, seconds=round(time.time() - t0, 1))
    return 0


# ---------------------------------------------------------------- log file

def log_dir():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], 'zgo_setup')
    return os.path.join(os.path.expanduser('~'), '.cache', 'zgo_setup')


class Log:
    """The log the window shows, also written to <log_dir>/zgo_setup.log
    (the previous run is kept as zgo_setup.previous.log)."""

    def __init__(self, path=None, echo=None):
        self.lines = []
        self.listeners = []
        self.echo = echo
        self.path = path
        self.f = None
        if path is None:
            try:
                d = log_dir()
                os.makedirs(d, exist_ok=True)
                self.path = os.path.join(d, 'zgo_setup.log')
                if os.path.exists(self.path):
                    shutil.copyfile(self.path, os.path.join(d, 'zgo_setup.previous.log'))
            except OSError:
                self.path = None
        if self.path:
            try:
                self.f = open(self.path, 'w', encoding='utf-8')
            except OSError:
                self.f = None

    def __call__(self, msg, level='info'):
        line = '%s  %s%s' % (time.strftime('%H:%M:%S'), '' if level == 'info' else level.upper() + ': ', msg)
        self.lines.append((level, line))
        if self.f:
            try:
                self.f.write(line + '\n')
                self.f.flush()
            except OSError:
                pass
        if self.echo:
            try:
                self.echo(line)
            except Exception:  # noqa: BLE001
                pass
        for fn in list(self.listeners):
            fn(level, line)

    def text(self):
        return '\n'.join(l for _, l in self.lines) + '\n'


def environment_lines(tools=None):
    """For the top of the log: what this is running on."""
    import platform
    lines = ['%s on %s %s, Python %s%s' % (APP, platform.system(), platform.release(), platform.python_version(),
                                           ' (frozen)' if getattr(sys, 'frozen', False) else '')]
    if under_wine():
        lines.append('Running under Wine / Proton')
    if tools:
        lines.append('Umbra Effects folder: %s (version %s, baker %d)' % (tools.mod, tools.bake.zgo_version(tools.mod),
                                                                tools.bake.BAKER_VERSION))
        if tools.fracture:
            lines.append('Props tool: found')
        elif tools.fracture_problem:
            lines.append('Props tool: not usable (%s)' % tools.fracture_problem)
        if getattr(tools, 'kidfx', None):
            lines.append('Kid mode for particles: found')
        elif getattr(tools, 'kidfx_problem', None):
            lines.append('Kid mode for particles: not usable (%s)' % tools.kidfx_problem)
    return lines


def under_wine():
    if os.name != 'nt':
        return False
    try:
        import ctypes
        ntdll = ctypes.WinDLL('ntdll')
        return hasattr(ntdll, 'wine_get_version')
    except Exception:  # noqa: BLE001
        return False
