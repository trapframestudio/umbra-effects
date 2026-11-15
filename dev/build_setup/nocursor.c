/*
 * An empty stand-in for libXcursor.so.1, bundled in zgo-setup-linux only
 * (built by build.sh linux; see "The cursor library" in README.md).
 *
 * python-build-standalone's tkinter has its own copy of libX11 built in. When
 * Tk asks for a named cursor (the I-beam over every text box, for one), that
 * libX11 dlopens "libXcursor.so.1" for themed cursors. The system's
 * libXcursor brings the system's libX11, and two libX11 copies then drive one
 * display connection: on a recent libX11 (Fedora 44 here) X aborts with
 * "[xcb] Unknown sequence number while appending request" the moment the
 * window builds its first text box.
 *
 * zgo_setup.py loads this file before Tk starts. Its SONAME is
 * libXcursor.so.1, so libX11's dlopen gets it; it has no symbols, so libX11
 * finds no XcursorTryShapeCursor and uses the classic X cursors instead. No
 * code, and no libc dependency (-nostdlib), so it loads on any x86_64 Linux.
 */
