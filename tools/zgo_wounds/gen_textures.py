#!/usr/bin/env python3
"""Umbra Gore & Effects - textures for the wound shaders (zgo\\dmg, PLAN Phase C).

    python3 tools/zgo_wounds/gen_textures.py            write them
    python3 tools/zgo_wounds/gen_textures.py --check    exit 1 if the files on disk differ
    python3 tools/zgo_wounds/gen_textures.py --out DIR  write somewhere else

Everything is procedural (numpy) and deterministic: fixed seeds, no input
files, so the same bytes come out on every machine. The files are shipped
with the mod (they do not depend on the player's mod list); this script is
how they were made.

Output, in gamedata/textures/zgo/wounds/ (engine names zgo\\wounds\\...):

  n/000.dds .. n/fff.dds   4096 "number" textures, 1x1 A8R8G8B8, one mip.
                           zgo_dmg.s binds four of them to vertex-shader
                           slots per damaged sub-mesh, chosen from the
                           texture string the runtime passes (npc.md 3, C3:
                           per-NPC data without native code). The shader
                           reads the texel with Load (no sampler, no
                           filtering) and decodes a 12-bit value:
                             R = v >> 4, G = (v & 15) * 17,
                             B = (R + (v & 15) * 3 + 90) & 255  (check byte),
                             A = 255
                           A texel that fails the check (the engine's pink
                           "texture not found" stand-in, an empty slot that
                           reads 0) decodes as "no wound": the mesh is drawn
                           undisplaced. One mip, so texture-quality settings
                           never drop it (dx10Texture.cpp Reduce needs > 1).
  tissue.dds               256x256 A8R8G8B8, full mip chain, tileable.
                           Grey patterns, one per channel, that the wound
                           pixel shader multiplies its layer colours by:
                             R muscle fibre bundles (streaks along x)
                             G fat lobules (cells)
                             B bone (fine pores)
                             A wet clot / height noise
  stump.dds                256x256 A8R8G8B8, full mip chain: the cut face of
                           a limb (ragged skin and fat ring, muscle bundles
                           with fascia lines, a darker clotted middle), laid
                           out for the stump caps' planar UV square
                           (0.15..0.85, docs/formats/caps.md). Offered to the
                           baker as caps.FLESH_TEX (docs/integration/wounds.md).
"""
import argparse
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(ROOT, 'gamedata', 'textures', 'zgo', 'wounds')

SIZE = 256

# ------------------------------------------------------------------ DDS

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT = 0x1000, 0x20000
DDPF_ALPHAPIXELS, DDPF_RGB = 0x1, 0x40
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000


