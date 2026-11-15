# Native add-on code for Anomaly/GAMMA (xrRazom engine): discovery report

(Saved by the parent session from the native agent's hand-back, which it could not write itself. The evidence files are in this folder: evidence_pe_dx11avx.txt, evidence_rtti_dx11avx.txt, evidence_ikinematics_vtable_dx11avx.txt, strings_dx11avx.txt, scripts/, src/.)

Tags: [V] verified, [I] inference, [T] needs a runtime test.

## TL;DR

1. **The exe is xrRazom's own monolith build [V].**
   - The PDB path is `D:\Playground\prison\xray-monolith-xrRazom\...`.
   - The log says "Modded Exes MT-TEST version 2026.10.02" and "xrCore build 10099, Oct 2 2026".
   - xrRazom-release.txt gives "engine develop-mt @ 82abfe14f". That commit is not in themrdemonized/xray-monolith (checked with the GitHub API).
   - The 8 AnomalyDX*.exe files in anomaly/bin have the same md5 as the xrRazom 1.4 zip.
   - Everything is static: no engine DLLs, and only 3 exports (AmdPowerXpressRequestHighPerformance, NvOptimusEnablement, luaopen_socket_core).
   - "Loading DLL: xrGame.dll" in the log is cosmetic: EngineAPI.cpp:247-250 calls DllMainXrGame directly.
2. **Native code can be loaded from Lua** through LuaJIT FFI and package.loadlib. No exe swap and no wine override are needed.
3. **Hooks can be found through RTTI without symbols.** The image base is fixed at 0x140000000 (no ASLR, relocations stripped) and full MSVC RTTI is present (10,278 complete object locators).
4. **Layouts differ from the public source.** IKinematics has 46 vtable slots here, 40 at b86d733f4a and 47 on public dev-mt. Always find offsets at runtime and verify them by reading their bytes.
5. **First target:** post-process bone transforms after CalculateBones.
6. **Architecture:**
   - The ZGO mod ships bin/zgo_native.dll plus a Lua bootstrap.
   - The bootstrap reports a capability bitmask and falls back per feature.
   - In co-op, peers exchange capabilities over xrr_script_event.

## 1. What runs

**anomaly/bin:**
- The 8 xrRazom exes (dated Oct 3 2026).
- GameNetworkingSockets.dll and steam_api64.dll (both from xrRazom).
- Stock Anomaly DLLs: discord_game_sdk, icudt65, icuuc65, soft_oal, tbb.
- VerifiedDX11.exe is a stock 1.5.3 build (Sep 2024) and is unused.
- ReShade .ini files are present, but not the ReShade DLL.
- anomaly/Anomaly/bin is a duplicate.

**What GAMMA ships:** no mod has a .dll, .asi or .addon64 file, and there are no .pdb files anywhere.

**PE:**
- DllCharacteristics is 0x8120: no DYNAMIC_BASE, no GUARD_CF.
- Imports include DINPUT8, VERSION, WINMM, dxgi, d3d11, D3DCOMPILER_47, d3dx11_43 and d3dx9_43. Kernel32 imports include LoadLibrary*, GetProcAddress and VirtualProtect.
- The export macros ENGINE_API, ECORE_API, XRCORE_API and XRCDB_API are empty.

**Renderer per exe:** DX8→R1, DX9→R2, DX10→R3, DX11→R4. The user runs DX11AVX with R4.

**Launch chain:**
- A Steam non-Steam shortcut, "STALKER GAMMA", launches ~/gamma/gamma/ModOrganizer.exe with `DISABLE_XWAYLAND_MM_SCALE=1 %command%`.
- Proton prefix: compatdata 3507050460, Proton Experimental 11.0-100.
- DXVK's d3d11 and dxgi are in system32.
- There are no dinput8, version or winmm overrides in the registry.
- MO2 2.5.2 is portable and starts the exes with working directory anomaly/bin.

**The MO2 virtual filesystem is active in the game [V].**
- Evidence: the engine reads bin\..\commandline.txt, which exists only in gamma/overwrite. The log shows "Found commandline file!" with -smap2048 -dbg.
- usvfs hooks LoadLibraryExA/W, NtOpenFile and NtCreateFile. So a DLL in a mod's bin/ folder should load [T].

## 2. Loading routes

### FFI and loadlib [V static]

**Source:**
- script_storage.cpp:409-410 calls luaL_openlibs when USE_LUAJIT_ONE is not defined, and xrGame.vcxproj:141,189,242 undefines it.
- lib_init.c:32-54 registers ffi in _PRELOAD.
- lj_arch.h:380-383 sets LJ_HASFFI = 1.
- disable_os_funcs (script_storage.cpp:324-341, 448) removes only os.execute, os.rename, os.remove, os.exit and io.popen.

**Binary:**
- "LuaJIT 2.0.4" string present.
- The ffi library definition is present.
- A luaL_Reg entry {"ffi", 0x14040d890} sits at 0x14125c988. The preload loop of luaL_openlibs (0x1406cd25c) reads it.
- The default cpath is `.\?.dll;!\?.dll`. Nothing else references "ffi".

**What this gives us:**
- ffi.C resolves symbols from the exe, the CRT, kernel32, user32 and gdi32 (lj_clib.c:159-168, 243-245).
- ffi.load and package.loadlib call LoadLibraryA.

**Gotcha:** classic Lua C modules won't work, because the lua_* API is not exported. Use FFI with C functions and shared buffers instead.

**Context:**
- No mod uses ffi, jit, require or loadlib.
- A public guide says FFI is disabled; that is outdated for this build.
- Future risk: monolith PR #249 (open since 2025-06) would "disable dangerous Lua primitives".

### Proxy DLLs (fallback) [I]

| Candidate | Wine override |
|---|---|
| dinput8 / version / winmm | needed (`<name>=n,b`) |
| dxgi / d3d11 | needed, and the proxy must chain to DXVK |
| discord_game_sdk / icuuc65 | none, but this replaces stock files |
| steam_api64 / GameNetworkingSockets | no (xrRazom's files) |

- Override through launch options: `WINEDLLOVERRIDES="dinput8=n,b" DISABLE_XWAYLAND_MM_SCALE=1 %command%`.
- Or per exe with protontricks 3507050460: `HKCU\Software\Wine\AppDefaults\AnomalyDX11AVX.exe\DllOverrides`.
- A proxy DLL must physically sit in bin/.
- The `-tune` launch flag makes the engine load vTuneAPI.dll (EngineAPI.cpp:263-277), but it asserts if the DLL is missing.

**Ecosystems:** there is no ASI ecosystem for Anomaly. ReShade addons are supported but can't tell which NPC a draw call belongs to.

## 3. Hook points

**Method:** TypeDescriptor → complete object locator → vtable.
- The CKinematics IKinematics subobject is at offset 232 and has 46 slots, the same layout in all 8 variants.
- Addresses differ per exe (DX11AVX 0x141297510, DX11 0x1412b39a0, …).
- Hook with a vtable slot swap or MinHook. Verify the bytes first, then read member offsets from trivial accessor functions.

### 3.1 CalculateBones (best first target)

**Source:**
- SkeletonRigid.cpp:23-174 calls Update_Callback(this) last.
- CLBone (:214-222) runs the per-bone callback (where physics writes) and then sets mRenderTransform = mTransform * m2b.
- R4 uploads LL_GetTransform_R (SkeletonX.cpp:128-138).

**Binary (DX11AVX):**

| Slot | Function | Members it uses |
|---|---|---|
| 35 | CalculateBones, at 0x1402ef2f0 | UCalc_Time at +0xf4; calls the callback at +0x118 |
| 36 | Invalidate | |
| 37–42 | callback accessors | callback at +0x118, parameter at +0x120 |
| — | NeedUCalc | reads +0x100 |
| 9 | bone instance access | CBoneInstance is 0x168 bytes; bone_instances at +0xc8 |
| 5 | LL_BoneID(LPCSTR) | |
| 4 | LL_BoneID (shared_str overload) | |

- Within CBoneInstance, mRenderTransform is at +0x80 (layout matches the source struct).
- Chain the existing callbacks, don't replace them: VisualCallback (GameObject.cpp:1021-1046) and update_visbox (:783, script_attachment_manager.cpp:1676).
- Prefer a global post-hook on CalculateBones with edits that are safe to apply twice.

**Binding to a game object:**
- `obj:bone_id("\1zgo:token")` calls LL_BoneID on that object's IKinematics (script_game_object.cpp:557-579). The hook captures the pointer.
- Hook the kinematics release too: handles go stale on visual change or despawn.

**This wins over the ragdoll's BonesCallBack**, which fixes severed limbs on active ragdolls and allows bone-level deformation.

Feasibility: High, about 1–2 weeks.

### 3.2 Skinned rendering

- CSkeletonX::_Render (SkeletonX.cpp:59-165) is reached through the Render virtual of ST and PM (primary vtables 0x141296f08 and 0x141296d78).
- The skin shader reads sbones_array and sbones_array_prev (SSS skin.h:56-60).
- Per-object data can't be smuggled in without native code, and all 8 shader_params are taken by GAMMA mods.

**Without native code:** obj:set_shader / reset_shader (script_game_object.cpp:1596-1620) plus a custom .s file with pre-made damage textures.

**With native code:**
- patch skin.h (that means overriding SSS's copy);
- find the D3D11 context through the CHW global (RTTI plus a .data scan);
- bind an unused cbuffer. The engine binds cbuffers by reflection, which complicates this.

Feasibility: Medium-Low, 3–6+ weeks.

### 3.3 Child visuals

Editing FHierrarhyVisual::children needs ModelPool calls, which are non-virtual, so they must be found by pattern scans. Medium-Hard. Script attachments plus bone collapse are better.

### 3.4 Level collision (CDB) and static geometry

- Code: xr_area.h:23-91 (CObjectSpace::Static) and xrCDB.h:61-106 (MODEL::build, non-virtual).
- Reaching it: CLevel RTTI (0x1412ef098), then scan for the live object, then member offsets.
- Cheapest edit: collapse triangles to degenerate ones.
- Physics-relevant, so every co-op peer must apply the same edits.

Feasibility: Medium-Hard.

### 3.5 Wallmarks

Already scriptable (script_wallmarks_manager.cpp:92, 107). Native code adds little.

### 3.7 Threading

This is an MT build:
- never call Lua from inside a hook;
- use lock-free buffers;
- wrap hooks in SEH guards.

## 4. Co-op

- Each peer loads its own DLL; pcall falls back if it is missing.
- Handshake over xrr_script_event.register / send (xrr_script_event.script:12-35). No xrRazom edits.
- xrRazom's join fingerprint covers configs only, and skip_mod_check is on, so ZGO must check native versions itself.
- Cosmetic features run per peer; features that change the simulation are host-gated.
- xrRazom installs no runtime hooks, but the callbacks behind its prop attachments must be preserved.

## 5. Bottom line

**Approaches, best first:**

| # | Approach | Rating |
|---|---|---|
| 1 | FFI loader | High |
| 2 | CalculateBones hook | High, 1–2 weeks |
| 3 | set_shader with pre-made textures | Medium, cheap |
| 4 | Vertex dents | Medium-Low |
| 5 | Child visuals | Medium-Hard |
| 6 | CDB edits | Medium-Hard |
| 7 | Wallmarks | Easy, low value |
| 8 | Proxy DLL | Backup only |

**Effort:**
- Smoke test: 1–2 h.
- Loader, API and scanner: 3–5 days.
- Each new xrRazom release: hours to days.

**Risks:**
- build churn (8 exes per xrRazom release);
- crashes from a wrong offset;
- MT threading;
- loading under Proton and usvfs [T];
- ffi being removed upstream;
- co-op divergence;
- SSS skin.h conflicts.

**First test (not run yet):**
1. Log `pcall(require, "ffi")` and `jit.version`.
2. Log `ffi.C.GetModuleHandleA(nil)`; expect 0x140000000.
3. `ffi.load` a hello-world DLL from a test mod's bin/ folder.

**Suggestion:** ask the xrRazom author for PDBs for each release.

## Sources

- https://raw.githubusercontent.com/ModOrganizer2/usvfs/master/src/usvfs_dll/hookmanager.cpp
- https://gh.r-mj.com/themrdemonized/xray-monolith/pull/249
- https://robe127.github.io/stalker-anomaly-modding-guide/scripting/lua-in-anomaly/
- https://github.com/ThirteenAG/Ultimate-ASI-Loader/releases/tag/v9.7.2
- https://openplanet.dev/docs/help/linux
- https://github.com/themrdemonized/xray-monolith
