# In-game checks for 1.8.0

1.8.0 is 1.7.1 under the new name, Umbra Gore & Effects (Umbra Effects for
short; the setup program, ZGO Setup before, is now Umbra Effects Setup).
Neither 1.7.0 nor 1.7.1 has been checked in the game yet, so this is the 1.7
list (docs/INGAME-CHECKS-1.7.md) brought up to date, plus section N for what
is new: the name, the setup program's Umbra look, and 1.7.1's body gibs and
fixes.

One ordered list for everything the test harness cannot show. Work from the
top: the safest checks first, then the Diagnostics probes, then what is on by
default, then each experimental option on its own, then co-op with a second
player. No console commands anywhere: everything is MCM, MO2 or Umbra Effects Setup.

Each check says what to do, what to look for, and what in the log (or which
probe verdict) means it passed. The log is `appdata\logs\xray_<user>.log` in
the Anomaly folder; Umbra Effects' lines start with `[ZGO]`, the probes' with
`[ZGO probe]`, and the probes also write `appdata\zgo_probe_report.txt` (under
MO2 it may land in `overwrite\appdata\`; "Run all safe probes" prints the full
path). Send the log and the report file with any finding.

## 0. Before you start

1. "Umbra Gore & Effects" 1.8.0 enabled in MO2: above Screen Space Shaders,
   below every mod that ships character models. No "Zone Gore Overhaul"
   folder enabled. Painter of the Zone (and its xrRazom patch) off.
2. Run Umbra Effects Setup once with its defaults (body models, stump caps,
   limb pieces, wound sites, body gibs, breakable props, kid mode for
   particles; nothing experimental) and close it. The bake on the dev
   machine: 4790 models, 54,500 gib pieces, 0 errors, about 3 minutes,
   7.2 GB. (The dev machine's folder was renamed with its 1.7.1 bake inside:
   "Check if my bake is up to date" must say it is, with no rebake.)
3. DirectX 11 renderer (xrRazom exe). Delete `appdata\shaders_cache` once
   before the first start if you haven't since 1.7 (1.7 added shaders).
4. Make a save at a base with several stalkers (Cordon village or Rookie
   Village), with open ground, a concrete wall, crates and barrels nearby.
5. MCM -> Umbra Gore & Effects -> General: tick **Debug log**, Accept. Leave it
   on for the whole list.

## N. New in 1.8.0 (and 1.7.1)

| # | Do | Look for | Passes when |
|---|---|---|---|
| N.1 | Look at MO2's left pane, then open MCM in English and in Russian. | The mod is "Umbra Gore & Effects"; MCM lists "Umbra Gore & Effects" with an ampersand, not `&amp;`. Your settings from Zone Gore Overhaul are still there. | Both languages show the name right; no option went back to its default. |
| N.2 | Start Umbra Effects Setup: `tools/zgo_setup/zgo-setup.sh` on Linux, `tools\zgo_setup\Umbra Effects Setup.exe` on Windows (or under Proton). | Umbra's look: dark window, the Umbra "U" icon in the header, the title bar and the taskbar, Tektur Narrow headings and buttons, an umber Bake button. Every text readable; tabs and column heads not tiny. | It finds MO2, the profile and the game by itself, and "Check if my bake is up to date" says it is. |
| N.3 | Kill a group with a grenade; blow a head off with a slug. | Pieces of the bodies themselves fly (clothes, skin or fur outside, raw flesh inside), nearest the blast first, not G.A.M.M.A.'s mutant meat. | No `[ZGO]` errors. MCM -> Dismemberment -> Gib look -> Meat models switches back to meat. |
| N.4 | Shoot metal (a barrel, a car); throw a grenade on open ground; shoot a dusty wall. | Sparks are short streaks (not metres long), prop sparks a few cm, crater smoke still puffs (no flicker through frames), dust puffs play once. | Looks right; a grenade never throws gibs out of someone it didn't kill. |
| N.5 | (Co-op, optional) a client on Zone Gore Overhaul 1.7.x joins a 1.8.0 host. | The client gets one notice naming both versions; effects still show on both screens (same sync protocol 3). | Host log: `co-op player ... differs from this host: Umbra Effects 1.7.x (host 1.8.0)`; nothing crashes. |

## 1. Safest: nothing changed, just look

| # | Do | Look for | Passes when |
|---|---|---|---|
| 1.1 | Start the game, load the save, wait 10 s. | The game starts and loads as with 1.6. | Log: `[ZGO] Umbra Gore & Effects 1.8.0 running (single player)` and `[ZGO] shader bus lane zgo_view: registered`. No `error` in any `[ZGO]` line, no `Shader 'zgo\particle_...' not found in library`, no `stub_default` for `zgo\` names, no `Shader compilation failed`, no missing texture or particle names starting with `zgo`. |
| 1.2 | Same load. | No message on screen about the bake. | Log: `[ZGO] bake check: Your baked models are up to date (4790 models checked).` (the number is your bake's). If it says `file sizes not compared (the index reads as X bytes, the bake wrote Y)`, write down X and Y. |
| 1.3 | Note the load time against 1.6. | At most a fraction of a second more (the bake scripts are 6.5 MB). | No visible stall; no `is from another bake` in the log. |
| 1.4 | Kid mode off. Shoot a stalker in the chest and head. | Blood puffs, mist and debris look exactly as in 1.6 (colour, brightness, sorting against smoke, fog), and fade into walls (soft particles). | Nothing looks different. If something does, see 4.1's undo. |
| 1.5 | MCM -> Baked models -> "Check the bake now", close the menu. | A message: "Your baked models are up to date (N models checked)". | The same line in the log. Switch the game to Russian and press it again: readable Cyrillic, no garbage characters. |

## 2. Diagnostics probes (MCM -> Diagnostics, shown with Debug log on)

| # | Do | Look for | Passes when |
|---|---|---|---|
| 2.1 | Press **Run all safe probes**, close the menu, wait about 15 s near stalkers. | Four on-screen lines and a summary `run all safe probes: ...`. Blood on walls and bodies vanishes for the hold time and comes back (probe 8). | **9 Baked models**: PASS "N of N baked model(s) near you are in use". **4 FFI**: PASS "GetModuleHandleA(nil) = 0x140000000". **8 Kid mode lane**: PASS (the lane takes the write token since 1.7.0), then press "The last probe looked right" if the blood really vanished and came back. **6 Co-op**: MANUAL in single player. |
| 2.2 | Kill two or three stalkers so limbs come off; stay within 40 m. Press **5. Save and reload: start**, close the menu, save, load that save, wait 10 s. | Stumps still capped, no pinched joints, no body jumps or falls. | PASS "N of N recorded bodies came back as saved". |
| 2.3 | Save. Tick **Allow the experimental probes**, Accept, reopen. Press **1. Off shader** standing 3-10 m from a living NPC and a dead body. | For 6 s each one's head (or top part) and its shadow vanish completely, no stretched skin, then come back. | Mark "looked right"; the report has no `set_shader did not take` / `reads back the old shader`. Gates every off-shader option in section 4. |
| 2.4 | Save. Press **2. Pass-through shader** among several kinds of NPCs and mutants. | For 12 s they look exactly as before: colour, bumps, shadows, no flicker or smearing in motion. If the game closes, that is a shader compile failure: send the log. | Mark "looked right". Gates wound craters (4.7). |
| 2.5 | Save. Press **3. Digit textures** near two or three NPCs. | Their torsos turn plain red, green and blue in the order the news names them. Magenta = pixel-shader slots failed; a missing torso with its shadow still there = vertex-shader slots failed. | Mark "looked right". Gates wound craters (4.7). |
| 2.6 | Single player: press **7. Props** next to a loose bottle, can or small box. | It turns into another small object for the hold time, still moves and falls when shot or walked into, then turns back. | Mark "looked right". |
| 2.7 | Tick General -> Kid mode, Accept, run **Run all safe probes** again. | Nothing gory appears. | Probe 8: "kid mode is on and the lane reads x = 1". Untick Kid mode afterwards; untick the experimental probes if you like. |

## 3. On by default

| # | Do | Look for | Passes when |
|---|---|---|---|
| 3.1 | Progressive wounds: shoot one spot on a standing NPC's chest with a 5.45 rifle, 3-5 times. | After the third round a few meat chunks fly from the wound and a larger torn mark appears; another burst around the fifth. A pistol never throws chunks before the fourth round. | Log: `wound body#... on ...: stage 2 -> 3`. No `wound ... failed` lines. |
| 3.2 | Kill an NPC, then fire a 12-gauge slug 3-4 times into one forearm or calf of the body. Repeat on a living NPC. | The dead body loses the part (cap, flying piece); the living one never does. | Log: wound stage 5 on that section; the cut shows like any Dismemberment cut. |
| 3.3 | Wound a body to stage 4, save, load, shoot the same spot once. | Chunks fly at once: the wound continued. | No restart from stage 0. |
| 3.4 | World impacts: shoot a concrete wall at 5-10 m, then empty a magazine into one spot. | Chips next to the game's holes, grey dust; then cracks, a gouge, a dark breach. Brick: reddish dust; plaster: white; wood: splinters and a split; sheet metal: sparks, dent, torn hole; ground: dirt, no build-up. No visible square or tinted border. | No `world impact error` in the log. |
| 3.5 | Throw an F1 onto open ground; an RPG at the ground; a grenade into a room. | A dark pit and scorch about 1.5 m across, pocks on nearby walls, a dust ring, smoke for about 15 s (High preset); larger for the RPG; grit from the ceiling indoors. The game's own explosion marks are still there, a little larger, with Umbra Effects scorch textures. | No `world crater error`; if explosion marks vanish entirely, the `![explosion_marks]` override failed. |
| 3.6 | Props: shoot a loose chair or bucket with a pistol, an AK, a shotgun. | It moves more than in vanilla, never more than about a metre from one round. | With Props -> "Extra push" at 0 it looks vanilla. |
| 3.7 | Shoot a small wooden crate (not a stash) until it breaks; rotate other crates and repeat. Knife a small crate the game can't break. | Planks appear exactly where the crate was, the same way round, fly from the shot, settle on the floor and vanish later. The knifed crate breaks after about 3 hits. | No log errors; nothing mirrored, rotated 90 degrees or offset. |
| 3.8 | Shoot a closed barrel low, then high; a gas bottle; a hanging lamp; a vodka bottle; throw a grenade near bottles. | Low hole: a stream and growing puddles that stop; high: no leak; gas: a short hissing jet; lamp: glass and sparks, or a flicker that ends with the lamp on; bottles shatter, also within a few metres of the grenade. | Puddles look like liquid, not squares. |
| 3.9 | Barrels and milk cans (needs Umbra Effects Setup's "Breakable props" step): shoot one until it breaks. | Metal shells with an inner face, the barrel's own texture, no gaps. | Log has no fracture errors. |
| 3.10 | Stashes, quest items, doors, explosive barrels, inventory boxes, the trader's crates. | Never break or vanish. | - |
| 3.11 | Break a crate, save, load. | It stays gone. | No errors. |
| 3.12 | Kid mode: tick it with cut bodies, wounds, marks and gibs in view; untick it. | On: all gore gone at once (decals, pools, gibs, caps, cuts with baked models); world impacts and props stay. Off: it comes back, cuts included. Wounds made meanwhile keep counting but draw nothing while it is on. | Log: `kid mode on: gore hidden`, then `kid mode off`. |
| 3.13 | Load order: in MO2 drag a mod with character models below Umbra Effects, start, load a save; load again; drag Umbra Effects back below and reload. | Within 10 s one news message names how many baked models are hidden, an example and the fix; it does not come back on the second load; no message once the order is fixed. | Log: a `bake check:` line naming the mod. |
| 3.14 | Umbra Effects Setup -> "Remove bake", load a save, load again; then bake again. | One reminder naming tools\zgo_setup on the first load, none on the second. | Log: `bake check:` reminder line once. |

## 4. Experimental options, one at a time (save first; untick each before the next)

| # | Option | Do | Look for | Passes when |
|---|---|---|---|---|
| 4.1 | General -> Kid mode: hide particles already flying | Fire a burst into a stalker and tick Kid mode mid-burst (MCM open and close). Knife a stalker; throw a body into an anomaly. Then untick both. | Flying droplets and mist vanish at once; no blood sprites from the knife or anomaly; sparks, dust and smoke still show. Unticking brings particles back, nothing stays hidden. | No `shader bus zgo_view: set failed` in the log. The knife and anomaly effects of other mods are only covered after Umbra Effects Setup's "Kid mode for particles" step. Escape hatch if particles look wrong: close the game, run `python3 tools/zgo_kidfx/kidfx_pe.py revert` in the Umbra Effects folder (or Umbra Effects Setup's undo button), start again. |
| 4.2 | Dismemberment -> Cut with the off shader (needs 2.3 PASS) | Kill NPCs with shots that take a forearm, a thigh, a head; then shoot a lying body until a limb comes off and shoot where it was. | Each part and its shadow vanish in the frame of the kill; no pinched stump while the body falls; no blood in thin air where the limb was. Save and load: still cut. Walk 200 m away and back: still cut. Untick with cut bodies in view: they stay cut. | Probe 5 (2.2) passes with the option on. No `set_shader failed` in the log. |
| 4.3 | Dismemberment -> Stump cap shape: Fitted to the cut | Cut a forearm, both thighs and a head off bodies; drag a body; cut the same arm higher up. | A flesh cap (Umbra Effects' stump texture) with a bone stub closes each stump with no gap, both thighs included, and stays on the seam while dragged; the elbow cap goes and a shoulder cap comes. | No `no bone_callback(bone, bone, true)` in the log (if present, the caps are rigid: report). |
| 4.4 | Stump cap shape: Inside the model (needs a bake with Umbra Effects Setup's experimental "Caps inside every model" and 4.2 on) | Same cuts as 4.3. | Before any cut every NPC looks unchanged (no caps showing). The cap is raw flesh, appears only after the cut, and switches off when the cut moves up. | Bake the default again afterwards. |
| 4.5 | Dismemberment -> Light severed limbs | Shoot an arm off; a hand then the forearm. | The flying arm starts exactly where the arm was, with a closed end, no stretched skin; the flying forearm has no hand. | No `limb piece ... could not be attached` in the log. |
| 4.6 | (Umbra Effects Setup) experimental damage bake, then Wounds -> Wound craters (needs 2.3, 2.4, 2.5 PASS) | Bake with "Damage meshes and gib chunks" ticked (much larger, about an hour). Shoot one spot on a body 4-5 times with a rifle. Walk away until it goes offline and come back; toggle kid mode. | A crater with a dark red rim, fat and muscle on the walls, bone at the bottom after the fifth round; the rest of the body unchanged (bump detail too); the shadow has the dent; it follows the ragdoll. The chunk that flies out of a deep wound is now the piece cut from that very spot (falls back to ordinary gibs when the bake has none). Back within seconds after returning; kid mode hides it at once. | Log has no `wound craters (experimental): off: ...`. Without the damage bake, ticking it logs exactly once `wound craters (experimental): off: the baked models have no damage meshes`. Bad signs: the game closes, pink bodies, a whole part vanishing, a seam at the crater, shadows without the dent. Bake the default again afterwards. |
| 4.7 | World impacts -> Crater rubble and clods | Grenade on open ground, then on concrete. | A low ring of dirt around the pit, 4-6 clods landing on the ground (not floating or sunk); grey chunks and a rubble rim on concrete. | No model or visual error. |
| 4.8 | World impacts -> Deep impact marks | Shoot a concrete wall until a gouge appears; move sideways. | Gouges and breaches look recessed (parallax) and fade out smoothly at the end of their lifetime. Flat grey squares = the shader route failed. | No crash at the first mark (a crash = shader compile failure: send the log). |
| 4.9 | (Umbra Effects Setup) Game breaks crates and stools itself (single player only) | Bake with it ticked; shoot or knife a crate the level spawned as a breakable. Then bake again without it. | It breaks by itself into the baked planks; loose crates with the same model behave as before. Without it, crates are back to normal. | No errors. |
| 4.10 | Native extensions (tick "Native extensions", leave "Bone hooks" off), load a save | Press "Write a status report to the log". Then tick "Bone hooks" and play 10-15 minutes with fights. | No crash, no FPS change. | Log: `native: zgo_native 1.0.0 (abi 1, ...) loaded from ...\bin\zgo_native.dll; supported exe ...; verified: finder+bones`; status: `state = ready`, `caps = finder+bones`; with hooks: `native: hooks in: bones`, `capture_test = ok` and a growing `calc_calls`. |
| 4.11 | Native: broken limbs | Kill a group with a grenade. Shoot a bent limb; drag and drop a bent body; kid mode on and off; untick Bone hooks; save and reload; leave and return; change level; quit to menu and exit. | A second after they go limp, arms and legs bend at broken angles (a close charge: flattened chest or shoulder out of place), stay attached, no stretching or jitter; wounds sit on the bent limb; physics as before. Kid mode straightens them within half a second and they bend again after; Bone hooks off straightens at once. Saved bodies come back bent the same way. No crash at any step. | Debug log: `native: body <id>: <n> groups`; `hooks in: none` after unticking. |
| 4.12 | Baked models -> Also look at the other mods' files (Proton) | Press "Check the bake now"; then disable a model mod in MO2 and reload. | Either the check runs quietly, or the log says `cannot read ... modlist.txt from the game (skipped)`: report which. The message names the disabled mod "(disabled or removed)". | - |

## 5. Co-op with a second player (xrRazom 1.5, both on 1.8.0)

| # | Do | Look for | Passes when |
|---|---|---|---|
| 5.1 | Both machines with the same mod list and a bake from it; the client joins the host. | No Umbra Effects notice on either screen. | Host log has no `co-op player ... differs from this host`; with Debug log on the client logs `co-op handshake: same Umbra Effects 1.8.0 and the same bakes as the host`. |
| 5.2 | Client removes its bake (Umbra Effects Setup -> Remove bake) and joins again. | The client gets one news message "Umbra Gore & Effects (co-op)": the host has baked body models and you don't ... Play goes on as usual. It does not repeat while the session lasts (the host re-announces every 30 s). | Client log: `co-op handshake: this machine differs from the host: Umbra Effects 1.8.0 (host 1.8.0), body bake - (host <fingerprint>), ...; play goes on`. Host log once: `co-op player <id> differs from this host: ...`. In Russian the notice is readable Cyrillic. The client bakes again afterwards. |
| 5.3 | (Optional) a client on Zone Gore Overhaul 1.6.x joins a 1.8.0 host. | Neither sees the other's effects; nothing crashes. | Host log once: `a co-op peer runs an older Umbra Gore & Effects (sync protocol 2, this is 3)`. |
| 5.4 | Stand together near a few cut-up bodies. On the host press Diagnostics -> **6. Co-op: compare machines**; then press it on the client. | - | Host: PASS "1 of 1 player(s) answered ... player N: match"; the client's log and report get "the host compared player N: match". A host with "Cut with the off shader" and a client without it (or the other way round) still match. |
| 5.5 | Host shoots one NPC's chest 4 times with a 7.62x54R. | The client sees the chunk bursts at the same moments and the same torn marks; the client's own shots do nothing until the host processes them. | No `wound chunks failed` in either log. |
| 5.6 | The client shoots a wall; an NPC fires at a wall near the client; the host throws a grenade (rubble on for the second run). | The client sees dust at once; the same marks on both screens; the same crater; clods land in the same places. | - |
| 5.7 | Repeat 3.6-3.8 with the client shooting. | The client sees its hit effect at once; both see the push, the break, the pieces landing in the same places, the object gone on the client too, leaks and flickers on both. | - |
| 5.8 | Cuts made before the client joined; then cuts while both watch. | The late client sees them within 20 s; both see the same parts missing. | - |
| 5.9 | Native: both tick both switches, blow up bodies; then the client unticks Bone hooks; a third player joins later if possible. | Both see the same limbs bent the same way; with the client's hooks off the bodies straighten on both machines; a late joiner sees them bent. | Host log: `co-op session capabilities: finder+bones`, then `... capabilities: finder`. Client: `... (from the host): finder+bones`. |
| 5.10 | One player ticks Kid mode. | Only that player's screen loses the gore; the partner still sees everything. | - |
| 5.11 | Performance: Potato preset, 20 s of automatic fire at a wall; a base with about 20 cut bodies in view and "Cut with the off shader" on. | Frame time does not climb. | - |
