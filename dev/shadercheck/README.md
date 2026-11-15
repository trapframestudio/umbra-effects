# shadercheck: compile ZGO's shaders before the game does

A shader that fails to compile in the game is fatal: `CHECK_OR_EXIT("Shader
compilation failed")` quits to the desktop, and a Lua error in a `.s` file is a
fatal `LuaError`. shadercheck finds both offline, against this machine's mod
list, with the same compiler the game loads.

    dev/run.sh dev/shadercheck/check.sh                     every ZGO shader
    dev/run.sh dev/shadercheck/check.sh zgo_particle_kid.ps  some files (name, r3/name, or a path)
    dev/run.sh dev/shadercheck/check.sh --overrides          mods that replace ZGO's shaders or
                                                             the stock files they include
    dev/run.sh dev/shadercheck/check.sh --selftest           stock shaders + known-bad inputs
    dev/run.sh dev/shadercheck/check.sh --which-compiler     which d3dcompiler the game loads
    dev/run.sh dev/shadercheck/check.sh --list-sets          the define sets and their macros

Options: `--sets user,default,...` or `--sets quick` (only the game's own
settings), `--compilers ms,wine,vkd3d` (or one `ms-<version>`), `--game-only`,
`--no-skin`, `--json report.json`, `-v` (every compiler message, full diffs).

Exit status: **0** everything passed, **1** a check failed, **2** the tool
could not run (no game / MO2 found, no compiler, bad arguments).

It reads the game folder, MO2's config, the profile and the mods. It writes
only to `~/.cache/zgo_shadercheck/` (override with `ZGO_SHADERCHECK_CACHE`) and
its Wine prefix `~/.cache/zgo-wine-shadercheck/` (`ZGO_SHADERCHECK_WINEPREFIX`).
Runs share the cache under a lock, so two at once wait for each other.

## What it does

1. **Assembles the shader tree the game sees** (`sc_tree.py`, read only),
   following xrCore's `CLocatorAPI` (xray-monolith b86d733f4a): the archives
   under fsgame.ltx's `$arch_dir...$` entries in order, then loose files under
   `gamedata` as MO2's usvfs merges them (the game's own `gamedata`, enabled
   mods from the bottom of `modlist.txt` to the top, then `overwrite`). The
   later registration wins, names are case blind. ZGO's working copy goes on
   top so its changes are what gets checked. Archives are read with
   `tools/zgo_baker/xdb.py`, the mod list with `tools/zgo_baker/resolve.py`
   (imported, never changed). The result is written to
   `~/.cache/zgo_shadercheck/tree/shaders/` with a `.manifest.json` that names
   the provider of every file.

