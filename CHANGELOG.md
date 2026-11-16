# Changelog

What changed in each version of Umbra Gore & Effects, newest first. Up to 1.7.1 the mod was
called Zone Gore Overhaul (ZGO). The player's guide is [README.md](README.md).


## 1.8.2

- **Much faster game start.** The bake's small parts (stump caps, limb pieces and gibs: about
  79,000 files for G.A.M.M.A.) are now packed into ten game archives, `db/mods/zgo_bake_*.db0`,
  instead of being loose files. The game reads every loose file of every mod through MO2 each
  time it starts; with the loose bake that alone took a minute or more (over four minutes on a
  large mod list). The body models stay loose files, so they still win over other mods' copies.
- An existing bake doesn't have to be baked again: Umbra Effects Setup's check says it "needs
  packing", and **Bake** packs it in place in a minute or two (`--pack --yes` on the command
  line). A downloaded ready-made bake is packed as soon as it is in.


## 1.8.1

- Umbra Effects Setup can download a ready-made bake. Before baking, it looks on Umbra's public
  download server for a bake made for G.A.M.M.A.'s own mod list; when that fits your mod list
  and your bake settings, it downloads it (about 4.7 GB) instead of baking, and otherwise, or if
  the download fails, it bakes on your computer as before. The tick box "Download a ready-made
  bake when one fits" is on by default; on the command line, `--no-download` turns it off.
  A download that gets cut off carries on where it stopped the next time, and every file is
  checked before it goes in. `--list-prebaked` lists the ready-made bakes.
- The README is now `README.md`, rewritten, and the version history is in `CHANGELOG.md`.
- The help for "Objects break apart" names Umbra Effects Setup's Breakable props box.


## 1.8.0

- **New name:** Zone Gore Overhaul (ZGO) is now Umbra Gore & Effects, Umbra Effects for short,
  and ZGO Setup is now Umbra Effects Setup. Same options (your MCM settings carry over), same
  bake, same co-op protocol (1.7 and 1.8 players still see each other's effects; the host's
  notice says the versions differ). MO2 installs it as a new mod: disable or remove the old
  "Zone Gore Overhaul" and run Umbra Effects Setup again (the old bake stays in the old folder).
- **Kid mode** also covers gory effects that a mod ships only inside its `particles.xr` (as
  Cinematic VFX and HollywoodFX do), and no longer mistakes fire, sparks and glows for blood.


## 1.7.1

- **Body gibs:** explosions and head bursts throw pieces torn out of the body itself (its
  clothes, skin or fur outside, raw flesh inside), each from the spot it came from, nearest the
  blast first, instead of G.A.M.M.A.'s mutant meat items. Umbra Effects Setup cuts them from
  every model (about 11 per body, 650 MB); run it again after updating.
  MCM -> Dismemberment -> Gib look switches back to meat models. Co-op: every machine throws the
  same pieces.
- **Fixes from in-game testing:** metal sparks were metres long (now short streaks), prop sparks
  were 10-20 cm (now 2-4.5 cm), crater smoke flickered through its frames (now still puffs) and
  dust loops played up to three times per puff; grenades no longer throw gibs or chunks out of
  someone they didn't kill.


## 1.7.0

- **ZGO Setup** (now Umbra Effects Setup, `tools/zgo_setup`): a window for Windows and Linux
  that bakes the models for your mod list, shows what and how much, checks whether the bake is
  still up to date and names the mod that changed, and removes it. The game checks the bake
  when a save loads and tells you when to run it (MCM -> Baked models). The baker no longer
  needs LuaJIT.
- **Baker:** fitted stump caps (the cut surface of each body, flesh and bone, made for every
  model and cut, with the mod's own stump texture), lighter severed-limb models with a closed
  end, and wound sites for every body; `bake.py` is now a library for the setup tool, with
  progress and cancel. Default baked models are unchanged; experimental in-model caps and
  damage meshes are off.
- **Progressive wounds** on baked bodies: bruise, open wound, crater, bone, destroyed; chunks
  fly from deep wounds, destroyed parts come off dead bodies. Experimental wound craters in the
  body itself.
- **Experimental, off by default:** cuts drawn with the mod's own off shader (no pinched joints,
  no waiting for the ragdoll), stump caps fitted to the cut from the bake, caps inside the
  model, light severed limbs from the bake's pieces. Both thighs now keep their stump caps.
  Co-op: bodies resync with one line per body.
- **World impacts:** calibre-sized bullet marks with dust, chips and sparks per material,
  damage that builds up per spot (chip -> crack -> gouge -> breach), explosion craters with
  fragment pocks, dust ring, hanging smoke and ceiling grit indoors; optional rubble and clods
  (experimental) and parallax "deep" marks (experimental). Host-decided in co-op.
- **Objects:** material hit effects, harder pushes and blast throws, leaking barrels and
  canisters with puddles, shattering and flickering lamps, bursts on the game's breakables;
  small crates, chairs, stools, bottles and jars break apart under fire, knife and explosions,
  barrels and cans too after Umbra Effects Setup's "Breakable props" step. Host-decided in
  co-op; the pieces land in the same places for everyone.
- **Kid mode** can also hide blood particles already flying (experimental; MCM -> General).
- **Native extensions** (experimental, off by default): an optional engine add-on that verifies
  the game executable before it does anything; first feature: broken limbs and crushed chests
  on bodies near explosions (same on every co-op machine; kid mode removes them).
- **Diagnostics page** (with Debug log on): nine engine probes for bug reports, written to
  `appdata\zgo_probe_report.txt`.
