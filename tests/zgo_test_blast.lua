-- Explosion tests for Umbra Gore & Effects (run: luajit zgo_test_blast.lua [seed])
-- S: this folder (scratch files are written here); the mod scripts are in ../gamedata/scripts
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 5
arg = { S .. "/../gamedata/scripts", "sp" }
NPC_YAW = 0.4
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local old_setting = zgo_util.setting
OVR = { ["general/debug"] = true }
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return old_setting(k) end
local function sure(on) OVR["dismember/chance"] = on and 3 or nil end   -- every part in reach goes

local function section(t) print(("\n== %s"):format(t)) end
local function hidden(o) local n, t = 0, {} for b, h in pairs(o._hidden) do if h then n = n + 1 t[#t + 1] = b end end table.sort(t) return n, table.concat(t, ",") end
local function has(o, list) for _, b in ipairs(list) do if o._hidden[b] then return true end end return false end
local UPPER = { "bip01_head", "jaw_1", "bip01_l_upperarm", "bip01_r_upperarm", "bip01_l_forearm", "bip01_r_forearm", "bip01_l_hand", "bip01_r_hand", "bip01_l_thigh", "bip01_r_thigh" }
local function fx(prefix) local n = 0 for _, f in ipairs(FX) do if f:sub(1, #prefix) == prefix then n = n + 1 end end return n end
local function logs(pat) local out = {} for _, l in ipairs(LOG) do if l:find(pat) then out[#out + 1] = l end end return out end
local function settle() run(400, 16) end   -- past the collection window
local function errors()
	local n = 0
	for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") then n = n + 1 print("  ERR " .. l) end end
	return n
end
-- where decals went relative to the blast: + = the far side of the body
local function far_side(list, center, body)
	local ax, az = body.x - center.x, body.z - center.z
	local l = math.sqrt(ax * ax + az * az)
	local far, near = 0, 0
	for _, p in ipairs(list) do
		if p.y > 0.05 then  -- walls only
			local s = ((p.x - center.x) * ax + (p.z - center.z) * az) / l
			if s > l then far = far + 1 elseif s < l * 0.5 then near = near + 1 end
		end
	end
	return far, near
end

section("F1 at a living stalker's feet (player's grenade): dead, lower legs gone, no full gib")
LOG, PLACED, FX, BODY = {}, {}, {}, {}
sure(true)
local a = NEW_NPC(10, "stalker", VV(0, 0, 0))
local c1 = VV(0, 0.1, 0.5)
local fired = explode(c1, { a }, { armor = 0.05 })   -- G.A.M.M.A. armour leaves almost nothing of the blast
settle()
sure(false)
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
local n, list = hidden(a)
print(("  fragments on body %d, parts removed %d (%s), debris %d"):format(fired[10], n, list, zgo_debris.count()))
print(("  gore debris fx %d, sparks %d"):format(fx("srbd\\effects\\debris"), fx("srbd\\hit\\body_impact_sparks")))
assert(not a._alive, "a grenade at the feet kills (overpressure over G.A.M.M.A. armour)")
assert(#logs("overpressure") >= 1, "the log shows the overpressure floor")
assert(#logs("gibbed") == 0 and #logs("-> GIB") == 0, "a hand grenade never takes a whole body apart")
assert((a._hidden.bip01_l_calf or a._hidden.bip01_l_foot) and (a._hidden.bip01_r_calf or a._hidden.bip01_r_foot), "both legs, at the foot or the knee: " .. list)
assert(not has(a, UPPER), "nothing above the knees: " .. list)
assert(fx("srbd\\hit\\body_impact_sparks") == 0, "a blast wave never sparks")
-- body parts fly away from the grenade
run(3000, 16)
local away, toward = 0, 0
for _, att in pairs(LEVEL_ATT) do
	local p = att.pos
	if (p.z - c1.z) < 0 then away = away + 1 else toward = toward + 1 end
end
print(("  debris at rest: %d on the far side, %d on the grenade's side"):format(away, toward))
assert(away > toward, "parts should be thrown away from the blast")
local far, near = far_side(PLACED, c1, VV(0, 0, 0))
print(("  wall blood: %d beyond the body, %d on the grenade's side   (%d decals, body %d)"):format(far, near, #PLACED, #BODY))
-- ~12 body + ~7 blast + ~18 debris landings (pieces now reach the wall beyond) + stump jets
assert(#PLACED < 60, "one explosion should not spam decals")

section("F1 at 3 m: the stalker survives with shrapnel")
LOG, PLACED, FX, BODY = {}, {}, {}, {}
local b = NEW_NPC(11, "stalker", VV(2, 0, 0.5))
local c2 = VV(2, 0.1, 3.4)
fired = explode(c2, { b }, { armor = 0.05, frags = 400 })
settle()
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
n = hidden(b)
print(("  alive %s, fragments %d, parts removed %d, body wounds %d, fx %d"):format(tostring(b._alive), fired[11], n, #BODY, #FX))
assert(b._alive and n == 0)
assert(#BODY >= 2, "shrapnel wounds on the body")
assert(zgo_decals.stats().bleeders >= 1, "survivor bleeds")
local bl = 0
for _, f in ipairs(FX) do if f:find("srbd_hit_flesh", 1, true) then bl = bl + 1 end end
assert(bl >= 1 and bl <= 3, "a few flesh hits, not one per fragment")

section("Grenade into two corpses (the blast hit reaches corpses)")
LOG, PLACED, FX = {}, {}, {}
local k1 = NEW_NPC(20, "stalker", VV(-2, 0, 1)); k1._alive = false
local k2 = NEW_NPC(21, "stalker", VV(-2, 0, 3.4)); k2._alive = false
sure(true)
explode(VV(-2, 0.1, 1.4), { k1, k2 })
settle()
sure(false)
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
local n1, l1 = hidden(k1)
local n2, l2 = hidden(k2)
print(("  near corpse: %d parts (%s)   far corpse: %d parts (%s)"):format(n1, l1, n2, l2))
assert(#logs("gibbed") == 0, "a grenade doesn't gib a corpse")
if BAKED then
	assert(n1 >= 2 and not has(k1, UPPER), "a grenade at a corpse's feet takes its feet or lower legs: " .. l1)
	assert(n2 == 0, "the far corpse keeps everything")
else
	-- un-baked ragdolls keep arms, legs and head on screen: nothing cut
	assert(n1 == 0 and n2 == 0 and #logs("can be shown") >= 1, "cut an un-baked ragdoll")
end
assert(#logs("corpse") >= 2)
CHECK_CUTS("corpses")

section("Corpse, no blast hit from the engine: fragments alone still count")
LOG = {}
local k3 = NEW_NPC(22, "stalker", VV(2, 0, -1)); k3._alive = false
sure(true)
explode(VV(2, 0.1, -0.6), { k3 }, { no_corpse_blast = true, eid = 901 })
-- (in the radius but no blast hit = fully behind cover: resolved at MAX_AGE)
run(300, 16)
assert(hidden(k3) == 0, "waits for the blast wave of a body inside the radius")
run(1400, 16)
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
local n3 = hidden(k3)
sure(false)
print(("  parts removed %d"):format(n3))
if BAKED then assert(n3 >= 2 and not has(k3, UPPER)) else assert(n3 == 0 and #logs("can be shown") >= 1) end

section("No fragment-init reports: the explosive's own position is used")
LOG = {}
local k4 = NEW_NPC(23, "stalker", VV(-1, 0, -1)); k4._alive = false
explode(VV(-1, 0.1, -0.5), { k4 }, { no_init = true, eid = 902 })
settle()
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
assert(#logs("explosion grenade_f1 on .* m,") == 1 and not logs("explosion")[1]:find("%? m"), "centre should be known")

section("Exoskeleton at 1.6 m, survives: fragments spark, the blast does not")
LOG, FX = {}, {}
local e = NEW_NPC(30, "stalker", VV(0, 0, 3))
e._visual = "actors\\stalker_neutral\\stalker_neutral_exo"
fired = explode(VV(0, 0.1, 4.5), { e }, { armor = 0.15, eid = 903 })
settle()
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
local sp = fx("srbd\\hit\\body_impact_sparks")
print(("  fragments %d, sparks %d, flesh %d"):format(fired[30], sp, fx("srbd\\srbd_hit_flesh")))
assert(e._alive and sp >= 1 and sp <= math.min(fired[30], 3))

section("NPC's grenade near you: tears bodies apart like yours")
LOG, PLACED = {}, {}
local thrower = NEW_NPC(950, "stalker", VV(0, 0, 5.5))
local v = NEW_NPC(31, "stalker", VV(1.5, 0, 1.5))
sure(true)
explode(VV(1.5, 0.1, 2), { v }, { thrower = 950, eid = 904, armor = 0.05 })
settle()
sure(false)
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
print(("  dead %s, parts removed %d, decals %d"):format(tostring(not v._alive), hidden(v), #PLACED))
assert(not v._alive and hidden(v) >= 2 and not has(v, UPPER) and #PLACED > 0)
CHECK_CUTS("npc grenade")

section("NPC's grenade far from you: blood only")
LOG, PLACED = {}, {}
local apos = ACTOR._pos
ACTOR._pos = VV(0, 0, 80)
local v2 = NEW_NPC(32, "stalker", VV(1.5, 0, 1.5))
explode(VV(1.5, 0.1, 2), { v2 }, { thrower = 950, eid = 905, armor = 0.05 })
settle()
ACTOR._pos = apos
print(("  dead %s, parts removed %d"):format(tostring(not v2._alive), hidden(v2)))
assert(not v2._alive and hidden(v2) == 0)

section("Heavy charges: an RPG hit to the chest and an IED underfoot take the body apart")
LOG = {}
local r1 = NEW_NPC(60, "stalker", VV(-4, 0, 6))
local rc = r1:bone_position("bip01_spine1")
explode(VV(rc.x, rc.y, rc.z + 0.25), { r1 }, { sec = "wpn_rpg7_missile", eid = 910, armor = 0.05 })
settle()
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
print(("  RPG: dead %s, parts removed %d"):format(tostring(not r1._alive), hidden(r1)))
assert(not r1._alive and #logs("gibbed") == 1 and hidden(r1) >= 3, "a direct RPG hit gibs")
LOG = {}
local i1 = NEW_NPC(61, "stalker", VV(-6, 0, 6))
explode(VV(-6, 0.05, 6.2), { i1 }, { sec = "ied_new_blow", eid = 911, armor = 0.05 })
settle()
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
print(("  IED: dead %s, parts removed %d"):format(tostring(not i1._alive), hidden(i1)))
assert(not i1._alive and #logs("gibbed") == 1, "an IED underfoot gibs")
CHECK_CUTS("heavy")

section("Mine underfoot: the legs, not the body")
LOG = {}
sure(true)
local m1 = NEW_NPC(62, "stalker", VV(-4, 0, 9))
local mf = m1:bone_position("bip01_l_foot")
explode(VV(mf.x, 0.05, mf.z), { m1 }, { sec = "mine_new_blow", eid = 912, armor = 0.05, frags = 0 })
settle()
sure(false)
local nm, lm = hidden(m1)
for _, l in ipairs(logs("explosion")) do print("  " .. l) end
print(("  dead %s, parts removed %d (%s)"):format(tostring(not m1._alive), nm, lm))
assert(not m1._alive and #logs("gibbed") == 0, "a mine kills but doesn't gib")
assert((m1._hidden.bip01_l_calf or m1._hidden.bip01_l_foot) and not has(m1, UPPER), "the leg it went off under: " .. lm)

section("Armour takes the edge off; a wall takes most of it")
LOG = {}
local plain = NEW_NPC(70, "stalker", VV(8, 0, 12))
local exo = NEW_NPC(71, "stalker", VV(12, 0, 12))
exo._outfit, exo._helmet = "test_exo_outfit", "test_exo_helmet"
explode(VV(8, 0.1, 12.85), { plain }, { eid = 920, armor = 0.05 })
explode(VV(12, 0.1, 12.85), { exo }, { eid = 921, armor = 0.05 })
settle()
print(("  0.85 m from the feet: jacket %s (%s), exoskeleton %s (%s)"):format(
	plain._alive and "alive" or "dead", zgo_util.r3(plain._blast_power), exo._alive and "alive" or "dead", zgo_util.r3(exo._blast_power)))
assert(not plain._alive and exo._alive, "an exoskeleton survives what kills a jacket")
assert(exo._blast_power < plain._blast_power * 0.7 and exo._blast_power > plain._blast_power * 0.5)
LOG = {}
local open_ = NEW_NPC(72, "stalker", VV(1.6, 0, -10))
local walled = NEW_NPC(73, "stalker", VV(3.6, 0, -10))   -- beyond the wall at x = 3
explode(VV(2.5, 0.1, -10), { open_, walled }, { eid = 922, armor = 0.05 })
settle()
print(("  1 m away: in the open %s, behind a wall %s"):format(zgo_util.r3(open_._blast_power), zgo_util.r3(walled._blast_power)))
assert(walled._blast_power < open_._blast_power * 0.5, "cover blocks most of the blast")

section("Story characters other mods protect get only the engine's damage")
LOG = {}
rawset(_G, "grok_additional_storyline_npc_invincible", { ads_npcs = { test_story_npc = 1 } })
local st = NEW_NPC(74, "stalker", VV(-8, 0, -10), "test_story_npc")
explode(VV(-8, 0.1, -9.5), { st }, { eid = 923, armor = 0.05 })
settle()
rawset(_G, "grok_additional_storyline_npc_invincible", nil)
print(("  alive %s, power %s"):format(tostring(st._alive), zgo_util.r3(st._blast_power)))
assert(st._alive and #logs("overpressure") == 0)

section("Overpressure off in MCM: G.A.M.M.A.'s own numbers")
LOG = {}
OVR["explosions/overpressure"] = false
local off = NEW_NPC(75, "stalker", VV(-8, 0, -14))
explode(VV(-8, 0.1, -13.5), { off }, { eid = 924, armor = 0.05 })
settle()
OVR["explosions/overpressure"] = nil
assert(off._alive and #logs("overpressure") == 0)

section("G.A.M.M.A. No NPC Friendly Fire: explosions get through, bullets don't")
local cancelled = 0
local ff = { npc_on_before_hit = function(npc, shit, bone, flags) cancelled = cancelled + 1 shit.power = 0 flags.ret_value = false end }
rawset(_G, "grok_no_npc_friendly_fire", ff)
zgo_main.patch_friendly_fire()
assert(ff.zgo_wrapped and ff.npc_on_before_hit ~= nil)
local victim = NEW_NPC(76, "stalker", VV(10, 0, -14))
OBJ[930] = { _grenade = true, id = function() return 930 end, section = function() return "grenade_f1" end, position = function() return VV(10, 0.1, -13.5) end }
OBJ[931] = { _weapon = true, id = function() return 931 end, section = function() return "wpn_ak74" end, position = function() return VV(10, 1, -10) end }
local hb = { power = 1.2, type = hit.explosion, weapon_id = 930 }
local fb = { ret_value = true }
ff.npc_on_before_hit(victim, hb, 0, fb)
local hg = { power = 0.4, type = hit.fire_wound, weapon_id = 931 }
local fg = { ret_value = true }
ff.npc_on_before_hit(victim, hg, 3, fg)
OBJ[930], OBJ[931] = nil, nil
rawset(_G, "grok_no_npc_friendly_fire", nil)
print(("  blast: power %s kept %s   bullet: power %s kept %s   (that mod ran %d times)"):format(hb.power, tostring(fb.ret_value), hg.power, tostring(fg.ret_value), cancelled))
assert(hb.power == 1.2 and fb.ret_value == true, "the blast gets through")
assert(hg.power == 0 and fg.ret_value == false, "friendly bullets are still cancelled")
assert(cancelled == 2, "that mod still runs (relations)")

section("Gunfire still works normally afterwards")
LOG, PLACED = {}, {}
local g = NEW_NPC(40, "stalker", VV(0, 0, -1.2))
shoot(g, "bip01_spine1", "ammo_5_45x39_fmj")
print(("  decals %d"):format(#PLACED))
assert(#PLACED > 0 and #logs("explosion") == 0)

section("Errors")
local errs = errors()
print("errors: " .. errs)
assert(errs == 0)
print("\nALL BLAST TESTS PASSED")
