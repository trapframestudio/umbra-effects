# Integration note: kidfx (kid mode for particles already on screen)

Workstream "kidfx". Tooling lives in `dev/shadercheck/` (see `shadercheck.md`).

## 1. Summary

**The gap**

In kid mode, `zgo_fx` stops starting gory effects and stops the ones it is
running. Two things still show blood:

- particles already emitted, which fly until their lifetime ends;
- gory effects the game plays by itself from other mods: knife hits on flesh
  (a material pair) and anomalies tearing a body.

**The fix: a shader swap**

1. **Four Lua shaders**, `gamedata/shaders/r3/zgo_particle_{blend,add,aadd,set}.s`.
   Each reproduces one stock C++ particle blender (`particles\blend`, `add`,
   `alpha_add`, `set`) exactly:
   - same elements, priority, sorting, Z, blending and alpha test;
   - same `s_base` / `smp_base` (clamped) / `s_position` / `smp_nofilter`
     bindings;
   - same shadow-map element for `set`.

   The source is xray-monolith `Blender_Particle.cpp` (R3/R4 branch), with
   this mod list's `shaders.xr` values. These come from base `files.db0`;
   no mod overrides them.
2. **Their pixel shaders**, `zgo_particle_kid.ps` and
   `zgo_particle_kid_deffer.ps`. Each is this mod list's stock `particle.ps` /
   `deffer_particle.ps` (base `shaders.db0`, sha1 in the header) plus two lines:

       uniform float4 bus_zgo_view;
       if (bus_zgo_view.x > 0.5 && abs(bus_zgo_view.w - 1.0) < 0.001) discard;

   With the lane at 0, or never set, they compute exactly what the stock
   shaders do.
3. **The swap.** Only the `shader = ...` line of every gory `.pe` changes:
   `particles\X` becomes `zgo\particle_X`. Nothing else in those files is
   touched.

**Which effects are gory**

The classifier is `dev/shadercheck/kidfx_pe.py`. It decides by name first,
then by texture:

- **gory**: blood, flesh, gore, brain, skull, skin, hair, gush, ...;
- **clean**: sparks, armour, glass, cloth, dust, smoke, ...;
- **carriers**: textures that draw nothing. They stay as they are.

Two red "pilot" glows are explicit overrides (gory). If in doubt, an effect
stays visible.

**What changed**

- 1199 particle files: 124 gory, 127 clean, 310 carriers, 638 groups.
- 123 shader lines switched: 107 `particles\blend`, 3 `add`, 1 `alpha_add`,
  2 `set` in ZGO's own effects, plus the 10 copies below.
- 1 gory effect, `srbd/effects/debris/srbd_hair_4.pe`, uses `effects\rain` and
  has no kid-mode copy. It stays visible.

**Copies of effects the game plays**

10 gory `.pe` the game plays from another mod were copied into ZGO, with only
the shader line changed:

- `hit_fx/effects/hit_bb_07_knife.pe`: knife on flesh;
- `anomaly2/effects/body_tear_blood_{00,03,05,10,11,13,16,18,19}.pe`: body
  tears.

Their source is "Particles Cinematic VFX 3.5 1.1.2 BOTZ YAWM". Sources and
hashes are in `dev/shadercheck/kidfx_copies.json`.

**When it hides (Rule 7)**

The discard needs **x = 1 and w = 1**:

- `x` is kid mode, which `zgo_settings` already sets;
- `w` is armed only by a new experimental option, off by default (request 2).

Until that option exists and is ticked, nothing is hidden.

**Verified offline**

- All four `.s` match the C++ blender in `dev/shadercheck/check.sh` parity.
- The kid PS has the same interface as the stock PS, plus one constant.
- 96 compiles PASS with the game's d3dcompiler (6.3.9600.16384), MO2's
  10.0.26100.1, Wine and vkd3d, under 6 define sets including MSAA and soft
  particles.
- `tests/zgo_test_kidfx.lua` checks snapshot, classification, mocked blender
  states and the visibility model.

**Escape hatch**

`python3 dev/shadercheck/kidfx_pe.py revert` puts every `zgo\particle_*` line
back to the stock shader in one command. `apply` redoes it, byte-identically.
Both round trips were tested.

## 2. Files

**Owned, added**

- `gamedata/shaders/r3/zgo_particle_blend.s`, `zgo_particle_add.s`,
  `zgo_particle_aadd.s`, `zgo_particle_set.s`
- `gamedata/shaders/r3/zgo_particle_kid.ps`, `zgo_particle_kid_deffer.ps`
- `gamedata/particles/hit_fx/effects/hit_bb_07_knife.pe` (copy)
- `gamedata/particles/anomaly2/effects/body_tear_blood_{00,03,05,10,11,13,16,18,19}.pe`
  (copies)