- **Co-op:** sync protocol 3 (every player needs 1.7). The host tells each client its version
  and bakes; a client that differs gets one notice and play goes on.


## 1.6.0

- **Settings rework:** every option explained (English and Russian) and grouped by concern; new
  Performance page with quality presets (Potato, Low, Medium, High, Ultra) and new sliders for
  things that were fixed before (particle effects at once, spreading wound stains, severed
  parts' lifetime and removal distance, detail distance, explosion victims per frame). Blood
  lifetime and streams per hit moved there (they start from the preset again).
- **Kid mode:** hides all gore at once and brings it back when switched off; per machine in
  co-op.
- **Co-op:** xrRazom now knows which settings the host decides (shown and locked on clients);
  clients draw the host's particle effects within their own performance limits; a client with
  the mod switched off ignores the host's effects.


## 1.5.0

- **Explosions**, an opinionated patch over G.A.M.M.A. (see "Changes to G.A.M.M.A. explosions"
  in README.md): blast damage follows overpressure, so a grenade at someone's feet kills them
  through G.A.M.M.A. armour; explosions get past No NPC Friendly Fire. Dismemberment from
  blasts goes by each part's distance to the charge: feet and lower legs from a grenade at the
  feet, whole-body gibs only from direct RPG hits and IEDs underfoot (not grenades, launcher
  rounds or mines). New MCM page Explosions.
- **Baked models** now go into this mod's own folder (no separate MO2 mod); `bake.py --remove`
  deletes them; MCM switch to turn them off.
- The explosion log shows the overpressure share and fragment hits.


## 1.4.1

- Log fix: console commands from other mods (e.g. Laser Settings writing `shader_param_6`) no
  longer show up in engine warnings as coming from `zgo_main.script`.


## 1.4.0

- Mesh baker (`tools/zgo_baker`) and support for its baked models: cuts on corpses and late
  blast cuts on every body with a baked model, no pinched joints (cuts wait for the ragdoll),
  saved corpses keep their pose and cuts. Without baked models nothing changes from 1.3.0.


## 1.3.0

- Dismemberment that matches what you see: the engine keeps a ragdoll's limbs on screen even
  when they are hidden (see "Known limits" in README.md). Cuts it can't show are no longer made,
  so no more whole limbs flying off bodies that keep them, no limb separated at the wrong joint
  (only the fingers / jaw collapsed), no doubled limbs.
- Explosions decide what comes off on the killing hit itself, before the ragdoll exists,
  instead of up to 1.5 s later; gibbing reaches further (about 1.4 m for an F1, heavier charges
  further) and close blasts take more; a gib still bursts meat and blood when nothing can come
  off. NPC explosives near you dismember too.
- Arteries in a limb a shot takes off keep pumping from the stump.
- New explosion log line (MCM: General -> Log explosions).


## 1.2.0

- **Explosions reworked:** fragments and blast collected per explosive and resolved per body;
  blast blood no longer starts at the feet (the engine reports blasts on the skeleton root); no
  sparks or exit spray from the blast wave; grenades into corpses dismember and gib; parts
  nearest the blast come off and fly away from it; gib by real distance to the explosion; NPC
  grenades no longer dismember.
- **Bleeding trails:** "standing still" judged by walking speed, so slow walkers leave drops
  instead of pools.
- **Stump caps fixed:** they sat on the parent bone's origin (the shoulder for a lost forearm,
  the hip for a lost calf), mostly buried in the body. Now on the cut itself, the meat disk
  faces along the limb so it covers the hole, sized per joint (thigh 17 cm, neck / knee 12,
  shoulder 11, elbow 8.5, wrist 6.5).
- **Fixes from a code review against the engine source:**
  - decal names are kept alive for the engine (it holds the raw string; a recycled one could
    draw the wrong decal);
  - effects play to the end (a full gib no longer cuts off the previous body's blood);
  - a late blast wave (cluttered areas: 3 objects a frame) no longer resolves a body twice;
    bodies inside the radius wait for it;
  - every stump gets its cap back after a load, not just the first; a cap or spurt is removed
    when the bone above it is cut off too;
  - a released body's id given to a new NPC no longer makes it spawn missing its head;
  - flying pieces no longer hold the corpse object (possible crash when the corpse is cleaned
    up mid-flight);
  - boar, pseudodog, burer, giant and chimera heads count as heads;
  - explosions: blood traces cheaper, bodies resolved two a frame, pieces thrown outward
    instead of up, fewer extra gibs in a gib; debris at rest is removed before pieces still in
    the air.
- **Co-op:** sync protocol 2. Every machine needs the same version; a peer on an older one is
  ignored with a note in the log instead of replaying effects this machine may not have (an
  engine crash).


## 1.1.0

- Severed limbs now visible (they were spawned at the wrong place); flying limbs and gibs
  physically simulated and identical in co-op.
- Full gibbing for overkill explosions.
- Distance-aware splatter: thick marks only close to the wound.
- Animated wall drip runs.
- Bleeding trails follow the engine's bleeding value and use sparse drip textures; small pools
  under heavy bleeders standing still; wound stains spread on the living.
- New droplet particles: arterial jets, exit and back sprays, dribbles, gushes, falling drips.
- Arteries: neck, thigh, collarbone, upper arm, calf, forearm; also on kills. Jets follow the
  wound and paint where they land.
- Exoskeleton and helmet sparks on every hit, not only stopped rounds.


## 1.0.0

- First release.
