#!/bin/sh
# ZGO Setup on Linux: double-click this file (or run "sh zgo-setup.sh").
# It starts the ready-made program zgo-setup-linux; if that cannot run on this
# system, it uses your own python3 (with numpy and tkinter) instead.
# Any options are passed on, e.g.  sh zgo-setup.sh --check
d=$(cd "$(dirname "$0")" && pwd)
bin="$d/zgo-setup-linux"

tell() {
	printf '%s\n' "$1" >&2
	# started from a file manager there is no terminal to read it in
	# (ZGO_SETUP_NO_DIALOG=1: never, for scripts and tests)
	if [ ! -t 2 ] && [ -z "${ZGO_SETUP_NO_DIALOG:-}" ]; then
		if command -v kdialog >/dev/null 2>&1; then kdialog --title "ZGO Setup" --error "$1"
		elif command -v zenity >/dev/null 2>&1; then zenity --error --title="ZGO Setup" --no-markup --text="$1"
		elif command -v notify-send >/dev/null 2>&1; then notify-send "ZGO Setup" "$1"
		fi
	fi
}

if [ -f "$bin" ]; then
	[ -x "$bin" ] || chmod +x "$bin" 2>/dev/null
	if "$bin" --version >/dev/null 2>&1; then
		exec "$bin" "$@"
	fi
	err=$("$bin" --version 2>&1 | head -n 3)
fi

for py in python3 python; do
	if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import numpy, tkinter' >/dev/null 2>&1; then
		exec "$py" "$d/zgo_setup.py" "$@"
	fi
done

tell "ZGO Setup could not start.
${err:+The ready-made program says: $err
}Either install Python 3 with numpy and tkinter
  (Debian/Ubuntu: sudo apt install python3-numpy python3-tk
   Fedora: sudo dnf install python3-numpy python3-tkinter
   Arch: sudo pacman -S python-numpy tk)
and start this again, or run \"ZGO Setup.exe\" from this folder with Wine or Proton."
exit 1