2. **Picks the targets.** With no arguments: every file ZGO ships under
   `gamedata/shaders/r3/` (`.ps .vs .gs .cs .hs .ds .s .h`). Files outside
   `r3\` are listed as skipped: the DX11 renderer never loads them.
   - A stage file (`.ps`, `.vs`, ...) is compiled itself, and every pass that
     uses it (from any `.s` or the C++ particle blender) is linkage-checked.
   - A `.s` file runs in the blender mock (below); the shaders its passes name
     are compiled, and a missing one is reported (the engine would silently
     substitute `stub_default`).
   - A header is compiled through every shader in the tree that includes it.

3. **Compiles like the engine** (`sc_engine.py`, from
   `dx10ResourceManager_Resources.cpp` and `CRender::shader_compile` in
   `r4.cpp`): file `r3\<name>.<stage>`, entry `main` with target `vs_5_0` /
   `ps_5_0` / `gs_5_0` / `cs_5_0` (legacy `main_vs_1_1`-style entries keep
   their old target), flags `D3D10_SHADER_PACK_MATRIX_ROW_MAJOR`, the macro
   list in the engine's order (`SMAP_size`, `FP16_*`, `USE_*`, `SKIN_*`,
   `SSFX_*`, `SM_4_1`, `SM_5`, `USE_MSAA` / `MSAA_SAMPLES` / `ISAMPLE`, ...),
   and the engine's includer (`r3\<name>` first, then `<name>`, relative to
   the shaders folder). Vertex shaders that use `SKIN_*` are also compiled
   skinned (`SKIN_0` .. `SKIN_4`, the `_0.._4` variants the engine builds for
   skinned visuals) with the first define set.

4. **Define sets** (`--list-sets`):
   - `user`: the settings this machine's game really uses, decoded from the
     shader cache key the engine builds from the same options
     (`appdata/shaders_cache/r4/<shader>/<key>`), when the cache exists;
   - `default`: GAMMA-like defaults (soft particles and water, DOF, SSR 2);
   - `low`: every optional effect off, SM 4.0 path, AMD;
   - `hbao_msaa`: HBAO (half data, vectorized) with MSAA 4x DX10.1 ATOC;
   - `ultra`: everything at its maximum, HDAO, MSAA 8x native DX10.1 alpha test;
   - `msaa_atoc10`: MSAA 2x with DX10.0 alpha-to-coverage.

5. **Compilers** (`sc_compilers.py`):
   - `ms-<version>`: Microsoft `d3dcompiler_47.dll`, called through
     `d3dc/zgo_d3dc.c` (a small Windows program built with
     `x86_64-w64-mingw32-gcc` into the cache, run under Wine with
     `WINEDLLOVERRIDES=d3dcompiler_47=n`). It calls `D3DCompile` with the
     engine's includer, then `D3DReflect` for the signatures, bound resources
     and constant-buffer variables. Every distinct x64 Microsoft copy found is
     used: `ZGO_D3DCOMPILER` (paths, `:`-separated), the game's `bin`, the
     game's Proton prefix, MO2's `dlls`, earlier copies in the cache, and only
     if none of those has one, any Steam prefix. Each is copied to
     `~/.cache/zgo_shadercheck/compilers/ms-<version>/` with a `SOURCE.txt`
     (where from, SHA-256). Nothing is downloaded.
   - `wine`: Wine's builtin `d3dcompiler_47` (vkd3d-shader inside), same
     driver: what a Proton prefix without the Microsoft DLL uses.
   - `vkd3d`: `vkd3d-compiler` (Fedora package `vkd3d-compiler`). It has no
     include-path option and takes `\` in `#include` literally, so it compiles
     a mirror of the tree (`tree-vkd3d/`) whose `#include` lines name the
     absolute path the engine's includer would pick; line numbers are
     unchanged, but its messages count lines through the includes
     (`<defines>:972:1` means line 972 of the whole preprocessed input).

6. **Counts failures fairly.** A ZGO file (or a file that includes one) that
   fails is a **FAIL**. When the stock file it replaces, or the one it names
   with `// shadercheck-baseline: <file>`, fails the same way with the same
   compiler, it is a **GAP** (a compiler limitation, not counted). A stock file
   ZGO doesn't touch that fails is **STOCK** (not counted). vkd3d-shader
   cannot compile about 90 of the 473 stock R4 shaders (SV_ClipDistance, some
   `[unroll]` / constant-expression cases), so expect GAPs if ZGO ever
   overrides one of those.

