# The textures' archive (`db/mods/zgo_static.db0`)

The mod ships its own textures as one engine archive, not as some 4,500 loose files.
`dev/package.py` builds it into the release zip, and `dev/deploy.py` builds it into the mod
folder. It is never kept in the repo (`.gitignore`).

## Why

MO2's virtual file system indexes every loose file of every mod each time the game starts. The
game log shows this as "Init FileSystem". On the maintainer's Wine setup, each loose file costs
about 1.1–2.3 ms there; a file inside an archive costs about 25 µs. Moving 4,455 textures into
the archive should save roughly 5–10 s at every start.

## What goes in

A texture goes in only if no other source has a file of that name:
- **Ours:** everything under `gamedata/textures/zgo/`, and the `gamedata/textures/wm/wm_blood_zgo_*.dds` wallmarks.
- **Rule:** `package.STATIC_PREFIXES`, `.dds` only.
- **Exceptions:** `package.STATIC_KEEP_LOOSE` lists exact paths that match the rule but must stay loose.

Everything else stays loose:
- **Textures that replace someone else's**, such as `wm_blood_2.dds` (the game's) and the
  Painter of the Zone / Cinematic VFX textures under `jdude/`, `fallout4/` and so on.
  - The engine registers the archives first and the loose files after them, and a loose file
    beats every archive.
  - Packed, our override would lose to the other mod's loose copy.
  - The order between two archives is not ours to rely on either.
- **Particles** (`.pe`/`.pg`): kid mode rewrites them per mod list (`tools/zgo_kidfx`).
- **Shaders, scripts, configs, meshes and `.thm` files.**

Scripts that check for a texture (`zgo_wounds.script`, `zgo_probe.script`) use
`getFS():exist`, which sees archived files too. No tool reads or rewrites these textures.

## Clash check

To check by hand:

```
python3 dev/package.py --check-clashes --game <Anomaly folder> --mods <MO2 folder>/mods
```

It reads the archive tables and walks the matching folders of all of these:
- the game's archives (`<game>/db/**`) and its loose `gamedata/`;
- every mod folder's loose `gamedata/` and its own `db/` archives;
- MO2's `overwrite` folder.

Names compare without case. Any folder that holds this mod (its `zgo_main.script`) is skipped.

`deploy.py` runs the same check against the MO2 install it deploys into, and the real deploy
refuses on a clash. To fix one, add the path to `STATIC_KEEP_LOOSE`.

On 2026-11-16, both the G.A.M.M.A. install and the Umbra dev install had no clashes for all
4,455 textures.

## Format

It uses `tools/zgo_baker/xdb_write.py`, the same writer as the bake's
`zgo_bake_<part>_NN.db0` archives:
- a header chunk with `entry_point = $fs_root$\gamedata\` (the header's `link` line names the
  bake, since the writer is shared; the engine ignores it);
- the files stored uncompressed;
- an LZHUF-compressed table with folder entries.

The files go in sorted by path, so the same textures always give the same bytes.
`package.static_matches` compares a deployed archive's table (names, sizes, CRCs) with the repo.

The archive stays under `xdb_write.LIMIT` (512 MiB), and package refuses past it. Today it is
253 MB.

The bake's tools only touch archives named `zgo_bake_*`, so `bake.py --remove` and Setup's
orphan check leave this one alone.

## Deploy and upgrades

`deploy.py` builds the archive in place: it writes `.part` and then renames it. It then deletes
the loose copies that an earlier deploy left at the archived paths, and prunes the folders that
leaves empty.
- It never deletes files that a bake report lists.
- A texture the repo no longer has is only listed.

A player's folder from an older version still holds those loose copies. They win over the
archive: harmless while the bytes are the same, stale once a texture changes. Handling by install
method:
- **Umbra's installer:** replaces the layer's folder on update, so nothing is left behind.
- **Manual install over an old folder:** remove `gamedata/textures/zgo/` and
  `gamedata/textures/wm/wm_blood_zgo_*` first.

## Tests

`tests/package/test_static_archive.py` (in `dev/ci_tests.py`) checks:
- the archive holds exactly the chosen textures, byte for byte, read back with `xdb.Archive`;
- two builds are identical;
- overrides stay loose;
- the clash check finds every kind of source;
- the dry runs of package and deploy show the archive and no loose copies.

Set `ZGO_TEST_ANOMALY` and `ZGO_TEST_MO2` to also check against a real install.
