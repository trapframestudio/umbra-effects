# PyInstaller spec for ZGO Setup (run by dev/build_setup/build.sh; see README.md there).
# One file: "ZGO Setup.exe" (Windows, no console window) or zgo-setup-linux.
#
# The program bundles Python, tkinter, numpy and a copy of tools/zgo_setup,
# tools/zgo_baker and tools/zgo_fracture. At start it puts the installed ZGO
# folder's own tools/ first on sys.path (zgo_setup.use_mod), so it always runs
# the baker that came with the installed ZGO; the bundled copy is the fallback.
import os
import sys

MOD = os.path.abspath(os.path.join(SPECPATH, '..', '..'))  # noqa: F821 (SPECPATH is set by PyInstaller)
WIN = sys.platform == 'win32'
DIRS = [os.path.join(MOD, 'tools', d) for d in ('zgo_setup', 'zgo_baker', 'zgo_fracture')]

ours = []
for d in DIRS:
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.py') and fn != 'zgo_setup.py':
            ours.append(fn[:-3])

# the standard library the tools use (a newer ZGO's tools may import more of it
# than this build's copy does, so be generous)
stdlib = ['argparse', 'array', 'bisect', 'collections', 'contextlib', 'copy', 'csv', 'ctypes', 'dataclasses',
          'datetime', 'decimal', 'errno', 'fnmatch', 'functools', 'glob', 'gzip', 'hashlib', 'heapq', 'io',
          'itertools', 'json', 'locale', 'math', 'multiprocessing', 'multiprocessing.pool', 'operator', 'pathlib',
          'platform', 'pickle', 'queue', 'random', 're', 'shutil', 'signal', 'stat', 'string', 'struct',
          'subprocess', 'tempfile', 'textwrap', 'threading', 'time', 'traceback', 'types', 'typing', 'unittest',
          'unittest.mock', 'uuid', 'warnings', 'zlib', 'tkinter', 'tkinter.ttk', 'tkinter.font',
          'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.scrolledtext']

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
    hiddenimports=ours + stdlib,
    excludes=['matplotlib', 'scipy', 'PIL', 'pytest', 'IPython', 'pandas', 'setuptools', 'pkg_resources'],
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
    name='ZGO Setup' if WIN else 'zgo-setup-linux',
    console=not WIN,
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    bootloader_ignore_signals=False,
)