7. **Pass checks** with the reflecting compilers:
   - linkage: every input the pixel shader reads must be written by the
     vertex (or geometry) shader with the same semantic, in the same register,
     covering the components it reads;
   - bindings: a texture or sampler the shaders use that the pass never binds
     is a note (the slot stays empty); a texture bound as a sampler or the
     other way round is a FAIL (`R_ASSERT(C->type == RC_dx10texture)` in game);
   - interface: a file with `// shadercheck-baseline: <stock file>` must keep
     the stock file's input / output signatures and textures / samplers (the
     constants it reads may grow);
   - parity: a `.s` with `-- shadercheck-parity: <shader>` must build the same
     elements and pass state as that shader (another `.s`, or a C++ particle
     blender read from this mod list's `shaders.xr`). The pixel shader may
     differ when it declares the reference's one as its baseline. Element 2 of
     a priority 2/3 shader is ignored: the shadow-map pass never draws those
     (`pmask` in `r__dsgraph_build.cpp`).

## The blender mock (`blender_mock.lua`)

An offline stand-in for the engine's `.s` VM after
`dx10ResourceManager_Scripting.cpp`: globals `blend`, `cmp_func`,
`stencil_op`, `log`; the `_compiler` methods (`begin`, `sorting`, `emissive`,
`distort`, `wmark`, `scopelense`, `fog`, `zb`, `blend`, `aref`,
`color_write_enable` / `dx10color_write_enable`, `dx10texture`,
`dx10stencil`, `dx10stencil_ref`, `dx10cullmode`, `dx10atoc`, `dx10zfunc`,
`dx10sampler():clamp()`, `dx10Options()`), argument counts and types checked
the way luabind matches overloads, and the pass-state rules of
`CBlender_Compile` (only the first pass writes Z; blend one/zero means no
blending; aref clamped to 0..255). Elements: `normal_hq` or `normal` -> E0,
`normal` -> E1, `l_point` -> E2, `l_spot` -> E3, `l_special` -> E4.

    luajit dev/shadercheck/blender_mock.lua gamedata/shaders/r3/zgo_particle_blend.s
    luajit dev/shadercheck/blender_mock.lua --dump <files...>     (tab-separated, for the tools)

`dofile` it from Lua (`tests/zgo_test_kidfx.lua` does) for `load_file`,
`shader`, `element`, `describe`, `has_shader`, `lua_name`.

## Which d3dcompiler the game loads

`--which-compiler` works it out read only: the exe's imports, a
`d3dcompiler_47.dll` in the game's `bin` (loaded first if present), and for
Linux the Steam shortcut that runs this MO2, its Proton prefix, the prefix's
`DllOverrides` and its `system32` copy. On this machine: no DLL in `bin`,
Proton 11.0-100 prefix 3507050460 with `d3dcompiler_47=native` and Microsoft
**6.3.9600.16384** in `system32` (the winetricks copy), so that is the one
whose result decides. On Windows 10/11 the game gets System32's 10.0.x copy;
MO2's own `dlls/d3dcompiler_47.dll` (10.0.26100.1) stands in for it.

## kidfx (`kidfx_pe.py`)

Kid mode for particles already on screen: see the module docstring and
`docs/integration/kidfx.md`. In short:

    python3 dev/shadercheck/kidfx_pe.py status | list | apply | revert
    python3 dev/shadercheck/kidfx_pe.py shaders [--write]   rebuild zgo_particle_* from this mod list
    python3 dev/shadercheck/kidfx_pe.py copies [--write|--remove]
    python3 dev/shadercheck/kidfx_pe.py bake                what a setup tool runs per mod list

`revert` is the escape hatch: every `zgo\particle_*` shader line goes back to
the stock one in one command, nothing else changes. `kidfx_snapshot.txt` is
the snapshot `tests/zgo_test_kidfx.lua` checks; `kidfx_copies.json` lists the
copied effects and their source mods.

## Files

| file | what |
|---|---|
| `check.sh` | entry point (no `.pyc` files written) |
| `shadercheck.py` | the CLI: targets, jobs, reports, `--overrides`, `--selftest` |
| `sc_tree.py` | the game's file system rebuilt offline; `materialize()` |
| `sc_engine.py` | macros, cache-key codec, define sets, entry / target rules |
| `sc_compilers.py` | Microsoft / Wine / vkd3d back ends; which DLL the game loads |
| `sc_blenders.py` | `shaders.xr` reader; the C++ particle blender's R4 passes |
| `blender_mock.lua` | the `.s` VM mock |
| `d3dc/zgo_d3dc.c` | the D3DCompile + D3DReflect batch driver (built into the cache) |
| `kidfx_pe.py`, `kidfx_snapshot.txt`, `kidfx_copies.json` | kid mode for particles |

Needs (zgo-dev container): `python3`, `luajit`, `wine-core`, `mingw64-gcc`,
`vkd3d-compiler`. Engine sources used for reference (read, not shipped):
xray-monolith b86d733f4a, fetched file by file from
`raw.githubusercontent.com/themrdemonized/xray-monolith/b86d733f4a/` into
`~/.cache/zgo_shadercheck/src/`.
