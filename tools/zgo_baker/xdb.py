"""
Reader for X-Ray / Anomaly .db archives (xrCore CLocatorAPI::ProcessArchive).

  chunk 0x29a      ltx header (mount point)
  chunk 0          file data
  chunk 1 | 0x80000000   file list, LZHUF-compressed (xrCore LzHuf.cpp)
  file list entry  u16 size, u32 real, u32 compressed, u32 crc, name, u32 offset
  file data        raw when real == compressed, else LZO1X (rtc_decompress)
"""
import struct

# ---------------------------------------------------------------- LZHUF
N, F, THRESHOLD = 4096, 60, 2
N_CHAR = 256 - THRESHOLD + F
T = N_CHAR * 2 - 1
R = T - 1
MAX_FREQ = 0x4000          # (Okumura used 0x8000; X-Ray archives need 0x4000)

D_CODE = bytes(
    [0x00] * 32 + [0x01] * 16 + [0x02] * 16 + [0x03] * 16 + [0x04] * 8 + [0x05] * 8 + [0x06] * 8 + [0x07] * 8 +
    [0x08] * 8 + [0x09] * 8 + [0x0A] * 8 + [0x0B] * 8 + [0x0C] * 4 + [0x0D] * 4 + [0x0E] * 4 + [0x0F] * 4 +
    sum(([x] * 4 for x in range(0x10, 0x18)), []) + sum(([x] * 2 for x in range(0x18, 0x30)), []) +
    list(range(0x30, 0x40)))
D_LEN = bytes(
    [0x03] * 32 + [0x04] * 48 + [0x05] * 64 + [0x06] * 48 + [0x07] * 48 + [0x08] * 16)
assert len(D_CODE) == 256 and len(D_LEN) == 256


def lzhuf_decode(src):
    textsize, = struct.unpack_from('<I', src)
    pos = 4
    getbuf = 0
    getlen = 0
    n = len(src)

    freq = [0] * (T + 1)
    prnt = [0] * (T + N_CHAR)
    son = [0] * T
    for i in range(N_CHAR):
        freq[i] = 1
        son[i] = i + T
        prnt[i + T] = i
    i, j = 0, N_CHAR
    while j <= R:
        freq[j] = freq[i] + freq[i + 1]
        son[j] = i
        prnt[i] = prnt[i + 1] = j
        i += 2
        j += 1
    freq[T] = 0xFFFF
    prnt[R] = 0

    def reconst():
        j = 0
        for i in range(T):
            if son[i] >= T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, N_CHAR
        while j < T:
            k = i + 1
            f = freq[j] = freq[i] + freq[k]
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(T):
            k = son[i]
            if k >= T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(c):
        if freq[R] == MAX_FREQ:
            reconst()
        c = prnt[c + T]
        while True:
            freq[c] += 1
            k = freq[c]
            l = c + 1
            if k > freq[l]:
                while k > freq[l + 1]:
                    l += 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break

    out = bytearray()
    text = bytearray(b' ' * N)
    r = N - F
    while len(out) < textsize:
        # DecodeChar
        c = son[R]
        while c < T:
            if getlen <= 8:
                b = src[pos] if pos < n else 0
                pos += 1
                getbuf |= b << (8 - getlen)
                getlen += 8
            bit = (getbuf >> 15) & 1
            getbuf = (getbuf << 1) & 0xFFFF
            getlen -= 1
            c = son[c + bit]
        c -= T
        update(c)
        if c < 256:
            out.append(c)
            text[r] = c
            r = (r + 1) & (N - 1)
            continue
        # DecodePosition
        def getbits(nb):
            nonlocal getbuf, getlen, pos
            while getlen <= 8:
                b = src[pos] if pos < n else 0
                pos += 1
                getbuf |= b << (8 - getlen)
                getlen += 8
            v = getbuf >> (16 - nb)
            getbuf = (getbuf << nb) & 0xFFFF
            getlen -= nb
            return v
        i = getbits(8)
        cc = D_CODE[i] << 6
        jlen = D_LEN[i] - 2
        while jlen:
            i = (i << 1) + getbits(1)
            jlen -= 1
        p = cc | (i & 0x3F)
        start = (r - p - 1) & (N - 1)
        for k in range(c - 255 + THRESHOLD):
            ch = text[(start + k) & (N - 1)]
            out.append(ch)
            text[r] = ch
            r = (r + 1) & (N - 1)
    return bytes(out[:textsize])


