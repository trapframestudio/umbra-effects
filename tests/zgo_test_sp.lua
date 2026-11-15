-- Single-player behaviour tests for Zone Gore Overhaul (run: luajit zgo_test_sp.lua)
-- S: this folder (scratch files are written here); the mod scripts are in ../gamedata/scripts
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
arg = { S .. "/../gamedata/scripts", "sp" }
NPC_YAW = 0.6     -- rotated NPCs: catches local/world transform mix-ups
dofile(S .. "/zgo_harness.lua")
math.randomseed(7)

local function section(t) print(("\n== %s"):format(t)) end
local function cats(list) return count_by_cat(list) end
local function tally(list, set)
	local n = 0
	for _, p in ipairs(list) do
		local k = p.sec:match("^zgo_fx_(%a+)_") or p.sec:match("^zgo_(p_%a+)_") or p.sec
		if set[k] then n = n + 1 end
	end
	return n
end
local THICK = { heavy = true, splash = true, gore = true, p_splash = true, buckshot = true }
local SPARSE = { fine = true, mist = true, spatter = true, dripspot = true, dribble = true, p_drip = true }
local function fx_count(prefix)
	local n = 0
	for _, f in ipairs(FX) do if f:sub(1, #prefix) == prefix then n = n + 1 end end
	return n
end
LOG = {}

section("5.45 body shots, NPC 0.8 m from a wall (x40)")
local npc = NEW_NPC(10, "stalker", VV(0, 0, -1.2))
PLACED, BODY, FX = {}, {}, {}
for i = 1, 40 do shoot(npc, i % 2 == 0 and "bip01_spine1" or "bip01_spine2", "ammo_5_45x39_fmj") end
local near_thick, near_sparse = tally(PLACED, THICK), tally(PLACED, SPARSE)
print(("decals %d (%.1f per hit), body %d, fx %d"):format(#PLACED, #PLACED / 40, #BODY, #FX))
print("  " .. cats(PLACED))
assert(#PLACED > 40, "too few decals")

section("same rounds, NPC 4.5 m from the wall (x40)")
local far = NEW_NPC(13, "stalker", VV(0.5, 0, 2.5))
PLACED = {}
for i = 1, 40 do shoot(far, "bip01_spine1", "ammo_5_45x39_fmj") end
local far_wall = {}
for _, p in ipairs(PLACED) do if p.z < -1.95 then far_wall[#far_wall + 1] = p end end
local far_thick, far_sparse = tally(far_wall, THICK), tally(far_wall, SPARSE)
print("  wall decals: " .. cats(far_wall))
print(("  near wall: thick %d sparse %d | far wall: thick %d sparse %d"):format(near_thick, near_sparse, far_thick, far_sparse))
assert(far_thick <= 1 and far_sparse > far_thick, "far walls should get spray, not splotches")
assert(near_thick > near_sparse * 0.3, "near walls should get thick splatter")

section("9x18 pistol body shots (x40)")
local npc2 = NEW_NPC(11, "stalker", VV(1, 0, -1.2))
PLACED, BODY, FX = {}, {}, {}
for i = 1, 40 do shoot(npc2, "bip01_spine1", "ammo_9x18_fmj", { speed = 300 }) end
print(("decals %d (%.1f per hit)"):format(#PLACED, #PLACED / 40))
print("  " .. cats(PLACED))

section("12x70 buckshot (x40)")
local npc3 = NEW_NPC(12, "stalker", VV(-1, 0, -1.2))
PLACED, BODY, FX = {}, {}, {}
for i = 1, 40 do shoot(npc3, "bip01_spine2", "ammo_12x70_buck", { speed = 380 }) end
print(("decals %d (%.1f per hit)"):format(#PLACED, #PLACED / 40))
print("  " .. cats(PLACED))

section("Drip runs grow, then settle")
PLACED = {}
run(14000)
local c = cats(PLACED)
print("  after 14 s: " .. c)
assert(c:find("drip=%d"), "drip runs never settled")

section("Exoskeleton and helmet hits show sparks")
local exo = NEW_NPC(14, "stalker", VV(-0.5, 0, -1.2))
exo._visual = "actors\\stalker_neutral\\stalker_neutral_exo"
FX = {}
for i = 1, 10 do shoot(exo, "bip01_spine1", "ammo_5_45x39_fmj") end
for i = 1, 4 do shoot(exo, "bip01_head", "ammo_5_45x39_fmj") end
local sparks = fx_count("srbd\\hit\\body_impact_sparks")
print(("  sparks %d, armour %d (14 hits)"):format(sparks, fx_count("srbd\\hit\\body_impact_armor")))
assert(sparks >= 10, "exo hits must always spark")

section("Neck shot on the living: pulsing jets that land, following the wound")
local a = NEW_NPC(700, "stalker", VV(2, 0, -1.2))
FX, PLACED = {}, {}
shoot(a, "bip01_neck", "ammo_5_45x39_fmj")
print("  sequences running: " .. zgo_fx.sequence_count())
run(1500, 33)
a._pos = VV(2.6, 0, 0.3)
a._yaw = 2.0
FXDIR = {}
run(1500, 33)
local neck = a:bone_position("bip01_neck")
local nj, worst = 0, 0
for _, e in ipairs(FXDIR) do
	if e.name:find("zgo\\jet_", 1, true) then
		nj = nj + 1
		worst = math.max(worst, e.pos:distance_to(neck))
	end
end
print(("  after moving: %d jets, furthest %.2f m from the neck"):format(nj, worst))
assert(nj >= 1 and worst < 0.25, "spurt should follow the wound")
run(4000, 33)
local jets = fx_count("zgo\\jet_")
local arterial = tally(PLACED, { arterial = true, castoff = true, dribble = true })
print(("  jets %d, dribbles %d, arterial decals %d in 7 s"):format(jets, fx_count("zgo\\dribble"), arterial))
assert(jets >= 6, "neck should pulse")
assert(arterial >= 2, "jets should paint where they land")

section("Neck kill: the dying heart still pumps a few times")
local k = NEW_NPC(701, "stalker", VV(-2, 0, -1.2))
FX = {}
shoot(k, "bip01_neck", "ammo_5_45x39_fmj", { kill = true })
run(4000, 33)
print(("  jets after a killing neck shot: %d"):format(fx_count("zgo\\jet_")))
assert(fx_count("zgo\\jet_") >= 2)

section("Thigh hits sometimes open the femoral artery (x20 NPCs)")
local opened = 0
for n = 1, 20 do
	local v = NEW_NPC(720 + n, "stalker", VV(0, 0, -1.2))
	local s0 = zgo_fx.sequence_count()
	shoot(v, "bip01_l_thigh", "ammo_5_45x39_fmj")
	if zgo_fx.sequence_count() > s0 then opened = opened + 1 end
end
print(("  femoral opened %d/20"):format(opened))
assert(opened >= 3 and opened <= 16)
run(10000, 50)

section("7.62x54 kill headshots: decapitation / head bursts (x100 NPCs)")
local heads, bursts, whole = 0, 0, 0
LOG = {}
for n = 1, 100 do
	local v = NEW_NPC(100 + n, "stalker", VV(0, 0, -1.2))
	shoot(v, "bip01_head", "ammo_7.62x54_7h1", { kill = true })
	if v._hidden["bip01_head"] then heads = heads + 1 end
end
for _, l in ipairs(LOG) do if l:find("severed bip01_head", 1, true) then if l:find("burst") then bursts = bursts + 1 else whole = whole + 1 end end end
print(("heads off %d/100 (burst %d, whole %d); debris now %d"):format(heads, bursts, whole, zgo_debris.count()))
assert(heads >= 10 and heads <= 60, "head chance looks wrong")

section("5.45 kill to the forearm: never severs on one hit")
local cnt = 0
for n = 1, 40 do
	local v = NEW_NPC(200 + n, "stalker", VV(0, 0, -1.2))
	shoot(v, "bip01_l_forearm", "ammo_5_45x39_fmj", { kill = true })
	if v._hidden["bip01_l_forearm"] then cnt = cnt + 1 end
end
print(("forearm off %d/40"):format(cnt))
assert(cnt == 0)

section("Corpse: keep shooting the leg with 5.45")
local c = NEW_NPC(300, "stalker", VV(0, 0, -1.2))
shoot(c, "bip01_spine1", "ammo_5_45x39_fmj", { kill = true })
local limbs0 = 0
for _, it in ipairs(zgo_debris.list()) do if it.kind == "limb" then limbs0 = limbs0 + 1 end end
local shots = 0
while not c._hidden["bip01_l_calf"] and shots < 12 do
	shots = shots + 1
	T_NOW = T_NOW + 400
	shoot(c, "bip01_l_calf", "ammo_5_45x39_fmj")
end
local limbs1 = 0
for _, it in ipairs(zgo_debris.list()) do if it.kind == "limb" then limbs1 = limbs1 + 1 end end
print(("calf came off after %d corpse shots; hidden: thigh=%s calf=%s; limbs flying %d"):format(shots,
	tostring(c._hidden["bip01_l_thigh"]), tostring(c._hidden["bip01_l_calf"]), limbs1 - limbs0))
if BAKED then
	assert(c._hidden["bip01_l_calf"] and not c._hidden["bip01_l_thigh"])
else
	-- an un-baked ragdoll's calf can't be hidden: no cut, and no calf flying off a whole leg
	assert(not c._hidden["bip01_l_calf"] and limbs1 == limbs0, "cut a ragdoll part that stays on screen")
end
CHECK_CUTS("corpse leg")

section("Severed limb: spawns where the arm was, flies, lands, bleeds")
zgo_debris.reset()
local level_count = 0
for _ in pairs(LEVEL_ATT) do level_count = level_count + 1 end
assert(level_count == 0, "reset must remove level attachments (" .. level_count .. " left)")
local old = zgo_util.setting
zgo_util.setting = function(k) if k == "dismember/chance" then return 50 end return old(k) end
local v = NEW_NPC(400, "stalker", VV(1.2, 0, 1.5))
v._yaw = 1.1
local true_hand = v:bone_position("bip01_r_hand")
local true_fore = v:bone_position("bip01_r_forearm")
PLACED = {}
shoot(v, "bip01_r_forearm", "ammo_12x76_zhekan", { kill = true, dir = VV(-1, 0, 0), settle = false })
-- (a baked body loses the arm once its ragdoll exists: measure on that frame)
local function limb_att() for name, x in pairs(LEVEL_ATT) do if name:find("limb") then return x end end end
local waited = 0
while not limb_att() and waited < 6 do frame() waited = waited + 1 end
zgo_util.setting = old
assert(v._hidden["bip01_r_forearm"], "forearm not severed")
-- the stump cap is drawn at XFORM * parent bone * offset: it must sit on the elbow
local cap
for _, att in pairs(v._att) do if att.parent_bone == "bip01_r_upperarm" then cap = att end end
assert(cap, "no stump cap on the upper arm")
local um = v:bone_transform("bip01_r_upperarm")
local o = cap.pos
local capw = VV(um.c.x + um.i.x * o.x + um.j.x * o.y + um.k.x * o.z, um.c.y + um.i.y * o.x + um.j.y * o.y + um.k.y * o.z,
	um.c.z + um.i.z * o.x + um.j.z * o.y + um.k.z * o.z)
print(("stump cap %.3f m from the elbow (shoulder is %.3f m away)"):format(capw:distance_to(true_fore), capw:distance_to(um.c)))
assert(capw:distance_to(true_fore) < 0.01, "stump cap must sit on the cut")
-- engine setHPB (xrCore/_matrix.h): mesh +y goes to j = (sp*sc + cs, cp*cb, ss - sp*cc)
local h, pp, bb = math.rad(cap.rot.x), math.rad(cap.rot.y), math.rad(cap.rot.z)
local sh, ch, sp, cp, sb, cb = math.sin(h), math.cos(h), math.sin(pp), math.cos(pp), math.sin(bb), math.cos(bb)
local jl = VV(sp * sh * cb + ch * sb, cp * cb, sh * sb - sp * ch * cb)
local jw = VV(um.i.x * jl.x + um.j.x * jl.y + um.k.x * jl.z, um.i.y * jl.x + um.j.y * jl.y + um.k.y * jl.z,
	um.i.z * jl.x + um.j.z * jl.y + um.k.z * jl.z)
local ax = VV(true_fore.x - um.c.x, true_fore.y - um.c.y, true_fore.z - um.c.z)
local al = ax:distance_to(VV(0, 0, 0))
local align = math.abs((jw.x * ax.x + jw.y * ax.y + jw.z * ax.z) / al)
print(("stump cap faces along the arm: |cos| = %.3f, scale %.2f (%.1f cm disk)"):format(align, cap.scale, cap.scale * 21))
assert(align > 0.999, "the meat disk must cover the cut, not stick out sideways")
assert(math.abs(cap.scale * 0.21 - 0.085) < 0.002, "elbow stump ~8.5 cm")
local att
for name, x in pairs(LEVEL_ATT) do if name:find("limb") then att = x end end
assert(att, "no limb level attachment")
local f_id, h_id = BONE_ID["bip01_r_forearm"], BONE_ID["bip01_r_hand"]
local p0f, p0h = ATT_WORLD(att, f_id), ATT_WORLD(att, h_id)
local of = VV(p0f.x - true_fore.x, p0f.y - true_fore.y, p0f.z - true_fore.z)
local oh = VV(p0h.x - true_hand.x, p0h.y - true_hand.y, p0h.z - true_hand.z)
local zero = VV(0, 0, 0)
print(("first frame: forearm moved %.3f m, hand %.3f m (apart %.3f)"):format(of:distance_to(zero), oh:distance_to(zero), of:distance_to(oh)))
assert(of:distance_to(zero) < 0.12 and of:distance_to(oh) < 0.05, "limb must start where the arm was")
local L0 = p0f:distance_to(p0h)
local fx0 = #FX
for t = 1, 8 do
	run(500)
	local pf, pfm = ATT_WORLD(att, f_id)
	local ph = ATT_WORLD(att, h_id)
	local L = pf:distance_to(ph)
	local det = pfm.i.x * (pfm.j.y * pfm.k.z - pfm.j.z * pfm.k.y) - pfm.i.y * (pfm.j.x * pfm.k.z - pfm.j.z * pfm.k.x) + pfm.i.z * (pfm.j.x * pfm.k.y - pfm.j.y * pfm.k.x)
	if t % 2 == 0 then print(("t=%.1f forearm %.2f %.2f %.2f  hand %.2f %.2f %.2f  len %.3f det %.3f"):format(t * 0.5, pf.x, pf.y, pf.z, ph.x, ph.y, ph.z, L, det)) end
	assert(math.abs(L - L0) < 0.02, "limb not rigid")
	assert(math.abs(det - 1) < 0.01, "rotation not orthonormal")
	assert(pf.y > -0.05 and ph.y > -0.05, "limb fell through the floor")
end
local collapse = att.cbs[0]()
assert(collapse.i.x < 0.01, "root not collapsed")
assert(att.cbs[BONE_ID["bip01_r_upperarm"]] == nil, "upperarm should not be part of the severed chain")
local torso = ATT_WORLD(att, BONE_ID["bip01_spine1"])
assert(torso:distance_to(att.pos) < 0.01, "everything outside the limb collapses into the stump")
print(("limb drips %d, decals under it: %s"):format(fx_count("zgo\\drip_fall"), cats(PLACED)))
assert(cats(PLACED):find("pool_grow"), "a resting limb should leave a small pool")

section("Explosion of unknown origin: no gib, at most one limb, never the head")
LOG = {}
local e = NEW_NPC(801, "stalker", VV(0, 0, -1.2))
PLACED, FX = {}, {}
shoot(e, "bip01_spine1", nil, { htype = hit.explosion, kill = true, power = 2.5 })
run(200)   -- explosions are collected per body for a moment
local off = {}
for b, h in pairs(e._hidden) do if h then off[#off + 1] = b end end
table.sort(off)
print("removed: " .. table.concat(off, ",") .. "  debris " .. zgo_debris.count())
local gibbed = false
for _, l in ipairs(LOG) do if l:find("gibbed") then gibbed = true end end
-- only RPG hits and IEDs underfoot take a whole body apart (zgo_test_blast)
assert(not gibbed and not e._hidden.bip01_head, "an unknown explosion never gibs or takes the head")
local limbs = 0
for _, side in ipairs({ "l", "r" }) do
	for _, limb in ipairs({ { "upperarm", "forearm", "hand" }, { "thigh", "calf", "foot" } }) do
		local hit_ = false
		for _, part in ipairs(limb) do if e._hidden["bip01_" .. side .. "_" .. part] then hit_ = true end end
		if hit_ then limbs = limbs + 1 end
	end
end
assert(limbs <= 1, "at most one limb")

section("Trails follow the engine's bleeding")
-- everyone else stops bleeding so only this NPC's trail is measured
for id in pairs(OBJ) do zgo_decals.stop_bleeding(id) end
local w = NEW_NPC(600, "stalker", VV(-2, 0, 3))
shoot(w, "bip01_spine1", "ammo_9x18_fmj", { speed = 300 })
run(300, 50)            -- the hit is processed and the first bleed reading taken
w.bleeding = 0.4        -- then the wound gets worse
local function near_w(list, r)
	local out = {}
	for _, p in ipairs(list) do
		if VV(p.x, p.y, p.z):distance_to(w._pos) < r then out[#out + 1] = p end
	end
	return out
end
for i = 1, 20 do
	PLACED = {}
	w._pos = VV(-2 + i * 0.25, 0, 3)
	run(500, 50)
end
PLACED = {}
local path = {}
for i = 1, 20 do
	w._pos = VV(-2 + i * 0.25, 0, 3)
	local before = #PLACED
	run(500, 50)
	for j = before + 1, #PLACED do path[#path + 1] = PLACED[j] end
end
local walking = count_by_cat(path)
print("  10 s walking: " .. walking)
assert(walking:find("dribble") and not walking:find("trail=") and not walking:find("drops=") and not walking:find("splash"),
	"walking trails should be sparse drips")
PLACED = {}
run(12000, 50)
local standing = count_by_cat(near_w(PLACED, 1.5))
print("  12 s standing: " .. standing)
assert(standing:find("dripspot") and standing:find("pool_grow"), "standing bleeders drip and pool")
w.bleeding = 0          -- bandaged
run(2000, 50)
PLACED = {}
run(6000, 50)
local after = near_w(PLACED, 1.5)
print("  after bandaging: " .. (#after > 0 and count_by_cat(after) or "nothing"))
assert(tally(after, { dribble = true, dripspot = true, p_drip = true }) == 0, "trail must stop when bleeding stops")

section("Wounds soak outward while alive")
local s = NEW_NPC(650, "stalker", VV(2, 0, 3))
BODY = {}
shoot(s, "bip01_spine2", "ammo_5_45x39_fmj")
local b0 = #BODY
run(20000, 100)
print(("  body marks: %d at the hit, %d after 20 s"):format(b0, #BODY))
assert(#BODY >= b0 + 2)

section("Save / load re-applies dismemberment")
local m_data = SAVE_GAME()
local n = 0
for _ in pairs(m_data.zgo_severed) do n = n + 1 end
for id, st in pairs(m_data.zgo_severed) do RESPAWN(OBJ[id]) end
CB.on_level_changing()
local left = 0
for _ in pairs(LEVEL_ATT) do left = left + 1 end
assert(left == 0, "level change must remove debris")
CB.load_state(m_data)
run(100)
local restored = 0
for id, st in pairs(m_data.zgo_severed) do if OBJ[id]._hidden[st.b[1]] then restored = restored + 1 end end
print(("saved %d bodies, restored %d"):format(n, restored))
CHECK_CUTS("loaded bodies")
assert(n == restored)

section("Melee (mutant bite)")
PLACED, FX = {}, {}
local m = NEW_NPC(800, "stalker", VV(0, 0, -1.2))
for i = 1, 10 do shoot(m, "bip01_spine1", nil, { htype = hit.wound, shooter = 0 }) end
print("bites: " .. cats(PLACED) .. "  fx " .. #FX)

section("Errors in log")
local errs = 0
for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") then errs = errs + 1; print("  " .. l) end end
print("errors: " .. errs)
print(("misses (place ray found nothing): %d"):format(MISSES or 0))
assert(errs == 0)
print("\nALL SP TESTS PASSED")
