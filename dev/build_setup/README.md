# Building and testing ZGO Setup

ZGO Setup is `tools/zgo_setup` (`zgo_setup.py` entry point, `setup_core.py`
logic, `setup_gui.py` window). It runs from source with Python 3.8+, numpy and
tkinter; the ready-made programs bundle Python, numpy and tkinter only. They
always run the `.py` files of the ZGO folder they sit in (the spec leaves
ZGO's own modules out of the bundle), so a ZGO update that changes the baker or
the window needs **no** rebuild; rebuild only for a new Python, numpy or
PyInstaller, or when the tools start using a standard-library module the
bundle lacks (`--selftest` imports every module and says so).

## Tests

    python3 -m unittest discover -s dev/build_setup -p 'test_*.py'

| Part | What |
| --- | --- |
| `TestLuaReader`, `TestVersions` | the pure-Python Lua reader (vs LuaJIT when installed), `BAKER_VERSION` = the game's `BAKER`, fingerprints |
| `TestCoreParts` | sizes, times, progress, plain-language errors, log |
| `TestFindingThings`, `TestPlan`, `TestBakeAndCheck` | the logic layer on a fake MO2 + game (`fakezgo.py`): detection, warnings, plan, a real bake of the synthetic models, every kind of "out of date", load order, broken bakes, cancel, remove, `zgo_bake_inputs.script` |
| `TestJob` | the worker process, crash reporting |
| `EndToEnd` | `zgo_setup.py` as a player runs it in a fake install with its own `tools/` copy |
| `TestLauncher` | `zgo-setup.sh`: program, python3 fallback, message |
| `TestWindow` | the window driven by `gui_driver.py` on a 1366x768 virtual display (needs tkinter and `xvfb-run`) |
| `FrozenLinux` | the same end-to-end tests against `tools/zgo_setup/zgo-setup-linux` (or `ZGO_SETUP_BIN`) |
| `WindowsUnderWine` | `ZGO Setup.exe --selftest` and a bake under Wine (`ZGO_TEST_WINE=1`) |

The host Python on the dev machine has no tkinter: run the window tests in the
container (`dev/run.sh python3 -m unittest discover -s dev/build_setup -p 'test_*.py'`).
`python3 dev/build_setup/fakezgo.py DIR` makes a fake install to try things by hand.

## Building

    dev/build_setup/build.sh linux      # tools/zgo_setup/zgo-setup-linux
    dev/build_setup/build.sh windows    # tools/zgo_setup/ZGO Setup.exe (under Wine)
    dev/build_setup/build.sh local      # quick test build with this machine's python3

| Input | Pin |
| --- | --- |
| Linux Python | python-build-standalone `cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only.tar.gz`, sha256 `e9cf6f7da499a4400ba30ae1da8f7ef25ce97827bd8c1084717aa05438035186` (glibc 2.17 baseline: runs on every x86_64 Linux since 2014) |
| Windows Python | python.org `python-3.12.10-amd64.exe`, sha256 `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb` |
| Python packages | `requirements.txt`: PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.9, altgraph 0.17.5, packaging 26.3, setuptools 84.2.1, numpy 2.2.6 (3.12) / 2.3.5 (3.13+), pefile 2024.8.26 and pywin32-ctypes 0.2.3 (Windows); every wheel by sha256, `--require-hashes --only-binary :all:` |
| Build | `zgo_setup.spec` (one file; Windows without a console window) |

Downloads go to `~/.cache/zgo-setup-build/downloads` and are checked against
the hashes before use; the Wine prefix is `~/.cache/zgo-wine-setup`. The
Windows build needs a Wine that runs 32-bit programs, because python.org's
installer is one: `WINE=/path/to/wine`, or else the system's `wine` if it
can, or else the newest Proton in Steam's `compatibilitytools.d` (Fedora's
default `wine` is 64-bit only; GE-Proton's works). Each
build runs the program's `--selftest` and the frozen tests, and writes
`tools/zgo_setup/SHA256SUMS.txt`.

### The cursor library (Linux)

python-build-standalone's tkinter has its own libX11 built in. For a named
cursor (the I-beam over a text box) that libX11 loads the system's
libXcursor, which brings the system's libX11, and two copies of libX11 on one
display connection make X abort ("[xcb] Unknown sequence number while
appending request") as soon as the window builds its first text box. It
happened on Fedora 44 (libX11 from 2026); older systems can be lucky, but no
user should depend on that. So `build.sh` compiles `nocursor.c` (empty, no
libc) into a `libXcursor.so.1` stand-in, the spec bundles it, and
`zgo_setup.no_xcursor()` loads it before Tk starts: libX11 finds no themed
cursor functions and uses the classic X cursors. That's why the Linux build
needs a C compiler (`cc`). The source script run with the system's Python is
not affected (its tkinter uses the system libX11).

Why not the system Python for release builds: a program frozen with Fedora's
Python needs Fedora's glibc (2.43 here), so it would not start on Ubuntu,
Debian or SteamOS. `build.sh local` exists to test the frozen program only.

On Windows without Wine: install Python 3.12.10 (64-bit, with tcl/tk), then

    py -3.12 -m venv venv
    venv\Scripts\python -m pip install --require-hashes --only-binary :all: -r dev\build_setup\requirements.txt
    venv\Scripts\python -m PyInstaller --noconfirm --clean dev\build_setup\zgo_setup.spec
    copy "dist\ZGO Setup.exe" tools\zgo_setup\