- `dev/shadercheck/kidfx_pe.py`: classifier, apply/revert/status, shader and
  copy generator, `bake()` for the setup GUI
- `dev/shadercheck/kidfx_snapshot.txt`: per file: class, stock shader, sha1 of
  the file with the stock shader line, reason
- `dev/shadercheck/kidfx_copies.json`: copied effects, source mod, sha1
- `tests/zgo_test_kidfx.lua`, `tests/mocks/kidfx.lua`: the KIDFX helper
  (LuaJIT SHA-1, `.pe`/`.pg` reader, child-effect walk, GPU visibility model).
  It only defines `KIDFX` and changes nothing for other suites.

**Owned, changed**

- `gamedata/particles/**/*.pe`: the `shader = ...` line of 113 of ZGO's own
  gory effects. A diff against the pre-change tree shows nothing else changed.

**Not added: needs request 1**

- `gamedata/shaders/r1/zgo_particle_*.s` and `gamedata/shaders/r2/zgo_particle_*.s`.

## 3. Requests to the integrator

1. **BLOCKING before release: the DX8 / DX9 fallbacks.** The DX8 (R1) and DX9
   (R2) exes read only `shaders\r1\` / `shaders\r2\`. For a shader name with
   neither a Lua `.s` nor a C++ blender, their `CResourceManager::_GetBlender`
   calls `Debug.fatal("Shader '%s' not found in library.")`, while the
   particle library creates every effect's shader at start-up. So with the
   swapped `.pe` lines, `AnomalyDX9*.exe` / `AnomalyDX8*.exe` would stop at
   launch. DX10/DX11 read `r3\` and are fine. Run:

       dev/run.sh python3 dev/shadercheck/kidfx_pe.py shaders --legacy --write

   It writes 8 files, `gamedata/shaders/{r1,r2}/zgo_particle_{blend,add,aadd,set}.s`,
   and reports the `r3\` files as "same". Each is the stock C++ particle
   blender for that renderer: R1 branch on every element; R2 branch with
   `s_position` soft particles and the `set` shadow element. They reference
   only stock `particle` / `deffer_particle` shaders, which exist in base
   `shaders.db0` for r1/r2. They hide nothing.

   I generated them into a scratch copy. There, `tests/zgo_test_kidfx.lua`
   runs them in the blender mock's DX9 mode and checks every element against
   the C++ blender, and it catches a corrupted one. Until they exist, the
   test prints a WARNING naming them.

   If you don't want them, run `python3 dev/shadercheck/kidfx_pe.py revert`
   before packaging instead.

2. **The experimental option that arms the discard (`zgo_settings.script`).**
   Apply this patch, then run `luajit dev/gen_mcm_text.lua`. I verified it in
   a scratch copy of the mod: every suite passes, including `settings`, after
   the MCM text is regenerated. `zgo_test_kidfx.lua` notices the option and
   then checks the lane (1, 0, 0, 1) and back to w = 0.

   ```diff
   --- a/gamedata/scripts/zgo_settings.script
   +++ b/gamedata/scripts/zgo_settings.script
   @@ -36,6 +36,10 @@
    			  name = { "Kid mode", "Детский режим" },
    			  desc = { "Turns gore off at once on this computer: ...",
    			           "Сразу отключает кровь ..." } },
   +			{ id = "kid_particles", type = "check", def = false, show_if = "general/kid_mode",
   +			  name = { "Kid mode: hide particles already flying (experimental)", "Детский режим: скрывать уже летящие частицы (экспериментально)" },
   +			  desc = { "Also hides blood sprays and gore debris that are already on screen when kid mode goes on, and the ones the game plays by itself (knife hits on flesh, anomalies tearing a body), by switching their particle shader off. Needs the xrRazom exe's shader bus and is not tested in game yet. Off: those particles finish playing as usual.",
   +			           "Также скрывает брызги крови и ошмётки, которые уже на экране при включении детского режима, и те, что игра запускает сама (удары ножом по телу, аномалии, разрывающие тело), отключая их шейдер частиц. Нужна шина шейдеров exe xrRazom; в игре ещё не проверено. Выкл.: эти частицы доигрывают как обычно." } },
    			{ id = "npc_shooters", type = "check", def = true, coop = "host",
   @@ -496,6 +500,7 @@
    local kid_state      -- last applied (nil until the first update)
   +local armed_state    -- last applied general/kid_particles (lane w)
   @@ -529,7 +534,9 @@
    local function lane_set(kid)
    	local b = bus()
    	if not (b and b.set and lane_ready(b)) then return false end
   -	local ok, err = pcall(b.set, LANE, kid and 1 or 0, 0, 0, 0)
   +	-- w = 1 arms the kid-mode particle shaders (zgo_particle_kid*.ps, experimental option)
   +	local armed = kid and zgo_util.setting("general/kid_particles") and 1 or 0
   +	local ok, err = pcall(b.set, LANE, kid and 1 or 0, 0, 0, armed)
   @@ -537,10 +544,13 @@
    function update()
    	local kid = not gore()
   -	if kid == kid_state then return end
   +	local armed = kid and zgo_util.setting("general/kid_particles") and true or false
   +	if kid == kid_state and armed == armed_state then return end
   +	local kid_changed = kid ~= kid_state
    	local first = kid_state == nil
   -	kid_state = kid
   +	kid_state, armed_state = kid, armed
    	lane_set(kid)
   +	if not kid_changed then return end
    	if first and not kid then return end
   @@ -550,6 +560,6 @@
    function reset()
   -	kid_state, lane_ok = nil, nil
   +	kid_state, armed_state, lane_ok = nil, nil, nil
    	invalidate()
   ```

   The option item goes right after the `kid_mode` item on the `general` page,
   which is `coop = "local"`. The item inherits that. Keep the existing
   `kid_mode` `desc` as it is: the elided strings above are unchanged.

3. **Setup GUI (workstream "setup"), the cross-platform per-modlist setup the
   user asked for.** It should call, in Python:

   ```python
   import kidfx_pe

   kidfx_pe.bake()      # shaders --write --legacy, then copies --write, then apply
   kidfx_pe.status()    # state, counts, inconsistent, snapshot_current
   kidfx_pe.revert()    # the escape hatch, as an "undo kid-mode particles" button
   ```

   Or the CLI `python3 dev/shadercheck/kidfx_pe.py bake --json`. Every
   function returns a report dict and prints nothing. The baked steps:
   - regenerate the `.ps` from this player's winning `particle.ps` /
     `deffer_particle.ps`, so another shader mod's soft-particle changes are
     kept;
   - regenerate the `.s` from their `shaders.xr`;
   - refresh the copies from their versions of the source mods;
   - write the r1/r2 fallbacks.

   Dependencies are the Python standard library plus `dev/shadercheck/sc_tree.py`,
   `sc_blenders.py`, and `tools/zgo_baker/xdb.py` / `resolve.py`.
   `dev/package.py` skips `dev/`, so ship `kidfx_pe.py`, `sc_tree.py`,
   `sc_blenders.py`, `kidfx_snapshot.txt` and `kidfx_copies.json` with the
   setup tool. Either add them to its bundle, or move them under
   `tools/zgo_setup/` and keep `HERE`/`MOD_ROOT` pointing at the mod root.

   `apply` / `revert` / `status` need only the mod folder. `shaders` /
   `copies` / `bake` read the game and MO2 (read only). I tested on Linux
   only; on Windows it needs the same MO2 / game discovery as the baker
   (`sc_tree.Paths`). An optional, slower check is
   `dev/shadercheck/check.sh --json` afterwards, when Wine is available.

4. **Copies of another mod's files: decide.** The 10 copies are files from
   "Particles Cinematic VFX 3.5 1.1.2 BOTZ YAWM" with one line changed.
   Shipping them redistributes that mod's work, and it pins those effects to
   this version of it. Options:
   - (a) ship them, with permission and credit in `CREDITS.txt`;
   - (b) run `python3 dev/shadercheck/kidfx_pe.py copies --remove` before
     packaging (it also removes the empty folders and refreshes the snapshot),
     and let the setup GUI's `bake()` create them per player.

   I recommend (b). Without the copies, kid mode still hides all of ZGO's own
   gore particles; only the knife and anomaly blood from that mod stays
   visible.

5. **Snapshot upkeep for other workstreams.** Anyone who adds or edits a
   `.pe` / `.pg` under `gamedata/particles` must then run
   `python3 dev/shadercheck/kidfx_pe.py apply`. That classifies the new
   effect, switches it if it is gory, and refreshes `kidfx_snapshot.txt`.
   `zgo_test_kidfx.lua` fails and names the file until that is done. Check
   new gory names with `kidfx_pe.py list --gore` / `--unsure`.

6. **`docs/PLAN.md`: what "kid mode" covers.** Particles already in flight
   and engine-played blood are hidden only with request 2's option, on
   DX10/DX11, with the xrRazom exe's shader bus.

## 4. Settings added

None directly. Request 2 adds:

| key | type | default | page | co-op | what |
|---|---|---|---|---|---|
| `general/kid_particles` | check | off | General (shown while Kid mode is ticked) | local | "Kid mode: hide particles already flying (experimental)": sets shader bus lane `zgo_view.w = 1` while kid mode is on |

Not part of any quality preset: it costs nothing either way, since one
compare is added to particle pixel shaders that already run.

## 5. Co-op

Purely local and visual. The lane `zgo_view` is per machine, and both kid mode
and the requested option are on the `coop = "local"` page. Nothing is sent and
there is no new sync kind. Players with different settings, or one with
`kidfx_pe.py revert` run, see their own result. The `.pe` / `.s` / `.ps`
files only change how particles draw, never what is played, so host and
clients play the same effects.

## 6. README text

Under the Kid mode entry:

    Kid mode: hide particles already flying (experimental, off by default; shown when Kid mode
    is ticked). Kid mode stops new blood effects at once, but blood droplets already in the air
    finish their flight, and a few effects other mods play themselves (knife hits, anomalies
    tearing a body) still show blood. Tick this to hide those too: the game switches their
    particle shader off on your screen. Needs DirectX 10 or 11 and the xrRazom game exe; it has
    not been tested in game yet. Sparks, dust, smoke and armour hits always stay visible.

    If anything about particles looks wrong after installing ZGO, this undoes ZGO's particle
    shader change completely (run it in the mod's folder, then restart the game):
        python3 dev/shadercheck/kidfx_pe.py revert

The second paragraph applies only if `dev/shadercheck` ships with the setup
tool (request 3). Otherwise, point the README at the setup GUI's "undo"
button.

## 7. In-game checks

Use DX11 (`AnomalyDX11AVX.exe`, xrRazom exe), and delete
`appdata/shaders_cache` before the first run.

1. **Start-up and log.** The game starts. The log has no
   `DX10: Shader 'zgo\particle_...' not found in library`, no `stub_default`
   for those names, and no `Shader compilation failed`.
2. **Unchanged when off.** Kid mode off: shoot a stalker in the chest and
   head, and compare with `kidfx_pe.py revert` (restart in between). Blood
   puffs, mist and debris look the same: colour, brightness, sorting against
   smoke, fog behaviour.
3. **Soft particles.** Kid mode off, soft particles on (default): a blood
   puff against a wall or the ground fades into it, with no hard intersect
   line. Same with MSAA 4x.
4. **Kid mode on, option off.** No new gory effects (zgo_fx). Droplets
   already flying finish as before. Knife-on-flesh and anomaly body-tear blood
   still shows. Nothing changes compared with before kidfx.
5. **Kid mode on, option on (after request 2).**
   - Fire a burst into a stalker, and tick Kid mode mid-burst: the flying
     blood droplets and mist vanish at once.
   - Knife a stalker, and throw a body into a springboard / vortex: no blood
     sprites.
   - Bullet hits on armour still spark, and dust and smoke from walls still
     show.
6. **Toggle back.** Untick Kid mode, then the option: blood particles appear
   again normally, with no permanently hidden effects.
7. **`set`-mode debris.** `srbd_flesh_wide_expl_fallout4_debris_02` and
   `srbd_gore_thin_expl_fallout4_debris_05` (explosion gibs) still draw and
   cast shadows with kid mode off.
8. **Without the shader bus** (plain monolith exe, if available): with kid
   mode off and on, particles draw as stock, and none flicker or disappear
   randomly (see risk 2).
9. **After request 1, DX9** (`AnomalyDX9AVX.exe`): the game starts, and blood
   particles draw (no hiding expected).

## 8. Risks and open questions

1. **Shader bus binding is unverified for particle shaders.** It is the same
   mechanism `effects_wallmark_blood.ps` relies on. If the exe does not fill
   `bus_zgo_view`, the option has no effect. That is safe, which is why it is
   experimental and off by default.
2. **Unset constant contents.** If the bus does not bind, the constant holds
   whatever the engine's CPU-side cbuffer copy holds. That copy is
   `xr_malloc`, not zeroed. A discard needs x > 0.5 *and* w within 0.001 of
   exactly 1.0, so random data is very unlikely to match. Check 8 covers it,
   and `revert` is the fallback.
3. **The swap itself is always on.** It cannot be behind an option: `.pe`
   files are static, and the Lua shaders replace the C++ blenders whatever the
   options say. It is offline-verified for pass state, bindings, interface and
   compile, but not yet seen in game (checks 1 to 3).
4. **DX8 / DX9 crash** until request 1 is done (or `revert` is run).
5. **Per-modlist drift.** The `.ps`/`.s` are built from this machine's GAMMA:
   base `particle.ps` and base `shaders.xr`. A player whose other mods change
   `particle.ps` gets the base version for gory particles only, until the
   setup GUI's `bake()` runs. Copies can go stale the same way: `copies`
   reports "stale", and `bake` refreshes them.
6. **Coverage.** `srbd_hair_4.pe` (rain shader) stays visible. A mod placed
   above ZGO that overrides one of ZGO's `.pe` brings back its own stock
   shader for that effect: visible, never hidden by mistake.
7. **HUD particles.** The DX11 C++ path flags HUD-loaded shaders
   (`HudElement`), and the Lua path does not. Particle shaders are created at
   start-up, not while a HUD model loads, so no difference is expected. Gory
   effects are never HUD particles.