# ---------------------------------------------------------------- LZO1X
def lzo1x_decompress(src, out_len):
    out = bytearray()
    ip = 0
    n = len(src)

    def length_ext(base):
        nonlocal ip
        t = 0
        while src[ip] == 0:
            t += 255
            ip += 1
        t += base + src[ip]
        ip += 1
        return t

    def copy_match(dist, length):
        s = len(out) - dist
        if dist >= length:
            out.extend(out[s:s + length])
        else:
            for k in range(length):
                out.append(out[s + k])

    state = 0
    t = src[ip]
    if t > 17:
        ip += 1
        t -= 17
        out.extend(src[ip:ip + t])
        ip += t
        state = 4 if t >= 4 else t
    while True:
        t = src[ip]
        ip += 1
        if t < 16:
            if state == 0:
                if t == 0:
                    t = length_ext(15)
                t += 3
                out.extend(src[ip:ip + t])
                ip += t
                state = 4
                continue
            elif state < 4:
                dist = 1 + (t >> 2) + (src[ip] << 2)
                ip += 1
                copy_match(dist, 2)
                lit = t & 3
            else:
                dist = 1 + 0x800 + (t >> 2) + (src[ip] << 2)
                ip += 1
                copy_match(dist, 3)
                lit = t & 3
        elif t >= 64:
            dist = 1 + ((t >> 2) & 7) + (src[ip] << 3)
            ip += 1
            copy_match(dist, (t >> 5) - 1 + 2 - 1 + 1)
            lit = t & 3
        elif t >= 32:
            ln = t & 31
            if ln == 0:
                ln = length_ext(31)
            ln += 2
            d16 = src[ip] | (src[ip + 1] << 8)
            ip += 2
            copy_match(1 + (d16 >> 2), ln)
            lit = d16 & 3
        else:
            ln = t & 7
            if ln == 0:
                ln = length_ext(7)
            ln += 2
            d16 = src[ip] | (src[ip + 1] << 8)
            ip += 2
            dist = ((t & 8) << 11) + (d16 >> 2)
            if dist == 0:
                break                       # end of stream
            copy_match(dist + 0x4000, ln)
            lit = d16 & 3
        if lit:
            out.extend(src[ip:ip + lit])
            ip += lit
        state = lit
    if len(out) != out_len:
        raise ValueError('lzo: %d bytes, expected %d' % (len(out), out_len))
    return bytes(out)


# ---------------------------------------------------------------- archive
class Archive:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            data = f.read()
        self.data = data
        self.header = b''
        lst = None
        o = 0
        while o + 8 <= len(data):
            cid, sz = struct.unpack_from('<II', data, o)
            body = data[o + 8:o + 8 + sz]
            if cid & 0x7FFFFFFF == 1:
                lst = lzhuf_decode(body) if cid & 0x80000000 else body
            elif cid == 0x29A:
                self.header = body
            o += 8 + sz
        if lst is None:
            raise ValueError('no file list')
        self.files = {}
        o = 0
        while o < len(lst):
            bs, = struct.unpack_from('<H', lst, o)
            real, comp, crc = struct.unpack_from('<III', lst, o + 2)
            name = lst[o + 14:o + 2 + bs - 4].decode('latin1')
            ptr, = struct.unpack_from('<I', lst, o + 2 + bs - 4)
            self.files[name.lower()] = (ptr, real, comp)
            o += 2 + bs

    def read(self, name):
        ptr, real, comp = self.files[name.lower()]
        raw = self.data[ptr:ptr + comp]
        if real == comp:
            return raw
        return lzo1x_decompress(raw, real)
