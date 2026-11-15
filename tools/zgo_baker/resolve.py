"""Which file the game actually loads for each model path: MO2 priority
(top of modlist.txt wins), then the base game archives (unpacked cache)."""
import os

def enabled_mods(mo2_root, profile):
    path = os.path.join(mo2_root, 'profiles', profile, 'modlist.txt')
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if line.startswith('+'):
                out.append(line[1:])
    return out                      # highest priority first


def winners(mo2_root, profile, subdirs=('meshes/actors', 'meshes/monsters'), skip=(), base_dirs=(), progress=None):
    """{ 'actors\\stalker_bandit\\bandit_1' : absolute path } for every .ogf.
    progress(done, total) per source folder scanned."""
    found = {}
    roots = [os.path.join(mo2_root, 'mods', m, 'gamedata') for m in enabled_mods(mo2_root, profile) if m not in skip]
    roots += list(base_dirs)        # lowest priority
    for i, root in enumerate(roots):
        if progress and (i % 50 == 0 or i + 1 == len(roots)):
            progress(i + 1, len(roots))
        for sub in subdirs:
            top = os.path.join(root, *sub.split('/'))
            if not os.path.isdir(top):
                continue
            for dp, _, files in os.walk(top):
                for fn in files:
                    if not fn.lower().endswith('.ogf'):
                        continue
                    full = os.path.join(dp, fn)
                    rel = os.path.relpath(full, os.path.join(root, 'meshes'))
                    key = rel[:-4].replace('/', '\\').lower()
                    if key not in found:
                        found[key] = full
    return found
