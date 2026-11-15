# Copied from Umbra (installer/umbra_installer/typeface.py) by dev/build_setup/umbra_assets.py:
# edit it there, then run that script. Umbra is MIT-licensed.
"""
Umbra's typefaces in Setup and the launcher: Tektur Narrow (headings, buttons) and Play
(text), the faces of the game's own UI. The font files ship in assets/fonts
(branding/fonts.py makes them).

setup(root) tries to give Tk the fonts themselves: on Windows privately for this program
(AddFontResourceEx), on a Tk built with Xft through fontconfig. Then every widget uses
them as fonts ("native"). The Linux program's Tk (python-build-standalone) has neither:
it draws only X's core bitmap fonts. There ("image"), the Label, Button, Radiobutton,
Checkbutton and Menubutton below draw their text from the font files (ttf.py) into an
image, one per state, in the style's colours; what Tk still draws itself (entries, lists,
the log) gets the best core font there is.

Use them in place of ttk's, with the same options. Fonts come from the ttk style, as
font("head" | "body" | "bold", size) set them.
"""
import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import ttf

HEAD = "Tektur Narrow SemiBold"
BODY = "Play"
FILES = {(HEAD, False): "TekturNarrow-SemiBold.ttf", (HEAD, True): "TekturNarrow-SemiBold.ttf",
         (BODY, False): "Play-Regular.ttf", (BODY, True): "Play-Bold.ttf"}
BODY_SIZE = 11
MODE = None          # "native" | "image" | None (not set up, or the files are missing: Tk's own fonts)
_fonts = {}          # file -> ttf.Font
_cache = {}          # (Tk, text, file, px, fg, bg, wrap, justify) -> PhotoImage
CACHE_MAX = 400


def font(role, size):
    """A ttk style's font: role "head" (Tektur Narrow), "body" (Play) or "bold" (Play Bold)."""
    return {"head": (HEAD, size), "body": (BODY, size), "bold": (BODY, size, "bold")}[role]


def font_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    base = getattr(sys, "_MEIPASS", None) or here
    for d in (os.path.join(here, "assets", "fonts"), os.path.join(base, "assets", "fonts")):
        if os.path.isdir(d):
            return d
    return None


def _files():
    d = font_dir()
    paths = [os.path.join(d, fn) for fn in sorted(set(FILES.values()))] if d else []
    return [p for p in paths if os.path.isfile(p)]


def _win_add(paths):
    import ctypes
    for p in paths:
        ctypes.windll.gdi32.AddFontResourceExW(p, 0x10, 0)          # FR_PRIVATE: this program only


# The name is a variable on purpose: PyInstaller bundles any library named in a literal
# ctypes call, and the system's fontconfig would bring its whole tree (glib, a new glibc).
# The built program's Tk has no Xft anyway; this is for a Tk that has (a source run).
FONTCONFIG = "fontconfig"


def _fc_add(paths):
    import ctypes
    import ctypes.util
    lib = ctypes.CDLL(ctypes.util.find_library(FONTCONFIG) or "lib%s.so.1" % FONTCONFIG)
    lib.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    for p in paths:
        lib.FcConfigAppFontAddFile(None, p.encode())


def fontsystem(root):
    try:
        return str(root.tk.call("::tk::pkgconfig", "get", "fontsystem"))
    except tk.TclError:
        return None