def dds_a8r8g8b8(levels):
    """DDS file bytes for a list of mip levels (uint8 HxWx4 arrays in R,G,B,A
    order, largest first). Legacy header, D3DFMT_A8R8G8B8 (bytes B,G,R,A),
    which D3DX11 loads as DXGI_FORMAT_B8G8R8A8_UNORM."""
    h, w = levels[0].shape[:2]
    n = len(levels)
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT | DDSD_MIPMAPCOUNT
    caps = DDSCAPS_TEXTURE | ((DDSCAPS_COMPLEX | DDSCAPS_MIPMAP) if n > 1 else 0)
    pf = struct.pack('<8I', 32, DDPF_RGB | DDPF_ALPHAPIXELS, 0, 32,
                     0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
    head = struct.pack('<7I', 124, flags, h, w, w * 4, 0, n) + b'\0' * 44 + pf + struct.pack('<5I', caps, 0, 0, 0, 0)
    assert len(head) == 124
    body = b''.join(np.ascontiguousarray(lv[:, :, [2, 1, 0, 3]]).astype(np.uint8).tobytes() for lv in levels)
    return b'DDS ' + head + body


def mips(img):
    """Full mip chain by 2x2 box filtering (tileable input stays tileable)."""
    out = [img]
    cur = img.astype(np.float64)
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        hh, ww = max(1, cur.shape[0] // 2), max(1, cur.shape[1] // 2)
        cur = cur[:hh * 2, :ww * 2].reshape(hh, 2, ww, 2, -1).mean(axis=(1, 3))
        out.append(np.clip(np.round(cur), 0, 255).astype(np.uint8))
    return out

# ------------------------------------------------------------------ numbers


def number_texel(v):
    """(R, G, B, A) of number texture v (0..4095); see the module docstring."""
    hi, lo = v >> 4, v & 15
    return hi, lo * 17, (hi + lo * 3 + 90) & 255, 255


def number_texture(v):
    r, g, b, a = number_texel(v)
    return dds_a8r8g8b8([np.array([[[r, g, b, a]]], dtype=np.uint8)])

# ------------------------------------------------------------------ noise (all periodic on the texture)


def value_noise(rng, gx, gy, size=SIZE):
    """Smooth periodic value noise with gx x gy lattice cells, in 0..1."""
    grid = rng.random((gy, gx))
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    fx, fy = x * gx / size, y * gy / size
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    x1, y1 = (x0 + 1) % gx, (y0 + 1) % gy
    x0, y0 = x0 % gx, y0 % gy
    a = grid[y0, x0] * (1 - sx) + grid[y0, x1] * sx
    b = grid[y1, x0] * (1 - sx) + grid[y1, x1] * sx
    return a * (1 - sy) + b * sy


def fbm(rng, base_x, base_y, octaves, gain=0.5):
    acc, amp, tot = 0.0, 1.0, 0.0
    for o in range(octaves):
        acc = acc + amp * value_noise(rng, base_x << o, base_y << o)
        tot += amp
        amp *= gain
    return acc / tot


def worley(rng, n, size=SIZE):
    """Periodic cellular noise: (F1, F2) distances to the nearest two of n
    random points, in texels."""
    pts = rng.random((n, 2)) * size
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    best = np.full((size, size, 2), 1e9)
    for px, py in pts:
        dx = np.abs(x - px)
        dy = np.abs(y - py)
        dx = np.minimum(dx, size - dx)
        dy = np.minimum(dy, size - dy)
        d = np.sqrt(dx * dx + dy * dy)
        f1 = best[:, :, 0]
        closer = d < f1
        best[:, :, 1] = np.where(closer, f1, np.minimum(best[:, :, 1], d))
        best[:, :, 0] = np.where(closer, d, f1)
    return best[:, :, 0], best[:, :, 1]


def norm01(a):
    lo, hi = a.min(), a.max()
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)


def to8(a):
    return np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)

# ------------------------------------------------------------------ tissue patterns


def tissue():
    rng = np.random.default_rng(0x2600)
    # muscle: long bundles along x (few lattice cells across x, many along y),
    # broken up by a finer fbm, with thin dark fascia between bundles
    streak = fbm(rng, 2, 32, 3, 0.55)
    wobble = fbm(rng, 4, 4, 3)
    y = np.mgrid[0:SIZE, 0:SIZE][0].astype(np.float64)
    bands = 0.5 + 0.5 * np.sin((y / SIZE * 24.0 + wobble * 3.0) * 2 * np.pi)
    fascia = np.clip((bands - 0.92) / 0.08, 0, 1)
    muscle = norm01(0.65 * streak + 0.35 * fbm(rng, 8, 8, 4)) * (1 - 0.55 * fascia)
    muscle = norm01(muscle) * 0.75 + 0.25
    # fat: soft lobules (cells) with darker septa between them
    f1, f2 = worley(rng, 48)
    septa = np.clip((f2 - f1) / 6.0, 0, 1)
    fat = norm01(0.7 * septa + 0.3 * fbm(rng, 16, 16, 2)) * 0.6 + 0.4
    # bone: fine pores in an ivory field
    p1, p2 = worley(rng, 160)
    pores = np.clip(p1 / 4.0, 0, 1)
    bone = norm01(0.6 * pores + 0.4 * fbm(rng, 32, 32, 2)) * 0.45 + 0.55
    # clot / height: blotchy, mostly mid
    clot = norm01(fbm(rng, 4, 4, 5, 0.6))
    img = np.stack([to8(muscle), to8(fat), to8(bone), to8(clot)], axis=2)
    return dds_a8r8g8b8(mips(img))

