"""Extract the base game's actor and monster models from Anomaly's db
archives into a cache (the lowest-priority source for the baker)."""
import os, sys
from multiprocessing import Pool
import xdb

ARCHIVES = ('meshes/meshes_actors.db0', 'meshes/meshes.db0')
WANT = ('meshes\\actors\\', 'meshes\\monsters\\')
_arch = {}

def _one(job):
    db, name, out = job
    a = _arch.get(db) or _arch.setdefault(db, xdb.Archive(db))
    dst = os.path.join(out, *name.split('\\'))
    if os.path.exists(dst):
        return 0
    data = a.read(name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, dst)
    return 1

def unpack(anomaly_root, out_dir, procs=12, progress=None, cancel=None):
    """Extract what is missing; returns (models in the archives, newly extracted).
    progress(done, total) and cancel() as in bake.bake."""
    jobs = []
    for rel in ARCHIVES:
        db = os.path.join(anomaly_root, 'db', *rel.split('/'))
        if not os.path.isfile(db):
            raise FileNotFoundError('missing game archive %s' % db)
        a = xdb.Archive(db)
        jobs += [(db, n, out_dir) for n in a.files if n.endswith('.ogf') and n.startswith(WANT)]
    todo = [j for j in jobs if not os.path.exists(os.path.join(out_dir, *j[1].split('\\')))]
    done = 0
    if todo:
        with Pool(procs) as p:
            for i, d in enumerate(p.imap_unordered(_one, todo, chunksize=4)):
                done += d
                if progress and (i + 1) % 100 == 0:
                    progress(len(jobs) - len(todo) + i + 1, len(jobs))
                if cancel and cancel():
                    p.terminate()
                    break
    if progress:
        progress(len(jobs), len(jobs))
    return len(jobs), done

if __name__ == '__main__':
    n, d = unpack(sys.argv[1], sys.argv[2])
    print('models %d, extracted now %d' % (n, d))
