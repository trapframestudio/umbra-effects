# Umbra Gore & Effects (ZGO): notes for agents

A blood, gore, dismemberment and explosion overhaul for S.T.A.L.K.E.R. G.A.M.M.A. (Anomaly),
built on Painter of the Zone. It must work in single player and in xrRazom co-op.
It was called Zone Gore Overhaul (ZGO) up to 1.7.1; the code still uses the `zgo` prefix.
`README.txt` is the player's guide; `docs/PLAN.md` is the roadmap; `docs/discovery/` holds
the engine research.

## Layout

| Path | What | Shipped |
|---|---|---|
| `gamedata/` | scripts (`zgo_*.script`), shaders, particles, textures | yes |
| `bin/zgo_native.dll` | the native add-on, built from `native/` (needs the mingw container) | yes |
| `tools/` | baker, fracture, kidfx, Umbra Effects Setup (`tools/zgo_setup`) | yes, minus the generators `package.py` lists |
| `dev/` | dev container, packaging, deploy, setup program builds | no |
| `tests/`, `docs/`, `native/` | tests, docs, native sources | no |

## Rules

- **Compatibility is the hard line.** Single-player G.A.M.M.A. and xrRazom co-op must keep
  working. Never edit xrRazom's files and never swap its exes. Patch around it with script
  callbacks and ZGO's own sync lines (`zgo_sync.script`). Bump `PROTO` there when a line
  format or a referenced asset changes. The host quantizes anything simulated so clients match.
- **This repo is the source of truth.** Never edit the live MO2 mod folder. Deploy into it:
  `python3 dev/deploy.py --dry-run`, then without `--dry-run`. Never install a release zip
  through MO2 under this mod's folder name: MO2's Replace deletes the folder outright.
- **The version** is `VERSION` in `gamedata/scripts/zgo_main.script`. MO2 writes a date stamp
  into `meta.ini`.
- **Feature rules:**
  - Every tweakable gets an MCM setting with a description, in English and Russian. All
    options live in `gamedata/scripts/zgo_settings.script`; `luajit dev/gen_mcm_text.lua`
    regenerates the MCM xml.
  - Performance presets (potato, low, medium, high, ultra) set every performance-relevant option.
  - Kid mode turns off all gore (blood, wounds, dismemberment, gibs) and keeps environmental
    effects (impacts, dust, destruction).
  - No in-game console commands. Command-line tools outside the game are fine, but players
    get a GUI (Umbra Effects Setup) for anything they must run, such as baking for their mod list.
  - Physical plausibility wins over tidiness.
- **Engine:** xrRazom's exes are a private Monolith build that differs from the public
  source. Before relying on a script API, check its name appears in the exe. After any
  xrRazom update, archive the old exes, then run `dev/run.sh make -C native test`.
- **Never in git:** the bake outputs, kid mode copies and setup program builds (see
  `.gitignore`), xrRazom's or the game's files, keys, or personal ids and paths. The
  pre-commit hook runs a secrets check.
- **Encodings:** `README.txt` and `zgo_mcm.script` are CRLF; the `ui_st` xml files are
  cp1251. `.gitattributes` has `* -text` so git leaves them alone; keep them that way when
  editing.
- **Naming (since 1.8.0):** players read "Umbra Gore & Effects" in full and "Umbra Effects"
  for short ("Umbra Effects Setup", "the Umbra Effects folder"); in MO2 instructions use the
  full name, which is the mod's folder name. Internal names keep the `zgo` prefix and must not
  be renamed: script and file names, MCM ids (they hold players' settings), sync event names,
  shader lanes, the `[ZGO]` log tags, the "ZGO kid mode" shader marker, `zgo-setup-linux`, the
  repo. Old names a tool must still recognise (the 1.4 "Zone Gore Overhaul - Baked Models"
  folder) stay too. In XML text write `&amp;`.
- **Shelved, don't re-propose:** DX12, frame generation, upscaling, bodycam, PiP scopes.
- **Commit only when asked. Nothing goes public without the maintainer's go.** The
  textures inherited from Painter of the Zone are not a release blocker (maintainer's call);
  `CREDITS.txt` keeps their provenance notes, so don't raise them again.

## Tests

The dev container: `dev/setup.sh` makes the distrobox `zgo-dev`; `dev/run.sh <cmd>` runs a
command in it from the repo root.

    dev/run.sh dev/test-all.sh                       # core Lua matrix: 70 runs
    dev/run.sh bash -c 'cd tests && luajit zgo_test_world.lua 1'    # the other Lua suites
    dev/run.sh python3 tests/baker/test_bake.py      # also test_geometry.py
    dev/run.sh python3 dev/build_setup/test_setup.py
    dev/run.sh make -C native test

Always use timeouts: a baker test run once hung for 10 hours.

Known stale failures as of 1.8.0 (they fail on the original 1.7.0 files too; the dev tree was
rebuilt after a loss and some tests weren't updated):
- `settings`: the kid-mode lane at line 170, which is 10 of test-all's 70 runs;
- `world`, `wounds`, `cuts`, `setup`, `props`, `probe`;
- `handshake`: the host run gets the "not baked yet" notice (the harness has no bake), where it
  expects no notice;
- `kidfx` and `native`: files missing (`native/` lacks `src/zgo_pe.c` and `include/`);
- baker: `test_damage_mesh`, `test_progress_report_manifest_remove`;
- `test_setup.py`: 5 tests (`TestBakeAndCheck` 2, `TestKidfx` 1, `TestLuaReader` 2). Run it in
  the container: the host's Python has no tkinter, so the window drive (`test_drive`) is skipped there.

## Releases

Build the setup programs first (`dev/build_setup/build.sh linux|windows`), then
`python3 dev/package.py --dry-run`, then `python3 dev/package.py`. It writes
`~/Desktop/Umbra Gore & Effects <VERSION>.zip` and refuses while a setup program is missing or
doesn't match `tools/zgo_setup/SHA256SUMS.txt`. Bump `VERSION` and `meta.ini`'s `version=`
together, and add the README's CHANGES entry.
