UMBRA GORE & EFFECTS  1.8.0
===========================

Blood, gore and effects overhaul for S.T.A.L.K.E.R. Anomaly / GAMMA, single
player and xrRazom co-op. Umbra Effects for short; up to 1.7.1 it was called
Zone Gore Overhaul (ZGO). Built on Painter of the Zone by sunn - see
CREDITS.txt.

INSTALL
  1. Disable "Painter of the Zone" and "Painter of the Zone - xrRazom Patch"
     in Mod Organizer. (If either is left on, this mod pauses itself and says
     so on screen; they would paint everything twice.)
     Coming from Zone Gore Overhaul? Disable or remove it too: this is the
     same mod under its new name, and MO2 installs it as a new mod. Your
     MCM settings carry over; your old bake stays in the old folder, so run
     Umbra Effects Setup again (step 3).
  2. Enable "Umbra Gore & Effects". In MO2's left pane a mod lower in the
     list wins over the ones above it. Keep Umbra Effects above Screen Space
     Shaders, and below every mod that ships character models (that part
     only matters for baked models; Umbra Effects Setup names such mods).
  3. Recommended: run Umbra Effects Setup once (see BAKED MODELS). It
     rebuilds the body models of your mod list so limbs come off corpses
     too, and wounds have somewhere to open. A few minutes; run it again
     after changing mods with character models (the game reminds you).
  4. Co-op: every player needs the same mod list and the same Umbra Effects
     version. Umbra Effects tells a client once when the host runs another
     version or a different bake; play goes on either way.

