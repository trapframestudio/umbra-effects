# Integration note: shadercheck (offline DX11 shader compile check against this mod list)

Workstream "shadercheck". Dev tooling only: nothing here ships in the mod
archive (`dev/package.py` skips `dev/`).

## 1. Summary

**What it is**

`dev/run.sh dev/shadercheck/check.sh [files...]` compiles ZGO's shaders the
way the game's DX11 renderer does and reports PASS / FAIL per file and per
define set, with the compiler's messages. Exit 0 = all passed, 1 = a check
failed, 2 = could not run. With no arguments it checks every file ZGO ships
under `gamedata/shaders/r3/`.

A shader that fails to compile in game is fatal (`CHECK_OR_EXIT("Shader
compilation failed")`), and so is a Lua error in a `.s` file. shadercheck
finds both before anyone launches the game.

**How it works**

- **The tree the game sees.** Base archives first (fsgame.ltx `$arch_dir...$`
  order), then the game's loose `gamedata`, then the mods in MO2 priority
  (profile G.A.M.M.A, read only), then `overwrite`, then ZGO's working copy on
  top. It uses `tools/zgo_baker/xdb.py` and `resolve.py` by import only. The
  result is materialised in `~/.cache/zgo_shadercheck/tree/`, with a manifest
  naming every file's provider.
- **Compiled like the engine** (xray-monolith b86d733f4a, `r4.cpp`
  `shader_compile` and `dx10ResourceManager_Resources.cpp`):
  - entry `main` and the target per stage (legacy entries kept);
  - flags 8 (pack matrix row major);
  - the macro list in the engine's order;
  - the engine's includer (`r3\name`, then `name`);
  - skinned `SKIN_0..4` variants for vertex shaders that use them.
- **`.s` files run in a strict blender mock** (`blender_mock.lua`, luabind-like
  overload checks), so a bad call is caught as it would be in game. Every pass
  they build is paired: the vs/ps the pass names are compiled, and then
  checked for:
  - linkage: semantics, registers, components;
  - bindings: texture vs sampler type;
  - missing stage files.
- **The C++ particle blender** (`particles\*` in `shaders.xr`) is modelled the
  same way. This is what the kid-mode particle shaders are compared against.
- **Six define sets** (`--list-sets`):
  - `user`, decoded from this machine's real shader cache key;
  - `default`, `low`, `hbao_msaa`, `ultra`, `msaa_atoc10`.
- **Two optional headers** let a ZGO shader declare what it must stay
  compatible with:
  - `// shadercheck-baseline: <stock file>`: same signatures and resources;
  - `-- shadercheck-parity: <shader>`: same elements and pass state.
- **`--overrides`** lists every mod in this mod list that replaces a ZGO
  shader or a stock file ZGO's shaders include.
- **`--selftest`**:
  - all 473 stock R4 shaders plus `effects_wallmark_blood.ps` under both
    compiler families;
  - the cache-key decoder;
  - negative tests: a compile error, a Lua error, a VS/PS COLOR0 mismatch, and
    compiler detection must all be caught.

**Compilers**

- **`ms-6.3.9600.16384`**: Microsoft `d3dcompiler_47.dll`.
  - Copied from the game's Proton prefix `system32`.
  - SHA-256 `e994847e01a6f1e4cbdc5a864616ac262f67ee4f14db194984661a8d927ab7f4`.
  - **This is the copy the game loads.**
- **`ms-10.0.26100.1`**: copied from MO2's `dlls/`.
  - SHA-256 `9489124759292316d11eae5ffb67b74bfaf0e1853b968137b047567f31c76232`.
  - Stands in for what Windows 10/11 players get from System32.
