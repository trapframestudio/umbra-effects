-- Progressive wounds (zgo_wounds) and the wound shader's data for Zone Gore Overhaul.
--   luajit zgo_test_wounds.lua [seed]             single player, then runs itself as
--                                                 a co-op host and a co-op client
--   luajit zgo_test_wounds.lua host|client seed   one co-op role (ZGO_WOUNDS_WIRE: the
--                                                 file the host leaves for the client)
-- ZGO_BAKED=0/1 (as every suite): what the harness model is before the test
-- installs its own bake (tests/mocks/wounds.lua).
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 1
WOUNDS_MOCKS, CUTS_MOCKS = true, true
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
local Wd, B = zgo_wounds, zgo_ballistics
local function section(t) print(("\n== %s"):format(t)) end
local function errs()
	local n = 0
	for _, l in ipairs(LOG) do
		if l:find("error") or l:find("traceback") or l:find("failed") then n = n + 1 print("  ERR " .. l) end
	end
	return n
end
local function logged(pat)
	for _, l in ipairs(LOG) do if l:find(pat) then return true end end
	return false
end
local function settle(ms) run(ms or 600, 16) end
local function split(l) local t = {} for f in (l .. "|"):gmatch("([^|]*)|") do t[#t + 1] = f end return t end
local function lines(kind, sub)
	local out = {}
	for _, b in ipairs(SENT) do
		for l in b:gmatch("[^\n]+") do
			local t = split(l)
			if t[1] == kind and (not sub or t[2] == sub) then out[#out + 1] = l end
		end
	end
	return out
end

-- what zgo_wounds itself draws (the hit's own marks and gibs are someone else's)
local MINE = { marks = {}, gibs = {} }
do
	local pb, sg = zgo_decals.place_body, zgo_debris.spawn_gibs
	zgo_decals.place_body = function(obj, sec, pos, dir, size, ttl)
		if debug.traceback():find("zgo_wounds") then MINE.marks[#MINE.marks + 1] = { sec = sec, size = size, drawn = zgo_util.gore() } end
		return pb(obj, sec, pos, dir, size, ttl)
	end
	zgo_debris.spawn_gibs = function(pos, dir, count, ignore, seed_)
		if debug.traceback():find("zgo_wounds") then
			MINE.gibs[#MINE.gibs + 1] = { pos = pos, dir = dir, n = count, seed = seed_ }
		end
		return sg(pos, dir, count, ignore, seed_)
	end
end
local function gib_atts()
	local n = 0
	for name in pairs(LEVEL_ATT) do if name:find("^zgo_gib_") then n = n + 1 end end
	return n
end
local function clear()
	PLACED, BODY, FX, SENT, UP = {}, {}, {}, {}, {}
	MINE.marks, MINE.gibs = {}, {}
end

local function prof(ammo) return B.make(B.ammo_info(ammo), 800) end
-- a world point on site i of section sec of npc (out: metres off the skin)
local function site_point(npc, sec, i, out)
	local s = WOUNDS_SPEC[sec][i]
	local bp = npc:bone_position(s[1])
	out = out or 0
	return VV(bp.x + s[2] + s[5] * out, bp.y + s[3] + s[6] * out, bp.z + s[4] + s[7] * out)
end
-- a hit as zgo_main raises it (authority)
local function hit(npc, sec, i, ammo, o)
	o = o or {}
	local s = WOUNDS_SPEC[sec][i]
	local p = type(ammo) == "table" and ammo or prof(ammo)
	local ev = { id = npc:id(), bone = o.bone or s[1], pos = o.pos or site_point(npc, sec, i, 0.005),
		dir = o.dir or VV(-s[5], -s[6], -s[7]), prof = p, vol = 1, head = sec == "bip01_head", neck = false,
		armor = "none", helmet = "none", penetrated = o.penetrated ~= false, exits = o.exits or false,
		dead = o.dead == nil and not npc._alive or o.dead or false, was_dead = o.was_dead or false,
		allow_dismember = o.allow ~= false }
	zgo_util.emit_event("hit", npc, ev)
end
local function wound(npc, sec, i)
	local st = Wd.get_state()[npc:id()]
	return st and st.w[sec .. "#" .. i]
end
local function nwounds(npc)
	local st = Wd.get_state()[npc:id()]
	local n = 0
	if st then for _ in pairs(st.w) do n = n + 1 end end
	return n
end
-- the 12-bit numbers in a zgo\dmg texture string
local function numbers(str)
	local hex = str:match(",zgo_dmg_(%x+)")
	local out = {}
	for k = 1, #hex, 3 do out[#out + 1] = tonumber(hex:sub(k, k + 2), 16) end
	return out
end
local function summary(npc)
	local st = Wd.get_state()[npc:id()]
	local keys = {}
	for k, w in pairs(st and st.w or {}) do
		if w.stage >= 2 then keys[#keys + 1] = ("%s:%d:%d:%s"):format(k, w.stage, w.level, w.bone and "b" or "-") end
	end
	table.sort(keys)
	return table.concat(keys, " ")
end

------------------------------------------------------------------------
if role == "sp" then
------------------------------------------------------------------------
section("Number textures: every 12-bit value, decoded as the vertex shader does")
do
	local function u32(h, o) local b1, b2, b3, b4 = h:byte(o + 1, o + 4) return b1 + b2 * 256 + b3 * 65536 + b4 * 16777216 end
	-- zgo_dmg.h zgo_number(): lo = g / 17, valid when a = 255, g = 17 lo, b = (r + 3 lo + 90) & 255
	local function decode(r, g, b, a)
		local lo = math.floor(g / 17)
		if a == 255 and lo * 17 == g and b == (r + lo * 3 + 90) % 256 then return r * 16 + lo end
		return 0
	end
	local bad = 0
	for v = 0, 4095 do
		local path = ("%s/textures/zgo/wounds/n/%03x.dds"):format(GD, v)
		local f = io.open(path, "rb")
		assert(f, "missing " .. path)
		local h = f:read("*a")
		f:close()
		assert(#h == 132 and h:sub(1, 4) == "DDS ", path .. ": not a 1x1 DDS")
		assert(u32(h, 4) == 124 and u32(h, 12) == 1 and u32(h, 16) == 1, path .. ": header")
		assert(u32(h, 80) == 0x41 and u32(h, 88) == 32 and u32(h, 92) == 0x00ff0000 and u32(h, 96) == 0x0000ff00
			and u32(h, 100) == 0xff and u32(h, 104) == 0xff000000, path .. ": not A8R8G8B8")
		local b, g, r, a = h:byte(129, 132)
		if decode(r, g, b, a) ~= v then bad = bad + 1 end
	end
	assert(bad == 0, bad .. " number textures decode wrong")
	-- the engine's stand-in for a missing texture (and an unbound slot) must read as "no wound"
	assert(decode(0, 0, 0, 0) == 0 and decode(255, 0, 255, 255) == 0 and decode(128, 128, 128, 255) == 0)
	for _, name in ipairs({ "tissue", "stump" }) do
		local f = assert(io.open(("%s/textures/zgo/wounds/%s.dds"):format(GD, name), "rb"), name)
		local h = f:read(128)
		f:close()
		assert(h:sub(1, 4) == "DDS " and u32(h, 12) == 256 and u32(h, 16) == 256 and u32(h, 28) == 9, name .. ": 256x256 with 9 mips")
	end
	print("  4096 number textures decode to their own value; tissue and stump 256x256 with mips")
end

section("zgo_dmg.s: the strings zgo_wounds makes bind the right textures (blender mock)")
do
	local M = dofile(S .. "/../dev/shadercheck/blender_mock.lua")
	local sh = assert(M.load_file(GD .. "/shaders/r3/zgo_dmg.s"))
	local function tex(el, slot)
		for _, t in ipairs(el.passes[1].textures) do if t[1] == slot then return t[2] end end
	end
	local function check(str, want_bump)
		local base, second = str:match("^([^,]*),(.*)$")
		local els, err = M.shader(sh, base, second)
		assert(not err, err)
		local nums = numbers(str)
		for _, idx in ipairs({ 0, 1, 2 }) do
			local el = assert(els[idx] and not els[idx].empty and els[idx], "element " .. idx)
			for k = 1, 4 do
				local t = tex(el, "s_zgo_w" .. (k - 1))
				assert(t == ("zgo\\wounds\\n\\%03x"):format(nums[k]), ("E%d slot %d: %s"):format(idx, k, tostring(t)))
				local f = io.open(GD .. "/textures/" .. t:gsub("\\", "/") .. ".dds", "rb")
				assert(f, "no texture " .. t) f:close()
			end
			assert(tex(el, "s_base") == base)
		end
		assert(els[2].passes[1].vs == "zgo_dmg_shadow")
		if want_bump then
			assert(els[0].passes[1].vs == "zgo_dmg_bump" and tex(els[0], "s_bump") == want_bump and tex(els[0], "s_bumpX") == want_bump .. "#")
		else
			assert(els[0].passes[1].vs == "zgo_dmg_flat" and tex(els[0], "s_bump") == nil)
		end
		assert(tex(els[0], "s_zgo_tissue") == "zgo\\wounds\\tissue")
	end
	for _ = 1, 40 do
		local nums = {}
		for k = 1, 4 do nums[k] = math.random() < 0.3 and 0 or Wd.pack(math.random(1, 20), math.random(1, 63), math.random() < 0.5) end
		check(Wd.texture_string("act\\act_stalker_neutral", nums, "act\\act_stalker_neutral_bump"), "act\\act_stalker_neutral_bump")
		check(Wd.texture_string("act\\act_face_1", nums, nil), nil)
	end
	-- a bump name too long for the engine's 128-char item: dropped (flat pair)
	local long = Wd.texture_string("a", { 1, 2, 3, 4 }, ("x"):rep(115))
	assert(#long:match(",(.*)$") <= 120 and not long:find("xxx"))
	-- anything that doesn't parse: all four slots 000 (an undented mesh)
	local els = M.shader(sh, "act\\x", "null")
	assert(tex(els[0], "s_zgo_w0") == "zgo\\wounds\\n\\000" and tex(els[2], "s_zgo_w3") == "zgo\\wounds\\n\\000")
	-- the shader reads the bits pack() writes
	local h = assert(io.open(GD .. "/shaders/r3/zgo_dmg.h")):read("*a")
	assert(h:find("(w0 & 31u) == site", 1, true) and h:find("(e >> 5) & 63u", 1, true) and h:find("(e >> 11) & 1u", 1, true))
	assert(Wd.pack(5, 10, true) == 5 + 32 * 10 + 2048 and Wd.pack(0, 10, true) == 0 and Wd.pack(3, 0, false) == 0)
	print("  80 random strings: four number slots, bump / flat pair and shadow pass as intended")
end

section("Pure rules: stages, caps, depths")
do
	assert(Wd.stage_of(0) == 0 and Wd.stage_of(0.1) == 1 and Wd.stage_of(0.4) == 2 and Wd.stage_of(2) == 3
		and Wd.stage_of(4) == 4 and Wd.stage_of(9) == 5)
	assert(Wd.stage_of(9, 3) == 3 and Wd.stage_of(9, Wd.cap_of(1, "bullet")) == 3 and Wd.stage_of(9, Wd.cap_of(2, "bullet")) == 4
		and Wd.stage_of(9, Wd.cap_of(4, "bullet")) == 5 and Wd.stage_of(9, Wd.cap_of(2, "slug")) == 5
		and Wd.stage_of(9, Wd.cap_of(1, "melee")) == 2 and Wd.stage_of(9, Wd.cap_of(1, "frag")) == 3)
	assert(Wd.section_class("body") == "body" and Wd.section_class("bip01_head") == "head" and Wd.section_class("bone01") == "head"
		and Wd.section_class("bip01_l_forearm") == "lower" and Wd.section_class("bip01_r_hand") == "end"
		and Wd.section_class("bip01_l_thigh") == "upper" and Wd.section_class("bip01_l_horselink") == "end")
	-- depth grows with the stage and progress, never past 85 % of the thickness; bone from stage 4
	local site = { thick = 0.09, depth = 0.045 }
	local last = 0
	for st = 2, 5 do
		for p = 0, 1, 0.25 do
			local d, bone = Wd.depth_of(st, p, site, "upper")
			assert(d >= last - 1e-9 and d <= 0.85 * site.thick + 1e-9, ("stage %d p %.2f: %.4f"):format(st, p, d))
			assert(bone == (st >= 4))
			last = d
		end
	end
	local dh = Wd.depth_of(4, 1, { thick = 0.16, depth = 0.06 }, "head")
	local db = Wd.depth_of(4, 1, { thick = 0.24, depth = 0.11 }, "body")
	assert(dh <= 0.03 and db > dh, "heads crater shallow")
	assert(Wd.level_of(0.0126) == 6 and Wd.level_of(1) == 63)
	print("  stage thresholds, calibre caps, depth limits OK")
end

section("No wound sites (the harness's own model, ZGO_BAKED=" .. (BAKED and 1 or 0) .. "): wounds change nothing")
do
	local function round(on_)
		OVR["wounds/enable"] = on_
		CB.on_level_changing() frame()
		run(5000, 100)     -- (the effect budget is per second: start each round fresh)
		math.randomseed(seed * 7 + 1)
		clear()
		local npc = NEW_NPC(100, "stalker", VV(0, 0, 3))
		for _ = 1, 6 do shoot(npc, "bip01_spine1", "ammo_7.62x54_7h1") end
		shoot(npc, "bip01_head", "ammo_12x76_zhekan", { kill = true })
		for _ = 1, 4 do shoot(npc, "bip01_l_forearm", "ammo_12x76_zhekan") end
		settle(300)
		local r = ("%d placed, %d on bodies, %d effects, %d gibs"):format(#PLACED, #BODY, #FX, gib_atts())
		OBJ[100] = nil
		return r
	end
	assert(zgo_bake.wound_sites(WOUNDS_VISUAL) == nil, "the harness model has no wound sites")
	local a, b = round(true), round(false)
	OVR["wounds/enable"] = nil
	print("  with wounds: " .. a .. "; without: " .. b)
	assert(a == b and #MINE.marks == 0 and #MINE.gibs == 0 and Wd.stats().matched == 0)
end

local bake = WOUNDS_BAKE({ damage = false })
section("Bake installed (sites on every section): a hit finds its site")
do
	assert(zgo_bake.wound_sites(WOUNDS_VISUAL) and not zgo_bake.features().damage)
	local npc = NEW_NPC(101, "stalker", VV(1, 0, 4))
	-- surface points: every site of every section
	local n = 0
	for _, sec in ipairs(bake.names) do
		for i = 1, #WOUNDS_SPEC[sec] do
			local s = WOUNDS_SPEC[sec][i]
			local ls, site = Wd.locate(npc, s[1], site_point(npc, sec, i, 0.004), VV(-s[5], -s[6], -s[7]), -1)
			assert(ls == sec and site.index == i, ("site %s#%d found as %s#%s"):format(sec, i, tostring(ls), tostring(site and site.index)))
			n = n + 1
		end
	end
	-- the engine's fallback point (the bone itself): the side the round came from wins
	local f1, s1 = Wd.locate(npc, "bip01_spine1", npc:bone_position("bip01_spine1"), VV(0, 0, -1), -1)
	local f2, s2 = Wd.locate(npc, "bip01_spine1", npc:bone_position("bip01_spine1"), VV(0, 0, 1), -1)
	assert(f1 == "body" and s1.index == 1 and f2 == "body" and s2.index == 2, "front from the front, back from behind")
	local e1, x1 = Wd.locate(npc, "bip01_spine1", VV(1, 1.25, 3.8), VV(0, 0, -1), 1)
	assert(e1 == "body" and x1.index == 2, "the exit is on the back")
	-- far from every site (a hand-held weapon, the floor): nothing
	assert(Wd.locate(npc, "bip01_spine1", VV(1, 1.25, 4.6), VV(0, 0, -1), -1) == nil)
	-- the object turned and moved: the same bind point
	npc._yaw, npc._pos = 1.1, VV(-3, 0.5, 2)
	local t, ts = Wd.locate(npc, "bip01_l_forearm", site_point(npc, "bip01_l_forearm", 1, 0.003))
	assert(t == "bip01_l_forearm" and ts.index == 1)
	OBJ[101] = nil
	print(("  %d sites found from their surface points; entry / exit sides; turned body OK"):format(n))
end

section("Stages: a rifle on one spot, bruise -> open -> crater -> bone (rifles stop there)")
do
	clear()
	local npc = NEW_NPC(110, "stalker", VV(0, 0, 3))
	local seen, levels = {}, {}
	for k = 1, 8 do
		hit(npc, "body", 1, "ammo_5_45x39_fmj")
		local w = wound(npc, "body", 1)
		seen[#seen + 1] = w.stage
		levels[#levels + 1] = w.level
	end
	print("  5.45 stages " .. table.concat(seen, " ") .. ", depth (2 mm) " .. table.concat(levels, " "))
	assert(seen[1] == 2 and seen[3] == 3 and seen[5] == 4 and seen[8] == 4, "2 at once, 3 after 3 hits, 4 after 5, never 5")
	for k = 2, #levels do assert(levels[k] >= levels[k - 1], "never shallower") end
	local w = wound(npc, "body", 1)
	assert(w.bone and w.level * 0.002 <= 0.85 * 0.24 + 1e-9 and w.level * 0.002 >= 0.03 - 1e-9)
	-- stage 3 and 4 left larger marks, once per stage; a body that lives
	-- throws no chunks (1.7.1: only a kill or a corpse does)
	run(400)
	assert(#MINE.gibs == 0 and #MINE.marks == 3, ("living body: %d chunk bursts, %d marks"):format(#MINE.gibs, #MINE.marks))
	for _, m in ipairs(MINE.marks) do assert(m.sec:find("^zgo_p_wound_") or m.sec:find("^zgo_p_splash_")) end
	-- the same rounds into a corpse: stage 3 and 4 throw chunks, a moment later
	local corpse = NEW_NPC(197, "stalker", VV(0, 0, 3))
	corpse._alive, corpse.health = false, 0
	for k = 1, 5 do hit(corpse, "body", 1, "ammo_5_45x39_fmj") end
	assert(#MINE.gibs == 0, "chunks wait for the killing hit to land")
	run(400)
	assert(#MINE.gibs == 2, ("corpse: %d chunk bursts"):format(#MINE.gibs))
	assert(gib_atts() >= 3, "chunks are in the level")
	OBJ[197] = nil
	-- a pistol never goes past a crater; melee past an open wound; armour that stops it: a bruise
	for _ = 1, 12 do hit(npc, "body", 3, "ammo_9x18_fmj") end
	assert(wound(npc, "body", 3).stage == 3)
	for _ = 1, 12 do hit(npc, "body", 4, B.melee()) end
	assert(wound(npc, "body", 4).stage == 2)
	for _ = 1, 12 do hit(npc, "body", 6, "ammo_9x18_fmj", { penetrated = false }) end
	assert(wound(npc, "body", 6).stage == 1 and wound(npc, "body", 6).level == 0)
	-- a slug craters at once and goes all the way
	hit(npc, "body", 7, "ammo_12x76_zhekan")
	assert(wound(npc, "body", 7).stage == 3)
	hit(npc, "body", 7, "ammo_12x76_zhekan") hit(npc, "body", 7, "ammo_12x76_zhekan")
	assert(wound(npc, "body", 7).stage == 5 and npc._alive, "the torso is destroyed, nothing comes off")
	-- an exit wound on the far side
	local before = nwounds(npc)
	hit(npc, "body", 1, "ammo_7.62x54_7h1", { exits = true })
	assert(wound(npc, "body", 2) and wound(npc, "body", 2).stage >= 2 and nwounds(npc) == before + 1)
	-- MCM: how fast wounds deepen
	OVR["wounds/growth"] = 2
	local npc2 = NEW_NPC(111, "stalker", VV(2, 0, 3))
	hit(npc2, "body", 1, "ammo_5_45x39_fmj") hit(npc2, "body", 1, "ammo_5_45x39_fmj")
	assert(wound(npc2, "body", 1).stage == 3, "growth 2: a crater after 2 hits")
	OVR["wounds/growth"] = nil
	-- MCM: no chunks, no marks
	OVR["wounds/chunks"], OVR["wounds/marks"] = false, false
	clear()
	for _ = 1, 4 do hit(npc2, "body", 3, "ammo_7.62x54_7h1") end
	assert(wound(npc2, "body", 3).stage == 4 and #MINE.gibs == 0 and #MINE.marks == 0)
	OVR["wounds/chunks"], OVR["wounds/marks"] = nil, nil
	-- Dismemberment -> Gibs off: no chunks either
	OVR["dismember/gibs"] = false
	for _ = 1, 4 do hit(npc2, "body", 4, "ammo_7.62x54_7h1") end
	assert(#MINE.gibs == 0)
	OVR["dismember/gibs"] = nil
	-- Performance: wounds kept per body
	OVR["performance/wound_sites"] = 3
	local npc3 = NEW_NPC(112, "stalker", VV(-2, 0, 3))
	hit(npc3, "body", 1, "ammo_7.62x54_7h1") hit(npc3, "body", 1, "ammo_7.62x54_7h1")
	for i = 2, 6 do hit(npc3, "body", i, "ammo_9x18_fmj") end
	assert(nwounds(npc3) == 3 and wound(npc3, "body", 1) and wound(npc3, "body", 6), "the lightest go, the deepest and the newest stay")
	OVR["performance/wound_sites"] = nil
	-- MCM: off
	OVR["wounds/enable"] = false
	local n0 = nwounds(npc3)
	hit(npc3, "bip01_head", 1, "ammo_7.62x54_7h1")
	assert(nwounds(npc3) == n0)
	OVR["wounds/enable"] = nil
	for _, id in ipairs({ 110, 111, 112 }) do OBJ[id] = nil end
end

section("Through the game's own path: shots, a kill, a corpse, an explosion")
do
	clear()
	CB.on_level_changing() frame()
	local npc = NEW_NPC(120, "stalker", VV(0, 0, 3))
	for _ = 1, 3 do shoot(npc, "bip01_spine1", "ammo_7.62x54_7h1") end
	local w = wound(npc, "body", 1)
	assert(w and w.stage >= 3, "three 7.62x54R in the chest: a crater at least")
	shoot(npc, "bip01_head", "ammo_5_45x39_fmj", { kill = true })
	assert(wound(npc, "bip01_head", 1), "the face")
	-- corpse hits (player rounds into a body)
	for _ = 1, 2 do shoot(npc, "bip01_l_upperarm", "ammo_12x76_zhekan", { dir = VV(0, 0, -1) }) end
	settle(100)
	local ua = wound(npc, "bip01_l_upperarm", 1)
	assert(ua and ua.stage >= 4, "corpse hits count")
	-- an explosion next to a fresh one: fragment wounds and the side facing it torn
	local v = NEW_NPC(121, "stalker", VV(4, 0, 0))
	explode(VV(4, 0.3, 1.6), { v }, { eid = 950 })
	settle(400)
	local st = Wd.get_state()[121]
	assert(st and nwounds(v) >= 2, "fragments and the blast wave wounded it")
	local front
	for _, i in ipairs({ 1, 3, 4, 6 }) do
		local w = wound(v, "body", i)
		if w and (not front or w.stage > front.stage) then front = w end
	end
	assert(front and front.stage >= 3, "the side that faced the blast")
	assert(not wound(v, "body", 2) and not wound(v, "body", 5), "not the back")
	print(("  shots: chest stage %d; kill + corpse hits: upper arm stage %d; grenade: %d wounds, front stage %d"):format(
		w.stage, ua.stage, nwounds(v), front.stage))
	OBJ[120], OBJ[121] = nil, nil
end

section("Destroyed parts: dead bodies lose them (Dismemberment rules), the living never")
do
	clear()
	OVR["dismember/chance"] = 0     -- (only the wound decides here)
	local live = NEW_NPC(130, "stalker", VV(0, 0, 3))
	for _ = 1, 4 do hit(live, "bip01_l_forearm", 1, "ammo_12x76_zhekan") end
	assert(wound(live, "bip01_l_forearm", 1).stage == 5 and not zgo_dismember.bone_gone(live, "bip01_l_forearm"))
	local dead = NEW_NPC(131, "stalker", VV(2, 0, 3))
	dead._alive, dead._died_at = false, T_NOW - 1000
	frame()
	for _ = 1, 4 do hit(dead, "bip01_l_forearm", 1, "ammo_12x76_zhekan", { dead = true }) end
	settle(200)
	assert(wound(dead, "bip01_l_forearm", 1).stage == 5)
	assert(zgo_dismember.bone_gone(dead, "bip01_l_forearm"), "the destroyed forearm came off")
	-- not from someone else's rounds (Dismemberment is the players' and explosions')
	local dead2 = NEW_NPC(132, "stalker", VV(-2, 0, 3))
	dead2._alive, dead2._died_at = false, T_NOW - 1000
	for _ = 1, 4 do hit(dead2, "bip01_r_forearm", 1, "ammo_12x76_zhekan", { dead = true, allow = false }) end
	assert(not zgo_dismember.bone_gone(dead2, "bip01_r_forearm"))
	-- MCM: off, and Dismemberment -> limbs off
	OVR["wounds/sever"] = false
	for _ = 1, 4 do hit(dead2, "bip01_l_calf", 1, "ammo_12x76_zhekan", { dead = true }) end
	assert(not zgo_dismember.bone_gone(dead2, "bip01_l_calf"))
	OVR["wounds/sever"], OVR["dismember/limbs"] = nil, false
	for _ = 1, 4 do hit(dead2, "bip01_r_calf", 1, "ammo_12x76_zhekan", { dead = true }) end
	assert(not zgo_dismember.bone_gone(dead2, "bip01_r_calf"))
	OVR["dismember/limbs"], OVR["dismember/chance"] = nil, nil
	settle(200)
	CHECK_CUTS("wound severs")
	print(("  severed by wounds: %d"):format(Wd.stats().severs))
	for _, id in ipairs({ 130, 131, 132 }) do OBJ[id] = nil end
end

section("Kid mode: wounds tracked, nothing gory drawn")
do
	clear()
	OVR["general/kid_mode"] = true
	frame()
	local npc = NEW_NPC(140, "stalker", VV(0, 0, 3))
	local g0 = gib_atts()
	for _ = 1, 4 do hit(npc, "body", 1, "ammo_7.62x54_7h1") end
	settle(100)
	assert(wound(npc, "body", 1).stage == 4, "tracked")
	assert(#BODY == 0 and gib_atts() == g0, "no marks, no chunks on screen")
	for _, m in ipairs(MINE.marks) do assert(not m.drawn) end
	OVR["general/kid_mode"] = nil
	frame()
	OBJ[140] = nil
end

section("Save and load (single player)")
do
	clear()
	CB.on_level_changing() frame()
	local a = NEW_NPC(150, "stalker", VV(0, 0, 3))
	local b = NEW_NPC(151, "stalker", VV(1, 0, 3))
	for _ = 1, 3 do hit(a, "body", 1, "ammo_7.62x54_7h1") end
	hit(a, "bip01_head", 2, "ammo_9x18_fmj")
	for _ = 1, 2 do hit(b, "bip01_r_thigh", 3, "ammo_5_45x39_fmj") end
	local sa, sb = summary(a), summary(b)
	local data = SAVE_GAME()
	assert(type(data.zgo_wounds) == "table" and data.zgo_wounds[150] and data.zgo_wounds[151])
	CB.load_state(data)
	assert(nwounds(a) == 0, "nothing until the body is back")
	-- b is offline for now; a comes online
	OBJ[151] = nil
	settle(3000)
	assert(summary(a) == sa, "same wounds after loading: " .. summary(a) .. " / " .. sa)
	-- saving again before b came back keeps b's wounds
	local data2 = SAVE_GAME()
	assert(data2.zgo_wounds[151] == data.zgo_wounds[151])
	OBJ[151] = b
	settle(3000)
	assert(summary(b) == sb)
	-- the id is released (and reused for someone else)
	CB.server_entity_on_unregister({ id = 151 })
	assert(Wd.get_state()[151] == nil)
	a._sec = "sim_default_bandit_2"
	hit(a, "body", 3, "ammo_9x18_fmj")
	assert(nwounds(a) == 1 and wound(a, "body", 3), "another body with this id starts fresh")
	print("  " .. sa .. " | " .. sb)
	OBJ[150] = nil
end

section("Wound craters (experimental) need damage meshes: off and harmless without them")
do
	clear()
	OVR["wounds/dents"] = true
	CB.on_level_changing() frame()
	local calls = CUTS_SET_CALLS
	local npc = NEW_NPC(160, "stalker", VV(0, 0, 3))
	for _ = 1, 3 do hit(npc, "body", 1, "ammo_7.62x54_7h1") end
	settle(600)
	assert(CUTS_SET_CALLS == calls and next(Wd.get_applied()) == nil)
	assert(logged("wound craters %(experimental%): off: the baked models have no damage meshes"))
	OBJ[160] = nil
	OVR["wounds/dents"] = nil
end

bake = WOUNDS_BAKE({ damage = true })
section("Wound craters (experimental): the damage mesh takes over, per section")
do
	clear()
	CB.on_level_changing() frame()
	local npc = NEW_NPC(170, "stalker", VV(0, 0, 3))
	for _ = 1, 3 do hit(npc, "body", 1, "ammo_7.62x54_7h1") end
	hit(npc, "bip01_head", 1, "ammo_5_45x39_fmj")
	settle(600)
	local calls = CUTS_SET_CALLS
	assert(next(Wd.get_applied()) == nil and CUTS_SHADER(npc, 15) == "zgo\\off" and CUTS_SHADER(npc, 1) == "models\\model",
		"off by default: today's marks only")
	OVR["wounds/dents"] = true
	settle(600)
	assert(CUTS_SHADER(npc, 1) == "zgo\\off" and CUTS_SHADER(npc, 15) == "zgo\\dmg", "body: C off, D on")
	assert(CUTS_SHADER(npc, 2) == "zgo\\off" and CUTS_SHADER(npc, 16) == "zgo\\dmg", "head too")
	assert(CUTS_SHADER(npc, 3) == "models\\model" and CUTS_SHADER(npc, 17) == "zgo\\off", "an unwounded arm stays as it was")
	local tb = npc:get_shaders(false)[15].texture
	local th = npc:get_shaders(false)[16].texture
	assert(tb:find("^act\\act_stalker_neutral,zgo_dmg_%x+_act\\act_stalker_neutral_bump$"), tb)
	assert(th:find("^act\\act_face_1,zgo_dmg_%x+$"), "no bump map for the face: the flat pair: " .. th)
	local w = wound(npc, "body", 1)
	assert(numbers(tb)[1] == Wd.pack(1, w.level, w.bone) and numbers(tb)[2] == 0, tb)
	-- more wounds on the body: deepest first, four at most
	for i = 2, 7 do hit(npc, "body", i, "ammo_5_45x39_fmj") end
	hit(npc, "body", 8, "ammo_12x76_zhekan")
	settle(600)
	local nums = numbers(npc:get_shaders(false)[15].texture)
	assert(#nums == 4 and nums[1] % 32 == 1 or nums[1] % 32 == 8, "the deepest first")
	for k = 1, 4 do assert(nums[k] > 0) end
	for k = 2, 4 do assert(math.floor(nums[k] / 32) % 64 <= math.floor(nums[k - 1] / 32) % 64) end
	print(("  body %s; head %s; %d set_shader calls"):format(npc:get_shaders(false)[15].texture, th, CUTS_SET_CALLS - calls))
	-- unchanged wounds: nothing set again
	calls = CUTS_SET_CALLS
	settle(3000)
	assert(CUTS_SET_CALLS == calls, "nothing new, nothing set")
	-- the engine dropped the overrides (offline / online): put back
	npc:reset_shader(-1, false)
	settle(3000)
	assert(CUTS_SHADER(npc, 15) == "zgo\\dmg" and CUTS_SHADER(npc, 1) == "zgo\\off")
	-- kid mode: everything back to the model's own at once, and back again after
	OVR["general/kid_mode"] = true
	frame() frame()
	assert(CUTS_SHADER(npc, 15) == "zgo\\off" and CUTS_SHADER(npc, 1) == "models\\model" and next(Wd.get_applied()) == nil)
	settle(600)
	assert(CUTS_SHADER(npc, 15) == "zgo\\off")
	OVR["general/kid_mode"] = nil
	settle(600)
	assert(CUTS_SHADER(npc, 15) == "zgo\\dmg")
	-- Performance: bodies with craters (nearest first)
	local far = NEW_NPC(171, "stalker", VV(0, 0, 20))
	for _ = 1, 3 do hit(far, "body", 1, "ammo_7.62x54_7h1") end
	settle(600)
	assert(CUTS_SHADER(far, 15) == "zgo\\dmg")
	OVR["performance/wound_npcs"] = 1
	settle(600)
	assert(CUTS_SHADER(far, 15) == "zgo\\off" and CUTS_SHADER(far, 1) == "models\\model" and CUTS_SHADER(npc, 15) == "zgo\\dmg")
	OVR["performance/wound_npcs"] = 0
	settle(600)
	assert(CUTS_SHADER(npc, 15) == "zgo\\off")
	OVR["performance/wound_npcs"] = nil
	settle(600)
	-- a section cut off on a dead body is left to zgo_dismember
	npc._alive, npc._died_at = false, T_NOW - 1000
	OVR["dismember/chance"] = 0
	for _ = 1, 2 do hit(npc, "bip01_l_forearm", 1, "ammo_5_45x39_fmj", { dead = true }) end
	settle(600)
	assert(CUTS_SHADER(npc, 18) == "zgo\\dmg" and CUTS_SHADER(npc, 4) == "zgo\\off")
	for _ = 1, 3 do hit(npc, "bip01_l_forearm", 1, "ammo_12x76_zhekan", { dead = true }) end
	settle(600)
	assert(zgo_dismember.bone_gone(npc, "bip01_l_forearm"))
	assert(CUTS_SHADER(npc, 18) == "zgo\\off", "the cut section's damage mesh is off again")
	assert(npc._hidden.bip01_l_forearm, "and the forearm is hidden by the cut")
	OVR["dismember/chance"] = nil
	-- the option off: everything back
	OVR["wounds/dents"] = false
	settle(600)
	assert(CUTS_SHADER(npc, 15) == "zgo\\off" and CUTS_SHADER(npc, 1) == "models\\model" and CUTS_SHADER(far, 15) == "zgo\\off")
	OBJ[170], OBJ[171] = nil, nil
end

section("Wound craters: fail-safe")
do
	OVR["wounds/dents"] = true
	local function body(id)
		local o = NEW_NPC(id, "stalker", VV(0, 0, 3))
		for _ = 1, 3 do hit(o, "body", 1, "ammo_7.62x54_7h1") end
		return o
	end
	-- DirectX 9 renderers: never (unknown shader names are fatal there)
	WOUNDS_RENDERER = "renderer_r2"
	CB.on_level_changing() frame()
	local calls = CUTS_SET_CALLS
	local a = body(180)
	settle(600)
	assert(CUTS_SET_CALLS == calls and logged("needs the DirectX 10 or 11 renderer"))
	WOUNDS_RENDERER = nil   -- (no such command)
	CB.on_level_changing() frame()
	settle(600)
	assert(CUTS_SET_CALLS == calls)
	WOUNDS_RENDERER = "renderer_r4"
	OBJ[180] = nil
	-- an exe without the shader API
	CUTS_NO_SHADER_API = true
	CB.on_level_changing() frame()
	local b = body(181)
	settle(600)
	assert(CUTS_SET_CALLS == calls and logged("no set_shader / reset_shader"))
	CUTS_NO_SHADER_API = nil
	OBJ[181] = nil
	-- set_shader raises: caught, undone, off until the next level
	CUTS_SHADER_ERROR = true
	CB.on_level_changing() frame()
	local c = body(182)
	settle(600)
	CUTS_SHADER_ERROR = nil
	assert(logged("set_shader failed") and next(Wd.get_applied()) == nil and CUTS_SHADER(c, 1) == "models\\model")
	settle(600)
	assert(next(Wd.get_applied()) == nil, "stays off")
	OBJ[182] = nil
	-- another mod's model wins (other sub-mesh count): not this one
	CB.on_level_changing() frame()
	CUTS_MODELS[WOUNDS_VISUAL].n = 25
	zgo_bake.reset()
	local d = body(183)
	settle(600)
	assert(next(Wd.get_applied()) == nil and CUTS_SHADER(d, 15) == "zgo\\off")
	CUTS_MODELS[WOUNDS_VISUAL].n = 24
	zgo_bake.reset()
	settle(3000)
	assert(CUTS_SHADER(d, 15) == "zgo\\dmg", "the right model again")
	OBJ[183] = nil
	OVR["wounds/dents"] = nil
	settle(600)
	-- the errors above were on purpose
	for i = #LOG, 1, -1 do if LOG[i]:find("set_shader failed") then table.remove(LOG, i) end end
	print("  DX9, no console command, no shader API, set_shader raising, another model: craters off, nothing breaks")
end

section("The baker's own fixture bake (synthetic model): sites and damage meshes line up")
do
	WOUNDS_FIXTURE()
	CB.on_level_changing() frame()
	local v = "actors\\synth\\synth_a"
	local npc = NEW_NPC(190, "stalker", VV(0, 0, 3))
	npc._visual = v
	CUTS_MODELS[v] = { n = zgo_bake.expected_children(v) }
	local W = assert(zgo_bake.wound_sites(npc))
	-- every site, from a point on it: the right section and site
	local n = 0
	for sec, list in pairs(W.sections) do
		for _, s in ipairs(list) do
			if npc:get_bone_id(s.bone) ~= 65535 then
				local bm = W.skel.by_name[s.bone]
				local p = Wd.bind_to_world(bm, npc:bone_transform(s.bone), s.pos)
				local ls, site = Wd.locate(npc, s.bone, p)
				assert(ls == sec and site.index == s.index, ("%s#%d -> %s#%s"):format(sec, s.index, tostring(ls), tostring(site and site.index)))
				n = n + 1
			end
		end
	end
	-- a crater on the body: its damage mesh (19, for child 1)
	OVR["wounds/dents"] = true
	local s = W.sections.body[1]
	local p = Wd.bind_to_world(W.skel.by_name[s.bone], npc:bone_transform(s.bone), s.pos)
	for _ = 1, 3 do
		zgo_util.emit_event("hit", npc, { id = 190, bone = s.bone, pos = p, dir = VV(0, 0, -1), prof = prof("ammo_7.62x54_7h1"),
			vol = 1, penetrated = true, exits = false, dead = false, was_dead = false })
	end
	settle(600)
	assert(CUTS_SHADER(npc, 1) == "zgo\\off" and CUTS_SHADER(npc, 19) == "zgo\\dmg", "child 1 -> damage mesh 19")
	print(("  %d fixture sites found; body crater on child 19: %s"):format(n, npc:get_shaders(false)[19].texture))
	OVR["wounds/dents"] = nil
	settle(600)
	OBJ[190] = nil
	WOUNDS_BAKE({ damage = true })
end

section("Errors")
assert(errs() == 0)
assert(CHECK_CUTS("end") >= 0)

section("Co-op: host and client")
do
	local wire = os.tmpname()
	local ok = true
	for _, r in ipairs({ "host", "client" }) do
		local p = io.popen(('ZGO_WOUNDS_WIRE="%s" luajit "%s/zgo_test_wounds.lua" %s %d 2>&1'):format(wire, S, r, seed))
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
print("\nALL WOUNDS TESTS PASSED")

------------------------------------------------------------------------
elseif role == "host" then
------------------------------------------------------------------------
local WIRE = assert(os.getenv("ZGO_WOUNDS_WIRE"), "ZGO_WOUNDS_WIRE")
WOUNDS_BAKE({ damage = true })
local npc = NEW_NPC(500, "stalker", VV(0, 0, 3))
local npc2 = NEW_NPC(501, "stalker", VV(2, 0, 3))
clear()
for _ = 1, 4 do hit(npc, "body", 1, "ammo_7.62x54_7h1") end
hit(npc, "bip01_l_upperarm", 1, "ammo_5_45x39_fmj")
hit(npc, "bip01_l_upperarm", 1, "ammo_5_45x39_fmj")
hit(npc, "body", 5, "ammo_9x18_fmj", { penetrated = false })     -- a bruise: not sent
settle(600)
zgo_sync.flush()
local wl, gl = lines("Y", "w"), lines("Y", "g")
print(("  host: %d Y|w lines, %d Y|g lines; drew %d chunk bursts here"):format(#wl, #gl, #MINE.gibs))
assert(#wl >= 1 and #gl == #MINE.gibs and #gl >= 2)
local last
for _, l in ipairs(wl) do
	local t = split(l)
	assert(#t == 5 and tonumber(t[3]) == 500 and t[4] == npc:section(), l)
	last = l
end
assert(not last:find("body,0,1100") and #Wd.decode(split(last)[5]) == 2, "two wounds worth drawing: " .. last)
for _, l in ipairs(gl) do
	local t = split(l)
	assert(#t == 11 and tonumber(t[3]) == 500 and tonumber(t[11]) and tonumber(t[10]) >= 1, l)
end
-- kid mode on the host: nothing drawn here, the lines still go
clear()
OVR["general/kid_mode"] = true
local g0 = gib_atts()
for _ = 1, 4 do hit(npc2, "bip01_head", 1, "ammo_12x76_zhekan") end
settle(600)
zgo_sync.flush()
local kw, kg = lines("Y", "w"), lines("Y", "g")
assert(#kw >= 1 and #kg >= 1 and gib_atts() == g0 and #BODY == 0, "kid mode host: lines out, nothing on screen")
OVR["general/kid_mode"] = nil
-- the rebroadcast covers both bodies for late joiners
clear()
run(21000, 100)
zgo_sync.flush()
local rb = lines("Y", "w")
local ids = {}
for _, l in ipairs(rb) do ids[tonumber(split(l)[3])] = true end
assert(ids[500] and ids[501], "rebroadcast")
-- a healed living body: partners forget it too
local f = assert(io.open(WIRE, "w"))
f:write(last, "\n", table.concat(gl, ";"), "\n", summary(npc), "\n", kw[#kw], "\n", kg[1], "\n")
f:close()
assert(errs() == 0)
print("WOUNDS HOST OK")

------------------------------------------------------------------------
else -- client
------------------------------------------------------------------------
local WIRE = assert(os.getenv("ZGO_WOUNDS_WIRE"), "ZGO_WOUNDS_WIRE")
local f = assert(io.open(WIRE, "r"))
local wline, glines, hsum, kwline, kgline = f:read("*l"), f:read("*l"), f:read("*l"), f:read("*l"), f:read("*l")
f:close()
WOUNDS_BAKE({ damage = true })
OVR["wounds/dents"] = true
local npc = NEW_NPC(500, "stalker", VV(0, 0, 3))
local npc2 = NEW_NPC(501, "stalker", VV(2, 0, 3))
clear()
-- the client never decides: its own hits make nothing
for _ = 1, 4 do hit(npc2, "body", 1, "ammo_7.62x54_7h1") end
settle(600)
assert(nwounds(npc2) == 0 and #SENT == 0 and #MINE.gibs == 0)
-- the host's wounds: the same sites, stages and depths here, craters drawn here
DISPATCH(zgo_sync.EVT, wline, "host")
settle(600)
print(("  client: host %s / here %s"):format(hsum, summary(npc)))
assert(summary(npc) == hsum, "same wounds as the host")
assert(CUTS_SHADER(npc, 15) == "zgo\\dmg" and CUTS_SHADER(npc, 17) == "zgo\\dmg" and CUTS_SHADER(npc, 1) == "zgo\\off")
-- the host's chunk bursts, from its seeds
local g0 = gib_atts()
local n = 0
for l in glines:gmatch("[^;]+") do DISPATCH(zgo_sync.EVT, l, "host") n = n + tonumber(split(l)[10]) end
settle(100)
assert(gib_atts() == g0 + n, ("%d chunks from the host, %d here"):format(n, gib_atts() - g0))
-- rubbish from the wire is dropped quietly
for _, bad in ipairs({ "Y|w|500", "Y|w|x|s|-", "Y|w|500|" .. npc:section() .. "|body,1,2", "Y|g|500|1|2", "Y|q|1|2|3", "Y|w|500|" .. npc:section() .. "|body,a,b,c,9,9,9" }) do
	DISPATCH(zgo_sync.EVT, bad, "host")
end
settle(600)
assert(errs() == 0)
-- kid mode here: the host's lines still arrive and are kept, nothing gory drawn
OVR["general/kid_mode"] = true
settle(100)
assert(CUTS_SHADER(npc, 15) == "zgo\\off" and CUTS_SHADER(npc, 1) == "models\\model")
g0 = gib_atts()
DISPATCH(zgo_sync.EVT, kwline, "host")
DISPATCH(zgo_sync.EVT, kgline, "host")
settle(600)
assert(gib_atts() == g0 and nwounds(npc2) >= 1 and CUTS_SHADER(npc2, 16) ~= "zgo\\dmg")
OVR["general/kid_mode"] = nil
settle(600)
assert(CUTS_SHADER(npc2, 16) == "zgo\\dmg" and CUTS_SHADER(npc, 15) == "zgo\\dmg", "back after kid mode")
-- a line for a body that isn't here yet waits for it
OBJ[502] = nil
DISPATCH(zgo_sync.EVT, (wline:gsub("^Y|w|500|", "Y|w|502|")), "host")
settle(100)
local late = NEW_NPC(502, "stalker", VV(-2, 0, 3))
settle(3000)
assert(summary(late) == hsum, "applied when it came online")
-- the host forgot a body: so does this machine
DISPATCH(zgo_sync.EVT, "Y|w|502|" .. late:section() .. "|-", "host")
settle(600)
assert(nwounds(late) == 0 and CUTS_SHADER(late, 15) == "zgo\\off")
-- a partner whose model comes from another bake: points far from its sites are dropped
WOUNDS_BAKE({ damage = true, shift = 0.12 })
CB.on_level_changing() frame()
DISPATCH(zgo_sync.EVT, wline, "host")
settle(600)
assert(nwounds(npc) == 0, "nothing mapped onto the wrong sites")
assert(errs() == 0)
print("WOUNDS CLIENT OK")
end
