#!/usr/bin/env bash
# Build the ready-made ZGO Setup programs (see README.md here).
#
#   dev/build_setup/build.sh linux       tools/zgo_setup/zgo-setup-linux   (python-build-standalone 3.12.10:
#                                         glibc 2.17+, runs on any x86_64 Linux from 2014 on)
#   dev/build_setup/build.sh windows     "tools/zgo_setup/ZGO Setup.exe"   (python.org 3.12.10 inside a Wine
#                                         prefix; no Windows machine needed)
#   dev/build_setup/build.sh all
#   dev/build_setup/build.sh local       a quick build with this machine's python3 for testing the frozen
#                                         program only; it stays in the build folder (needs this glibc)
#
# Everything downloaded is pinned by sha256 (below and requirements.txt) and kept in
# ~/.cache/zgo-setup-build (ZGO_BUILD_CACHE); the Wine prefix is ~/.cache/zgo-wine-setup (WINEPREFIX).
# After building, each program runs its --selftest and the setup tests run against it.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mod="$(cd "$here/../.." && pwd)"
cache="${ZGO_BUILD_CACHE:-$HOME/.cache/zgo-setup-build}"
dl="$cache/downloads"
out="$mod/tools/zgo_setup"

PBS_FILE='cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only.tar.gz'
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20250409/cpython-3.12.10%2B20250409-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_SHA='e9cf6f7da499a4400ba30ae1da8f7ef25ce97827bd8c1084717aa05438035186'
WINPY_FILE='python-3.12.10-amd64.exe'
WINPY_URL='https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
WINPY_SHA='67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'

say() { printf '\n== %s\n' "$*"; }

fetch() {   # fetch FILE URL SHA256
	mkdir -p "$dl"
	if [ ! -f "$dl/$1" ]; then
		say "downloading $1"
		curl -L --fail --proto '=https' -o "$dl/$1.part" "$2"
		mv "$dl/$1.part" "$dl/$1"
	fi
	echo "$3  $dl/$1" | sha256sum -c --quiet - || { echo "sha256 of $dl/$1 does not match; delete it and retry" >&2; exit 1; }
}

pip_install() {   # pip_install PYTHON
	"$1" -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary :all: \
		-r "$here/requirements.txt"
}

record() {   # record FILE: its sha256 next to the programs (SHA256SUMS.txt is shipped)
	( cd "$out" && sha256sum -- "$(basename "$1")" ) > "$cache/sum.$$"
	touch "$out/SHA256SUMS.txt"
	grep -v -F -- "$(basename "$1")" "$out/SHA256SUMS.txt" > "$cache/sums.$$" || true
	cat "$cache/sum.$$" >> "$cache/sums.$$"
	sort -k2 "$cache/sums.$$" > "$out/SHA256SUMS.txt"
	rm -f "$cache/sum.$$" "$cache/sums.$$"
}

nocursor() {   # nocursor DIR: the empty libXcursor.so.1 stand-in (nocursor.c says why)
	command -v cc >/dev/null || { echo "a C compiler (cc) is needed for the Linux program" >&2; exit 1; }
	mkdir -p "$1"
	cc -shared -nostdlib -fPIC -Wl,-soname,libXcursor.so.1 -o "$1/libXcursor.so.1" "$here/nocursor.c"
}

build_unix() {   # build_unix PYTHON DEST
	local py="$1" dest="$2" venv="$cache/$3/venv"
	[ -x "$venv/bin/python" ] || "$py" -m venv "$venv"
	pip_install "$venv/bin/python"
	nocursor "$cache/$3/stub"
	ZGO_NOCURSOR="$cache/$3/stub/libXcursor.so.1" \
	"$venv/bin/python" -m PyInstaller --noconfirm --clean --log-level WARN \
		--distpath "$cache/$3/dist" --workpath "$cache/$3/work" "$here/zgo_setup.spec"
	cp "$cache/$3/dist/zgo-setup-linux" "$dest"
	chmod 755 "$dest"
}

linux() {
	fetch "$PBS_FILE" "$PBS_URL" "$PBS_SHA"
	local py="$cache/linux/python/bin/python3"
	if [ ! -x "$py" ]; then
		say "unpacking Python 3.12.10 (python-build-standalone)"
		mkdir -p "$cache/linux"
		tar -xzf "$dl/$PBS_FILE" -C "$cache/linux"
	fi
	say "building zgo-setup-linux"
	build_unix "$py" "$out/zgo-setup-linux" linux
	record "$out/zgo-setup-linux"
	say "self-test"
	env -u DISPLAY -u WAYLAND_DISPLAY "$out/zgo-setup-linux" --selftest
	say "setup tests against the program"
	( cd "$mod" && ZGO_SETUP_BIN="$out/zgo-setup-linux" python3 -m unittest -v test_setup.FrozenLinux \
		2>&1 | tail -n 15 ) || true
	( cd "$here" && ZGO_SETUP_BIN="$out/zgo-setup-linux" python3 -m unittest test_setup.FrozenLinux )
}

