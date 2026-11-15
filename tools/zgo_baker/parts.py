"""
Attachment models built from a baked model (docs/formats/caps.md, pieces.md):

  stump caps   gamedata/meshes/zgo/baked/caps/<h[:2]>/<h>.ogf
  limb pieces  gamedata/meshes/zgo/baked/pieces/<h[:2]>/<h>.ogf
  K_s          (--experimental-caps) the same caps as sub-meshes of the model
               itself, shader zgo\\off, switched on by the runtime at the cut

Both attachment kinds are MT_SKELETON_RIGID models (CKinematics: script
attachments R_ASSERT dcast_PKinematics, and set_shader needs a skeleton).
File names are the first 12 hex digits of the SHA-1 of the file, so identical
caps / pieces from different models are one file.

Frames (the part that makes attachments exact):
  * a cap's bone 0 is the cut root's parent bone p, with an identity bind, so
    the cap's model space IS p's bind frame. Attached to p with no offset it
    renders exactly where the victim's own skinning would put a vertex held
    by p; with every cap bone following the victim's bone of the same name
    (bone_callback(name, name, true)) it skins exactly like the victim's seam.
  * a piece's bone 0 is the cut root s with an identity bind (s's bind frame);
    its other bones keep their bind exactly, so bone callbacks that return
    "world bone matrix relative to the attachment" (what zgo_debris does
    today) pose it exactly like the victim's limb.
"""
import hashlib
import numpy as np
import ogf
import caps as capmod

CAP_DIR = 'zgo\\baked\\caps'
PIECE_DIR = 'zgo\\baked\\pieces'
OFF_SHADER = 'zgo\\off'


def content_name(folder, data):
    """Engine model name (no .ogf) for these file bytes."""
    h = hashlib.sha1(data).hexdigest()[:12]
    return folder + '\\' + h[:2] + '\\' + h


def model_path(name):
    """gamedata-relative file path of an engine model name."""
    return 'gamedata/meshes/' + name.replace('\\', '/') + '.ogf'


def subtree_sections(skel, roots):
    """{root: [roots in its subtree, itself first]}"""
    out = {}
    for s in roots:
        below = set(skel.descendants(s))
        out[s] = [s] + [r for r in roots if r != s and r in below]
    return out


def _used_bones(geoms):
    used = set()
    for g in geoms:
        live = g.weights[:, :g.links] > 0
        live[:, 0] = True
        used.update(np.unique(g.bones[:, :g.links][live]).tolist())
    return used


def _bounds_obb(P, m_inv, margin=0.01):
    """OBB (axis-aligned in a bone's frame) around points P given in the
    attachment's model space; m_inv maps model space into that bone's frame."""
    Q = P @ m_inv[:3, :3].T + m_inv[:3, 3]
    return ogf.obb_bytes(Q.min(0), Q.max(0), margin)


def stump_cap(model, s, loops, salt):
    """caps.Cap for the stump left when s goes (anchor: s's parent)."""
    skel = model.skeleton
    p = skel.bones[s].parent
    toward = loops[1] if loops[1] is not None else skel.pos(s)
    return capmod.build(loops[0], toward, p, skel.pos(s), salt + ':stump')


def piece_cap(model, s, loops, body_centre, salt):
    """caps.Cap for the open end of the limb piece s (anchor: s)."""
    skel = model.skeleton
    toward = body_centre if body_centre is not None else skel.pos(skel.bones[s].parent)
    return capmod.build(loops[0], toward, s, skel.pos(s), salt + ':piece')


def cap_geoms(cap, shader=capmod.SHADER):
    """(face, stub) Geoms in model space (either may be None)."""
    return cap.face.geom(capmod.FLESH_TEX, shader), cap.stub.geom(capmod.BONE_TEX, shader)


