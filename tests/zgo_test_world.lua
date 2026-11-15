-- World impacts and craters (zgo_impacts*) for Umbra Gore & Effects.
--   luajit zgo_test_world.lua [seed]            single player, then runs itself as
--                                               a co-op host and a co-op client
--   luajit zgo_test_world.lua host|client seed  one co-op role (ZGO_WORLD_WIRE: the
--                                               file the host leaves for the client)
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 1
arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local GD = S .. "/../gamedata"

local base_setting = zgo_util.setting
local OVR = {}
zgo_util.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	return base_setting(k)
end
local I, C, D, FXP = zgo_impacts, zgo_impacts_crater, zgo_impacts_data, zgo_impacts_fx
local function section(t) print(("\n== %s"):format(t)) end
local function errs()
	local n = 0
	for _, l in ipairs(LOG) do if l:find("error") or l:find("traceback") then n = n + 1 print("  ERR " .. l) end end
	return n
end
local function clear()
	PLACED, FX, WORLD_PLACED, WORLD_FX, WORLD_FXDIR, WORLD_STOPPED, SENT, UP = {}, {}, {}, {}, {}, {}, {}, {}
end
local function count(list, pat)
	local n = 0
	for _, p in ipairs(list) do if (type(p) == "table" and p.sec or p):find(pat) then n = n + 1 end end
	return n
end
local function world_atts()
	local n = 0
	for name in pairs(LEVEL_ATT) do if name:find("^zgo_world_") then n = n + 1 end end
	return n
end
-- a round hitting level geometry, as the engine reports it
local function hit_static(pos, dir, ammo, shooter, extra)
	local b = { position = pos, direction = dir, speed = 800, section = ammo or "ammo_5_45x39_fmj", element = 1,
		parent_id = shooter or 0, target_id = 65535, weapon_id = 500 }
	for k, v in pairs(extra or {}) do b[k] = v end
	CB.bullet_on_impact(b)
end
local function wall_shot(x, y, ammo, shooter) hit_static(VV(x, y, -2), VV(0, 0, -1), ammo, shooter) end
local function settle(ms) run(ms or 100, 16) end
local function reset_all()
	CB.on_level_changing()
	frame()
	clear()
