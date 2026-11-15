# Copied from Umbra (installer/umbra_installer/ttf.py) by dev/build_setup/umbra_assets.py:
# edit it there, then run that script. Umbra is MIT-licensed.
"""
A small TrueType reader and renderer, so Umbra's windows can show Umbra's
typefaces where Tk can't load a font file: the Linux program's Tk
(python-build-standalone) draws only X's core bitmap fonts.

It reads glyph outlines (glyf, composite glyphs included), cmap formats 4 and
12 and the horizontal metrics, and renders antialiased coverage: no hinting,
no kerning, which is plenty for a window's labels and buttons. typeface.py
turns the coverage into Tk images. No Tk here, so the tests can run it.
"""
import math
import struct

SS = 4            # vertical samples per pixel (horizontal coverage is exact)


class FontError(Exception):
    pass


class Font:
    def __init__(self, path):
        with open(path, "rb") as f:
            d = f.read()
        self.d = d
        try:
            n = struct.unpack_from(">H", d, 4)[0]
            self.t = {}
            for i in range(n):
                tag, _sum, off, ln = struct.unpack_from(">4sIII", d, 12 + 16 * i)
                self.t[tag.decode("latin1")] = (off, ln)
            head = self.t["head"][0]
            self.upem = struct.unpack_from(">H", d, head + 18)[0]
            self.loca_long = struct.unpack_from(">h", d, head + 50)[0] == 1
            hhea = self.t["hhea"][0]
            self.ascent, self.descent, self.gap = struct.unpack_from(">hhh", d, hhea + 4)
            self.n_hmetrics = struct.unpack_from(">H", d, hhea + 34)[0]
            self.n_glyphs = struct.unpack_from(">H", d, self.t["maxp"][0] + 4)[0]
            if "glyf" not in self.t or "loca" not in self.t:
                raise FontError("%s has no TrueType outlines" % path)
            self.cmap = self._cmap()
        except (KeyError, struct.error) as e:
            raise FontError("%s is not a TrueType font I can read (%s)" % (path, e))
        self._outlines = {}
        self._bitmaps = {}

    # ------------------------------------------------------------ tables
    def _H(self, o):
        return struct.unpack_from(">H", self.d, o)[0]

    def _cmap(self):
        base = self.t["cmap"][0]
        n = self._H(base + 2)
        subs = {}
        for i in range(n):
            pid, eid, off = struct.unpack_from(">HHI", self.d, base + 4 + 8 * i)
            subs[(pid, eid)] = base + off
        for key in ((3, 10), (0, 4), (3, 1), (0, 3), (0, 1), (0, 0)):
            o = subs.get(key)
            if o is None:
                continue
            fmt = self._H(o)
            if fmt == 12:
                return self._cmap12(o)
            if fmt == 4:
                return self._cmap4(o)
        raise FontError("no Unicode cmap")

    def _cmap4(self, o):
        seg2 = self._H(o + 6)
        ends = o + 14
        starts = ends + seg2 + 2
        deltas = starts + seg2
        ranges = deltas + seg2
        m = {}
        for i in range(seg2 // 2):
            end, start = self._H(ends + 2 * i), self._H(starts + 2 * i)
            delta, ro = self._H(deltas + 2 * i), self._H(ranges + 2 * i)
            for c in range(start, end + 1):
                if c == 0xFFFF:
                    continue
                if ro == 0:
                    g = (c + delta) & 0xFFFF
                else:
                    g = self._H(ranges + 2 * i + ro + 2 * (c - start))
                    g = (g + delta) & 0xFFFF if g else 0
                if g:
                    m[c] = g
        return m

    def _cmap12(self, o):
        n = struct.unpack_from(">I", self.d, o + 12)[0]
        m = {}
        for i in range(n):
            start, end, gid = struct.unpack_from(">III", self.d, o + 16 + 12 * i)
            for c in range(start, min(end, 0x10FFFF) + 1):
                m[c] = gid + c - start
        return m

    def glyph_id(self, ch):
        return self.cmap.get(ord(ch), 0)

    def advance(self, gid):
        """In font units."""
        hmtx = self.t["hmtx"][0]
        i = min(gid, self.n_hmetrics - 1)
        return self._H(hmtx + 4 * i)

    def outline(self, gid, depth=0):
        """[[(x, y, on_curve), ...], ...] in font units."""
        if gid in self._outlines:
            return self._outlines[gid]
        loca, glyf = self.t["loca"][0], self.t["glyf"][0]
        if gid >= self.n_glyphs:
            gid = 0
        if self.loca_long:
            a, b = struct.unpack_from(">II", self.d, loca + 4 * gid)
        else:
            a, b = (2 * x for x in struct.unpack_from(">HH", self.d, loca + 2 * gid))
        out = []
        if b > a:
            p = glyf + a
            nc = struct.unpack_from(">h", self.d, p)[0]
            p += 10
            out = self._simple(p, nc) if nc >= 0 else self._composite(p, depth)
        self._outlines[gid] = out
        return out

    def _simple(self, p, nc):
        d = self.d
        ends = list(struct.unpack_from(">%dH" % nc, d, p))
        p += 2 * nc
        p += 2 + self._H(p)                              # instructions
        npts = (ends[-1] + 1) if ends else 0
        flags = []
        while len(flags) < npts:
            f = d[p]
            p += 1
            flags.append(f)
            if f & 8:
                flags.extend([f] * d[p])
                p += 1
        flags = flags[:npts]
        coords = []
        for short, same in ((2, 0x10), (4, 0x20)):
            v, vals = 0, []
            for f in flags:
                if f & short:
                    v += d[p] if f & same else -d[p]
                    p += 1
                elif not f & same:
                    v += struct.unpack_from(">h", d, p)[0]
                    p += 2
                vals.append(v)
            coords.append(vals)
        contours, s = [], 0
        for e in ends:
            contours.append([(coords[0][i], coords[1][i], flags[i] & 1) for i in range(s, e + 1)])
            s = e + 1
        return contours

    def _composite(self, p, depth):
        d = self.d
        out = []
        while True:
            flags, gid = struct.unpack_from(">HH", d, p)
            p += 4
            if flags & 1:
                a1, a2 = struct.unpack_from(">hh", d, p)
                p += 4
            else:
                a1, a2 = struct.unpack_from(">bb", d, p)
                p += 2
            xx, xy, yx, yy = 1.0, 0.0, 0.0, 1.0
            if flags & 8:
                xx = yy = struct.unpack_from(">h", d, p)[0] / 16384.0
                p += 2
            elif flags & 0x40:
                xx, yy = (v / 16384.0 for v in struct.unpack_from(">hh", d, p))
                p += 4
            elif flags & 0x80:
                xx, xy, yx, yy = (v / 16384.0 for v in struct.unpack_from(">hhhh", d, p))
                p += 8
            dx, dy = (a1, a2) if flags & 2 else (0, 0)    # point-matched components: rare, left in place
            if depth < 8:
                for c in self.outline(gid, depth + 1):
                    out.append([(xx * x + yx * y + dx, xy * x + yy * y + dy, on) for x, y, on in c])
            if not flags & 0x20:
                return out

    # ------------------------------------------------------------ drawing
    def line_height(self, px):
        return int(round((self.ascent - self.descent + self.gap) * px / self.upem))

    def baseline(self, px):
        return int(round(self.ascent * px / self.upem))

    def width(self, text, px):
        s = px / self.upem
        return sum(self.advance(self.glyph_id(ch)) for ch in text) * s

    def bitmap(self, gid, px):
        """(coverage list, w, h, left, top): the glyph's pixels, left/top from the pen
        position on the baseline."""
        key = (gid, px)
        if key in self._bitmaps:
            return self._bitmaps[key]
        s = px / self.upem
        segs = []
        for c in self.outline(gid):
            segs.extend(_flatten(c, s))
        if not segs:
            r = ([], 0, 0, 0, 0)
        else:
            x0 = math.floor(min(min(a[0], a[2]) for a in segs)) - 1
            x1 = math.ceil(max(max(a[0], a[2]) for a in segs)) + 1
            y0 = math.floor(min(min(a[1], a[3]) for a in segs)) - 1
            y1 = math.ceil(max(max(a[1], a[3]) for a in segs)) + 1
            w, h = x1 - x0, y1 - y0
            edges = [(a[0] - x0, a[1] - y0, a[2] - x0, a[3] - y0) for a in segs]
            r = (_raster(edges, w, h), w, h, x0, y0)
        self._bitmaps[key] = r
        return r


def _flatten(contour, s):
    """A contour's line segments in pixels, y down: [(x0, y0, x1, y1), ...]."""
    pts = [(x * s, -y * s, on) for x, y, on in contour]
    n = len(pts)
    if n < 2:
        return []
    # start on an on-curve point (or between two off-curve ones)
    start = next((i for i in range(n) if pts[i][2]), None)
    if start is None:
        a, b = pts[0], pts[1]
        first = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        seq = pts[1:] + pts[:1]
    else:
        first = pts[start][:2]
        seq = pts[start + 1:] + pts[:start]
    seq = seq + [(first[0], first[1], 1)]
    out = []
    cur, ctrl = first, None
    for x, y, on in seq:
        if on:
            if ctrl is None:
                out.append((cur[0], cur[1], x, y))
            else:
                out.extend(_quad(cur, ctrl, (x, y)))
                ctrl = None
            cur = (x, y)
        else:
            if ctrl is not None:
                mid = ((ctrl[0] + x) / 2, (ctrl[1] + y) / 2)
                out.extend(_quad(cur, ctrl, mid))
                cur = mid
            ctrl = (x, y)
    return out


def _quad(p0, p1, p2):
    dd = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
    n = max(1, int(math.ceil(math.sqrt(dd * 2))))
    out, prev = [], p0
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        q = (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])
        out.append((prev[0], prev[1], q[0], q[1]))
        prev = q
    return out


