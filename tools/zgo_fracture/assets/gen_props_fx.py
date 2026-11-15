#!/usr/bin/env python3
"""
Writes the props particle effects (gamedata/particles/zgo/props/*.pe) as
tuned copies of effects ZGO already ships (srbd debris, sparks and dust
clouds, ZGO's droplet jet): colour, count, size, speed and lifetime change;
textures and shaders stay the templates' own (the kid-mode workstream owns
shader lines; these effects are environmental and never need its swap).

Direction convention of every effect written here: particles fly or drift
along the effect's +z, which zgo_props points along the surface normal (out
of the object, back toward the shooter) or along the leak.

  python3 gen_props_fx.py            (developer tool; the output ships)
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
PDIR = os.path.join(MOD_ROOT, 'gamedata', 'particles')
OUT = os.path.join(PDIR, 'zgo', 'props')

T_CHUNK = 'srbd/headshot/srbd_headshot_debris_armor.pe'   # chunky bits, cone toward -z
T_GLASS = 'srbd/hit/srbd_hit_debris_glass.pe'            # glass shards, ball biased to -z
T_CLOTH = 'srbd/hit/srbd_hit_debris_cloth.pe'            # fluttering cloth bits, upward
T_SPARK = 'srbd/effects/hfx/body_impact_sparks_08.pe'    # sparks, every way
T_CLOUD = 'srbd/effects/cloud/smoke_point_brick_cloud.pe'  # one dust puff drifting +z
T_JET = 'zgo/jet_weak.pe'                                # droplet stream along +z

WOOD = (0.58, 0.45, 0.30)
SPECS = {
    # name: (template, options)
    'splinters':      (T_CHUNK, dict(flip=True, color=WOOD, count=10, size=0.8)),
    'burst_wood':     (T_CHUNK, dict(flip=True, color=WOOD, count=28, size=1.7, speed=0.8)),
    'chips_light':    (T_CHUNK, dict(flip=True, color=(0.78, 0.77, 0.74), count=8, size=0.6)),
    'chips_stone':    (T_CHUNK, dict(flip=True, color=(0.56, 0.55, 0.52), count=10, size=0.7)),
    'glass':          (T_GLASS, dict(flip=True, count=10)),
    'glass_burst':    (T_GLASS, dict(flip=True, count=36, size=1.2, speed=0.6)),
    'fluff':          (T_CLOTH, dict(count=6)),
    'fluff_paper':    (T_CLOTH, dict(color=(0.86, 0.84, 0.78), count=10)),
    'sparks_small':   (T_SPARK, dict(count=3)),
    'sparks':         (T_SPARK, dict(count=8)),
    'sparks_big':     (T_SPARK, dict(count=20, speed=1.6)),
    'dust_wood':      (T_CLOUD, dict(color=(0.50, 0.42, 0.33), size=0.6)),
    'dust_wood_big':  (T_CLOUD, dict(color=(0.50, 0.42, 0.33), size=2.5, life=1.5, drift=1.5)),
    'dust_metal':     (T_CLOUD, dict(color=(0.45, 0.44, 0.42), size=0.4)),
    'dust_light':     (T_CLOUD, dict(color=(0.62, 0.60, 0.56), size=0.6)),
    'dust_stone':     (T_CLOUD, dict(color=(0.55, 0.53, 0.50), size=0.7)),
    'dust_stone_big': (T_CLOUD, dict(color=(0.55, 0.53, 0.50), size=2.5, life=1.5, drift=1.5)),
    'leak_water':     (T_JET, dict(color=(0.40, 0.43, 0.45), speed=0.8)),
    'leak_fuel':      (T_JET, dict(color=(0.45, 0.36, 0.14), speed=0.8)),
    'leak_oil':       (T_JET, dict(color=(0.07, 0.06, 0.05), speed=0.7)),
    'leak_chem':      (T_JET, dict(color=(0.42, 0.52, 0.12), speed=0.8)),
    'jet_gas':        (T_CLOUD, dict(color=(0.85, 0.86, 0.88), size=0.5, drift=6.0)),
    'jet_powder':     (T_CLOUD, dict(color=(0.93, 0.93, 0.93), size=0.8, drift=4.0)),
}


def parse(path):
    secs, order, cur = {}, [], None
    with open(path, encoding='latin1') as f:
        for line in f:
            m = re.match(r'\s*\[(.+)\]', line)
            if m:
                cur = m.group(1)
                secs[cur] = []
                order.append(cur)
            elif '=' in line and cur is not None:
                k, v = line.split('=', 1)
                secs[cur].append([k.strip(), v.strip()])
    return secs, order


def get(sec, key):
    for kv in sec:
        if kv[0] == key:
            return kv[1]


def put(sec, key, val):
    for kv in sec:
        if kv[0] == key:
            kv[1] = val
            return
    sec.append([key, val])


def vec(s):
    return [float(x) for x in s.split(',')]


def fmt(v):
    return ', '.join('%.6f' % x for x in v)


def actions(secs, order, name):
    return [s for s in order if s.startswith('action_') and get(secs[s], 'action_name') == name]


def transform(secs, order, o):
    if 'count' in o:
        put(secs['_effect'], 'max_particles', str(o['count']))
    if 'life' in o:
        for a in actions(secs, order, 'killold'):
            put(secs[a], 'flt_0000', '%.6f' % (float(get(secs[a], 'flt_0000')) * o['life']))
    for a in actions(secs, order, 'source'):
        n = a.split('_')[1]
        col = secs.get('domain_action_%s_0000' % n)
        size = secs.get('domain_action_%s_0003' % n)
        vel = secs.get('domain_action_%s_0004' % n)
        if 'color' in o and col is not None:
            put(col, 'type', '0')
            put(col, 'v0', fmt(o['color']))
            put(col, 'v1', fmt(o['color']))
        if 'size' in o and size is not None:
            for k in ('v0', 'v1'):
                put(size, k, fmt([x * o['size'] for x in vec(get(size, k))]))
        if vel is not None:
            t = int(get(vel, 'type'))
            v0, v1, v2 = vec(get(vel, 'v0')), vec(get(vel, 'v1')), vec(get(vel, 'v2'))
            sp = o.get('speed', 1.0)
            if t == 5:      # sphere: centre, radii
                v0 = [x * sp for x in v0]
                v1 = [v1[0] * sp, v1[1] * sp, v1[2]]
                if o.get('flip'):
                    v0[2] = -v0[2]
            elif t == 4:    # box: min, max
                v0, v1 = [x * sp for x in v0], [x * sp for x in v1]
                if o.get('flip'):
                    v0[2], v1[2] = -v1[2], -v0[2]
            else:           # point, line, cylinder, cone: points, then radii
                v0, v1 = [x * sp for x in v0], [x * sp for x in v1]
                v2 = [v2[0] * sp, v2[1] * sp, v2[2]]
                if o.get('flip'):
                    v0[2], v1[2] = -v0[2], -v1[2]
            put(vel, 'v0', fmt(v0))
            put(vel, 'v1', fmt(v1))
            put(vel, 'v2', fmt(v2))
    if 'color' in o:
        for a in actions(secs, order, 'targetcolor'):
            if get(secs[a], 'vec_0000') is not None:
                put(secs[a], 'vec_0000', fmt(o['color']))
    if 'drift' in o:
        for a in actions(secs, order, 'targetvelocity'):
            put(secs[a], 'vec_0000', fmt([0.0, 0.0, o['drift']]))


def write(secs, order, path):
    lines = []
    for s in order:
        lines.append('[%s]' % s)
        for k, v in secs[s]:
            lines.append('        %-32s = %s' % (k, v))
        lines.append(' ')
    with open(path, 'w', encoding='latin1', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (tpl, o) in sorted(SPECS.items()):
        secs, order = parse(os.path.join(PDIR, *tpl.split('/')))
        transform(secs, order, o)
        write(secs, order, os.path.join(OUT, name + '.pe'))
    print('%d effects -> %s' % (len(SPECS), OUT))


if __name__ == '__main__':
    main()
