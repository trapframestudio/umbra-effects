"""Cut roots per creature kind, read from the mod's own zgo_tables.script
(limb_map: [hit bone] = { bone_to_remove, ... }).

Pure Python since 1.7: a small reader for the Lua table constructors that
file is made of, so the baker (and the setup tool built from it) needs no
LuaJIT. It understands Lua 5.1 tokens (comments, long strings, escapes,
numbers) and table constructors whose values are literals, nested tables or
dotted names (clsid.x, kept as the text "clsid.x"); anything else in the file
(functions, calls, operators) is skipped, not evaluated.
"""
import os
import re

__all__ = ['load', 'read_tables', 'roots_from_limb_map', 'canonical', 'LuaReadError']


class LuaReadError(ValueError):
    """zgo_tables.script could not be read; the message says where."""


class Name(str):
    """A bare or dotted name used as a value (e.g. clsid.dog_s)."""


_NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
_NUM = re.compile(r'0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_SYMBOLS = ('...', '..', '==', '~=', '<=', '>=', '::')
_ESC = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v',
        '\\': '\\', '"': '"', "'": "'", '\n': '\n'}


def _line(text, pos):
    return text.count('\n', 0, pos) + 1


def _long_bracket(text, pos):
    """At '[' of '[[' / '[==[': returns (content, end) or None."""
    m = re.compile(r'\[(=*)\[').match(text, pos)
    if not m:
        return None
    close = ']' + m.group(1) + ']'
    end = text.find(close, m.end())
    if end < 0:
        raise LuaReadError('unfinished long string or comment at line %d' % _line(text, pos))
    body = text[m.end():end]
    if body.startswith('\r\n'):
        body = body[2:]
    elif body.startswith('\n'):
        body = body[1:]
    return body, end + len(close)


def _string(text, pos):
    q = text[pos]
    out = []
    i = pos + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == q:
            return ''.join(out), i + 1
        if c == '\n':
            break
        if c == '\\':
            i += 1
            if i >= n:
                break
            e = text[i]
            if e in _ESC:
                out.append(_ESC[e])
                i += 1
            elif e == '\r':
                out.append('\n')
                i += 2 if text.startswith('\r\n', i) else 1
            elif e.isdigit():
                m = re.compile(r'\d{1,3}').match(text, i)
                out.append(chr(int(m.group(0)) & 0xFF))
                i = m.end()
            elif e == 'x' and re.compile(r'[0-9a-fA-F]{2}').match(text, i + 1):
                out.append(chr(int(text[i + 1:i + 3], 16)))
                i += 3
            elif e == 'z':
                i += 1
                while i < n and text[i] in ' \t\r\n\v\f':
                    i += 1
            else:
                out.append(e)
                i += 1
            continue
        out.append(c)
        i += 1
    raise LuaReadError('unfinished string at line %d' % _line(text, pos))


def tokens(text):
    """[(kind, value, pos)]: kind is 'name', 'str', 'num' or 'sym'."""
    out = []
    i, n = 0, len(text)
    if text.startswith('#'):                     # a shebang line
        i = text.find('\n')
        i = n if i < 0 else i
    while i < n:
        c = text[i]
        if c in ' \t\r\n\v\f﻿':
            i += 1
            continue
        if text.startswith('--', i):
            lb = _long_bracket(text, i + 2) if text.startswith('[', i + 2) else None
            if lb:
                i = lb[1]
            else:
                j = text.find('\n', i)
                i = n if j < 0 else j + 1
            continue
        if c == '[' and (text.startswith('[[', i) or text.startswith('[=', i)):
            lb = _long_bracket(text, i)
            if lb:
                out.append(('str', lb[0], i))
                i = lb[1]
                continue
        if c in '"\'':
            s, i2 = _string(text, i)
            out.append(('str', s, i))
            i = i2
            continue
        m = _NAME.match(text, i)
        if m:
            out.append(('name', m.group(0), i))
            i = m.end()
            continue
        m = _NUM.match(text, i)
        if m:
            t = m.group(0)
            out.append(('num', float(int(t, 16)) if t[:2].lower() == '0x' else float(t), i))
            i = m.end()
            continue
        for s in _SYMBOLS:
            if text.startswith(s, i):
                out.append(('sym', s, i))
                i += len(s)
                break
        else:
            out.append(('sym', c, i))
            i += 1
    return out