local_build() {
	say "building a local test program with $(command -v python3)"
	build_unix "$(command -v python3)" "$cache/local/zgo-setup-linux" local
	( cd "$here" && ZGO_SETUP_BIN="$cache/local/zgo-setup-linux" python3 -m unittest test_setup.FrozenLinux )
	echo "built $cache/local/zgo-setup-linux (for testing only: it needs this machine's glibc)"
}

wow64() {   # wow64 WINE: can this Wine run 32-bit programs? (the Python installer is one)
	local p="$cache/wow64-probe"
	rm -rf "$p"
	WINEPREFIX="$p" "$1" wineboot -i >/dev/null 2>&1 || true
	WINEPREFIX="$p" "$1" 'C:\windows\syswow64\cmd.exe' /c ver >/dev/null 2>&1
	local ok=$?
	WINEPREFIX="$p" "$(dirname "$1")/wineserver" -k >/dev/null 2>&1 || WINEPREFIX="$p" wineserver -k >/dev/null 2>&1 || true
	rm -rf "$p"
	return $ok
}

pick_wine() {   # WINE (and WINESERVER): one that runs 32-bit programs
	if [ -n "${WINE:-}" ]; then
		:
	elif command -v wine >/dev/null && wow64 "$(command -v wine)"; then
		WINE="$(command -v wine)"
	else
		# e.g. Fedora's default wine is 64-bit only; Proton's Wine has WoW64
		local w
		for w in $(ls -d "$HOME"/.local/share/Steam/compatibilitytools.d/*/files/bin/wine \
				"$HOME"/.steam/steam/compatibilitytools.d/*/files/bin/wine 2>/dev/null | sort -rV); do
			if wow64 "$w"; then WINE="$w"; break; fi
		done
		[ -n "${WINE:-}" ] || { echo "no Wine here can run 32-bit programs (the Python installer is one);" \
			"set WINE to one that can, e.g. Proton's files/bin/wine" >&2; exit 1; }
	fi
	if [ -z "${WINESERVER:-}" ]; then
		if [ -x "$(dirname "$WINE")/wineserver" ]; then WINESERVER="$(dirname "$WINE")/wineserver"; else WINESERVER=wineserver; fi
	fi
	export WINE WINESERVER
	say "using $WINE"
}

windows() {
	fetch "$WINPY_FILE" "$WINPY_URL" "$WINPY_SHA"
	export WINEPREFIX="${WINEPREFIX:-$HOME/.cache/zgo-wine-setup}" WINEDEBUG="${WINEDEBUG:--all}"
	pick_wine
	wine() { "$WINE" "$@"; }
	wineserver() { "$WINESERVER" "$@"; }
	winepath() { "$WINE" winepath "$@"; }
	[ -d "$WINEPREFIX/drive_c" ] || { say "making the Wine prefix $WINEPREFIX"; wine wineboot -i >/dev/null 2>&1; }
	local pydir="$WINEPREFIX/drive_c/zgo-py312"
	if [ ! -f "$pydir/python.exe" ]; then
		say "installing Python 3.12.10 into the Wine prefix"
		wine "$dl/$WINPY_FILE" /quiet InstallAllUsers=0 'TargetDir=C:\zgo-py312' Include_launcher=0 \
			Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1 PrependPath=0 Shortcuts=0 AssociateFiles=0
		wineserver -w
	fi
	local venv='C:\zgo-venv-setup'
	[ -f "$WINEPREFIX/drive_c/zgo-venv-setup/Scripts/python.exe" ] || wine 'C:\zgo-py312\python.exe' -m venv "$venv"
	local wpy="$venv\\Scripts\\python.exe"
	wine "$wpy" -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary :all: \
		-r "$(winepath -w "$here/requirements.txt")"
	say "building ZGO Setup.exe"
	mkdir -p "$cache/windows"
	wine "$wpy" -m PyInstaller --noconfirm --clean --log-level WARN \
		--distpath "$(winepath -w "$cache/windows/dist")" --workpath "$(winepath -w "$cache/windows/work")" \
		"$(winepath -w "$here/zgo_setup.spec")"
	wineserver -w
	cp "$cache/windows/dist/ZGO Setup.exe" "$out/ZGO Setup.exe"
	record "$out/ZGO Setup.exe"
	say "self-test under Wine"
	( cd "$here" && ZGO_TEST_WINE=1 python3 -m unittest -v test_setup.WindowsUnderWine )
}

case "${1:-}" in
	linux) linux ;;
	windows) windows ;;
	all) linux; windows ;;
	local) local_build ;;
	*) sed -n '2,15p' "$0"; exit 2 ;;
esac
say "done"
