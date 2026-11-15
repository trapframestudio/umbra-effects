"""
Split every sub-mesh of a skinned model into one sub-mesh per severable
section, so the renderer can drop a section once its bones are hidden.

CSkeletonX::has_visible_bones() keeps a sub-mesh on screen while ANY bone
its vertices reference (BonesUsed, zero weights included) is visible. Umbra Effects
hides a cut part recursively (root bone and everything below it). So a
section's sub-mesh may only reference bones at or below the section root:

  * every triangle goes to the section of the lowest common ancestor of the
    bones its three vertices really use (weight > EPS). A triangle that
    spans the elbow (upper arm + forearm weights) belongs to the upper arm:
    the joint ring stays with the part that remains, and a lost forearm
    leaves an elbow, not a hole in the upper arm;
  * bone references with no real weight are pointed at the vertex's main
    bone (they would otherwise keep the sub-mesh alive, e.g. a gas mask
    glass weighted 0 to the root bone would float over a headless body).
"""
import numpy as np
import ogf

EPS = 0.0025          # exporters pad unused slots with ~0.0002 on random bones
BODY = -1


def section_roots(skel, limb_roots):
    """Cut roots (by bone id) for this skeleton: the roots of every creature
    kind whose roots all exist in it."""
    names = set(skel.by_name)
    roots = set()
    for kind, rs in limb_roots.items():
        if rs and all(r in names for r in rs):
            roots.update(rs)
    return sorted(skel.by_name[r] for r in roots)


def section_of_bone(skel, roots):
    rs = set(roots)
    sec = [BODY] * len(skel.bones)
    for b in skel.order():
        p = skel.bones[b].parent
        sec[b] = b if b in rs else (sec[p] if p >= 0 else BODY)
    return np.array(sec, np.int64)


def clean_weights(g):
    """Drop references with no real weight: point them at the main bone."""
    w = g.weights.copy()
    b = g.bones.copy()
    main = b[np.arange(g.n), w.argmax(1)]
    dead = w <= EPS
    w[dead] = 0
    b[dead] = np.broadcast_to(main[:, None], b.shape)[dead]
    s = w.sum(1, keepdims=True)
    w = w / np.where(s > 0, s, 1)
    # slots beyond the format's link count stay as they were (unused)
    g.bones, g.weights = b, w.astype(np.float32)


def tri_lca(skel, g):
    """Lowest common ancestor bone of each triangle (real weights only)."""
    anc = np.array(skel.anc, np.uint64)
    allbits = np.uint64(0xFFFFFFFFFFFFFFFF)
    vm = np.full(g.n, allbits, np.uint64)
    for k in range(g.links):
        live = g.weights[:, k] > EPS
        vm[live] &= anc[g.bones[live, k]]
    tm = vm[g.tris[:, 0]] & vm[g.tris[:, 1]] & vm[g.tris[:, 2]]
    lca = np.full(len(tm), -1, np.int64)
    for b in sorted(range(len(skel.bones)), key=lambda x: -skel.depth[x]):
        hit = (lca < 0) & ((tm >> np.uint64(b)) & np.uint64(1)).astype(bool)
        lca[hit] = b
    if (lca < 0).any():
        raise ogf.OgfError('triangle with no common bone')
    return lca


def bones_used(g):
    return set(np.unique(g.bones[:, :g.links]).tolist())


def split_model(model, limb_roots):
    """New sub-mesh list and a report. Returns (children, info) or None when
    the skeleton has no known cut roots. Every child carries .section (cut
    root bone id or BODY) and .source_child; info['labels'][ci] is the section
    of each triangle of source sub-mesh ci."""
    skel = model.skeleton
    roots = section_roots(skel, limb_roots)
    if not roots:
        return None
    sec_of = section_of_bone(skel, roots)
    out, report, labels = [], [], []
    for ci, g in enumerate(model.children):
        clean_weights(g)
        sec = sec_of[tri_lca(skel, g)]
        labels.append(sec)
        parts = [BODY] + roots
        for s in parts:
            mask = sec == s
            if not mask.any():
                continue
            sub = g.subset(mask)
            used = bones_used(sub)
            if s != BODY:
                allowed = set(skel.descendants(s))
                if not used <= allowed:
                    raise ogf.OgfError('section %s of sub-mesh %d uses bones outside it' % (skel.bones[s].name, ci))
            sub.section = s
            sub.source_child = ci
            out.append(sub)
            report.append((ci, skel.bones[s].name if s != BODY else 'body', int(mask.sum())))
    secs = sorted({skel.bones[g.section].name for g in out if g.section != BODY})
    # (labels: the section of every source triangle, for caps / pieces / wound sites;
    # the source sub-meshes in model.children now carry the cleaned weights)
    return out, {'sections': secs, 'children_in': len(model.children), 'children_out': len(out), 'parts': report,
                 'roots': roots, 'labels': labels, 'section_of_bone': sec_of}