def cap_model(model, s, cap):
    """(bytes, bone names) of the cap attachment for section s, or None.

    Bones: p (bone 0, identity bind), then the bones on the paths from s down
    to every bone a cap vertex uses, with their parents and local binds as in
    the victim, then (rare: a seam weighted to bones above p, e.g. a neck seam
    that also follows the spine) any other used bone as a child of p with its
    bind relative to p. In every case the cap bind of a bone b equals
    inverse(Bind_p) * Bind_b, so the attachment frames in docs/formats/caps.md
    hold for all of them."""
    skel = model.skeleton
    p = skel.bones[s].parent
    geoms = [g for g in cap_geoms(cap) if g is not None]
    if not geoms or p < 0:
        return None
    below = set(skel.descendants(s))
    need, outside = {p}, set()
    for b in _used_bones(geoms):
        if b == p:
            continue
        if b not in below:
            outside.add(b)
            continue
        while b != p and b not in need:
            need.add(b)
            b = skel.bones[b].parent
    order = [p] + sorted(need - {p}) + sorted(outside)
    if len(order) > 64:
        return None
    new_id = {b: i for i, b in enumerate(order)}
    to_local = ogf.rigid_inverse(skel.bones[p].world)
    local = [ogf.transform_geom(g, to_local, new_id) for g in geoms]
    P = np.concatenate([g.P for g in local]).astype(np.float64)
    bones = []
    for b in order:
        bn = skel.bones[b]
        # cap-bind of b relative to p, and its inverse (p frame -> b frame)
        rel = to_local @ bn.world
        obb = _bounds_obb(P, ogf.rigid_inverse(rel))
        if b == p:
            bones.append((bn.name, '', obb, ogf.ik_record(bn, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), ogf.NO_SHAPE)))
        elif b in outside:
            rot = ogf.xyzi_from_matrix(rel[:3, :3])
            bones.append((bn.name, skel.bones[p].name, obb,
                          ogf.ik_record(bn, rot, tuple(float(x) for x in rel[:3, 3]), ogf.NO_SHAPE)))
        else:
            bones.append((bn.name, skel.bones[bn.parent].name, obb, ogf.ik_record(bn, shape=ogf.NO_SHAPE)))
    return ogf.build_skeleton_model(bones, local), [skel.bones[b].name for b in order]


def piece_model(model, kids, s, subtree, pcap):
    """(bytes, bone names) of the limb piece for section s: the sub-meshes of
    every section in s's subtree plus the flesh end, in s's bind frame."""
    skel = model.skeleton
    order = [s] + sorted(set(skel.descendants(s)) - {s})
    if len(order) > 64:
        return None
    new_id = {b: i for i, b in enumerate(order)}
    # the piece end copies the seam's weights; a seam that also follows bones
    # above s (rare) is held by s instead (the piece has nothing else)
    lut = np.array([new_id.get(b, 0) for b in range(len(skel.bones))], np.int64)
    to_local = ogf.rigid_inverse(skel.bones[s].world)
    secs = set(subtree)
    geoms = [k for k in kids if getattr(k, 'section', None) in secs]
    if not geoms:
        return None
    n_end = 0
    if pcap is not None:
        end = [g for g in cap_geoms(pcap) if g is not None]
        geoms, n_end = geoms + end, len(end)
    local = [ogf.transform_geom(g, to_local, new_id) for g in geoms[:len(geoms) - n_end]]
    local += [ogf.transform_geom(g, to_local, lut) for g in geoms[len(geoms) - n_end:]]
    bones = []
    for b in order:
        bn = skel.bones[b]
        if b == s:
            bones.append((bn.name, '', bn.obb, ogf.ik_record(bn, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))))
        else:
            bones.append((bn.name, skel.bones[bn.parent].name, bn.obb, ogf.ik_record(bn)))
    return ogf.build_skeleton_model(bones, local), [skel.bones[b].name for b in order]


def kcap_geoms(cap, section):
    """K_s sub-meshes (model space, the model's bone ids), shader zgo\\off.
    .section is set to the anchor's section by the caller."""
    out = []
    for g in cap_geoms(cap, OFF_SHADER):
        if g is not None:
            out.append(g)
    return out