def _raster(edges, w, h):
    """Coverage 0..1 per pixel (rows of w), non-zero winding: SS scanlines a pixel, each
    span's horizontal coverage exact."""
    cov = [0.0] * (w * h)
    edges = [e for e in edges if e[1] != e[3]]
    wgt = 1.0 / SS
    for sy in range(h * SS):
        y = (sy + 0.5) / SS
        xs = []
        for x0, y0, x1, y1 in edges:
            if y0 <= y < y1 or y1 <= y < y0:
                xs.append((x0 + (y - y0) * (x1 - x0) / (y1 - y0), 1 if y1 > y0 else -1))
        if len(xs) < 2:
            continue
        xs.sort()
        row = (sy // SS) * w
        wind = 0
        for i in range(len(xs) - 1):
            wind += xs[i][1]
            if not wind:
                continue
            a, b = max(xs[i][0], 0.0), min(xs[i + 1][0], float(w))
            if b <= a:
                continue
            ia, ib = int(a), int(b)
            if ia == ib:
                cov[row + ia] += (b - a) * wgt
                continue
            cov[row + ia] += (ia + 1 - a) * wgt
            for k in range(row + ia + 1, row + ib):
                cov[k] += wgt
            if ib < w:
                cov[row + ib] += (b - ib) * wgt
    return [min(c, 1.0) for c in cov]


# ---------------------------------------------------------------- text
def wrap(font, text, px, width):
    """Lines of text no wider than width pixels (a word longer than that gets a line of
    its own). Newlines in the text are kept."""
    if not width:
        return text.split("\n")
    lines = []
    space = font.width(" ", px)
    for para in text.split("\n"):
        cur, cw = [], 0.0
        for word in para.split(" "):
            ww = font.width(word, px)
            if cur and cw + space + ww > width:
                lines.append(" ".join(cur))
                cur, cw = [word], ww
            else:
                cw = cw + space + ww if cur else ww
                cur.append(word)
        lines.append(" ".join(cur))
    return lines


def render(font, text, px, width=None, justify="left"):
    """(w, h, coverage bytes 0..255 in rows of w): text laid out in lines of the font's
    height, wrapped at width pixels when given."""
    lines = wrap(font, text, px, width)
    lh, base = font.line_height(px), font.baseline(px)
    s = px / font.upem
    widths = [int(math.ceil(font.width(t, px))) for t in lines]
    w = max(widths + [1]) + 1
    h = max(1, lh * len(lines))
    out = bytearray(w * h)
    for n, (t, lw) in enumerate(zip(lines, widths)):
        pen = {"left": 0.0, "center": (w - lw) / 2.0, "right": float(w - lw)}.get(justify, 0.0)
        by = n * lh + base
        for ch in t:
            gid = font.glyph_id(ch)
            cov, gw, gh, gl, gt = font.bitmap(gid, px)
            ox, oy = int(round(pen)) + gl, by + gt
            for yy in range(gh):
                ty = oy + yy
                if not 0 <= ty < h:
                    continue
                src, dst = yy * gw, ty * w
                for xx in range(gw):
                    c = cov[src + xx]
                    tx = ox + xx
                    if c and 0 <= tx < w:
                        v = out[dst + tx] + int(c * 255 + 0.5)
                        out[dst + tx] = 255 if v > 255 else v
            pen += font.advance(gid) * s
    return w, h, bytes(out)