WHAT IT DOES
  Hit profiles
    Every hit is classified from the actual bullet (ammo section and impact
    speed): pistol, intermediate rifle, full-power rifle, magnum/slug,
    anti-materiel, buckshot, explosion, melee/claws. Everything below scales
    with it.

  Trajectory blood
    Each hit throws several blood streams out of the exit wound (and some
    back toward the shooter). Streams fly under gravity and are traced step
    by step; where and how they land picks the decal:
      distance flown    -> thick splashes and heavy spatter only close to the
                           wound (the range grows with calibre); further out
                           medium spatter, then only fine spray and mist
      glancing          -> directional spatter aimed along its travel
      head-on           -> radial splash (buckshot clusters, gore for heads)
      steep onto floors -> splash close by, drops further out
      slow              -> single drops
    Bystanders in the way get stained.
    15 categories, ~170 generated textures plus Painter's graded set.

  Drip runs
    Wet blood high on a wall runs: thin rivulets creep down over 6-15
    seconds, at different speeds, and stop with a bead (10 shapes; the
    length is limited by how much wall there is above the floor). Same
    shader trick as the pools, so it costs nothing per frame.

  Bodies and bleeding
    Entry and exit wounds on the victim (exits larger), smears when someone
    dies against a wall, slowly spreading death pools (12 shapes).
    The wounded bleed by the engine's own bleeding value for that NPC: a
    sparse line of drops behind them as they move, drops piling up and a
    small pool when a heavy bleeder stands still, drips falling from the
    wound itself. It stops when the bleeding stops (bandaged, healed).
    While they bleed, the stain around the wound on their clothes spreads.

  Progressive wounds (baked models, see BAKED MODELS)
    Damage builds up where a body is hit. Every hit lands on the nearest
    wound spot the baker marked on the model and adds to it by calibre:
    bruise, open wound, crater, down to the bone, destroyed. A pistol opens
    and craters wounds but never reaches the bone by itself, rifles do,
    slugs, magnums, anti-materiel rounds and explosions go all the way;
    fragments and the blast tear the side that faced the explosion. From a
    crater on, chunks of meat fly out of the wound and a larger torn mark
    goes on the body; a destroyed head or limb on a dead body comes off
    (Dismemberment settings apply; the living never lose parts).
    Experimental, off by default (MCM -> Wounds -> Wound craters): with
    models baked with --experimental-damage, wounds become real craters in
    the body that move with it and its shadow: a bloody rim, fat and muscle
    on the walls, bone at the bottom of the deepest, and the chunk that
    flies out is the piece cut from that very spot. DirectX 10/11 only.

  Particles
    Painter's particle library, picked by calibre and armour, plus this
    mod's own droplet effects: stretched, gravity-driven drops that die on
    contact, so sprays read as streams instead of puffs.
      armour   sparks on every exoskeleton and helmet hit (penetrating or
               not), plate / cloth fragments, visor glass
      wounds   back spray from the entry, exit sprays that grow with energy
      arteries neck, thigh (femoral), collarbone, upper arm, calf and
               forearm hits can open an artery: a jet pulses out of the
               wound on every heartbeat, follows the body as it moves,
               weakens beat by beat, dribbles in between, and paints the
               wall or floor where it lands. A killing shot still gets the
               last few beats.
      stumps   gush the same way.

  Dismemberment
    Kills and corpses only. Big calibres and explosions take heads and limbs
    off from the hit bone downward; damage builds up on a body part, so a
    few rifle rounds into a dead man's arm will take it off. Jaws can be shot
    off alone. Heads either come off whole or burst.
    Severed parts fly off and tumble with simple physics (they bounce, roll
    and come to rest on the ground, dripping, and leave a small pool), meat
    gibs fly, stumps get a meat cap and gush. A shot that takes a limb off
    with an artery in it leaves the stump pumping. Direct RPG hits and IEDs
    going off underfoot take the whole body apart: head, two to four limbs
    and a shower of meat. Dismemberment is saved with the game.
    On a body that is already a ragdoll the engine can't hide arms, legs or
    the head (see LIMITS), so those cuts are only made at the moment of
    death; corpses can still have the jaw shot off and get torn open by
    blasts.

  Explosions
    The engine sends a grenade to a body as fragments (separate bullets) and
    a blast hit. Both are collected per explosive and resolved once per body,
    so a grenade is one coherent event instead of a pile of separate hits:
      fragments  small entry wounds where each one actually hit, a short
                 spray from the first few, sparks off exoskeletons and
                 helmets (small fragments mostly stop there); survivors bleed
                 and can have an artery nicked
      blast      blood and meat thrown off the far side of the body, away
                 from the explosion, and a stain on the side that faced it;
                 no sparks, no exit wounds
      the dead   decided on the hit that kills, before the body turns into
                 a ragdoll. A part goes by how close its nearest point was
                 to the charge (distance scaled by the size of the charge),
                 and it is cut at the joint nearest the body that was still
                 inside the blast: a grenade at someone's feet takes feet or
                 lower legs, not arms or the head. Only heavy charges (a
                 direct RPG hit, an IED going off underfoot) take the whole
                 body apart; grenades, launcher rounds and mines never do
      corpses    the same, with baked models (see LIMITS); without them
                 corpses are torn open and showered with meat
    Dismemberment from explosions: yours and your co-op partners' always;
    NPC explosives too when they go off within 55 m of you ("NPC firefights
    bleed too" on), further away they only bleed.
    Every explosion that hurts or kills writes one line to the game log
    (distance, damage and this mod's overpressure share, fragment hits, and
    what came off and why not); MCM can turn it off.

  World impacts
    Rounds that hit walls, floors, trees and objects leave marks sized by
    calibre on top of the game's own bullet holes: a pistol round chips,
    a rifle round gouges, buckshot peppers. Dust, chips, splinters and
    sparks match the surface (concrete, brick, plaster, wood, metal,
    earth). Keep firing at one spot and the damage builds up: chips turn
    into cracks, then a deep gouge, and sustained fire knocks a dark breach
    into masonry and wood (metal dents and tears). Marks only: walls don't
    open and bullets don't pass through.
    Explosions leave a scorched crater sized by the charge (grenade, VOG,
    mine, RPG, IED), pock marks from fragments on the walls and floor
    around it, a ring of dust rolling out along the ground and smoke that
    hangs for a while; indoors, grit and dust rain from the ceiling.
    Optional (experimental): clods of earth and chunks of concrete thrown
    out of the crater, and a rim of thrown-up dirt or rubble.
    MCM -> World impacts; how many marks, effects and pieces, their
    lifetime and range are on the Performance page. Not gore: kid mode
    leaves all of it alone.

  Objects (PROPS)
    Bullets throw splinters, dust, sparks, glass or fluff off crates,
    barrels, bottles, lamps and furniture, and shove loose objects harder
    (heavier rounds more, heavy objects less); explosions lift and spin
    them. A hole in a barrel, canister or milk can below its fill line
    leaks water, fuel, oil or chemicals into a growing puddle until it runs
    dry; gas bottles hiss out a jet. Shot lamps shower glass, or flicker if
    they survive. Crates, boards and jars the game can already break now
    burst with dust and splinters.
    Small crates, chairs, stools, bottles and jars that the game can't
    break wear down under fire, knife hits and explosions and come apart
    into pieces (the game's own crate and bottle parts). Barrels and milk
    cans break too once Umbra Effects Setup's "Breakable props" step has
    cut pieces from the models your mod list uses (about 5 seconds; run it
    again after changing mods that replace prop models). Explosions shatter
    glass nearby. Quest items, stashes, doors, explosive barrels and
    anything with its own script never break.
    MCM -> Props and destruction; how many effects, pieces and leaks, their
    lifetime and range are on the Performance page. Not gore: kid mode
    leaves all of it alone.

  Native extensions (experimental, off by default)
    An optional engine add-on (bin\zgo_native.dll) for the xrRazom game
    executables, for what scripts can't do. It only switches on when it
    recognises the exact exe: it looks up every engine function it needs and
    compares its code byte by byte; on any other exe it stays off and says
    why in the log. Nothing to set up or bake: it finds what it needs when
    the game starts.
    First feature: broken limbs. Bodies close to an explosion get arms and
    legs bent at broken angles, and with a heavy charge a crushed chest or a
    dislocated shoulder. Only bodies, only once they have gone limp, the
    same on every co-op machine. Needs MCM -> Native extensions -> both
    switches on (on every player's computer in co-op).

CHANGES TO G.A.M.M.A. EXPLOSIONS (opinionated; MCM -> Explosions)
  G.A.M.M.A. made NPCs very hard to hurt with explosives, for two reasons:
    * armour subtracts its whole explosion protection from a blast (0.1 to
      1.6, against 3 for a hand grenade before distance falloff), so a
      grenade at someone's feet could do nothing at all;
    * "G.A.M.M.A. No NPC Friendly Fire" cancels every hit an NPC lands on a
      friendly or neutral NPC, a grenade's blast and shrapnel included, so an
      NPC's grenade hurt nobody but its target.
  This mod overrides both, on purpose:
    Realistic blast damage   a blast hit on an NPC or mutant does at least
                             what its overpressure would. From a hand grenade
                             to the nearest of chest, pelvis, head or knees:
                             0.5 m about 1.9 (a full health bar is 1), 1 m
                             about 1.0, 2 m about 0.27, 3 m about 0.1.
                             Heavier charges reach further (cube-root
                             scaling: an RPG warhead counts as 3 grenades, an
                             IED as 6, a mine as 1.5). Armour takes the edge
                             off (an exoskeleton with helmet about a third,
                             a jacket hardly anything), a wall between the
                             body and the blast cuts it to about 30%, and the
                             creature's own explosion immunity applies (story
                             characters with 0 are untouched, as are the ones
                             G.A.M.M.A.'s storyline script protects). Where
                             the engine's own number is higher, it stands.
                             Fragments are left as G.A.M.M.A. has them.
    Grenades hurt allies     explosions get past No NPC Friendly Fire;
                             bullets are still filtered and that mod still
                             patches relations, so allies caught in a blast
                             stay allies.
  So: a grenade at someone's feet kills them and takes feet or lower legs;
  at 2-3 m it wounds; heavy armour can survive what kills a man in a jacket.
  The player is not affected (G.A.M.M.A.'s own damage model still applies to
  you). Co-op: the host decides, as with everything else.

  Co-op (xrRazom)
    The host decides everything and sends compact effect lines to everyone;
    each client draws the same decals, particles, pools, drip runs and
    severed limbs. Flying limbs and gibs use a seeded fixed-step simulation,
    so they land in the same place on every machine.
    Clients forward their own bullet impacts so the host knows their ammo.
    The host also tells every client which Umbra Effects version it runs
    and what it baked. When a client differs (another version, no bake, a
    bake from a different mod list or with other options), that player gets
    one notice in English or Russian and the log says what differs; nothing
    is refused, the client just draws some things the simpler way.

BAKED MODELS (optional, recommended)
  Umbra Effects Setup rebuilds every character and mutant model your mod
  list uses so that each part that can come off (head, upper arm, forearm,
  hand, thigh, calf, foot) is its own sub-mesh, with a fitted stump cap for
  every cut, light severed-limb models, wound sites and body gibs (the
  pieces a blast tears out of a body, cut from that body's own model). The
  game drops a sub-mesh once its bones are hidden, ragdoll or not, so with
  baked models limbs come off corpses too, and blasts that arrive after
  death still take parts.
  Start it from the Umbra Gore & Effects folder (close the game first):
    Windows                      tools\zgo_setup\Umbra Effects Setup.exe
    Linux (MO2 under Proton)     tools/zgo_setup/zgo-setup.sh, or
                                 Umbra Effects Setup.exe with Wine/Proton
    any system with Python 3, numpy and tkinter
                                 python3 tools/zgo_setup/zgo_setup.py
  It finds MO2, your profile and the game by itself (you can change them),
  shows how many models come from which mod and how much space the bake will
  take, and bakes with a progress bar (Cancel leaves everything as it was).
  The bake is about 7.2 GB and about 3 minutes for G.A.M.M.A.: 3 GB of
  models, 3.2 GB of severed-limb models ("Limb pieces"; untick to leave them
  out), 650 MB of body gibs ("Body gibs"; without them explosions throw
  meat models) and 250 MB of stump caps. "Breakable props" also cuts barrels,
  crates and stools for "Objects break apart", and "Kid mode for particles"
  fits Umbra Effects' particle shaders to your mod list (see SETTINGS, Kid
  mode). The experimental parts stay off unless you tick them.
  Everything is written into this mod's own folder and listed in
  zgo_bake_report.json; "Remove bake" deletes exactly those files.
  Bake again when you add, remove or update a mod with character models:
  "Check if my bake is up to date" tells you whether you need to, and the
  game tells you too when a save loads (MCM -> Baked models). In MO2's left
  pane keep Umbra Gore & Effects BELOW every mod that ships character models
  (lower in the list wins), or the game shows their unbaked models;
  Umbra Effects Setup names such mods. MCM -> Dismemberment -> Use baked
  models turns the bake off without deleting it.
  Co-op: every player bakes for their own mod list; a player without a bake
  just sees fewer cuts on corpses (Umbra Effects tells them so when they
  join).
  Cost: about 4.5 times as many sub-meshes per NPC (draw calls; roughly 15
  extra per stalker), and distant NPCs lose the models' built-in level of
  detail. In testing there was no noticeable FPS loss in a crowded base.
  With a bake from version 1.7 three experimental ways of drawing a cut
  can be tried on the Dismemberment page (each player's own, all off by
  default; save first, and run probe 1 on the Diagnostics page before the
  first one):
    Cut with the off shader   a part is switched off by Umbra Effects'
                              own shader instead of hiding its bones: it
                              goes at once, before the body has fallen,
                              and the joint above it never pinches
    Stump cap shape           the bake's cap for that cut (flesh and a bone
                              stub shaped like the wound) instead of a meat
                              disk; or the caps inside the model (bake with
                              --experimental-caps, needs the off shader)
    Light severed limbs       a flying limb is the bake's piece (only the
                              part that came off, with a closed end)
  Bodies whose model another mod replaced, or a bake from before 1.7, are
  drawn the old way.
  Without a window: Umbra Effects Setup --check / --bake / --remove (see
  tools/zgo_setup/README.md). The baker also runs on its own:
  python3 tools/zgo_baker/bake.py (needs Python 3 with numpy; "--no-pieces"
  leaves the limb pieces out, "--remove" deletes the bake).

SETTINGS
  Everything is in MCM -> Umbra Gore & Effects; hover over an option for what
  it does. Pages:
    General         on/off, kid mode (and hiding particles already flying,
                    experimental), NPC-vs-NPC blood, explosion log, debug log
    Performance     a quality preset and the sliders it sets (see below),
                    including world impacts, props, bodies with wound
                    craters, wounds kept per body, wound updates per second
    Blood           amount, wounds on bodies, blood on bystanders, trails,
                    drip runs, death pools and their size
    Particles       on/off, intensity, arterial spurts, armour feedback
    Dismemberment   heads, limbs, mutants, shooting bodies, chance, severed
                    limbs, gibs, stump caps and their shape, full gibbing,
                    baked models, cutting with the off shader, light
                    severed limbs
    Wounds          progressive wounds on/off, how fast they deepen, marks,
                    chunks, destroyed parts coming off; wound craters
                    (experimental, each player's own)
    Baked models    the bake check when a game loads, its reminder, and a
                    button to check the bake now
    Explosions      the G.A.M.M.A. overrides (realistic blast damage and its
                    strength, grenades hurting allies)
    World impacts   bullet marks, damage building up, mark size, hits on
                    objects, NPC gunfire, craters, rubble (experimental),
                    deep marks (experimental, your own)
    Props and destruction
                    hit effects, pushes, blasts, leaks, bursting crates,
                    lamps, objects breaking apart and how tough they are,
                    melee, glass, sounds
    Native extensions  (experimental) loading the engine add-on, its bone
                    hooks, broken limbs from explosions and their strength,
                    a status report for the log
    Diagnostics     (shown while General -> Debug log is ticked) smoke tests,
                    see below

  Quality presets (Performance page): Potato, Low, Medium, High (default)
  and Ultra set blood lifetime, streams per hit, spreading wound stains,
  particle effects per second and at once, severed parts at once and how
  long and how far they stay, the detail distance for NPC fights, explosion
  victims per frame and jobs per frame. Pick one, adjust any slider, Accept.

  Kid mode (General page): one tick and gore is gone from this computer at
  once: blood on walls, floors and bodies (the game's own included), blood
  sprays, pools, severed parts, gibs and stump caps, including what is
  already there; bodies cut up with baked models get their parts back.
  Explosions, sparks, dust and debris stay, and nothing about how the game
  plays changes. Untick it and the gore comes back (cuts included). In
  co-op it only changes your screen; your partners still see everything.
  Kid mode: hide particles already flying (experimental, off by default;
  shown when Kid mode is ticked). Kid mode stops new blood effects at once,
  but blood droplets already in the air finish their flight, and a few
  effects other mods play themselves (knife hits, anomalies tearing a body)
  still show blood. Tick this to hide those too: the game switches their
  particle shader off on your screen. Needs DirectX 10 or 11 and the xrRazom
  game exe; it has not been tested in game yet. Sparks, dust, smoke and
  armour hits always stay visible. The effects other mods play are only
  covered after Umbra Effects Setup's "Kid mode for particles" step.
  If anything about particles looks wrong after installing Umbra Effects,
  press "Undo..." next to "Kid mode for particles" in Umbra Effects Setup:
  it undoes Umbra Effects' particle shader change completely, and "Apply
  now" puts it back (close the game first; only files in this mod's folder
  change). Without the window:
      python3 tools/zgo_kidfx/kidfx_pe.py revert   (and ... apply)

  Diagnostics (shown while General -> Debug log is ticked): smoke tests
  for the engine features later versions of this mod build on. Each
  button runs one probe when you close the menu; it writes PASS, FAIL or
  MANUAL (judge it by eye) to the log and to appdata\zgo_probe_report.txt,
  says on screen what to look for, and puts back everything it changed.
  After a probe you judge by eye, press "looked right" or "looked wrong";
  send the report file with a bug report.
    Run all safe probes   baked models in use, FFI, the kid mode shader
                          lane, co-op comparison (changes nothing; blood
                          hides for a few seconds)
    5 Save and reload     press, save, load that save, wait 8 seconds:
                          bodies with parts cut off must come back the same
    6 Co-op               the host compares what every player sees of the
                          bodies nearby (a client's button asks the host)
    Experimental probes (tick "Allow the experimental probes", Accept,
    reopen; save first: if a shader fails to compile the game closes):
    1 Off shader, 2 Pass-through shader, 3 Digit textures (Umbra Effects
    shaders on NPCs for a few seconds), 7 Props (single player: a loose
    object's model is swapped and back).

  Co-op: the Blood, Particles, Dismemberment and Explosions pages (and NPC-
  vs-NPC blood) change what happens in the world, so the host's values
  apply to everyone; xrRazom shows them on clients and locks them. The
  Wounds, World impacts and Props and destruction pages are the host's too,
  except the options marked "your own". General (apart from that),
  Performance, Baked models, Native extensions and Diagnostics belong to
  each player, as do "Use baked models" and the experimental ways of
  drawing a cut.

LIMITS
  * Kid mode stops new blood at once, but particles already in the air
    finish their flight unless "hide particles already flying"
    (experimental) is ticked. A body cut up without baked models stays cut
    while kid mode is on (its ragdoll was built without the parts), and one
    killed during kid mode stays whole afterwards.
  * Ragdolls: once a body is a ragdoll the engine's physics rewrites the
    position of every bone that has a physics part (pelvis, spine, head,
    upper arms, forearms, hands, thighs, calves, feet) every frame, so
    hiding one does nothing. A part removed before the ragdoll is built is
    gone for good (saved games keep it that way). So limbs come off at the
    moment of death, not afterwards, and this mod skips a cut it can't show
    rather than throwing a limb off a body that still has it. Baked models
    (see BAKED MODELS) lift this: there a part is hidden once the ragdoll
    exists (hidden earlier, the joint above it would pinch), and for the
    instant of a save the cut parts are shown so the saved ragdoll loads
    back whole; the cuts are re-applied from this mod's save data.
    With "Cut with the off shader" (experimental) a baked part is switched
    off by a shader at once, and its bones are hidden only once the ragdoll
    exists, so the joint never pinches.
  * Wound craters are experimental (off by default): they need models
    baked with --experimental-damage (much larger), the DirectX 10/11
    renderer, and up to four craters per body part are drawn. Without them
    wounds still deepen, throw chunks and tear limbs off bodies, shown with
    wound marks. Wounds need the wound sites of a 1.7 bake; without baked
    models bodies get the usual entry and exit marks only.
  * Severed limbs are the victim's own model with everything but the limb
    collapsed into the stump (or, with "Light severed limbs" and a 1.7
    bake, the bake's piece of that limb), as level script attachments,
    moved by this mod's own little physics (the engine gives attachments no
    physics). They collide with the level, not with other objects, and are
    not saved: after loading, bodies stay dismembered but the loose pieces
    are gone.
  * Blood can't drip in real time on surfaces; drip runs are pre-made
    shapes revealed over time by the shader.
  * Body gibs need a bake from 1.7.1 or newer; without one, and for "Meat
    models" in MCM, gibs and stump caps use meat meshes from another mod
    (GAMMA has them). Body gibs show the body's skin and clothes but leave
    no hole where they came from.
  * World impact marks are decals: walls never open, and marks are not
    kept in saves. The game's own marks around explosions
    ([explosion_marks]) are made a little larger and get scorch textures
    from this mod; they don't follow the MCM options.
  * Deep impact marks (experimental) need the effects_wallmark.s file
    shipped with this mod; another mod that replaces that file turns them
    back into ordinary marks.
  * Broken objects are gone for good (also after loading a save); their
    pieces, leaks and puddles are not saved.
  * Pieces of broken objects are visual only: they don't block bullets,
    can't be picked up and don't push other objects.
  * Window panes are part of the level and never break.
  * The "Breakable props" pieces are made from your own game files and
    are not in the download. In co-op, a player without them sees the
    game's own parts instead.
  * Experimental: "Game breaks crates and stools itself" (in Umbra Effects
    Setup) replaces those crate and stool models with copies that the
    game breaks on its own. Untested in co-op; leave it off there.
  * Native extensions are experimental and off by default. They only work
    on the xrRazom executables they recognise (all eight of xrRazom 1.4
    and of xrRazom 1.5); after an xrRazom update they may switch themselves
    off until the mod is updated. Broken limbs are a visual change of the
    body's bones: the ragdoll's physics and collision stay as they were. In
    co-op a native feature only runs when every player has it switched on
    and working.
  * The Diagnostics probes need something near you (NPCs, bodies, cut
    bodies, a small loose object); they say so when there is none. The
    probes you judge by eye can only tell you what to look for.
  * Co-op needs every player on 1.7 or newer: older versions use another
    sync protocol and the two simply don't see each other's effects (the
    log says so).

CHANGES
  1.8.0  New name: Zone Gore Overhaul (ZGO) is now Umbra Gore & Effects,
         Umbra Effects for short, and ZGO Setup is now Umbra Effects Setup.
         Nothing else changed: same options (your MCM settings carry
         over), same bake, same co-op protocol (1.7 and 1.8 players still
         see each other's effects; the host's notice says the versions
         differ). MO2 installs it as a new mod: disable or remove the old
         "Zone Gore Overhaul" and run Umbra Effects Setup again (the old
         bake stays in the old folder).
  1.7.1  Body gibs: explosions and head bursts throw pieces torn out of the
         body itself (its clothes, skin or fur outside, raw flesh inside),
         each from the spot it came from, nearest the blast first, instead
         of G.A.M.M.A.'s mutant meat items. Umbra Effects Setup cuts them
         from every model (about 11 per body, 650 MB); run it again after
         updating.
         MCM -> Dismemberment -> Gib look switches back to meat models.
         Co-op: every machine throws the same pieces.
         Fixes from in-game testing: metal sparks were metres long (now
         short streaks), prop sparks were 10-20 cm (now 2-4.5 cm), crater
         smoke flickered through its frames (now still puffs) and dust
         loops played up to three times per puff; grenades no longer throw
         gibs or chunks out of someone they didn't kill.
  1.7.0  ZGO Setup, now Umbra Effects Setup (tools/zgo_setup): a window for
         Windows and Linux that bakes the models for your mod list, shows
         what and how much, checks whether the bake is still up to date and
         names the mod that changed, and removes it. The game checks the
         bake when a save loads and tells you when to run it (MCM -> Baked
         models). The baker no longer needs LuaJIT.
         Baker: fitted stump caps (the cut surface of each body, flesh and
         bone, made for every model and cut, with the mod's own stump
         texture), lighter severed-limb models with a closed end, and wound
         sites for every body; bake.py is now a library for the setup tool,
         with progress and cancel. Default baked models are unchanged;
         experimental in-model caps and damage meshes are off.
         Progressive wounds on baked bodies: bruise, open wound, crater,
         bone, destroyed; chunks fly from deep wounds, destroyed parts come
         off dead bodies. Experimental wound craters in the body itself.
         Experimental, off by default: cuts drawn with the mod's own off
         shader (no pinched joints, no waiting for the ragdoll), stump caps
         fitted to the cut from the bake, caps inside the model, light
         severed limbs from the bake's pieces. Both thighs now keep their
         stump caps. Co-op: bodies resync with one line per body.
         World impacts: calibre-sized bullet marks with dust, chips and
         sparks per material, damage that builds up per spot (chip ->
         crack -> gouge -> breach), explosion craters with fragment pocks,
         dust ring, hanging smoke and ceiling grit indoors; optional
         rubble and clods (experimental) and parallax "deep" marks
         (experimental). Host-decided in co-op.
         Objects: material hit effects, harder pushes and blast throws,
         leaking barrels and canisters with puddles, shattering and
         flickering lamps, bursts on the game's breakables; small crates,
         chairs, stools, bottles and jars break apart under fire, knife
         and explosions, barrels and cans too after Umbra Effects Setup's
         "Breakable props" step. Host-decided in co-op, the pieces land
         in the same places for everyone.
         Kid mode can also hide blood particles already flying
         (experimental; MCM -> General).
         Native extensions (experimental, off by default): an optional
         engine add-on that verifies the game executable before it does
         anything; first feature: broken limbs and crushed chests on bodies
         near explosions (same on every co-op machine; kid mode removes them).
         Diagnostics page (with Debug log on): nine engine probes for
         bug reports, written to appdata\zgo_probe_report.txt.
         Co-op: sync protocol 3 (every player needs 1.7). The host tells
         each client its version and bakes; a client that differs gets one
         notice and play goes on.
  1.6.0  Settings rework: every option explained (English and Russian) and
         grouped by concern; new Performance page with quality presets
         (Potato, Low, Medium, High, Ultra) and new sliders for things that
         were fixed before (particle effects at once, spreading wound
         stains, severed parts' lifetime and removal distance, detail
         distance, explosion victims per frame). Blood lifetime and streams
         per hit moved there (they start from the preset again).
         Kid mode: hides all gore at once and brings it back when switched
         off; per machine in co-op.
         Co-op: xrRazom now knows which settings the host decides (shown
         and locked on clients); clients draw the host's particle effects
         within their own performance limits; a client with the mod
         switched off ignores the host's effects.
  1.5.0  Explosions, an opinionated patch over G.A.M.M.A. (see CHANGES TO
         G.A.M.M.A. EXPLOSIONS): blast damage follows overpressure, so a
         grenade at someone's feet kills them through G.A.M.M.A. armour;
         explosions get past No NPC Friendly Fire. Dismemberment from
         blasts goes by each part's distance to the charge: feet and lower
         legs from a grenade at the feet, whole-body gibs only from direct
         RPG hits and IEDs underfoot (not grenades, launcher rounds or
         mines). New MCM page Explosions.
         Baked models now go into this mod's own folder (no separate MO2
         mod); bake.py --remove deletes them; MCM switch to turn them off.
         The explosion log shows the overpressure share and fragment hits.
  1.4.1  Log fix: console commands from other mods (e.g. Laser Settings
         writing shader_param_6) no longer show up in engine warnings as
         coming from zgo_main.script.
  1.4.0  Mesh baker (tools/zgo_baker) and support for its baked models:
         cuts on corpses and late blast cuts on every body with a baked
         model, no pinched joints (cuts wait for the ragdoll), saved
         corpses keep their pose and cuts. Without baked models nothing
         changes from 1.3.0.
  1.3.0  Dismemberment that matches what you see: the engine keeps a
         ragdoll's limbs on screen even when they are hidden (see LIMITS).
         Cuts it can't show are no longer made, so no more whole limbs
         flying off bodies that keep them, no limb separated at the wrong
         joint (only the fingers / jaw collapsed), no doubled limbs.
         Explosions decide what comes off on the killing hit itself,
         before the ragdoll exists, instead of up to 1.5 s later; gibbing
         reaches further (about 1.4 m for an F1, heavier charges further)
         and close blasts take more; a gib still bursts meat and blood
         when nothing can come off. NPC explosives near you dismember too.
         Arteries in a limb a shot takes off keep pumping from the stump.
         New explosion log line (MCM: General -> Log explosions).
  1.2.0  Explosions reworked: fragments and blast collected per explosive and
         resolved per body; blast blood no longer starts at the feet (the
         engine reports blasts on the skeleton root); no sparks or exit
         spray from the blast wave; grenades into corpses dismember and gib;
         parts nearest the blast come off and fly away from it; gib by real
         distance to the explosion; NPC grenades no longer dismember.
         Bleeding trails: "standing still" judged by walking speed, so slow
         walkers leave drops instead of pools.
         Stump caps fixed: they sat on the parent bone's origin (the
         shoulder for a lost forearm, the hip for a lost calf), mostly
         buried in the body. Now on the cut itself, the meat disk faces
         along the limb so it covers the hole, sized per joint (thigh 17 cm,
         neck / knee 12, shoulder 11, elbow 8.5, wrist 6.5).
         Fixes from a code review against the engine source:
         - decal names are kept alive for the engine (it holds the raw
           string; a recycled one could draw the wrong decal);
         - effects play to the end (a full gib no longer cuts off the
           previous body's blood);
         - a late blast wave (cluttered areas: 3 objects a frame) no longer
           resolves a body twice; bodies inside the radius wait for it;
         - every stump gets its cap back after a load, not just the first;
           a cap or spurt is removed when the bone above it is cut off too;
         - a released body's id given to a new NPC no longer makes it
           spawn missing its head;
         - flying pieces no longer hold the corpse object (possible crash
           when the corpse is cleaned up mid-flight);
         - boar, pseudodog, burer, giant and chimera heads count as heads;
         - explosions: blood traces cheaper, bodies resolved two a frame,
           pieces thrown outward instead of up, fewer extra gibs in a gib;
           debris at rest is removed before pieces still in the air.
         Co-op: sync protocol 2. Every machine needs the same version; a
         peer on an older one is ignored with a note in the log instead of
         replaying effects this machine may not have (an engine crash).
  1.1.0  Severed limbs now visible (they were spawned at the wrong place);
         flying limbs and gibs physically simulated and identical in co-op.
         Full gibbing for overkill explosions.
         Distance-aware splatter: thick marks only close to the wound.
         Animated wall drip runs.
         Bleeding trails follow the engine's bleeding value and use sparse
         drip textures; small pools under heavy bleeders standing still;
         wound stains spread on the living.
         New droplet particles: arterial jets, exit and back sprays,
         dribbles, gushes, falling drips.
         Arteries: neck, thigh, collarbone, upper arm, calf, forearm; also
         on kills. Jets follow the wound and paint where they land.
         Exoskeleton and helmet sparks on every hit, not only stopped rounds.
  1.0.0  First release.