class _Parser:
    def __init__(self, text):
        self.text = text
        self.t = tokens(text)
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ('eof', None, len(self.text))

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def fail(self, what):
        kind, val, pos = self.peek()
        raise LuaReadError('%s at line %d (found %r)' % (what, _line(self.text, pos), val))

    def expect(self, sym):
        kind, val, _ = self.peek()
        if kind != 'sym' or val != sym:
            self.fail("expected '%s'" % sym)
        self.i += 1

    def value(self):
        kind, val, _ = self.peek()
        if kind == 'str' or kind == 'num':
            self.i += 1
            return int(val) if kind == 'num' and val == int(val) else val
        if kind == 'sym' and val == '{':
            return self.table()
        if kind == 'sym' and val == '-' and self.peek(1)[0] == 'num':
            self.i += 1
            v = -self.take()[1]
            return int(v) if v == int(v) else v
        if kind == 'name':
            if val in ('nil', 'true', 'false'):
                self.i += 1
                return {'nil': None, 'true': True, 'false': False}[val]
            parts = [self.take()[1]]
            while self.peek()[:2] == ('sym', '.') and self.peek(1)[0] == 'name':
                self.i += 1
                parts.append(self.take()[1])
            if self.peek()[:2] in (('sym', '('), ('sym', ':'), ('sym', '[')) or self.peek()[0] == 'str':
                self.fail('a function call or index is not a plain value')
            return Name('.'.join(parts))
        self.fail('expected a value')

    def table(self):
        """{ ... } -> dict; positional fields get keys 1, 2, ... as in Lua."""
        self.expect('{')
        out = {}
        n = 0
        while True:
            kind, val, _ = self.peek()
            if kind == 'sym' and val == '}':
                self.i += 1
                return out
            if kind == 'sym' and val == '[':            # ('[[' is a long string token)
                self.i += 1
                key = self.value()
                self.expect(']')
                self.expect('=')
                v = self.value()
                if key is None:
                    self.fail('table index is nil')
                if v is not None:
                    out[key] = v
                else:
                    out.pop(key, None)
            elif kind == 'name' and self.peek(1)[:2] == ('sym', '='):
                self.i += 2
                v = self.value()
                if v is not None:
                    out[val] = v
                else:
                    out.pop(val, None)
            else:
                n += 1
                v = self.value()
                if v is not None:
                    out[n] = v
            kind, val, _ = self.peek()
            if kind == 'sym' and val in (',', ';'):
                self.i += 1
            elif not (kind == 'sym' and val == '}'):
                self.fail("expected ',' or '}'")

    def globals(self, wanted=None):
        """Top-level 'name = <table/literal>' statements -> {name: value}.
        Everything else is skipped by bracket and block depth."""
        out = {}
        depth = 0
        while self.peek()[0] != 'eof':
            kind, val, _ = self.peek()
            if depth == 0 and kind == 'name' and self.peek(1)[:2] == ('sym', '=') \
                    and not (self.i > 0 and self.t[self.i - 1][:2] in (('sym', '.'), ('sym', ':'))):
                local = self.i > 0 and self.t[self.i - 1][:2] == ('name', 'local')
                self.i += 2
                if wanted is not None and val not in wanted:
                    continue
                start = self.i
                try:
                    v = self.value()
                except LuaReadError:
                    self.i = start                  # not a plain value: skip it
                    continue
                if not local:
                    out[val] = v
                continue
            self.i += 1
            if kind == 'sym' and val in '{([':
                depth += 1
            elif kind == 'sym' and val in '})]':
                depth = max(0, depth - 1)
            elif kind == 'name' and val in ('function', 'if', 'do', 'repeat'):
                depth += 1
            elif kind == 'name' and val in ('end', 'until'):
                depth = max(0, depth - 1)
        return out


def read_tables(path, wanted=None):
    """{global name: value} for the top-level table assignments of a script."""
    with open(path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', errors='replace')
    return _Parser(text).globals(wanted)


def roots_from_limb_map(limb_map):
    """limb_map -> {kind: sorted lower-case cut roots}, as the game sees it:
    for each kind, the first value of every entry."""
    if not isinstance(limb_map, dict):
        raise LuaReadError('limb_map is not a table')
    out = {}
    for kind, m in limb_map.items():
        if not isinstance(m, dict):
            continue
        roots = set()
        for v in m.values():
            if isinstance(v, dict) and isinstance(v.get(1), str):
                roots.add(v[1].lower())
        out[str(kind)] = sorted(roots)
    return out


def load(mod_root):
    """{kind: [cut root bone, ...]} from <mod_root>/gamedata/scripts/zgo_tables.script."""
    tables = os.path.join(mod_root, 'gamedata', 'scripts', 'zgo_tables.script')
    try:
        g = read_tables(tables, wanted={'limb_map'})
    except OSError as e:
        raise LuaReadError("can't read %s: %s" % (tables, e))
    if 'limb_map' not in g:
        raise LuaReadError('%s has no limb_map table' % tables)
    return roots_from_limb_map(g['limb_map'])


def canonical(limb_roots):
    """One line that changes whenever the cut roots change (kinds and roots
    sorted): 'boar=bip01_head,...;dog=...'. The bake records it, and the game
    builds the same line from zgo_tables.limb_map (zgo_setup_notice)."""
    return ';'.join('%s=%s' % (k, ','.join(sorted(v))) for k, v in sorted(limb_roots.items()) if v)