- **`wine`**: Wine 11.20's builtin d3dcompiler_47 (vkd3d-shader inside).
- **`vkd3d`**: `vkd3d-compiler` 1.17. It has no include path and reads `\`
  literally, so it compiles an include-resolved mirror of the tree.

The `ms-*` and `wine` compilers are driven by `d3dc/zgo_d3dc.c`, built with
mingw into the cache and run under Wine with its own prefix,
`~/.cache/zgo-wine-shadercheck`. That driver also reflects each shader
(signatures, resources, used constants).

**Which d3dcompiler the game loads** (`--which-compiler`, read only)

- The exe imports `D3DCOMPILER_47.DLL`, and there is none in the game's `bin`.
- Steam shortcut "STALKER GAMMA" uses Proton 11.0-100, prefix appid 3507050460.
- That prefix has `DllOverrides d3dcompiler_47=native` and Microsoft
  6.3.9600.16384 in `system32`.

**Results now**

- Default run: 16 files, 484 compiles, all PASS on all four compilers.
- Linkage OK.
- `zgo_particle_kid*.ps` have the same interface as `particle.ps` /
  `deffer_particle.ps`, plus one constant.
- The four `zgo_particle_*.s` have the same elements and pass state as the C++
  `particles\blend/add/alpha_add/set` with this mod list's `shaders.xr`.

**Stock baseline**

- 17 of the 473 stock R4 shaders fail under Microsoft (dead files nothing
  loads).
- 90 fail under vkd3d (compiler gaps).
- These count as STOCK or GAP, never as ZGO failures.

## 2. Files

All under `dev/shadercheck/` (owned):

| file | what |
|---|---|
| `check.sh` | entry point (`python3 -B`, no `.pyc`) |
| `shadercheck.py` | CLI: targets, plan, jobs, reports, `--overrides`, `--selftest`, `--which-compiler`, `--json` |
| `sc_tree.py` | game VFS + MO2 usvfs order rebuilt offline (imports `tools/zgo_baker/xdb.py`, `resolve.py`) |
| `sc_engine.py` | engine macros, shader-cache-key codec, define sets, entry/target rules |
| `sc_compilers.py` | Microsoft / Wine / vkd3d back ends, DLL discovery, which DLL the game loads |
| `sc_blenders.py` | `shaders.xr` reader, C++ particle blender R4 pass table |
| `blender_mock.lua` | `.s` VM mock (also used by `tests/zgo_test_kidfx.lua`) |
| `d3dc/zgo_d3dc.c` | Windows D3DCompile + D3DReflect batch driver (built into the cache) |
| `README.md` | usage, engine facts, define sets, compilers, limits |
| `kidfx_pe.py`, `kidfx_snapshot.txt`, `kidfx_copies.json` | kid mode for particles (see `kidfx.md`) |

**Outside the mod folder** (never shipped):

- `~/.cache/zgo_shadercheck/`: tree, vkd3d mirror, compiler copies with
  `SOURCE.txt`, the built driver, jobs, selftest scratch, and the engine
  sources fetched for reference.
- `~/.cache/zgo-wine-shadercheck/`: its Wine prefix.

## 3. Requests to the integrator

1. **`dev/distrobox.ini`: add the vkd3d packages** to the zgo-dev container.
   I installed them in the running container (see "Downloads and packages"
   below). Add this line under `[zgo-dev]`:

       additional_packages="vkd3d-compiler libvkd3d-shader"

   Extend the comment block at the top with:

       #   vkd3d-compiler second HLSL compiler for dev/shadercheck (Wine's builtin d3dcompiler uses it)

   `mingw64-gcc` and `wine-core` are already listed. shadercheck builds its
   driver with them.

2. **`dev/README.md`: one line in the tools list.**

       dev/run.sh dev/shadercheck/check.sh     compile ZGO's shaders like the game does (see dev/shadercheck/README.md)

3. **Release checklist (`docs/PLAN.md` or wherever it lives).** Before
   packaging, run:
   - `dev/run.sh dev/shadercheck/check.sh`, which must exit 0;
   - `dev/run.sh dev/shadercheck/check.sh --overrides`, and read it.

   It is not in `dev/test-all.sh` because it needs Wine, the game and MO2
   (about 15 s warm, 1 to 2 min cold).

4. **Setup GUI (workstream "setup").** For the user-requested cross-platform
   setup, `shadercheck.py --json report.json` is a machine-readable
   "will ZGO's shaders compile on this mod list" check. Run it after a per-user
   bake if Wine and mingw are present; skip it otherwise (Windows users have no
   Wine). It is optional. The kidfx entry points the GUI needs are in
   `kidfx.md`.

5. **Other workstreams that add or change shaders**: add a
   `// shadercheck-baseline: <stock file>` line to a pixel/vertex shader that
   must stay drop-in compatible with a stock one. Add a
   `-- shadercheck-parity: <shader>` line to a `.s` that must reproduce a stock
   shader's pass state. Both are comments, so the game ignores them.