# ------------------------------------------------------------------ stump cut face


def stump():
    rng = np.random.default_rng(0x5717)
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64)
    u, v = (x + 0.5) / SIZE, (y + 0.5) / SIZE
    # the caps' planar UV square is 0.15..0.85 around (0.5, 0.5)
    dx, dy = (u - 0.5) / 0.35, (v - 0.5) / 0.35
    r = np.sqrt(dx * dx + dy * dy)
    ang = np.arctan2(dy, dx)
    ragged = 0.05 * (fbm(rng, 8, 8, 3) - 0.5) + 0.03 * np.sin(ang * 7.0)
    rr = r + ragged
    noise = fbm(rng, 16, 16, 4)
    f1, f2 = worley(rng, 28)
    # fascia lines between muscle bundles, domain-warped so they wander
    wx, wy = fbm(rng, 4, 4, 3), fbm(rng, 4, 4, 3)
    iy = (y + (wy - 0.5) * 40).astype(int) % SIZE
    ix = (x + (wx - 0.5) * 40).astype(int) % SIZE
    bundles = np.clip((f2 - f1)[iy, ix] / 4.0, 0, 1)
    fibre = fbm(rng, 32, 32, 2)
    muscle = np.stack([0.50, 0.07, 0.06]) * (0.6 + 0.4 * bundles[..., None]) * (0.75 + 0.5 * fibre[..., None])
    fascia = np.stack([0.66, 0.44, 0.42]) * (0.8 + 0.3 * noise[..., None])
    line = np.clip(1 - bundles / 0.07, 0, 1)[..., None] * 0.6
    muscle = muscle * (1 - line) + fascia * line
    fat = np.stack([0.86, 0.74, 0.42]) * (0.85 + 0.25 * noise[..., None])
    skin = np.stack([0.55, 0.36, 0.30]) * (0.8 + 0.3 * noise[..., None])
    clot = np.stack([0.20, 0.02, 0.02]) * (0.7 + 0.6 * noise[..., None])
    blood = np.stack([0.32, 0.02, 0.02]) * (0.8 + 0.4 * noise[..., None])
    col = muscle
    col = np.where((rr < 0.28)[..., None], clot * 0.6 + muscle * 0.4, col)     # clotted middle
    col = np.where(((rr > 0.80) & (rr <= 0.93))[..., None], fat, col)          # fat ring
    col = np.where((rr > 0.93)[..., None], skin, col)                          # skin edge
    # blood smeared over everything, heavier toward the rim
    smear = np.clip((noise - 0.45) * 3.0 + (r - 0.6), 0, 0.85)[..., None]
    col = col * (1 - smear) + blood * smear
    img = np.concatenate([to8(np.clip(col, 0, 1)), np.full((SIZE, SIZE, 1), 255, np.uint8)], axis=2)
    return dds_a8r8g8b8(mips(img))

# ------------------------------------------------------------------ main


def outputs():
    """{relative path: bytes} of everything this script writes."""
    out = {}
    for v in range(4096):
        out['n/%03x.dds' % v] = number_texture(v)
    out['tissue.dds'] = tissue()
    out['stump.dds'] = stump()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--check', action='store_true', help='compare with the files on disk, write nothing')
    a = ap.parse_args(argv)
    files = outputs()
    bad = []
    for rel, data in sorted(files.items()):
        path = os.path.join(a.out, rel.replace('/', os.sep))
        if a.check:
            try:
                with open(path, 'rb') as f:
                    if f.read() != data:
                        bad.append(rel)
            except OSError:
                bad.append(rel)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'rb') as f:
                if f.read() == data:
                    continue
        except OSError:
            pass
        with open(path, 'wb') as f:
            f.write(data)
    if a.check:
        if bad:
            print('%d of %d texture(s) differ or are missing, e.g. %s' % (len(bad), len(files), ', '.join(bad[:5])))
            return 1
        print('all %d textures are current' % len(files))
        return 0
    print('wrote %d textures to %s' % (len(files), a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
