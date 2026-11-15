-- Props and destruction tests (zgo_props*). Run: luajit zgo_test_props.lua [seed]
-- Single player here; the co-op part runs this file again as "host" and
-- "client" (separate processes, like zgo_test_mp) and compares what each drew.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local role = (arg and (arg[1] == "host" or arg[1] == "client")) and arg[1] or "sp"
local seed = tonumber(role == "sp" and arg and arg[1] or arg and arg[2]) or 5
local WIRE = os.getenv("ZGO_PROPS_WIRE")
arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local old_setting = zgo_util.setting
OVR = {}
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return old_setting(k) end

local P, DEB = zgo_props, zgo_props_debris
local function section(t) if role == "sp" then print(("\n== %s"):format(t)) end end
local function fx(name) local n = 0 for _, f in ipairs(FX) do if f == name or f:sub(1, #name) == name then n = n + 1 end end return n end
local function pieces() local n = 0 for name in pairs(LEVEL_ATT) do if name:find("^zgo_prop_") then n = n + 1 end end return n end
local function released(id) for _, r in ipairs(RELEASED) do if r == id then return true end end return false end
local function errors()
	local n = 0
	for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") then n = n + 1 print("  ERR " .. l) end end
	return n
end
local function clear() FX, PLACED, FORCES, TORQUES, SOUNDS, SENT, UP = {}, {}, {}, {}, {}, {}, {} end
local function lines(kind, sub)
	local n = 0
	for _, b in ipairs(SENT) do
		for l in b:gmatch("[^\n]+") do
			if l:sub(1, #kind + 1) == kind .. "|" and (not sub or l:sub(#kind + 2, #kind + 2 + #sub) == sub .. "|") then n = n + 1 end
		end
	end
	return n
end

-- a round from the player at a prop: from 3 m back along -dir to point p
local function shoot_at(o, p, ammo, opts)
	opts = opts or {}
	local d = opts.dir or VV(0, 0, -1)
	CB.bullet_on_impact({ position = VV(p.x, p.y, p.z), direction = d, speed = opts.speed or 880, section = ammo or "ammo_5_45x39_fmj",
		element = 0, parent_id = opts.shooter or 0, target_id = o:id(), weapon_id = 500 })
	frame()
end

-- the props in the room (floor y = 0, wall z = -2, wall x = 3); same ids on every machine
local function room()
	return {
		crate = NEW_PROP(1001, { vis = "dynamics\\box\\box_1a", sec = "physic_destroyable_object", kind = "destr", pos = VV(-1, 0, -1), yaw = 0.5, mass = 30 }),
		barrel = NEW_PROP(1002, { vis = "dynamics\\balon\\bochka_close_1", sec = "physic_object", pos = VV(1.5, 0, -1), mass = 62 }),
		bottle = NEW_PROP(1003, { vis = "dynamics\\devices\\dev_vodka\\dev_vodka", sec = "physic_object", pos = VV(0.5, 0, -1.5), mass = 0.6 }),
		lamp = NEW_PROP(1004, { vis = "dynamics\\light\\light_alarm_glass", sec = "hanging_lamp", kind = "lamp", pos = VV(0, 2.5, -1) }),
		chair = NEW_PROP(1005, { vis = "dynamics\\stul\\stul_wood_01", sec = "physic_object", pos = VV(-2, 0, 0.5), yaw = 1.2, mass = 60 }),
		gas = NEW_PROP(1006, { vis = "dynamics\\balon\\gaz_balon", sec = "physic_object", pos = VV(2, 0, 0.5), mass = 65 }),
	}
end

------------------------------------------------------------------------
-- Single player
------------------------------------------------------------------------
if role == "sp" then
	OVR["general/debug"] = true

	section("Rotations: the engine's HPB convention round-trips")
	for _, a in ipairs({ { 0.3, -0.4, 1.1 }, { -2.5, 1.2, -0.2 }, { 1.0, 0, 0 }, { 0, 1.5, 0.3 } }) do
		local i, j, k = DEB.rows_from_hpb(a[1], a[2], a[3])
		local h, p, b = DEB.hpb_from_rows(i, j, k)
		local i2, j2, k2 = DEB.rows_from_hpb(h, p, b)
		for _, pr in ipairs({ { i, i2 }, { j, j2 }, { k, k2 } }) do
			assert(math.abs(pr[1].x - pr[2].x) + math.abs(pr[1].y - pr[2].y) + math.abs(pr[1].z - pr[2].z) < 1e-6, "hpb round trip")
		end
		assert(math.abs(zgo_util.dot(i, j)) < 1e-9 and math.abs(zgo_util.len(k) - 1) < 1e-9, "orthonormal rows")
	end
	print("  rows -> hpb -> rows: exact, orthonormal")

	section("Classification: material, kind, what may break, what leaks")
	local R = room()
	local story = NEW_PROP(1010, { vis = "dynamics\\box\\box_1b", sec = "physic_destroyable_object", kind = "destr", pos = VV(-2.5, 0, -1.5) })
	STORY[1010] = "quest_crate"
	local bound = NEW_PROP(1011, { vis = "dynamics\\box\\box_1c", sec = "physic_object", pos = VV(-2.5, 0, 1.5), binder = true })
	local native = NEW_PROP(1012, { vis = "dynamics\\box\\box_wood_01", sec = "physic_destroyable_object", kind = "destr", pos = VV(1, 0, 1), binder = true })
	local stash = NEW_PROP(1013, { vis = "dynamics\\box\\box_1a", sec = "stash_box_1a", pos = VV(0, 0, 2) })
	local expect = {
		{ R.crate, "destr", "wood", true }, { R.barrel, "phys", "barrel", false, "oil" }, { R.bottle, "phys", "glass", true },
		{ R.lamp, "lamp", "lamp", false }, { R.chair, "phys", "wood", true }, { R.gas, "phys", "metal", false, "gas" },
		{ story, "destr", "wood", false }, { bound, "phys", "wood", false }, { native, "destr", "wood", false }, { stash, "phys", "wood", false },
	}
	for _, e in ipairs(expect) do
		local inf = P.classify(e[1])
		local brk = P.can_break(e[1], inf)
		print(("  %-34s %-6s %-7s breaks %-5s leaks %s"):format(inf.vis, inf.kind, inf.mtl, tostring(brk), tostring(inf.liquid)))
		assert(inf.kind == e[2] and inf.mtl == e[3], "kind / material of " .. inf.vis)
		assert(brk == e[4], "breakable: " .. inf.vis)
		assert(inf.liquid == e[5], "liquid of " .. inf.vis)
	end
	assert(P.classify(NEW_NPC(1020, "stalker", VV(0, 0, 3))).kind == nil, "creatures are never props")
	for _, o in ipairs({ story, bound, native, stash }) do OBJ[o:id()] = nil end

	section("Kit-bash rig: the crate's planks fill the small crate's box")
	do
		local inf = P.classify(R.crate)
		local rig = P.rig_for(inf.vis, inf.mtl)
		assert(rig and rig.src == "k" and #rig.pieces == 7, "seven planks")
		-- world box of every piece at spawn vs the crate's world box
		local f = P.frame_of(R.crate)
		local lo, hi = { 1e9, 1e9, 1e9 }, { -1e9, -1e9, -1e9 }
		for _, pc in ipairs(rig.pieces) do
			for sx = -1, 1, 2 do for sy = -1, 1, 2 do for sz = -1, 1, 2 do
				local v = VV(pc.o.x + sx * pc.half.x, pc.o.y + sy * pc.half.y, pc.o.z + sz * pc.half.z)
				local m = VV(pc.s.x * v.x + pc.t.x, pc.s.y * v.y + pc.t.y, pc.s.z * v.z + pc.t.z)
				lo = { math.min(lo[1], m.x), math.min(lo[2], m.y), math.min(lo[3], m.z) }
				hi = { math.max(hi[1], m.x), math.max(hi[2], m.y), math.max(hi[3], m.z) }
			end end end
		end
		local b = zgo_props_models.boxes[inf.vis]
		print(("  pieces span (%.3f %.3f %.3f)-(%.3f %.3f %.3f), crate (%.3f %.3f %.3f)-(%.3f %.3f %.3f)"):format(lo[1], lo[2], lo[3], hi[1], hi[2], hi[3], b[1], b[2], b[3], b[4], b[5], b[6]))
		for a = 1, 3 do assert(math.abs(lo[a] - b[a]) < 0.01 and math.abs(hi[a] - b[a + 3]) < 0.01, "planks fill the box") end
		assert(math.abs(f.pos.x - (-1)) < 1e-3 and math.abs(f.h - 0.5) < 1e-3, "frame from the xform")
	end

	section("Hit feedback and extra push")
	clear()
	shoot_at(R.crate, VV(-1, 0.12, -0.8), "ammo_5_45x39_fmj")
	print(("  crate: splinters %d, wood dust %d, pushes %d"):format(fx("zgo\\props\\splinters"), fx("zgo\\props\\dust_wood"), #FORCES))
	assert(fx("zgo\\props\\splinters") == 1, "splinters from wood")
	assert(#FORCES == 1, "one extra push")
	local F = FORCES[1]
	local J = math.sqrt(F.x * F.x + F.y * F.y + F.z * F.z) / 100
	print(("  impulse %.2f N s on %d kg: %.2f m/s, along the round: %s"):format(J, F.m, J / F.m, tostring(F.z < 0)))
	assert(F.z < 0 and J / F.m > 0.05 and J / F.m <= 4.0001, "push along the bullet, within the cap")
	assert(#TORQUES == 1, "an off-centre hit spins it")
	assert(zgo_impacts == nil or zgo_props.handles_impact({ target_id = R.crate:id() }) == true, "world impacts leave props to this module")
	clear()
	for i = 1, 3 do shoot_at(R.barrel, VV(1.5, 0.9, -0.63), "ammo_7.62x54_7h1") end
	print(("  barrel (3 rifle rounds above the fill line): sparks %d, metal dust %d, leaks %d"):format(fx("zgo\\props\\sparks"), fx("zgo\\props\\dust_metal"), P.leak_count()))
	assert(fx("zgo\\props\\dust_metal") == 3 and fx("zgo\\props\\sparks") >= 1, "sparks and dust from metal")
	clear()
	OVR["props/push"] = 0
	shoot_at(R.chair, VV(-2, 0.5, 0.75), "ammo_5_45x39_fmj")
	assert(#FORCES == 0, "push 0: only the game's own push")
	OVR["props/push"] = nil
	-- the per-object cap: a light bottle doesn't fly off at bullet speed
	clear()
	OVR["props/breaking"] = false
	for i = 1, 6 do shoot_at(R.bottle, VV(0.5, 0.15, -1.47), "ammo_12x76_zhekan") end
	local dv = 0
	for _, f in ipairs(FORCES) do dv = dv + math.sqrt(f.x * f.x + f.y * f.y + f.z * f.z) / 100 / f.m end
	print(("  six slugs into a 0.6 kg bottle in 0.1 s: %.1f m/s in total (cap 8 per second)"):format(dv))
	assert(dv <= 8.0001, "per-second push cap")
	OVR["props/breaking"] = nil

	section("Breaking: health from material and mass, pieces fly and settle")
	clear()
	local shots = 0
	while OBJ[R.crate:id()] and shots < 40 do
		shoot_at(R.crate, VV(-1, 0.12, -0.8), "ammo_5_45x39_fmj")
		shots = shots + 1
	end
	print(("  small crate (30 kg wood) broke after %d rifle rounds; released %s; pieces %d; burst %d; sounds %d"):format(
		shots, tostring(released(1001)), pieces(), fx("zgo\\props\\burst_wood"), #SOUNDS))
	assert(released(1001) and shots >= 2 and shots <= 12, "a crate takes a few rounds")
	assert(pieces() == 7 and fx("zgo\\props\\burst_wood") == 1 and #SOUNDS >= 1, "planks, a burst, a crack")
	run(7000)
	local asleep, low, maxd = 0, 1e9, 0
	for _, it in ipairs(DEB.list()) do
		local B = it.body
		if B.asleep then asleep = asleep + 1 end
		for sx = -1, 1, 2 do for sy = -1, 1, 2 do for sz = -1, 1, 2 do
			local y = B.c.y + sx * B.i.y * B.h.x + sy * B.j.y * B.h.y + sz * B.k.y * B.h.z
			low = math.min(low, y)
		end end end
		maxd = math.max(maxd, math.sqrt((B.c.x + 1) ^ 2 + (B.c.z + 1) ^ 2))
	end
	print(("  after 7 s: %d of %d at rest, lowest corner %.3f m, farthest %.2f m from where it stood"):format(asleep, pieces(), low, maxd))
	assert(asleep == pieces(), "every piece comes to rest")
	assert(low > -0.03, "nothing sinks through the floor")
	assert(maxd < 4, "pieces stay near")
	for name, a in pairs(LEVEL_ATT) do
		if name:find("^zgo_prop_") then assert(a.type == 1 and a.scale and a.scale.x > 0, "world attachment with a scale") end
	end
	OVR["performance/props_pieces_life"] = 10
	run(13000)
	print(("  pieces left after their lifetime: %d"):format(pieces()))
	assert(pieces() == 0, "pieces are removed after their lifetime")
	OVR["performance/props_pieces_life"] = nil
	-- the chair breaks too (same planks fitted to the chair)
	clear()
	shots = 0
	while OBJ[R.chair:id()] and shots < 40 do shoot_at(R.chair, VV(-2, 0.5, 0.75), "ammo_7.62x54_7h1") shots = shots + 1 end
	print(("  chair (60 kg) broke after %d rounds of 7.62x54"):format(shots))
	assert(released(1005) and pieces() == 7, "the chair comes apart")
	-- a bottle: one round, jar shards
	clear()
	shoot_at(R.bottle, VV(0.5, 0.15, -1.47), "ammo_9x18_fmj")
	print(("  bottle: released %s after one 9x18, shards %d, glass burst %d"):format(tostring(released(1003)), pieces(), fx("zgo\\props\\glass_burst")))
	assert(released(1003) and fx("zgo\\props\\glass_burst") == 1 and pieces() >= 7 + 8 - 1, "bottles shatter")
	DEB.reset()

	section("Leaks: below the fill line a barrel pours and puddles, above it doesn't")
	clear()
	local inf = P.classify(R.barrel)
	print(("  barrel fill line at %.0f%% of its height"):format(inf.fill and inf.fill * 100 or -1))
	shoot_at(R.barrel, VV(1.5, 0.08, -0.63), "ammo_5_45x39_fmj")
	assert(P.leak_count() == 1, "a hole near the bottom leaks")
	run(4000)
	local puddles = 0
	for _, p in ipairs(PLACED) do if p.sec:find("^zgo_props_puddle_oil") then puddles = puddles + 1 assert(math.abs(p.y) < 0.01, "puddle on the floor") end end
	print(("  4 s later: oil stream effects %d, puddles %d"):format(fx("zgo\\props\\leak_oil"), puddles))
	assert(fx("zgo\\props\\leak_oil") >= 12 and puddles >= 1, "a stream and a puddle")
	run(120000)
	assert(P.leak_count() == 0, "the barrel runs dry")
	local before = P.leak_count()
	shoot_at(R.barrel, VV(1.5, 1.0, -0.63), "ammo_5_45x39_fmj")
	assert(P.leak_count() == before, "a hole above the liquid doesn't leak")
	clear()
	shoot_at(R.gas, VV(2, 0.3, 0.68), "ammo_5_45x39_fmj")
	run(1000)
	print(("  gas bottle: jet puffs %d, puddles %d"):format(fx("zgo\\props\\jet_gas"), #PLACED))
	assert(fx("zgo\\props\\jet_gas") >= 4 and #PLACED == 0, "gas hisses, no puddle")
	OVR["performance/props_leaks"] = 1
	local b2 = NEW_PROP(1030, { vis = "dynamics\\balon\\bochka_close_2", sec = "physic_object", pos = VV(2.5, 0, -1.5), mass = 62 })
	local b3 = NEW_PROP(1031, { vis = "dynamics\\balon\\bochka_close_3", sec = "physic_object", pos = VV(2.5, 0, 1.5), mass = 62 })
	shoot_at(b2, VV(2.5, 0.05, -1.13), "ammo_5_45x39_fmj")
	shoot_at(b3, VV(2.5, 0.05, 1.87), "ammo_5_45x39_fmj")
	assert(P.leak_count() == 1, "leak limit")
	OVR["performance/props_leaks"] = nil
	run(100000)

	section("Hanging lamps: glass and sparks, flicker, a lamp that goes out showers glass")
	clear()
	local lamp = R.lamp
	local flickers = 0
	for i = 1, 12 do
		shoot_at(lamp, VV(0, 2.3, -1), "ammo_5_45x39_fmj", { dir = VV(0, 0, -1) })
		local off_seen = false
		for _ = 1, 50 do frame() if not lamp._on then off_seen = true end end
		if off_seen then flickers = flickers + 1 end
		assert(lamp._on, "a flicker ends with the lamp on")
	end
	print(("  12 hits on a live lamp: glass %d, sparks %d, flickers %d"):format(fx("zgo\\props\\glass"), fx("zgo\\props\\sparks"), flickers))
	assert(fx("zgo\\props\\glass") >= 12 and flickers >= 1, "glass and some flicker")
	clear()
	-- this round kills it (the engine turns a dead lamp off)
	CB.bullet_on_impact({ position = VV(0, 2.3, -1), direction = VV(0, 0, -1), speed = 880, section = "ammo_5_45x39_fmj",
		element = 0, parent_id = 0, target_id = lamp:id(), weapon_id = 500 })
	lamp._lamp_alive, lamp._on = false, false
	run(400)
	print(("  the lamp went out: glass burst %d"):format(fx("zgo\\props\\glass_burst")))
	assert(fx("zgo\\props\\glass_burst") == 1, "shards when it goes out")

	section("Native breaks: the game's own crates and jars burst")
	clear()
	local nat = NEW_PROP(1040, { vis = "dynamics\\box\\box_wood_01", sec = "physic_destroyable_object", kind = "destr", pos = VV(1, 0, 1), binder = true })
	run(2100)   -- the scan hooks the vanilla binder
	local binder = bind_physic_object.generic_physics_binder
	binder.death_callback({ object = nat }, nat, ACTOR)
	run(100)
	print(("  vanilla crate: burst %d, the binder's own death_callback still ran %d time(s)"):format(fx("zgo\\props\\burst_wood"), BINDER_DEATHS))
	assert(fx("zgo\\props\\burst_wood") == 1 and BINDER_DEATHS == 1, "burst, and the original callback chained")
	clear()
	local jar = NEW_PROP(1041, { vis = "dynamics\\kitchen_room\\bottle_3l", sec = "physic_destroyable_object", kind = "destr", pos = VV(-1, 0, 1.5) })
	run(2100)
	assert(jar._cb[callback.death], "a death callback on an unbound destroyable")
	jar._cb[callback.death](jar, ACTOR)
	run(100)
	jar._cb[callback.death](jar, ACTOR)   -- (a second report of the same break)
	run(100)
	print(("  unbound jar: glass bursts %d (one, deduped)"):format(fx("zgo\\props\\glass_burst")))
	assert(fx("zgo\\props\\glass_burst") == 1, "one burst")
	assert(not nat._cb[callback.death], "bound objects keep their binder's callbacks")

	section("Melee: knife hits wear down unbound destroyables")
	clear()
	local box = NEW_PROP(1050, { vis = "dynamics\\box\\box_1b", sec = "physic_destroyable_object", kind = "destr", pos = VV(-0.5, 0, 0.5), mass = 30 })
	run(2100)
	assert(box._cb[callback.hit], "hit callback set")
	local hits = 0
	while OBJ[1050] and hits < 10 do box._cb[callback.hit](box, 0.6, VV(0, 0, -1), ACTOR, 0) run(50) hits = hits + 1 end
	print(("  small crate broke after %d knife hits"):format(hits))
	assert(released(1050) and hits <= 4, "a few knife hits")
	DEB.reset()

	section("Explosions: glass shatters, objects get thrown, crates break up close")
	clear()
	local jar2 = NEW_PROP(1060, { vis = "dynamics\\devices\\dev_vodka\\dev_vodka2", sec = "physic_object", pos = VV(-1.5, 0, -1.5), mass = 0.5 })
	local far_bottle = NEW_PROP(1061, { vis = "dynamics\\devices\\dev_vodka\\dev_vodka", sec = "physic_object", pos = VV(2.8, 0, 2.8), mass = 0.5 })
	local close_crate = NEW_PROP(1062, { vis = "dynamics\\box\\box_1c", sec = "physic_object", pos = VV(-0.6, 0, -1.2), mass = 30 })
	local heavy = NEW_PROP(1063, { vis = "dynamics\\balon\\bochka_close_4", sec = "physic_object", pos = VV(0.8, 0, -0.6), mass = 62 })
	explode(VV(-1, 0.1, -1), {}, { eid = 990, sec = "grenade_f1" })
	run(200)
	print(("  F1 grenade: bottle 0.7 m away broken %s, bottle 5.4 m away broken %s, crate 0.45 m away broken %s, barrel pushed %s"):format(
		tostring(released(1060)), tostring(released(1061)), tostring(released(1062)), tostring(#FORCES > 0)))
	assert(released(1060) and not released(1061), "glass near the blast shatters")
	assert(released(1062), "a crate right next to a grenade breaks")
	local up = false
	for _, f in ipairs(FORCES) do if f.id == 1063 and f.y > 0 then up = true end end
	assert(up, "the barrel is thrown up and away")
	OBJ[1061], OBJ[1063] = nil, nil
	DEB.reset()

	section("Options: off switches, performance, kid mode")
	clear()
	local c2 = NEW_PROP(1070, { vis = "dynamics\\box\\box_1a", sec = "physic_object", pos = VV(-1, 0, -1), mass = 30 })
	OVR["props/enable"] = false
	for i = 1, 20 do shoot_at(c2, VV(-1, 0.12, -0.78), "ammo_7.62x54_7h1") end
	assert(#FX == 0 and #FORCES == 0 and not released(1070), "off: nothing at all")
	OVR["props/enable"] = nil
	OVR["props/feedback"], OVR["props/breaking"] = false, false
	for i = 1, 20 do shoot_at(c2, VV(-1, 0.12, -0.78), "ammo_7.62x54_7h1") end
	assert(fx("zgo\\props\\") == 0 and #FORCES > 0 and not released(1070), "no effects, no breaking, still pushed")
	OVR["props/feedback"], OVR["props/breaking"] = nil, nil
	clear()
	OVR["general/kid_mode"] = true
	OVR["performance/props_pieces"] = 0
	OVR["props/toughness"] = 0.25
	for i = 1, 4 do if OBJ[1070] then shoot_at(c2, VV(-1, 0.12, -0.78), "ammo_7.62x54_7h1") end end
	print(("  kid mode, pieces 0: effects %d, broken %s, pieces %d"):format(fx("zgo\\props\\"), tostring(released(1070)), pieces()))
	assert(fx("zgo\\props\\splinters") >= 1 and released(1070) and pieces() == 0, "kid mode leaves destruction alone; 0 pieces = burst only")
	OVR["general/kid_mode"], OVR["performance/props_pieces"], OVR["props/toughness"] = nil, nil, nil
	clear()
	OVR["performance/props_fx"] = 6
	local c3 = NEW_PROP(1071, { vis = "dynamics\\balon\\bochka_close_1", sec = "physic_object", pos = VV(-1, 0, -1), mass = 62 })
	for i = 1, 20 do
		CB.bullet_on_impact({ position = VV(-1, 0.9, -0.63), direction = VV(0, 0, -1), speed = 880, section = "ammo_5_45x39_fmj",
			element = 0, parent_id = 0, target_id = 1071, weapon_id = 500 })
	end
	frame()
	print(("  20 rounds in one frame with 6 effects per second: %d effects"):format(fx("zgo\\props\\")))
	assert(fx("zgo\\props\\") <= 6, "effects budget")
	OVR["performance/props_fx"] = nil
	-- creatures are not props: shooting an NPC draws none of this
	clear()
	shoot(NEW_NPC(1080, "stalker", VV(0, 0, -1.2)), "bip01_spine1", "ammo_5_45x39_fmj")
	assert(fx("zgo\\props\\") == 0, "NPC hits are not prop hits")

	section("Co-op: host decides, client draws the same")
	local me = S .. "/zgo_test_props.lua"
	local wire = os.tmpname()
	local env = ("ZGO_PROPS_WIRE=%q ZGO_BAKED=%s "):format(wire, BAKED and "1" or "0")
	local h = io.popen(env .. "luajit " .. ("%q"):format(me) .. " host " .. seed .. " 2>&1")
	local hout = h:read("*a") h:close()
	local c = io.popen(env .. "luajit " .. ("%q"):format(me) .. " client " .. seed .. " 2>&1")
	local cout = c:read("*a") c:close()
	os.remove(wire)
	io.write(hout, cout)
	assert(hout:find("HOST OK"), "host run")
	assert(cout:find("CLIENT OK"), "client run")

	print(("\n  errors: %d"):format(errors()))
	assert(errors() == 0, "no errors logged")
	print("\nALL PROPS TESTS PASSED")
	return
end

------------------------------------------------------------------------
-- Co-op: host
------------------------------------------------------------------------
local function rest_summary()
	local out = {}
	for name, a in pairs(LEVEL_ATT) do
		if name:find("^zgo_prop_") then
			out[#out + 1] = ("%s %.3f %.3f %.3f %.2f %.2f %.2f"):format(a.model, a.pos.x, a.pos.y, a.pos.z, a.rot.x, a.rot.y, a.rot.z)
		end
	end
	table.sort(out)
	return out
end

if role == "host" then
	local R = room()
	clear()
	-- the host's own rounds: a crate breaks, the barrel leaks, the lamp is hit
	while OBJ[1001] do shoot_at(R.crate, VV(-1, 0.12, -0.8), "ammo_7.62x54_7h1") end
	shoot_at(R.barrel, VV(1.5, 0.08, -0.63), "ammo_5_45x39_fmj")
	shoot_at(R.lamp, VV(0, 2.3, -1), "ammo_5_45x39_fmj")
	-- a client's round on the bottle comes up as K (the host never simulated it)
	local nf = #FORCES
	DISPATCH(zgo_sync.EVT_UP, table.concat({ "K", 1003, "physic_object", "ammo_5_45x39_fmj", 880, 0.5, 0.15, -1.47, 0, 0, -1, 123456789 }, "|"), "2")
	frame()
	assert(released(1003), "the client's round broke the bottle on the host")
	-- and one on the chair: damage and push, with the engine's share
	DISPATCH(zgo_sync.EVT_UP, table.concat({ "K", 1005, "physic_object", "ammo_5_45x39_fmj", 880, -2, 0.5, 0.75, 0, 0, -1, 222 }, "|"), "2")
	frame()
	assert(#FORCES > nf, "a client's round pushes on the host")
	run(200)
	zgo_sync.flush()
	local b, xh, xl = lines("B"), lines("X", "h"), lines("X", "l")
	print(("host: B %d, X|h %d, X|l %d, X|f/s %d"):format(b, xh, xl, lines("X", "f") + lines("X", "s")))
	assert(b == 2 and xh >= 5 and xl == 1, "lines for partners")
	local tok = false
	for _, batch in ipairs(SENT) do if batch:find("|123456789") then tok = true end end
	assert(tok, "the client's token comes back with its hit")
	-- the wire: every batch, then where the pieces came to rest
	run(7000)
	local f = assert(io.open(WIRE, "w"))
	for _, batch in ipairs(SENT) do f:write("L ", (batch:gsub("\n", "\\n")), "\n") end
	for _, l in ipairs(rest_summary()) do f:write("R ", l, "\n") end
	f:close()
	assert(errors() == 0, "no errors on the host")
	print(("host: %d pieces at rest"):format(#rest_summary()))
	print("HOST OK")
	return
end

------------------------------------------------------------------------
-- Co-op: client
------------------------------------------------------------------------
if role == "client" then
	local R = room()
	clear()
	-- its own round: drawn at once, forwarded up, the echo is ignored
	shoot_at(R.chair, VV(-2, 0.5, 0.75), "ammo_5_45x39_fmj")
	local own = fx("zgo\\props\\splinters")
	assert(own == 1 and #UP >= 1 and UP[#UP]:find("^K|1005|"), "client draws its own hit and sends K")
	assert(#FORCES == 0 and not released(1005), "a client never pushes or breaks")
	local tok = UP[#UP]:match("|(%d+)$")
	DISPATCH(zgo_sync.EVT, table.concat({ "X", "h", "w", -2, 0.5, 0.75, 0, 0, 1, 1, 5, tok }, "|"))
	run(100)
	assert(fx("zgo\\props\\splinters") == own, "the host's echo of its own hit is not drawn twice")
	-- the host's lines
	local rest = {}
	for l in io.lines(WIRE) do
		local kind, body = l:match("^(%a) (.*)$")
		if kind == "L" then
			DISPATCH(zgo_sync.EVT, (body:gsub("\\n", "\n")))
		elseif kind == "R" then
			rest[#rest + 1] = body
		end
	end
	-- the host released what broke (replicated); the client only draws
	OBJ[1001], OBJ[1003] = nil, nil
	frame()
	print(("client: pieces %d, leaks %d, hit effects %d"):format(#rest_summary(), P.leak_count(), fx("zgo\\props\\")))
	assert(P.leak_count() == 1, "the host's leak plays here")
	run(7000)
	local mine = rest_summary()
	assert(#mine == #rest and #mine > 0, ("same number of pieces (%d here, %d on the host)"):format(#mine, #rest))
	local diff = 0
	for i = 1, #mine do if mine[i] ~= rest[i] then diff = diff + 1 print("  differs: " .. mine[i] .. " / " .. rest[i]) end end
	print(("client: %d pieces, %d rest differently from the host"):format(#mine, diff))
	assert(diff == 0, "pieces rest where they rest on the host")
	assert(errors() == 0, "no errors on the client")
	print("CLIENT OK")
	return
end