**Downloads and packages (recorded)**

- **Packages**: `vkd3d-compiler-1.17` and `libvkd3d-shader-1.17` (Fedora 44),
  installed 2026-11-13 14:34 with
  `dev/run.sh sudo dnf install -y vkd3d-compiler`. Nothing else was installed.
- **Downloads**: xray-monolith engine sources at commit `b86d733f4a`, for
  reference only (read, not shipped, nothing vendored). Saved to
  `~/.cache/zgo_shadercheck/src/`. Two sources:
  - the tree listing from `api.github.com/repos/themrdemonized/xray-monolith/git/trees/b86d733f4a?recursive=1`;
  - 36 files from `raw.githubusercontent.com/themrdemonized/xray-monolith/b86d733f4a/src/...`
    (`Layers/xrRender*`, `xrRenderPC_R4`, `xrCore/LocatorAPI.cpp`,
    `xrParticles/particle_effect.cpp`).

  No user data was sent: plain anonymous GETs.
- **Microsoft DLLs**: not downloaded. Two existing copies on this machine were
  copied into the cache, with their source and hash in `SOURCE.txt`.

## 4. Settings added

None. This is a dev tool. Its options are command-line flags: `--sets`,
`--compilers`, `--game-only`, `--no-skin`, `--overrides`, `--selftest`,
`--which-compiler`, `--list-sets`, `--json`, `-v`. Environment overrides:
`ZGO_SHADERCHECK_CACHE`, `ZGO_SHADERCHECK_WINEPREFIX`, `ZGO_D3DCOMPILER`.

## 5. Co-op

Not applicable: offline tool, no game code.

## 6. README text

For the developer section of `README.md`, if there is one. Players never see
this tool.

    Shader check (developers): dev/run.sh dev/shadercheck/check.sh compiles every ZGO
    shader the way the game's DX11 renderer does, against your own mod list, with the
    d3dcompiler your game loads (plus Wine's and vkd3d's), and exits non-zero if any would
    fail in game. --overrides lists mods that replace ZGO's shaders. See
    dev/shadercheck/README.md.

## 7. In-game checks

The tool predicts. These confirm its predictions:

1. Start the game with ZGO and delete `appdata/shaders_cache/r4` first, so
   every shader recompiles. Load a save. The log has no
   `! Shader compilation failed`, no `DX10: Shader '...' not found in
   library`, and no `stub_default` for a `zgo\...` or `zgo_*` name.
2. Repeat with MSAA 4x on and with "low" render settings. These match the
   `hbao_msaa` and `low` define sets.

## 8. Risks and open questions

- **Static include closure.** Header dependencies are found by scanning
  `#include` lines, not by preprocessing, so a header pulled in only under one
  `#ifdef` is still counted. Results can only be too cautious, never miss a
  file.
- **Only the C++ particle blenders are modelled.** Other C++ blenders (model,
  LOD, tree, ...) are not. A ZGO `.vs`/`.ps` used only by those is compiled
  but not pair-checked; the report says so ("used by no checked pass").
- **vkd3d GAPs.** vkd3d-shader cannot compile about a fifth of the stock
  shaders. If ZGO overrides one of them, the result shows as GAP (not counted)
  and only the Microsoft compilers decide.
- **Windows players** use System32's d3dcompiler_47 10.0.x. `ms-10.0.26100.1`
  stands in for it, but builds differ slightly. Older Windows 8.1 copies match
  `ms-6.3`.
- **Uncommon render settings.** The `user` define set comes from this
  machine's shader cache. Other players' settings are approximated by the five
  fixed sets, and rare combinations are not all enumerated.