def setup(root, force=None):
    """Make Umbra's fonts what the windows use (call before building widgets). force:
    "image" or "native" for tests."""
    global MODE
    _cache.clear()                     # images belong to one Tk (the self-test opens two in turn)
    paths = _files()
    if not paths:
        MODE = None
        return MODE
    if force != "image":
        try:
            if os.name == "nt":
                _win_add(paths)
            elif fontsystem(root) == "xft" and not getattr(sys, "frozen", False):
                _fc_add(paths)
        except (OSError, AttributeError):
            pass
    fams = {f.lower() for f in tkfont.families(root)}
    if force == "native" or (force is None and HEAD.lower() in fams and BODY.lower() in fams):
        MODE = "native"
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkTooltipFont", "TkSmallCaptionFont",
                     "TkIconFont"):
            _named(root, name, family=BODY, size=BODY_SIZE)
        for name in ("TkHeadingFont", "TkCaptionFont"):
            _named(root, name, family=HEAD, size=BODY_SIZE + 1)
        return MODE
    MODE = "image"
    for want, names in ((("liberation sans", "dejavu sans", "noto sans", "helvetica"),
                         ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont")),
                        (("liberation mono", "dejavu sans mono", "noto mono", "courier"), ("TkFixedFont",))):
        fam = next((f for f in want if f in fams), None)
        for name in names:
            # the drawn text takes its size from these too (a style without a font of its own)
            kw = dict(family=fam) if fam else {}
            if name != "TkFixedFont":
                kw["size"] = BODY_SIZE
            _named(root, name, **kw)
    return MODE


def _named(root, name, **kw):
    try:
        tkfont.nametofont(name, root=root).configure(**kw)
    except tk.TclError:
        pass


# ---------------------------------------------------------------- drawing text
def _font_for(widget, style):
    """(ttf.Font, pixel size) for a ttk style's font."""
    desc = ttk.Style(widget).lookup(style, "font") or "TkDefaultFont"
    parts = list(widget.tk.splitlist(desc))
    fam, size, bold = BODY, BODY_SIZE, False
    if parts and parts[0] in tkfont.names(widget):
        a = tkfont.nametofont(parts[0], root=widget).actual()
        size, bold = a.get("size", BODY_SIZE), a.get("weight") == "bold"
        fam = HEAD if a.get("family") == HEAD else BODY
    elif parts:
        fam = HEAD if parts[0] == HEAD else BODY
        if len(parts) > 1:
            try:
                size = int(parts[1])
            except ValueError:
                pass
        bold = "bold" in parts[2:]
    px = -size if size < 0 else size * float(widget.tk.call("tk", "scaling"))
    path = os.path.join(font_dir(), FILES[(fam, bold)])
    if path not in _fonts:
        _fonts[path] = ttf.Font(path)
    return _fonts[path], max(6, int(round(px)))


def _hex(c, widget):
    r, g, b = (v // 257 for v in widget.winfo_rgb(c))
    return r, g, b


def text_image(widget, text, style, state=(), wrap=None, justify="left"):
    """The text in the style's font and colours (for that state) as a PhotoImage."""
    f, px = _font_for(widget, style)
    st = ttk.Style(widget)
    fg = st.lookup(style, "foreground", list(state)) or "#d9cca6"
    bg = st.lookup(style, "background", list(state)) or "#14130f"
    key = (id(widget.tk), text, id(f), px, fg, bg, wrap, justify)
    img = _cache.get(key)
    if img is not None:
        return img
    w, h, cov = ttf.render(f, text, px, width=wrap, justify=justify)
    F, B = _hex(fg, widget), _hex(bg, widget)
    pal = ["#%02x%02x%02x" % tuple(B[i] + (F[i] - B[i]) * c // 255 for i in range(3)) for c in range(256)]
    rows = ["{" + " ".join(pal[c] for c in cov[y * w:(y + 1) * w]) + "}" for y in range(h)]
    img = tk.PhotoImage(master=widget, width=w, height=h)
    img.put(" ".join(rows))
    _remember(key, img)
    return img


def _with_icon(widget, icon, img, style, state, gap=4):
    """icon, then the text image, on the style's background."""
    bg = ttk.Style(widget).lookup(style, "background", list(state)) or "#14130f"
    key = (id(widget.tk), "icon", str(icon), str(img), bg)
    if key in _cache:
        return _cache[key]
    iw, ih = int(widget.tk.call("image", "width", icon)), int(widget.tk.call("image", "height", icon))
    tw, th = int(img.width()), int(img.height())
    w, h = iw + gap + tw, max(ih, th)
    out = tk.PhotoImage(master=widget, width=w, height=h)
    out.put(bg, to=(0, 0, w, h))
    out.tk.call(out, "copy", icon, "-to", 0, (h - ih) // 2)
    out.tk.call(out, "copy", img, "-to", iw + gap, (h - th) // 2)
    _remember(key, out)
    return out


def _remember(key, img):
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = img


class _Drawn:
    """In image mode the widget's text is drawn from Umbra's font files into images."""
    STATES = ((),)                      # the states it has an image for (first: normal)
    DEFAULT_STYLE = "TLabel"

    def __init__(self, master=None, **kw):
        self._t = None
        if MODE == "image":
            self._t = {k: kw.pop(k) for k in ("text", "image") if k in kw}
            self._t.setdefault("text", "")
            self._t.setdefault("image", "")
            self._t["compound"] = kw.get("compound")
            self._t["wraplength"] = kw.get("wraplength")
            self._t["justify"] = kw.get("justify") or "left"
        super().__init__(master, **kw)
        if self._t is not None:
            self._draw()

    def configure(self, cnf=None, **kw):
        if self._t is None:
            return super().configure(cnf, **kw)
        if cnf:
            kw = dict(cnf, **kw)
        if not kw:
            return super().configure()
        redraw = False                     # (progress updates set the same text again and again)
        for k in ("text", "image"):
            if k in kw:
                v = kw.pop(k)
                redraw = redraw or str(v) != str(self._t.get(k))
                self._t[k] = v
        for k in ("compound", "wraplength", "justify", "style"):
            if k in kw:
                redraw = redraw or str(kw[k]) != str(self._t.get(k, ""))
                self._t[k] = kw[k]
        r = super().configure(**kw) if kw else None
        if redraw:
            self._draw()
        return r

    config = configure

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def cget(self, key):
        if self._t is not None and key in ("text", "image"):
            return self._t[key]
        return super().cget(key)

    __getitem__ = cget

    def _draw(self):
        t = self._t
        text, icon, compound = str(t["text"]), t["image"], t.get("compound")
        if icon and compound in (None, "", "none", "image"):
            super().configure(image=icon, text="")          # an image alone (the Play button's lettering)
            return
        if not text:
            super().configure(image=icon or "", text="")
            return
        style = str(super().cget("style")) or self.DEFAULT_STYLE
        wrap = t.get("wraplength")
        wrap = int(self.winfo_fpixels(wrap)) if wrap not in (None, "", 0, "0") else None
        imgs = []
        for state in self.STATES:
            img = text_image(self, text, style, state, wrap, str(t.get("justify") or "left"))
            if icon:
                img = _with_icon(self, icon, img, style, state)
            imgs.append(img)
        self._imgs = imgs                                  # (Tk drops images nobody holds)
        spec = [imgs[0]]
        for state, img in zip(self.STATES[1:], imgs[1:]):
            spec += [" ".join(state), img]
        super().configure(image=spec if len(spec) > 1 else imgs[0], text="", compound="image")


class Label(_Drawn, ttk.Label):
    pass


class Button(_Drawn, ttk.Button):
    STATES = ((), ("disabled",), ("active",))          # (pressed comes with active: the mouse is on it)
    DEFAULT_STYLE = "TButton"


class Menubutton(_Drawn, ttk.Menubutton):
    STATES = ((), ("disabled",), ("active",))
    DEFAULT_STYLE = "TMenubutton"


class Radiobutton(_Drawn, ttk.Radiobutton):
    STATES = ((), ("disabled",), ("active",))
    DEFAULT_STYLE = "TRadiobutton"


class Checkbutton(_Drawn, ttk.Checkbutton):
    STATES = ((), ("disabled",), ("active",))
    DEFAULT_STYLE = "TCheckbutton"