end
local function lines(kind)
	local out = {}
	for _, b in ipairs(SENT) do
		for l in b:gmatch("[^\n]+") do if l:sub(1, #kind + 1) == kind .. "|" then out[#out + 1] = l end end
	end
	return out
end
local function split(l) local t = {} for f in (l .. "|"):gmatch("([^|]*)|") do t[#t + 1] = f end return t end
local function sig(list)   -- a mark list as text (section and position), for comparisons
	local out = {}
	for _, p in ipairs(list) do out[#out + 1] = ("%s %.2f %.2f %.2f %.3f"):format(p.sec, p.x, p.y, p.z, p.size) end
	return table.concat(out, "\n")
end
local function rests()
	local out = {}
	for _, it in ipairs(C.list()) do
		if it.body then out[#out + 1] = ("%.3f %.3f %.3f"):format(it.body.p.x, it.body.p.y, it.body.p.z) end
	end
	table.sort(out)
	return table.concat(out, "\n")
end
-- a firearm-free explosive that is still in the level when the crater is decided
local function blast(center, sec, eid)
	return explode(center, {}, { eid = eid or 940, sec = sec or "grenade_f1" })
end

------------------------------------------------------------------------
if role == "sp" then
------------------------------------------------------------------------
section("Data: every section, texture, effect and model the scripts can ask for exists")
do
	local nsec, ntex = 0, 0
	local function dds_ok(path)
		local f = io.open(path, "rb")
		if not f then return false, "missing" end
		local h = f:read(128 + 4)
		f:close()
		if h:sub(1, 4) ~= "DDS " then return false, "not a DDS" end
		local function u32(o) local b1, b2, b3, b4 = h:byte(o + 1, o + 4) return b1 + b2 * 256 + b3 * 65536 + b4 * 16777216 end
		if u32(88) ~= 32 or u32(80) ~= 0x41 then return false, "not 32-bit BGRA" end
		local b, g, r = h:byte(129, 131)
		if b ~= 128 or g ~= 128 or r ~= 128 then return false, "corner texel is not neutral grey" end
		return true
	end
	for mark, fams in pairs(D.VARIANTS) do
		for fam, nvar in pairs(fams) do
			for v = 1, nvar do
				for _, deep in ipairs({ false, true }) do
					local sec = D.section(mark, fam == "all" and "stone" or fam, v, deep)
					assert(sec and WM_SECTIONS[sec], "no wallmark section " .. tostring(sec))
					nsec = nsec + 1
					local tex = ("%s/textures/zgo/impacts/%s%s_%s_%d.dds"):format(GD, (deep and D.DEEP[mark]) and "deep/" or "", mark, fam, v)
					local ok, why = dds_ok(tex)
					assert(ok, tex .. ": " .. tostring(why))
					ntex = ntex + 1
				end
			end
		end
	end
	for _, name in ipairs(D.FX) do
		local f = io.open(("%s/particles/zgo/world/%s.pe"):format(GD, name), "r")
		assert(f, "missing effect " .. name)
		local txt = f:read("*a")
		f:close()
		assert(txt:find("%[_effect%]") and txt:find("action_count") and txt:find("%[sprite%]"), "malformed effect " .. name)
		for tex in txt:gmatch("texture = ([%w_\\]+)") do
			local tf = io.open(GD .. "/textures/" .. tex:gsub("\\", "/") .. ".dds", "rb")
			assert(tf, name .. " uses a texture the mod doesn't ship: " .. tex)
			tf:close()
		end
	end
	local nmesh = 0
	for _, set in ipairs({ D.RIM, D.CLODS }) do
		for _, list in pairs(set) do
			for _, m in ipairs(list) do
				local f = assert(io.open(("%s/meshes/zgo/world/%s.ogf"):format(GD, m), "rb"), "missing model " .. m)
				local h = f:read(10)
				f:close()
				-- chunk 1 (header): version 4, type 10 = MT_SKELETON_RIGID (attachments need a skeleton)
				assert(h:byte(1) == 1 and h:byte(9) == 4 and h:byte(10) == 10, m .. " is not a rigid skeleton model")
				nmesh = nmesh + 1
			end
		end
	end
	print(("  %d sections, %d textures (modulate-2x, neutral border), %d effects, %d models"):format(nsec, ntex, #D.FX, nmesh))
	-- the engine's explosion marks: extended, not replaced
	local f = io.open(GD .. "/configs/mod_system_zgo_impacts.ltx")
	local txt = f:read("*a")
	f:close()
	assert(txt:find("\n!%[explosion_marks%]") and txt:find("wm\\wm_grenade", 1, true), "explosion_marks must be a DLTX override keeping wm_grenade")
end

section("Surfaces: material names to families")
do
	local cases = { { "materials\\concrete", "stone" }, { "materials\\bricks", "brick" }, { "materials\\stucco", "plaster" },
		{ "materials\\wooden_board", "wood" }, { "materials\\metal_plate", "metal" }, { "materials\\earth", "earth" },
		{ "materials\\glass", "glass" }, { "MATERIALS\\Concrete", "stone" }, { "materials\\water", nil }, { "materials\\bush", nil },
		{ "materials\\fake", nil }, { "materials\\some_mod_concrete_wall", "stone" }, { "materials\\rusty_iron_sheet", "metal" },
		{ "", nil }, { nil, nil } }
	for _, c in ipairs(cases) do
		assert(I.family_of(c[1]) == c[2], ("%s -> %s, expected %s"):format(tostring(c[1]), tostring(I.family_of(c[1])), tostring(c[2])))
	end
	-- the probe turns the triangle's normal to face the shooter
	local p, n, m = I.probe(VV(3, 1, 0), VV(1, 0, 0))
	assert(p and math.abs(p.x - 3) < 1e-6 and n.x < -0.99 and m == "materials\\bricks")
	local p2, n2 = I.probe(VV(0.5, 0, 1), U and nil or zgo_util.unit(VV(0.3, -1, -0.2)))
	assert(p2 and math.abs(p2.y) < 1e-6 and n2.y > 0.99)
	print("  " .. #cases .. " material names, probe normals face the shooter")
end

section("A burst at a concrete wall: chips by calibre, dust off the surface, no build-up")
do
	reset_all()
	for i = 0, 39 do wall_shot(-2 + (i % 8) * 0.5, 0.4 + math.floor(i / 8) * 0.35) end
	settle()
	local chips = count(WORLD_PLACED, "^zgo_world_chip_stone_")
	print(("  40 rifle rounds on 40 spots: %d chip marks, %d effects, stage marks %d"):format(chips, #WORLD_FX, #WORLD_PLACED - chips))
	assert(chips >= 8 and chips <= 34, "chip chance is calibre based")
	assert(#WORLD_PLACED == chips, "no damage builds up from one round per spot")
	for _, p in ipairs(WORLD_PLACED) do assert(math.abs(p.z + 2) < 1e-6, "marks on the wall") end
	assert(count(WORLD_FX, "dust_stone") >= 30, "every hit raises dust")
	for i, f in ipairs(WORLD_FXDIR) do assert(f.dir == nil or f.dir.z > 0.7, "effects come off the surface: " .. f.name) end
	assert(#PLACED == 0 and #FX == 0, "nothing goes through the gore lists")
	-- calibre: pistol chips are smaller than rifle chips, which are smaller than slug chips
	local function avg(ammo)
		reset_all()
		OVR["world/escalation"] = false
		for i = 0, 199 do wall_shot(-2 + (i % 20) * 0.25, 0.3 + math.floor(i / 20) * 0.25, ammo) run(40, 40) end
		settle()
		OVR["world/escalation"] = nil
		local s, n = 0, 0
		for _, p in ipairs(WORLD_PLACED) do s, n = s + p.size, n + 1 end
		return n > 0 and s / n or 0, n
	end
	local ps, pn = avg("ammo_9x18_fmj")
	local rs, rn = avg("ammo_5_45x39_fmj")
	local ss, sn = avg("ammo_12x76_zhekan")
	local bs, bn = avg("ammo_12x70_buck")
	print(("  mean chip size: buckshot pellet %.3f (%d), pistol %.3f (%d), rifle %.3f (%d), slug %.3f (%d)"):format(bs, bn, ps, pn, rs, rn, ss, sn))
	assert(bs < ps and ps < rs and rs < ss, "chips grow with calibre")
	assert(bn < pn and pn <= sn, "a pellet chips less often than a pistol round, a slug most often")
end

section("Sustained fire on one spot: chip -> crack -> gouge -> breach, by material")
do
	local function escalate(fam_mat, shots, at, dir, ammo)
		reset_all()
		WORLD_MAT.wall, WORLD_MAT.side = fam_mat, fam_mat
		for i = 1, shots do
			hit_static(VV(at.x + math.sin(i) * 0.02, at.y + math.cos(i * 1.7) * 0.02, at.z), dir, ammo)
			frame()
		end
		settle()
		WORLD_MAT.wall, WORLD_MAT.side = "materials\\concrete", "materials\\bricks"
		local order = {}
		for _, p in ipairs(WORLD_PLACED) do
			local m = p.sec:match("^zgo_world_(%a+)_")
			if m ~= "chip" then order[#order + 1] = m end
		end
		return table.concat(order, " ")
	end
	local wall, side = VV(0.3, 1.2, -2), VV(3, 1.1, 0.4)
	local r = {
		stone = escalate("materials\\concrete", 22, wall, VV(0, 0, -1)),
		brick = escalate("materials\\bricks", 18, side, VV(1, 0, 0)),
		plaster = escalate("materials\\stucco", 14, wall, VV(0, 0, -1)),
		wood = escalate("materials\\wood", 12, wall, VV(0, 0, -1)),
		metal = escalate("materials\\metal", 22, wall, VV(0, 0, -1)),
	}
	for _, k in ipairs({ "stone", "brick", "plaster", "wood", "metal" }) do print(("  %-8s %s"):format(k, r[k])) end
	assert(r.stone == "crack gouge breach" and r.brick == "crack gouge breach" and r.plaster == "crack gouge breach")
	assert(r.wood == "split gouge breach", "wood splits along the grain")
	assert(r.metal == "dent tear", "metal dents and tears, it never breaches")
	-- a breach throws a burst of debris and heavy dust
	assert(count(WORLD_FX, "breach_") == 0 and count(WORLD_FX, "sparks_big_metal") > 0)
	escalate("materials\\concrete", 22, wall, VV(0, 0, -1))
	assert(count(WORLD_FX, "breach_stone") == 1 and count(WORLD_FX, "dust_big_stone") >= 3)
	-- the stage marks sit at the middle of the hits, on the wall
	for _, p in ipairs(WORLD_PLACED) do assert(math.abs(p.z + 2) < 1e-6 and math.abs(p.x - 0.3) < 0.05 and math.abs(p.y - 1.2) < 0.05) end
	local n, staged = I.grid_stats()
	assert(n == 1 and staged == 1)
	-- switched off: chips only
	OVR["world/escalation"] = false
	assert(escalate("materials\\concrete", 30, wall, VV(0, 0, -1)) == "")
	OVR["world/escalation"] = nil
	-- earth takes splashes, never builds up
	reset_all()
	for i = 1, 40 do hit_static(VV(1, 0, 1), zgo_util.unit(VV(0, -1, -0.3))) frame() end
	settle()
	print(("  earth floor, 40 rounds on one spot: %d splash marks, %d other, dirt %d"):format(count(WORLD_PLACED, "splash_earth"),
		#WORLD_PLACED - count(WORLD_PLACED, "splash_earth"), count(WORLD_FX, "dirt_earth")))
	assert(#WORLD_PLACED == count(WORLD_PLACED, "splash_earth") and count(WORLD_FX, "dirt_earth") >= 10)
	for _, p in ipairs(WORLD_PLACED) do assert(math.abs(p.y) < 1e-6, "splashes on the floor") end
end

section("Damage grid: limited memory, forgets spots whose marks have faded")
do
	reset_all()
	OVR["performance/world_cells"] = 32
	for i = 0, 99 do wall_shot(-2.5 + (i % 10) * 0.5, 0.3 + math.floor(i / 10) * 0.25) frame() end
	settle()
	local n = I.grid_stats()
	print(("  100 spots hit, %d remembered (limit 32)"):format(n))
	assert(n <= 32 and n >= 20)
	OVR["performance/world_cells"] = nil
	-- a breached spot starts again once its marks are gone
	reset_all()
	OVR["performance/world_mark_lifetime"] = 60
	for i = 1, 22 do wall_shot(0.3, 1.2) frame() end
	local _, staged = I.grid_stats()
	assert(staged == 1)
	run(60 * 1000 * 0.95, 500)
	clear()
	wall_shot(0.3, 1.2)
	settle()
	assert(count(WORLD_PLACED, "breach") == 0 and count(WORLD_PLACED, "crack") == 0, "a forgotten spot starts from a chip")
	for i = 1, 4 do wall_shot(0.3, 1.2) frame() end
	settle()
	assert(count(WORLD_PLACED, "crack") == 1, "and builds up again")
	-- marks carry the lifetime from Performance
	for _, p in ipairs(WORLD_PLACED) do assert(p.ttl == 60) end
	OVR["performance/world_mark_lifetime"] = nil
end

section("What gets nothing: glass, water, creatures, fragments, far away, switched off")
do
	reset_all()
	WORLD_MAT.wall = "materials\\glass"
	for i = 1, 10 do wall_shot(0, 1) end
	WORLD_MAT.wall = "materials\\water"
	for i = 1, 10 do wall_shot(0.5, 1) end
	WORLD_MAT.wall = "materials\\concrete"
	settle()
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0, "glass is the engine's, water takes nothing")
	-- creatures: the gore modules' business
	local npc = NEW_NPC(801, "stalker", VV(0, 0, -1.2))
	for i = 1, 5 do shoot(npc, "bip01_spine1", "ammo_5_45x39_fmj") end
	settle()
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0)
	-- fragments carry no ammo section
	for i = 1, 10 do hit_static(VV(i * 0.2 - 1, 0.5, -2), VV(0, 0, -1), "") end
	settle()
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0)
	-- out of range (the wall is ~8 m from the player)
	OVR["performance/world_range"] = 5
	for i = 1, 10 do wall_shot(i * 0.2 - 1, 0.5) end
	settle()
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0)
	OVR["performance/world_range"] = nil
	-- switched off: on this page, or the whole mod
	for _, k in ipairs({ "world/enable", "general/enable" }) do
		OVR[k] = false
		for i = 1, 10 do wall_shot(i * 0.2 - 1, 0.5) end
		settle()
		assert(#WORLD_PLACED == 0 and #WORLD_FX == 0, k)
		OVR[k] = nil
	end
	-- NPC gunfire off: players' rounds still count
	local shooter = NEW_NPC(802, "stalker", VV(0, 0, 3))
	OVR["world/npc_impacts"] = false
	for i = 1, 10 do wall_shot(i * 0.2 - 1, 0.5, nil, 802) end
	settle()
	assert(#WORLD_FX == 0)
	for i = 1, 10 do wall_shot(i * 0.2 - 1, 0.8, nil, 0) end
	settle()
	assert(#WORLD_FX > 0)
	OVR["world/npc_impacts"] = nil
	print(("  nothing from glass, water, bodies, fragments, far away, or when off; %d errors"):format(errs()))
end

section("Your own switches: dust off, deep marks on")
do
	reset_all()
	OVR["world/particles"] = false
	for i = 0, 19 do wall_shot(-1 + i * 0.1, 0.6) end
	settle()
	assert(#WORLD_FX == 0 and #WORLD_PLACED > 0, "marks stay without dust")
	OVR["world/particles"] = nil
	reset_all()
	OVR["world/deep_marks"] = true
	for i = 1, 22 do wall_shot(0.3, 1.2) frame() end
	settle()
	OVR["world/deep_marks"] = nil
	for _, p in ipairs(WORLD_PLACED) do assert(p.sec:find("_d$"), "deep sections: " .. p.sec) end
	print(("  dust off: marks only; deep marks: %d marks, all *_d"):format(#WORLD_PLACED))
end

section("Objects: dust and splinters off crates and barrels, no marks")
do
	reset_all()
	local box = NEW_NPC(803, "stalker", VV(-1, 0, 0))
	box._kind, box._visual = "item", "dynamics\\box\\box_wood_01"
	local barrel = NEW_NPC(804, "stalker", VV(1, 0, 0))
	barrel._kind, barrel._visual = "item", "dynamics\\bochka\\bochka_close_1"
	zgo_util.is_creature = (function(orig) return function(o) if o == box or o == barrel then return false end return orig(o) end end)(zgo_util.is_creature)
	for _, o in ipairs({ box, barrel }) do
		for i = 1, 3 do
			CB.bullet_on_impact({ position = o:position(), direction = VV(0, 0, -1), speed = 800, section = "ammo_5_45x39_fmj", element = 0,
				parent_id = 0, target_id = o:id(), weapon_id = 500 })
		end
	end
	settle()
	print(("  crate: %d wood effects, barrel: %d spark effects, marks %d"):format(count(WORLD_FX, "wood"), count(WORLD_FX, "metal"), #WORLD_PLACED))
	assert(#WORLD_PLACED == 0 and count(WORLD_FX, "splinters_wood") == 3 and count(WORLD_FX, "sparks_metal") == 3)
	clear()
	OVR["world/objects"] = false
	CB.bullet_on_impact({ position = box:position(), direction = VV(0, 0, -1), speed = 800, section = "ammo_5_45x39_fmj", element = 0, parent_id = 0, target_id = box:id(), weapon_id = 500 })
	settle()
	assert(#WORLD_FX == 0)
	OVR["world/objects"] = nil
	OBJ[803], OBJ[804] = nil, nil
end

section("Budgets: marks and effects per second, a bounded queue")
do
	reset_all()
	OVR["performance/world_marks"], OVR["performance/world_fx"] = 6, 6
	local picks = WORLD_PICKS
	for i = 0, 299 do wall_shot(-2.5 + (i % 20) * 0.25, 0.2 + math.floor(i / 20) * 0.12) end
	settle(200)
	print(("  300 rounds in one frame: %d marks, %d effects, %d rays"):format(#WORLD_PLACED, #WORLD_FX, WORLD_PICKS - picks))
	assert(#WORLD_PLACED <= 6 and #WORLD_FX <= 6)
	assert(I.queued() == 0 and WORLD_PICKS - picks <= 64 * 3, "the queue drops what it can't take")
	run(1100, 50)
	clear()
	for i = 0, 9 do wall_shot(-2.5 + i * 0.5, 2.2) end
	settle()
	assert(#WORLD_PLACED > 0, "the next second has budget again")
	OVR["performance/world_marks"], OVR["performance/world_fx"] = nil, nil
end

section("Craters: scorch and pit by charge, pocks, dust ring, hanging smoke")
do
	reset_all()
	blast(VV(0, 0.1, 0), "grenade_f1", 941)
	settle()
	local sc = count(WORLD_PLACED, "scorch_earth")
	local cr = count(WORLD_PLACED, "crater_earth")
	local pocks = count(WORLD_PLACED, "pock_all")
	print(("  grenade on earth: scorch %d, pit %d, pocks %d, effects: %s"):format(sc, cr, pocks, table.concat(WORLD_FX, " "):gsub("zgo\\world\\", "")))
	assert(sc == 1 and cr == 1 and pocks >= 2)
	assert(count(WORLD_FX, "crater_ring_earth") == 1 and count(WORLD_FX, "crater_column_earth") == 1 and count(WORLD_FX, "crater_smoke") == 1)
	local g_size
	for _, p in ipairs(WORLD_PLACED) do
		if p.sec:find("scorch") then g_size = p.size assert(math.abs(p.y) < 1e-6 and math.abs(p.x) < 1e-3) end
	end
	-- the smoke hangs for Performance -> Explosion smoke, then fades out (stop_deffered)
	run(14 * 1000, 250)
	assert(#WORLD_STOPPED == 0)
	run(2000, 250)
	assert(#WORLD_STOPPED == 1 and WORLD_STOPPED[1]:find("crater_smoke"))
	-- bigger charge, bigger crater; concrete floor, stone marks
	reset_all()
	WORLD_MAT.floor = "materials\\concrete"
	blast(VV(0, 0.1, 0), "wpn_rpg7_missile", 942)
	settle()
	WORLD_MAT.floor = "materials\\earth"
	local r_size
	for _, p in ipairs(WORLD_PLACED) do if p.sec:find("scorch_stone") then r_size = p.size end end
	print(("  scorch size: grenade %.2f m, RPG %.2f m (on concrete)"):format(g_size, r_size or -1))
	assert(r_size and r_size > g_size * 1.3)
	assert(count(WORLD_FX, "crater_ring_stone") == 1)
	-- an explosive the mod has no entry for: charge from its blast value (ini)
	assert(math.abs(C.charge_of(nil) - D.DEFAULT_CHARGE) < 1e-9)
	OBJ[950] = { section = function() return "ammo_vog-25" end }
	assert(math.abs(C.charge_of(950) - 4.6 / 3) < 1e-6)
	OBJ[950] = nil
	-- a rocket into a wall: scorch on the wall, no pit
	reset_all()
	blast(VV(0.5, 1.6, -1.75), "wpn_rpg7_missile", 943)
	settle()
	assert(count(WORLD_PLACED, "scorch_stone") == 1 and count(WORLD_PLACED, "crater_") == 0)
	for _, p in ipairs(WORLD_PLACED) do if p.sec:find("scorch") then assert(math.abs(p.z + 2) < 1e-6) end end
	-- in the air: dust and smoke, nothing to mark
	reset_all()
	blast(VV(0, 3.5, 2), "grenade_f1", 944)
	settle()
	assert(count(WORLD_PLACED, "scorch") == 0 and count(WORLD_FX, "crater_flash_dust") == 1)
	-- indoors: grit falls from the ceiling, and keeps falling for a moment
	reset_all()
	WORLD_CEILING = 2.8
	blast(VV(0, 0.1, 0), "grenade_f1", 945)
	settle()
	local now_grit = count(WORLD_FX, "ceiling_grit")
	run(2500, 50)
	local later = count(WORLD_FX, "ceiling_grit")
	WORLD_CEILING = nil
	print(("  indoors: ceiling grit %d at once, %d over the next seconds"):format(now_grit, later - now_grit))
	assert(now_grit == 1 and later > now_grit and count(WORLD_FX, "ceiling_dust") == 1)
	for _, f in ipairs(WORLD_FXDIR) do if f.name:find("ceiling") then assert(f.pos.y > 2.6 and f.dir.y < -0.99) end end
	-- a gun with section-less bullets is not an explosion
	reset_all()
	local gun = { _weapon = true, id = function() return 3999 end, section = function() return "wpn_mystery" end, position = function() return VV(0, 1, 5) end }
	OBJ[3999] = gun
	CB.bullet_on_init({ position = VV(0, 1, 5), direction = VV(0, 0, -1), speed = 800, section = "", weapon_id = 3999, parent_id = 0, target_id = 65535 })
	settle()
	OBJ[3999] = nil
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0)
	-- switched off
	OVR["world/craters"] = false
	blast(VV(0, 0.1, 0), "grenade_f1", 946)
	settle()
	assert(#WORLD_PLACED == 0 and #WORLD_FX == 0)
	OVR["world/craters"] = nil
	-- kid mode: not gore, nothing changes
	OVR["general/kid_mode"] = true
	blast(VV(0, 0.1, 0), "grenade_f1", 947)
	for i = 1, 10 do wall_shot(i * 0.2 - 1, 0.5) end
	settle()
	assert(count(WORLD_PLACED, "scorch") == 1 and count(WORLD_FX, "dust_stone") > 0, "kid mode leaves impacts and craters alone")
	OVR["general/kid_mode"] = nil
end

section("Crater rubble (experimental): a rim and clods that come to rest the same way every time")
do
	reset_all()
	assert(zgo_settings.default("world/crater_debris") == false, "experimental: off by default")
	blast(VV(0, 0.1, 0), "grenade_f1", 948)
	settle()
	assert(world_atts() == 0)
	OVR["world/crater_debris"] = true
	local line = { "C", 0.5, 0, 0.5, 0, 1, 0, D.CODE.earth, 1, 0, 12345, 1 + 4 }
	local function once()
		reset_all()
		C.draw(C.parse(line))
		run(5000, 16)
		return sig(WORLD_PLACED), rests()
	end
	local m1, r1 = once()
	local atts = world_atts()
	local rim, clods, models = 0, 0, true
	for name, a in pairs(LEVEL_ATT) do
		if name:find("^zgo_world_rim") then rim = rim + 1 end
		if name:find("^zgo_world_clod") then clods = clods + 1 end
		if name:find("^zgo_world_") then
			local f = io.open(GD .. "/meshes/" .. a.model:gsub("\\", "/") .. ".ogf", "rb")
			if f then f:close() else models = false end
			assert(a.type == 1 and a.scale and a.scale > 0)
		end
	end
	for _, it in ipairs(C.list()) do
		if it.body then
			assert(it.body.rest, "every clod comes to rest")
			assert(it.body.p.y >= -0.01 and it.body.p.y < 0.3, "on the floor")
		end
	end
	local m2, r2 = once()
	print(("  rim %d, clods %d, all at rest on the floor; the same line again: marks %s, rest positions %s"):format(rim, clods,
		m1 == m2 and "same" or "DIFFERENT", r1 == r2 and "same" or "DIFFERENT"))
	assert(rim == 1 and clods >= 3 and models and atts == rim + clods)
	assert(m1 == m2 and r1 == r2, "a crater line draws the same on every machine")
	-- the budget, oldest first; then their lifetime; then a level change
	OVR["performance/world_debris"] = 3
	reset_all()
	C.draw(C.parse(line))
	C.draw(C.parse(line))
	assert(world_atts() == 3)
	OVR["performance/world_debris"] = nil
	OVR["performance/world_mark_lifetime"] = 30
	run(31000, 500)
	assert(world_atts() == 0, "pieces go with the marks")
	OVR["performance/world_mark_lifetime"] = nil
	C.draw(C.parse(line))
	assert(world_atts() > 0)
	CB.on_level_changing()
	assert(world_atts() == 0 and C.count() == 0 and I.grid_stats() == 0)
	OVR["world/crater_debris"] = nil
	-- a rubbish line does nothing
	for _, bad in ipairs({ { "C" }, { "C", "x", 0, 0, 0, 1, 0, 1, 1, 0, 1, 1 }, { "C", 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 1 }, { "C", "nan", 0, 0, 0, 1, 0, 1, 1, 0, 1, 1 } }) do
		assert(C.parse(bad) == nil)
	end
end

section("Errors")
assert(errs() == 0)

section("Co-op: host and client")
do
	local wire = os.tmpname()
	local ok = true
	for _, r in ipairs({ "host", "client" }) do
		local p = io.popen(('ZGO_WORLD_WIRE="%s" luajit "%s/zgo_test_world.lua" %s %d 2>&1'):format(wire, S, r, seed))
		local out = p:read("*a")
		p:close()
		local last = out:match("([^\n]*)\n?$") or ""
		for l in out:gmatch("[^\n]+") do if l:find("^  ") or l:find("luajit:") or l:find("ERR") then print("  [" .. r .. "]" .. l) end end
		print(("  %s: %s"):format(r, last))
		ok = ok and last:find("OK") ~= nil
	end
	os.remove(wire)
	assert(ok, "co-op roles failed")
end
print("\nALL WORLD TESTS PASSED")

------------------------------------------------------------------------
elseif role == "host" then
------------------------------------------------------------------------
local WIRE = assert(os.getenv("ZGO_WORLD_WIRE"), "ZGO_WORLD_WIRE")
local npc = NEW_NPC(500, "stalker", VV(0, 0, 3))
-- NPC fire at the wall: decided here, drawn here, sent as I lines
clear()
for i = 1, 22 do wall_shot(0.3, 1.2, "ammo_5_45x39_fmj", 500) frame() end
for i = 0, 9 do wall_shot(-2 + i * 0.4, 0.6, "ammo_5_45x39_fmj", 500) end
settle()
zgo_sync.flush()
local il = lines("I")
print(("  host: 32 NPC rounds -> %d marks drawn here, %d I lines"):format(#WORLD_PLACED, #il))
assert(#il >= 13 and #WORLD_PLACED > 0)
local stages = 0
for _, l in ipairs(il) do
	local t = split(l)
	assert(#t == 15, "I line has 15 fields: " .. l)
	for k = 2, 7 do assert(tonumber(t[k]), l) end
	if tonumber(t[10]) > 1 then stages = stages + 1 end
end
assert(stages == 3, "crack, gouge and breach go out")
-- a partner's own round: the partner sends it up, the host does nothing itself
clear()
for i = 1, 5 do wall_shot(1, 1, "ammo_5_45x39_fmj", 77) end
settle()
zgo_sync.flush()
assert(#lines("I") == 0 and #WORLD_FX == 0)
-- ... and here it is (J): resolved, drawn, and sent back with the partner's token
for i = 1, 6 do DISPATCH(zgo_sync.EVT_UP, ("J|1.000|1.000|-2.000|0.000|0.000|1.000|1|2|1.000|%d|0"):format(4242 + i), "peer") end
settle()
zgo_sync.flush()
il = lines("I")
local toks = 0
for _, l in ipairs(il) do if tonumber(split(l)[15]) >= 4243 then toks = toks + 1 end end
print(("  host: 6 J lines -> %d I lines, %d with the partner's token, effects here %d"):format(#il, toks, #WORLD_FX))
assert(#il >= 6 and toks == 6 and #WORLD_FX > 0)
-- rubbish from the wire is dropped quietly
for _, bad in ipairs({ "J|1|2", "J|nan|1|1|0|0|1|1|2|1|5|0", "J|1|1|-2|0|0|0|1|2|1|5|0", "J|1|1|-2|0|0|1|99|2|1|5|0", "J|1e9|1|-2|0|0|1|1|2|1|5|0" }) do
	DISPATCH(zgo_sync.EVT_UP, bad, "peer")
end
settle()
-- range counts every player: a far spot near a partner still gets marks
clear()
OVR["performance/world_range"] = 4
local peer = NEW_NPC(600, "stalker", VV(-2, 0, -1))
XrrPlayers = function() return { IsPlayerDummy = function(self, id) return id == 77 end,
	GetPeerCount = function() return 1 end, GetPeerLocalIdAt = function(self, i) return 600 end } end
run(600, 50)
for i = 0, 9 do wall_shot(-2 + i * 0.1, 0.6, "ammo_5_45x39_fmj", 500) end
settle()
assert(#WORLD_FX > 0, "near the partner")
XrrPlayers = function() return { IsPlayerDummy = function(self, id) return id == 77 end } end
OVR["performance/world_range"] = nil
-- an explosion: one C line; the host's own drawing goes to the client for comparison
clear()
OVR["world/crater_debris"] = true
CB.on_level_changing()
frame()
blast(VV(0.4, 0.1, 0.6), "grenade_f1", 960)
run(5000, 16)
zgo_sync.flush()
local cl = lines("C")
assert(#cl == 1 and #split(cl[1]) == 12, "one C line with 12 fields")
local t = split(cl[1])
print(("  host: grenade -> %s; %d marks, %d pieces"):format(cl[1], #WORLD_PLACED, C.count()))
assert(tonumber(t[12]) % 2 == 1 and math.floor(tonumber(t[12]) / 4) % 2 == 1, "on the ground, with debris")
local f = assert(io.open(WIRE, "w"))
f:write(cl[1], "\n", sig(WORLD_PLACED):gsub("\n", ";"), "\n", rests():gsub("\n", ";"), "\n")
f:close()
assert(errs() == 0)
print("WORLD HOST OK")

------------------------------------------------------------------------
else -- client
------------------------------------------------------------------------
local WIRE = assert(os.getenv("ZGO_WORLD_WIRE"), "ZGO_WORLD_WIRE")
local npc = NEW_NPC(500, "stalker", VV(0, 0, 3))
-- someone else's round: the host's lines cover it
clear()
for i = 1, 5 do wall_shot(0.2 * i, 1, "ammo_5_45x39_fmj", 500) end
settle()
assert(#WORLD_PLACED == 0 and #WORLD_FX == 0 and #UP == 0)
-- my own round: dust now, the impact goes up, marks wait for the host
for i = 1, 3 do wall_shot(0.5 + i * 0.3, 1.1, "ammo_7.62x54_7h1", 0) end
settle()
print(("  client: 3 own rounds -> %d J lines up, %d effects here, %d marks"):format(#UP, #WORLD_FX, #WORLD_PLACED))
assert(#UP == 3 and #WORLD_FX >= 3 and #WORLD_PLACED == 0)
local tok
for _, l in ipairs(UP) do
	local t = split(l)
	assert(t[1] == "J" and #t == 12, l)
	assert(math.abs(tonumber(t[4]) + 2) < 1e-6 and tonumber(t[7]) > 0.99, "point on the wall, normal out of it")
	tok = tonumber(t[11])
end
-- the host answers: my mark comes back with my token (no second puff of dust), others' with theirs
clear()
DISPATCH(zgo_sync.EVT, ("I|1.400|1.100|-2.000|0.000|0.000|1.000|1|3|1|2|0.070|45|1|%d"):format(tok), "host")
settle()
assert(#WORLD_PLACED == 1 and WORLD_PLACED[1].sec == "zgo_world_chip_stone_2" and #WORLD_FX == 0)
DISPATCH(zgo_sync.EVT, "I|0.300|1.200|-2.000|0.000|0.000|1.000|1|2|4|1|0.200|10|4|0", "host")
settle()
assert(#WORLD_PLACED == 2 and WORLD_PLACED[2].sec == "zgo_world_breach_stone_1" and count(WORLD_FX, "breach_stone") == 1)
-- rubbish is dropped
for _, bad in ipairs({ "I|1", "I|x|1|-2|0|0|1|1|2|1|1|0.1|0|1|0", "I|1|1|-2|0|0|1|42|2|1|1|0.1|0|1|0", "C|1|2" }) do DISPATCH(zgo_sync.EVT, bad, "host") end
settle()
assert(#WORLD_PLACED == 2)
-- kid mode changes nothing here either
OVR["general/kid_mode"] = true
DISPATCH(zgo_sync.EVT, "I|0.900|1.200|-2.000|0.000|0.000|1.000|1|2|2|1|0.110|10|3|0", "host")
settle()
assert(#WORLD_PLACED == 3)
OVR["general/kid_mode"] = nil
-- the host's crater: same marks, same rest positions
local f = assert(io.open(WIRE, "r"))
local cline, hmarks, hrest = f:read("*l"), f:read("*l"), f:read("*l")
f:close()
OVR["world/crater_debris"] = true   -- (the host decided: flag 4 is on the line; this only checks the client draws it)
CB.on_level_changing()
frame()
clear()
DISPATCH(zgo_sync.EVT, cline, "host")
run(5000, 16)
local mine, mrest = sig(WORLD_PLACED):gsub("\n", ";"), rests():gsub("\n", ";")
print(("  client: host crater line -> %d marks (%s), pieces at rest %s"):format(#WORLD_PLACED, mine == hmarks and "same as the host" or "DIFFERENT",
	mrest == hrest and "same as the host" or "DIFFERENT"))
assert(mine == hmarks and mrest == hrest and #WORLD_PLACED > 0)
assert(errs() == 0)
print("WORLD CLIENT OK")
end
