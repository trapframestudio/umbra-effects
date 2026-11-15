-- Edge cases for Umbra Gore & Effects (run: luajit zgo_test_edge.lua [seed])
-- S: this folder (scratch files are written here); the mod scripts are in ../gamedata/scripts
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 3
arg = { S .. "/../gamedata/scripts", "sp" }
NPC_YAW = 0.8
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local base_setting = zgo_util.setting
local OVR = {}
zgo_util.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	if k == "general/debug" then return true end   -- debug lines are checked too
	return base_setting(k)
end
local function section(t) print(("\n== %s"):format(t)) end
local function errs()
	local out = {}
	for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") or l:find("traceback") then out[#out + 1] = l end end
	return out
end
local function check(name)
	local e = errs()
	for _, l in ipairs(e) do print("  ERR " .. l) end
	assert(#e == 0, name .. ": errors in log")
end
local nid = 2000
local function npc(pos, kind) nid = nid + 1 return NEW_NPC(nid, kind or "stalker", pos) end
local eid = 3000
-- a busy little fight: gunfire, neck shot, kill, corpse shots, a grenade into a crowd + corpse
local function scenario(tag)
	local a, b, c, d = npc(VV(0, 0, -1.2)), npc(VV(1, 0, -1.2)), npc(VV(-1, 0, 0.5)), npc(VV(1.5, 0, 1))
	for i = 1, 4 do shoot(a, "bip01_spine1", "ammo_5_45x39_fmj") end
	shoot(b, "bip01_neck", "ammo_5_45x39_fmj")
	shoot(c, "bip01_head", "ammo_7.62x54_7h1", { kill = true })
	for i = 1, 6 do T_NOW = T_NOW + 300 shoot(c, "bip01_l_calf", "ammo_12x76_zhekan") end
	d._alive = false
	eid = eid + 1
	explode(VV(0.8, 0.1, 0.4), { a, b, c, d }, { eid = eid })
	shoot(a, "bip01_l_thigh", "ammo_12x70_buck", { speed = 380 })
	run(3000, 33)
	return a, b, c, d
end

section("Every option switched off, one at a time")
local KEYS = { "decals/body", "decals/bystanders", "decals/trails", "decals/pools", "decals/drips", "particles/enable",
	"particles/spurts", "particles/armor_feedback", "dismember/enable", "dismember/head", "dismember/limbs",
	"dismember/corpses", "dismember/severed_limbs", "dismember/gibs", "dismember/stump_caps", "dismember/full_gib",
	"dismember/mutants", "general/npc_shooters" }
for _, k in ipairs(KEYS) do
	LOG = {}
	OVR = { [k] = false }
	scenario(k)
	check(k)
	io.write(k, " ok  ")
end
OVR = {}
print()

section("Odd numeric settings (zero amount / streams / budgets)")
for _, ov in ipairs({ { ["decals/amount"] = 0.25, ["decals/max_streams"] = 1 }, { ["particles/intensity"] = 0.25, ["performance/fx_budget"] = 6 },
	{ ["performance/max_debris"] = 0 }, { ["dismember/chance"] = 0 }, { ["dismember/chance"] = 3, ["decals/amount"] = 2.5, ["decals/max_streams"] = 12 } }) do
	LOG = {}
	OVR = ov
	scenario("numeric")
	check("numeric")
end
OVR = {}
print("  ok")

section("Mod disabled in MCM: nothing happens, nothing breaks")
LOG, PLACED, FX = {}, {}, {}
OVR = { ["general/enable"] = false }
scenario("disabled")
check("disabled")
print(("  decals %d, fx %d"):format(#PLACED, #FX))
assert(#PLACED == 0 and #FX == 0)
OVR = {}

section("Mutants (dog class on a human-shaped mock skeleton): shots, kills, grenade, corpse")
LOG = {}
local m1, m2 = npc(VV(0, 0, 0), "monster"), npc(VV(1, 0, 0), "monster")
for i = 1, 5 do shoot(m1, "bip01_spine1", "ammo_12x76_zhekan") end
shoot(m1, "bip01_head", "ammo_12x76_zhekan", { kill = true })
m2._alive = false
eid = eid + 1
explode(VV(0.5, 0.1, 0.3), { m1, m2 }, { eid = eid })
run(2000, 33)
check("mutants")
print("  ok")

section("Objects going offline mid-way (sequences, trails, soaks, pending explosion, debris)")
LOG = {}
local a, b, c, d = npc(VV(0, 0, -1)), npc(VV(1, 0, -1)), npc(VV(-1, 0, 0)), npc(VV(0.5, 0, 0.8))
shoot(a, "bip01_neck", "ammo_5_45x39_fmj")
shoot(b, "bip01_spine1", "ammo_9x18_fmj")
shoot(c, "bip01_l_forearm", "ammo_12x76_zhekan", { kill = true })
eid = eid + 1
-- fragments arrive, then the victims vanish before the explosion resolves
OBJ[eid] = { _grenade = true, id = function() return eid end, section = function() return "grenade_f1" end, position = function() return VV(0, 0.1, 0) end }
CB.bullet_on_init({ position = VV(0, 0.1, 0), direction = VV(0, 0, 1), speed = 200, weapon_id = eid, parent_id = 0, target_id = 65535 })
CB.bullet_on_impact({ position = VV(0.5, 1, 0.75), direction = VV(0, 0, 1), speed = 200, element = 4, parent_id = 0, target_id = d:id(), weapon_id = eid })
frame()
OBJ[a:id()], OBJ[b:id()], OBJ[c:id()], OBJ[d:id()], OBJ[eid] = nil, nil, nil, nil, nil
run(3000, 33)
check("offline")
print(("  pending explosions %d"):format(zgo_blast.count()))
assert(zgo_blast.count() == 0)

section("Level change in the middle of everything")
LOG = {}
scenario("before level change")
eid = eid + 1
OBJ[eid] = { _grenade = true, id = function() return eid end, section = function() return "grenade_f1" end, position = function() return VV(0, 0.1, 0) end }
CB.bullet_on_init({ position = VV(0, 0.1, 0), direction = VV(0, 0, 1), speed = 200, weapon_id = eid, parent_id = 0, target_id = 65535 })
CB.on_level_changing()
local left = 0
for _ in pairs(LEVEL_ATT) do left = left + 1 end
print(("  after level change: level attachments %d, pending explosions %d, sequences %d"):format(left, zgo_blast.count(), zgo_fx.sequence_count()))
assert(left == 0 and zgo_blast.count() == 0 and zgo_fx.sequence_count() == 0)
run(2000, 33)
check("level change")

section("Save / load restores stumps with caps on the cut")
LOG = {}
local v = npc(VV(0, 0, 0))
OVR = { ["dismember/chance"] = 50 }
shoot(v, "bip01_r_forearm", "ammo_12x76_zhekan", { kill = true })
OVR = {}
local function cap_on(o)
	for _, att in pairs(o._att) do if att.parent_bone == "bip01_r_upperarm" and att.pos then return att end end
end
assert(cap_on(v), "cap missing after sever")
local data = SAVE_GAME()
RESPAWN(v)
CB.on_level_changing()
CB.load_state(data)
run(3000, 33)
local cap = cap_on(v)
assert(v._hidden["bip01_r_forearm"] and cap, "stump + cap not restored")
CHECK_CUTS("loaded stump")
local um = v:bone_transform("bip01_r_upperarm")
local o = cap.pos
local w = VV(um.c.x + um.i.x * o.x + um.j.x * o.y + um.k.x * o.z, um.c.y + um.i.y * o.x + um.j.y * o.y + um.k.y * o.z, um.c.z + um.i.z * o.x + um.j.z * o.y + um.k.z * o.z)
print(("  restored cap %.3f m from the elbow"):format(w:distance_to(v:bone_position("bip01_r_forearm"))))
assert(w:distance_to(v:bone_position("bip01_r_forearm")) < 0.01)
check("save/load")

section("Explosions that should do nothing")
LOG, PLACED, FX = {}, {}, {}
-- the player in the blast, nobody else
eid = eid + 1
explode(VV(0, 0.1, 5.5), { ACTOR }, { eid = eid })
-- a firearm firing section-less bullets (must not become an "explosion")
local gun = { _weapon = true, id = function() return 3999 end, section = function() return "wpn_mystery" end, position = function() return VV(0, 1, 5) end }
OBJ[3999] = gun
local t = npc(VV(0, 0, -1.2))
CB.bullet_on_init({ position = VV(0, 1, 5), direction = VV(0, 0, -1), speed = 800, section = "", weapon_id = 3999, parent_id = 0, target_id = 65535 })
CB.bullet_on_impact({ position = VV(0, 1.25, -1.1), direction = VV(0, 0, -1), speed = 800, section = "", element = 4, parent_id = 0, target_id = t:id(), weapon_id = 3999 })
CB.on_before_hit_after_calcs({ power = 0.3, type = hit.fire_wound, draftsman = ACTOR, direction = VV(0, 0, -1), weapon_id = 3999 }, t, 4)
run(500, 33)
print(("  decals %d (from the gun only), explosion lines %d, pending %d"):format(#PLACED, (function() local n = 0 for _, l in ipairs(LOG) do if l:find("explosion ") then n = n + 1 end end return n end)(), zgo_blast.count()))
for _, l in ipairs(LOG) do if l:find("explosion ") then print("  " .. l) end end
check("nothing")

section("Twenty grenades at once into a crowd: bounded work")
LOG, PLACED, FX = {}, {}, {}
local crowd = {}
for i = 1, 10 do crowd[i] = npc(VV(-2 + (i % 5), 0, (i > 5) and 1 or -1)) end
local t0 = os.clock()
for g = 1, 20 do
	eid = eid + 1
	explode(VV(-2 + (g % 5), 0.1, (g % 2 == 0) and 0.2 or -0.2), crowd, { eid = eid })
end
run(8000, 33)   -- 200 bodies at 2 a frame
local dt = os.clock() - t0
print(("  %d decals, %d particle plays, debris %d, %.2f s of script time in the mock"):format(#PLACED, #FX, zgo_debris.count(), dt))
check("crowd")
assert(zgo_debris.count() <= 14 and zgo_blast.count() == 0)


------------------------------------------------------------------ review findings
local function caps_on(o)
	local t = {}
	for _, at in pairs(o._att) do if at.parent_bone then t[at.parent_bone] = (t[at.parent_bone] or 0) + 1 end end
	return t
end

section("Forearm off, then the whole arm: nothing left hanging at the elbow")
LOG = {}
OVR = { ["dismember/chance"] = 50 }
local w = npc(VV(0, 0, -1.2))
shoot(w, "bip01_r_forearm", "ammo_12x76_zhekan", { kill = true })
run(200, 33)
assert(w._hidden["bip01_r_forearm"] and caps_on(w)["bip01_r_upperarm"] == 1, "forearm off with an elbow cap")
for i = 1, 6 do T_NOW = T_NOW + 300 shoot(w, "bip01_r_upperarm", "ammo_12x76_zhekan") end
run(200, 33)
OVR = {}
local cw = caps_on(w)
print(("  upper arm off %s, caps: elbow %d shoulder %d"):format(tostring(w._hidden["bip01_r_upperarm"]), cw["bip01_r_upperarm"] or 0, cw["bip01_r_clavicle"] or 0))
if BAKED then
	assert(w._hidden["bip01_r_upperarm"] and not cw["bip01_r_upperarm"] and cw["bip01_r_clavicle"] == 1)
else
	-- the ragdoll holds the upper arm in view: it stays, and so does the elbow stump
	assert(not w._hidden["bip01_r_upperarm"] and cw["bip01_r_upperarm"] == 1 and not cw["bip01_r_clavicle"])
end
CHECK_CUTS("elbow then shoulder")
for _, sq in ipairs(zgo_fx.sequence_list()) do
	local gone = sq.bone == "bip01_r_forearm" or (BAKED and sq.bone == "bip01_r_upperarm")
	assert(not (sq.id == w:id() and gone), "spurt left on a bone that's gone")
end
check("elbow then shoulder")

section("A shot that takes a leg off: the femoral artery pumps from the stump")
LOG = {}
OVR = { ["dismember/chance"] = 50 }
local on_stump, on_lost, cuts = 0, 0, 0
for n = 1, 30 do
	local t = npc(VV(-1 + n * 0.05, 0, -1.2))
	shoot(t, "bip01_l_thigh", "ammo_12x76_zhekan", { kill = true })
	if t._hidden["bip01_l_thigh"] then cuts = cuts + 1 end
	for _, sq in ipairs(zgo_fx.sequence_list()) do
		if sq.id == t:id() and sq.kind == "artery" then
			if sq.bone == "bip01_pelvis" then on_stump = on_stump + 1 end
			if sq.bone == "bip01_l_thigh" or sq.bone == "bip01_l_calf" then on_lost = on_lost + 1 end
		end
	end
end
OVR = {}
print(("  legs off %d/30, femoral spurts from the stump %d, from the lost leg %d"):format(cuts, on_stump, on_lost))
assert(cuts >= 10 and on_stump >= 3 and on_lost == 0)
run(8000, 50)
check("femoral stump")

section("Save / load: every stump gets its cap back, not only the first")
LOG = {}
OVR = { ["dismember/chance"] = 50 }
local v2 = npc(VV(1.2, 0, -1.2))
if BAKED then
	shoot(v2, "bip01_l_forearm", "ammo_12x76_zhekan", { kill = true })
	for i = 1, 6 do T_NOW = T_NOW + 300 shoot(v2, "bip01_r_calf", "ammo_12x76_zhekan") end
else
	-- (un-baked: a corpse can't lose more, so cut several at the kill)
	eid = eid + 1
	explode(VV(1.2, 0.1, -0.7), { v2 }, { eid = eid })
end
OVR = {}
run(200, 33)
local before = caps_on(v2)
local cut = {}
for _, b in ipairs(zgo_dismember.get_state()[v2:id()].b) do cut[#cut + 1] = b end
print(("  cut: %s"):format(table.concat(cut, ", ")))
assert(#cut >= 2, "two parts off")
local data = SAVE_GAME()
RESPAWN(v2)
CB.on_level_changing()
CB.load_state(data)
run(3000, 33)
CHECK_CUTS("loaded caps")
local after = caps_on(v2)
for bone, n in pairs(before) do
	print(("  cap on %s: before %d, after load %d"):format(bone, n, after[bone] or 0))
	assert(after[bone] == n, "cap lost on load: " .. bone)
end
check("save/load caps")

section("A released body's id handed to a new NPC: it doesn't inherit the wounds")
LOG = {}
OVR = { ["dismember/chance"] = 50 }
local r1 = npc(VV(2.5, 0, 1))
shoot(r1, "bip01_head", "ammo_12x76_zhekan", { kill = true })
OVR = {}
local rid = r1:id()
assert(zgo_dismember.get_state()[rid], "head shot off")
OBJ[rid] = nil
local r2 = NEW_NPC(rid, "stalker", VV(2.5, 0, 1))
run(8000, 33)
print(("  new NPC hidden bones: %d, record kept: %s"):format((function() local n = 0 for _ in pairs(r2._hidden) do n = n + 1 end return n end)(), tostring(zgo_dismember.get_state()[rid] ~= nil)))
assert(next(r2._hidden) == nil and zgo_dismember.get_state()[rid] == nil)
OVR = { ["dismember/chance"] = 50 }
local r3 = npc(VV(3.5, 0, 1))
shoot(r3, "bip01_head", "ammo_12x76_zhekan", { kill = true })
OVR = {}
assert(zgo_dismember.get_state()[r3:id()])
CB.server_entity_on_unregister({ id = r3:id() }, "se_stalker")
assert(zgo_dismember.get_state()[r3:id()] == nil, "release forgets the body")
check("id reuse")

section("Blast wave arriving late: waited for inside the radius, never resolved twice")
LOG = {}
local lb = npc(VV(-3, 0, 2)); lb._alive = false
eid = eid + 1
local late_eid = eid
explode(VV(-3, 0.1, 2.6), { lb }, { eid = late_eid, no_corpse_blast = true })
run(500, 33)
CB.on_before_hit_after_calcs({ power = 1.4, type = hit.explosion, draftsman = ACTOR, direction = VV(0, 1, 0), weapon_id = late_eid }, lb, 0)
run(1500, 33)
-- and once more, long after (a cluttered camp, 3 objects a frame)
CB.on_before_hit_after_calcs({ power = 1.4, type = hit.explosion, draftsman = ACTOR, direction = VV(0, 1, 0), weapon_id = late_eid }, lb, 0)
run(2000, 33)
local lines = {}
for _, l in ipairs(LOG) do if l:find("explosion ") then lines[#lines + 1] = l print("  " .. l) end end
assert(#lines == 1, "resolved once")
assert(lines[1]:find("power 1.4", 1, true), "the blast wave counted")
check("late blast")

section("Particles: a two-body gib burst isn't cut short")
LOG = {}
local real_po = particles_object
local early, started_n = 0, 0
particles_object = function(name)
	local o = real_po(name)
	local pa, st = o.play_at_pos, o.stop
	local t0
	function o:play_at_pos(p) t0 = T_NOW started_n = started_n + 1 return pa(self, p) end
	function o:stop() if t0 and T_NOW - t0 < 2500 then early = early + 1 end return st(self) end
	return o
end
local g1, g2 = npc(VV(-1, 0, -3)), npc(VV(-0.4, 0, -3))
g1._alive, g2._alive = false, false
eid = eid + 1
explode(VV(-0.7, 0.1, -2.6), { g1, g2 }, { eid = eid })
for i = 1, 30 do shoot(npc(VV(-2 + (i % 5) * 0.8, 0, -2)), "bip01_spine1", "ammo_12x76_zhekan") end
run(2000, 16)
particles_object = real_po
print(("  %d effects started, %d stopped before they finished, %d alive now"):format(started_n, early, zgo_fx.live_count()))
assert(early == 0)
check("particles")

section("Wallmark sections: only real ones reach the engine, names are pinned")
assert(zgo_decals.pin("zgo_no_such_section") == nil and zgo_decals.pin("wm_bogus") == nil and zgo_decals.pin(nil) == nil)
assert(zgo_decals.place_raw(VV(0, -1, 0), VV(0, 1, 0), 2, 0.5, "zgo_no_such_section") == false)
local nsec = 0
for _ in pairs(WM_PLACED_SECS) do nsec = nsec + 1 end
print(("  %d distinct sections placed in this run, every one defined in the configs"):format(nsec))
for _, it in ipairs(zgo_debris.list()) do assert(it.ignore == nil, "debris holds a game_object across frames") end

print("\nALL EDGE TESTS PASSED")
