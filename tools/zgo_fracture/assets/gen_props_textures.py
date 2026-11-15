#!/usr/bin/env python3
"""
Writes the puddle decals of leaking containers (gamedata/textures/zgo/props/
puddle_<liquid>_<n>.dds, DXT5 with mipmaps) and their wallmark sections
(gamedata/configs/mod_system_zgo_props.ltx).

A puddle is a soft, noisy blob: colour = the liquid, alpha = how much it
covers (water only darkens, oil nearly hides the floor). Drawn with the
engine's wallmark shader like every other ZGO decal.

  python3 gen_props_textures.py      (developer tool; needs numpy, Pillow, ImageMagick)
"""
import os, subprocess, tempfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
TEX = os.path.join(MOD_ROOT, 'gamedata', 'textures', 'zgo', 'props')
LTX = os.path.join(MOD_ROOT, 'gamedata', 'configs', 'mod_system_zgo_props.ltx')
SIZE = 256

# liquid: (variants, rgb 0..1, peak alpha, sheen) - keep in step with zgo_props_data.LIQUIDS
LIQUIDS = {
    'water': (3, (0.10, 0.10, 0.09), 0.55, 0.0),
    'fuel':  (3, (0.17, 0.14, 0.07), 0.62, 0.35),
    'oil':   (3, (0.025, 0.022, 0.02), 0.86, 0.25),
    'chem':  (2, (0.30, 0.36, 0.07), 0.62, 0.0),
}


def smooth_noise(rng, n, cells):
    g = rng.random((cells + 1, cells + 1))
    img = Image.fromarray((g * 255).astype(np.uint8)).resize((n, n), Image.BICUBIC)
    return np.asarray(img, dtype=np.float64) / 255.0


def fbm(rng, n):
    out = np.zeros((n, n))
    amp, tot = 1.0, 0.0
    for cells in (3, 6, 12, 24):
        out += amp * smooth_noise(rng, n, cells)
        tot += amp
        amp *= 0.5
    return out / tot


def puddle(seed, rgb, peak, sheen):
    rng = np.random.default_rng(seed)
    n = SIZE
    y, x = np.mgrid[0:n, 0:n] / (n - 1) * 2 - 1
    r = np.sqrt(x * x + y * y)
    a = np.arctan2(y, x)
    # wobbly outline: radius varies with angle (low harmonics) and noise
    edge = 0.62
    for k in (2, 3, 5):
        edge = edge + rng.uniform(0.03, 0.09) * np.cos(k * a + rng.uniform(0, 6.28))
    edge = edge + 0.12 * (fbm(rng, n) - 0.5)
    cover = np.clip((edge - r) / 0.08, 0, 1)            # soft rim
    depth = np.clip((edge - r) / max(0.2, edge.mean()), 0, 1) ** 0.5
    alpha = cover * peak * (0.75 + 0.25 * depth) * (0.9 + 0.2 * fbm(rng, n))
    tone = 0.85 + 0.3 * fbm(rng, n)
    col = np.stack([np.full((n, n), c) for c in rgb], -1) * tone[..., None]
    if sheen > 0:
        # a faint oily rainbow: hue swirls with the noise
        h = fbm(rng, n) * 6.28 * 2
        rain = np.stack([np.sin(h), np.sin(h + 2.09), np.sin(h + 4.19)], -1) * 0.5 + 0.5
        col = col * (1 - sheen * 0.5) + rain * 0.12 * sheen
    rgba = np.concatenate([np.clip(col, 0, 1), np.clip(alpha, 0, 1)[..., None]], -1)
    return Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), 'RGBA')


def to_dds(img, path):
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, 'p.png')
        img.save(png)
        subprocess.run(['magick', png, '-define', 'dds:compression=dxt5', '-define', 'dds:mipmaps=6', path], check=True)
    with open(path, 'rb') as f:
        head = f.read(128)
    assert head[:4] == b'DDS ' and head[84:88] == b'DXT5', path


def main():
    os.makedirs(TEX, exist_ok=True)
    lines = ['; Zone Gore Overhaul - props: puddles under leaking containers (zgo_props).',
             '; Written by tools/zgo_fracture/assets/gen_props_textures.py.', '']
    seed = 7100
    for liquid in sorted(LIQUIDS):
        count, rgb, peak, sheen = LIQUIDS[liquid]
        for i in range(1, count + 1):
            seed += 1
            name = 'puddle_%s_%d' % (liquid, i)
            to_dds(puddle(seed, rgb, peak, sheen), os.path.join(TEX, name + '.dds'))
            lines += ['[zgo_props_%s]' % name, 'wallmarks = zgo\\props\\%s' % name]
    with open(LTX, 'w', encoding='ascii', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    print('puddles -> %s, sections -> %s' % (TEX, LTX))


if __name__ == '__main__':
    main()
