# PyInstaller spec for Umbra Effects Setup (run by dev/build_setup/build.sh; see README.md there).
# One file: "Umbra Effects Setup.exe" (Windows, no console window) or zgo-setup-linux.
#
# The program bundles Python, tkinter, numpy and the standard library, and only
# zgo_setup.py of ZGO's own code: everything else (tools/zgo_setup, zgo_baker,
# zgo_fracture, zgo_kidfx, and Umbra's typeface.py and ttf.py) is left out, and the
# program imports it from the installed mod folder (zgo_setup.use_mod), so it always
# runs the code that came with the installed mod. Leaving it out matters: Windows
# starts pool workers afresh (spawn), and a bundled copy of the baker would win
# over the mod folder's in them (the self-test's "parallel workers" check).
import os
import re
import struct
import sys

MOD = os.path.abspath(os.path.join(SPECPATH, '..', '..'))  # noqa: F821 (SPECPATH is set by PyInstaller)
WIN = sys.platform == 'win32'
DIRS = [os.path.join(MOD, 'tools', d) for d in ('zgo_setup', 'zgo_baker', 'zgo_fracture', 'zgo_kidfx')]

ours = []
for d in DIRS:
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.py') and fn != 'zgo_setup.py':
            ours.append(fn[:-3])

# the standard library the tools use (a newer ZGO's tools may import more of it
# than this build's copy does, so be generous): PyInstaller can't follow the
# imports of modules it leaves out
stdlib = ['argparse', 'array', 'bisect', 'collections', 'contextlib', 'copy', 'csv', 'ctypes', 'ctypes.util', 'ctypes.wintypes', 'dataclasses',
          'datetime', 'decimal', 'errno', 'fnmatch', 'functools', 'glob', 'gzip', 'hashlib', 'heapq', 'io',
          'itertools', 'json', 'locale', 'math', 'multiprocessing', 'multiprocessing.pool', 'operator', 'pathlib',
          'platform', 'pickle', 'queue', 'random', 're', 'shutil', 'signal', 'stat', 'string', 'struct',
          'subprocess', 'tempfile', 'textwrap', 'threading', 'time', 'traceback', 'types', 'typing', 'unittest',
          'unittest.mock', 'uuid', 'warnings', 'zlib', 'tkinter', 'tkinter.ttk', 'tkinter.font',
          'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.scrolledtext',
          # prebaked.py: the ready-made bake's download
          'ssl', 'urllib', 'urllib.error', 'urllib.parse', 'urllib.request', 'http', 'http.client', 'zipfile']

# Umbra's look (dev/build_setup/umbra_assets.py copies it from the Umbra repo into
# tools/zgo_setup): the window loads the icon and the typefaces from the mod folder like
# its code; the build only needs the icon PNGs, for the Windows program's .ico
ASSETS = os.path.join(MOD, 'tools', 'zgo_setup', 'assets')
for need in ('umbra-icon-256.png', 'umbra-icon-64.png', os.path.join('fonts', 'TekturNarrow-SemiBold.ttf'),
             os.path.join('fonts', 'Play-Regular.ttf'), os.path.join('fonts', 'Play-Bold.ttf')):
    if not os.path.isfile(os.path.join(ASSETS, need)):
        raise SystemExit('missing %s in tools/zgo_setup/assets (run dev/build_setup/umbra_assets.py)' % need)

with open(os.path.join(MOD, 'gamedata', 'scripts', 'zgo_main.script'), encoding='utf-8') as f:
    VERSION = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M).group(1)


def make_ico(dest, names):
    """A Windows .ico holding the PNG icons as they are (Vista and later read PNG entries)."""
    imgs = []
    for n in names:
        with open(os.path.join(ASSETS, n), 'rb') as f:
            data = f.read()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            raise SystemExit('%s is not a PNG' % n)
        w, h = struct.unpack('>II', data[16:24])
        imgs.append((w, h, data))
    imgs.sort(key=lambda i: -i[0])
    out = struct.pack('<HHH', 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    for w, h, data in imgs:
        out += struct.pack('<BBBBHHII', w % 256, h % 256, 0, 0, 1, 32, len(data), off)
        off += len(data)
    out += b''.join(d for _, _, d in imgs)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(out)
    return dest


icon = version = None
if WIN:
    from PyInstaller.utils.win32 import versioninfo as vi

    icon = make_ico(os.path.join(workpath, 'umbra-effects.ico'), ['umbra-icon-256.png', 'umbra-icon-64.png'])  # noqa: F821
    nums = tuple((list(map(int, re.findall(r'\d+', VERSION)[:4])) + [0, 0, 0, 0])[:4])
    version = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            vi.StringFileInfo([vi.StringTable('040904B0', [
                vi.StringStruct('ProductName', 'Umbra Gore & Effects'),
                vi.StringStruct('FileDescription', 'Umbra Effects Setup'),
                vi.StringStruct('FileVersion', VERSION),
                vi.StringStruct('ProductVersion', VERSION),
                vi.StringStruct('InternalName', 'Umbra Effects Setup'),
                vi.StringStruct('OriginalFilename', 'Umbra Effects Setup.exe'),
                vi.StringStruct('CompanyName', 'Umbra'),
                vi.StringStruct('LegalCopyright', 'Umbra contributors'),
            ])]),
            vi.VarFileInfo([vi.VarStruct('Translation', [0x0409, 1200])]),
        ])

# Linux: the empty libXcursor.so.1 stand-in (dev/build_setup/nocursor.c says why;
# build.sh builds it and passes its path). zgo_setup.py loads it before Tk.
binaries = []
if not WIN:
    stub = os.environ.get('ZGO_NOCURSOR')
    if not stub or not os.path.isfile(stub):
        raise SystemExit('ZGO_NOCURSOR must name the built libXcursor.so.1 stand-in (run dev/build_setup/build.sh)')
    binaries.append((stub, '.'))

a = Analysis(  # noqa: F821
    [os.path.join(MOD, 'tools', 'zgo_setup', 'zgo_setup.py')],
    pathex=DIRS,
    binaries=binaries,
    hiddenimports=['numpy'] + stdlib,
    excludes=ours + ['matplotlib', 'scipy', 'PIL', 'pytest', 'IPython', 'pandas', 'setuptools', 'pkg_resources'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Umbra Effects Setup' if WIN else 'zgo-setup-linux',
    console=not WIN,
    icon=icon,
    version=version,
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    bootloader_ignore_signals=False,
)
