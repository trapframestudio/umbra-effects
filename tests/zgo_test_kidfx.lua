-- Kid mode for particles (run: luajit zgo_test_kidfx.lua [seed])
-- Gory particle effects draw through zgo\particle_* (ZGO's copies of the stock
-- particle shaders, whose pixel shader discards while the shader bus lane
-- zgo_view hides gore); everything else must be byte for byte what it was.
-- The snapshot and the classification come from dev/shadercheck/kidfx_pe.py.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 5
arg = { S .. "/../gamedata/scripts", "sp" }

-- shader bus as the exe has it (as in zgo_test_settings.lua)
BUS = { lanes = {}, sets = {} }
shader_bus = {
	try_register = function(id, owner, desc) assert(type(id) == "string" and type(owner) == "string" and type(desc) == "string") BUS.lanes[id] = { 0, 0, 0, 0 } return true end,
	has = function(id) return BUS.lanes[id] ~= nil end,
	set = function(id, x, y, z, w) assert(BUS.lanes[id], "set on unregistered lane " .. tostring(id)) BUS.lanes[id] = { x, y, z, w } BUS.sets[#BUS.sets + 1] = { x, y, z, w } end,
}
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local K = KIDFX
assert(K, "tests/mocks/kidfx.lua not loaded by the harness")
local MOCK = dofile(S .. "/../dev/shadercheck/blender_mock.lua")
local SNAPSHOT = S .. "/../dev/shadercheck/kidfx_snapshot.txt"
local R3 = S .. "/../gamedata/shaders/r3/"

local function section(t) print(("\n== %s"):format(t)) end
local fails = 0
local function check(ok, msg) if not ok then fails = fails + 1 print("  FAIL " .. msg) end return ok end

------------------------------------------------------------------------
section("Every particle file is in the kidfx snapshot; only shader lines differ from it")
local snap, nsnap = {}, 0
for line in io.lines(SNAPSHOT) do
	if not line:match("^#") and line:match("%S") then
		local rel, cls, stock, sha, reason = line:match("^([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]+)\t(.*)$")
		assert(rel, "bad snapshot line: " .. line)
		snap[rel] = { cls = cls, stock = stock, sha = sha, reason = reason }
		nsnap = nsnap + 1
	end
end
local files = K.files()
local by_class, seen = {}, {}
local fx = {}           -- rel -> { data, shader, texture, snap }
for _, f in ipairs(files) do
	local s = snap[f.rel]
	seen[f.rel] = true
	if check(s, f.rel .. " is not in the snapshot: run python3 dev/shadercheck/kidfx_pe.py apply") then
		local data = K.read(f.path)
		local shader, texture = nil, nil
		if f.rel:lower():match("%.pe$") then shader, texture = K.sprite(data) end
		local h = K.sha1(f.rel:lower():match("%.pe$") and K.normalized(data) or data)
		check(h == s.sha, f.rel .. " differs from the snapshot in more than its shader line")
		by_class[s.cls] = (by_class[s.cls] or 0) + 1
		fx[f.rel] = { data = data, shader = shader, texture = texture, snap = s }
	end
end
for rel in pairs(snap) do check(seen[rel], rel .. " is in the snapshot but not on disk") end
print(("  %d files (snapshot %d): %d gory, %d clean, %d carriers, %d groups"):format(#files, nsnap,
	by_class.gore or 0, by_class.clean or 0, by_class.carrier or 0, by_class.group or 0))
assert(#files > 500 and (by_class.gore or 0) > 50 and (by_class.clean or 0) > 50)

------------------------------------------------------------------------
section("Gory effects draw through zgo\\particle_*, the rest are untouched")
local applied, stock_gory, unmapped = 0, 0, 0
for rel, e in pairs(fx) do
	if e.shader and K.REVERSE[e.shader:lower()] then applied = applied + 1 end
end
local state = applied > 0 and "applied" or "reverted"
print("  state: " .. state .. (state == "reverted" and " (kidfx_pe.py revert was run: everything draws with the stock shaders)" or ""))
for rel, e in pairs(fx) do
	local s = e.snap
	if s.cls == "group" then
		check(e.shader == nil, rel .. ": a group has no shader")
	elseif s.cls == "gore" then
		local want = K.MAP[s.stock:lower()]
		if not want then
			unmapped = unmapped + 1
			check(e.shader == s.stock and s.reason:find("no kid%-mode copy"), rel .. ": unmapped gory shader not reported")
		elseif state == "applied" then
			check(e.shader == want, ("%s is gory: shader %s, expected %s"):format(rel, tostring(e.shader), want))
		else
			check(e.shader == s.stock, rel .. ": partly reverted")
			stock_gory = stock_gory + 1
		end
	else
		-- not gory: byte for byte the file it was (its shader line included)
		check(not (e.shader and K.REVERSE[e.shader:lower()]), rel .. " is " .. s.cls .. " but uses " .. tostring(e.shader))
		check(K.sha1(e.data) == s.sha, rel .. " (" .. s.cls .. ") is not byte-identical to the snapshot")
	end
end
print(("  %d gory effects on zgo\\particle_*, %d gory with a shader that has no kid-mode copy"):format(applied, unmapped))
if state == "applied" then assert(applied >= 100, "most gory effects are switched") end
-- spot checks on the rules: blood is gory, sparks / dust / armour / glass are not
local EXPECT = {
	["zgo/gush.pe"] = "gore", ["zgo/jet_strong.pe"] = "gore", ["srbd/effects/burst/srbd_hit_impact_blood_02.pe"] = "gore",
	["srbd/effects/debris/srbd_flesh.pe"] = "gore", ["srbd/headshot/debris_brain.pe"] = "gore",
	["srbd/headshot/srbd_upsplash.pe"] = "gore", ["srbd/effects/dust/srbd_hit_impact_blood_00.pe"] = "gore",
	["srbd/effects/hfx/body_impact_sparks_00.pe"] = "clean", ["srbd/headshot/debris_armor.pe"] = "clean",
	["srbd/headshot/debris_glass.pe"] = "clean", ["srbd/hit/srbd_hit_debris_cloth.pe"] = "clean",
	["srbd/effects/dust/srbd_hit_impact_smoke_00.pe"] = "clean", ["zgo/world/dust_earth.pe"] = "clean",
	["zgo/props/sparks.pe"] = "clean", ["srbd/hit/smoke_point_fingers_short.pe"] = "clean",
	["srbd/hit/srbd_single_blank_tracer.pe"] = "carrier",
}
for rel, cls in pairs(EXPECT) do
	if snap[rel] then check(snap[rel].cls == cls, rel .. " should be " .. cls .. ", is " .. snap[rel].cls) end
end
-- every zgo\particle_* name a .pe uses has its .s (shader "a\b" -> r3\a_b.s)
for rel, e in pairs(fx) do
	if e.shader and K.REVERSE[e.shader:lower()] then
		local f = R3 .. MOCK.lua_name(e.shader:lower()) .. ".s"
		check(K.read(f), rel .. ": " .. f .. " is missing")
	end
end

------------------------------------------------------------------------
section("The kid-mode .s files build the stock particle blender's elements (mocked blender)")
-- xray-monolith Blender_Particle.cpp (R4) with GAMMA's shaders.xr settings: blend p3 strict,
-- add p3, alpha_add p3, set p1, texture clamp on. dev/shadercheck/check.sh compares them
-- with this mod list's real shaders.xr as well.
local function pass(vs, ps, zwrite, ablend, src, dst, atest, aref, cw)
	return { vs = vs, gs = "null", ps = ps, fog = false, ztest = true, zfunc = "lessequal", zwrite = zwrite, ablend = ablend,
		src = src, dst = dst, atest = atest, aref = aref, colorwrite = cw }
end
local BLEND = {
	zgo_particle_blend = { prio = 3, strict = true, e = { pass("particle", "zgo_particle_kid", false, true, "srcalpha", "invsrcalpha", true, 0) } },
	zgo_particle_add = { prio = 3, strict = false, e = { pass("particle", "zgo_particle_kid", false, true, "one", "one", true, 0) } },
	zgo_particle_aadd = { prio = 3, strict = false, e = { pass("particle", "zgo_particle_kid", false, true, "srcalpha", "one", true, 0) } },
	zgo_particle_set = { prio = 1, strict = false, e = { pass("deffer_particle", "zgo_particle_kid_deffer", true, false, "one", "zero", false, nil) },
		shadow = pass("particle", "zgo_particle_kid", true, false, "one", "zero", true, 200, { false, false, false, false }) },
}
local TBASE = "jdude\\newblood\\bloodburst07_var4"
for name, want in pairs(BLEND) do
	local s, err = MOCK.load_file(R3 .. name .. ".s")
	if check(s, name .. ".s does not load: " .. tostring(err)) then
		check(MOCK.has_shader(s), name .. ".s has no normal(): the engine would look for a C++ blender")
		local els, eerr = MOCK.shader(s, TBASE, "null")
		check(not eerr, name .. ".s: " .. tostring(eerr))
		local idx = { 0, 1 }
		if want.shadow then idx[#idx + 1] = 2 end
		for _, i in ipairs(idx) do
			local el = els[i]
			local wp = i == 2 and want.shadow or want.e[1]
			if check(el and #el.passes == 1, ("%s E%d: one pass"):format(name, i)) then
				check(el.priority == want.prio and el.strict == want.strict, ("%s E%d priority %d/%s"):format(name, i, el.priority, tostring(el.strict)))
				check(not el.emissive and not el.distort and not el.wmark, name .. " flags")
				local p = el.passes[1]
				for _, k in ipairs({ "vs", "gs", "ps", "fog", "ztest", "zfunc", "zwrite", "ablend", "src", "dst", "atest", "aref" }) do
					check(p[k] == wp[k], ("%s E%d %s = %s, stock %s"):format(name, i, k, tostring(p[k]), tostring(wp[k])))
				end
				if wp.colorwrite then
					check(p.colorwrite and p.colorwrite[1] == false and p.colorwrite[4] == false, name .. " shadow colour writes off")
				else
					check(p.colorwrite == nil, name .. " colour writes left alone")
				end
				local tex = {}
				for _, t in ipairs(p.textures) do tex[t[1]] = t[2] end
				check(tex.s_base == TBASE and tex.s_position == "$user$position", name .. " textures")
				check(#p.samplers == 2 and p.samplers[1][1] == "smp_base" and p.samplers[1][2] == true
					and p.samplers[2][1] == "smp_nofilter", name .. " samplers (smp_base clamped, smp_nofilter)")
			end
		end
		for _, i in ipairs({ 3, 4 }) do check(els[i] == nil, ("%s E%d must not exist (stock has none)"):format(name, i)) end
		if not want.shadow then
			check(els[2] == nil, name .. " E2: priority 3 particles never reach the shadow map, stock E2 is unused")
		end
		print(("  %s: E0/E1%s match the stock blender"):format(name, want.shadow and "/E2" or ""))
	end
end
-- the mock is strict like luabind: a wrong call is caught, as the game would crash on it
do
	local tmp = os.tmpname()
	local f = io.open(tmp, "w")
	f:write('function normal(shader, t_base)\n  shader:begin("particle", "zgo_particle_kid"):blend(true, blend.srcalpha)\nend\n')
	f:close()
	local s = MOCK.load_file(tmp)
	local _, err = MOCK.shader(s, TBASE, "null")
	f = io.open(tmp, "w")
	f:write('function normal(shader, t_base)\n  shader:begin("particle", "particle")\n  shader:dx10texture("s_base", t_base)\nend\n')
	f:close()
	local s9 = MOCK.load_file(tmp)
	local _, err9 = MOCK.shader(s9, TBASE, "null", { api = "dx9" })
	os.remove(tmp)
	check(err and err:find("no match for blend"), "the blender mock catches a wrong blend() call")
	check(err9 and err9:find("dx10texture"), "the DX9 blender mock has no dx10* methods")
end

------------------------------------------------------------------------
section("DX8 / DX9: r1\\ and r2\\ fallbacks, so effects naming zgo\\particle_* still load there")
-- The DX8 (R1) and DX9 (R2) renderers read only their own shader folder, and their
-- CResourceManager::_GetBlender calls Debug.fatal for a shader name with neither a Lua .s nor a
-- C++ blender: without these, an exe other than DX10/DX11 would stop while loading particles.
-- They are the stock C++ blender (Blender_Particle.cpp, R1 / R2 branches) and hide nothing.
local LEGACY = {
	r2 = {
		zgo_particle_blend = { prio = 3, strict = true, e = { [0] = pass("particle", "particle", false, true, "srcalpha", "invsrcalpha", true, 0) } },
		zgo_particle_add = { prio = 3, strict = false, e = { [0] = pass("particle", "particle", false, true, "one", "one", true, 0) } },
		zgo_particle_aadd = { prio = 3, strict = false, e = { [0] = pass("particle", "particle", false, true, "srcalpha", "one", true, 0) } },
		zgo_particle_set = { prio = 1, strict = false, e = { [0] = pass("deffer_particle", "deffer_particle", true, false, "one", "zero", false, nil),
			[2] = pass("particle", "particle", true, false, "one", "zero", true, 200) } },
	},
	r1 = {
		zgo_particle_blend = { prio = 3, strict = true, all = pass("particle", "particle", false, true, "srcalpha", "invsrcalpha", true, 0) },
		zgo_particle_add = { prio = 3, strict = false, all = pass("particle", "particle", false, true, "one", "one", true, 0) },
		zgo_particle_aadd = { prio = 3, strict = false, all = pass("particle", "particle", false, true, "srcalpha", "one", true, 0) },
		zgo_particle_set = { prio = 1, strict = false, all = pass("particle", "particle", true, false, "one", "zero", true, 200) },
	},
}
local legacy_missing = {}
for _, r in ipairs({ "r1", "r2" }) do
	for name, want in pairs(LEGACY[r]) do
		local path = S .. "/../gamedata/shaders/" .. r .. "/" .. name .. ".s"
		if not K.read(path) then
			legacy_missing[#legacy_missing + 1] = r .. "/" .. name .. ".s"
		else
			local s, err = MOCK.load_file(path)
			if check(s, path .. " does not load: " .. tostring(err)) then
				local els, eerr = MOCK.shader(s, TBASE, "null", { api = "dx9" })
				check(not eerr, r .. "/" .. name .. ".s: " .. tostring(eerr))
				local wants = {}
				if want.all then for i = 0, 4 do wants[i] = want.all end
				else wants = { [0] = want.e[0], [1] = want.e[0], [2] = want.e[2] } end
				for i = 0, 4 do
					local el, wp = els[i], wants[i]
					if not wp then
						check(el == nil, ("%s/%s E%d must not exist"):format(r, name, i))
					elseif check(el and #el.passes == 1, ("%s/%s E%d: one pass"):format(r, name, i)) then
						check(el.priority == want.prio and el.strict == want.strict, ("%s/%s E%d sorting"):format(r, name, i))
						local p = el.passes[1]
						for _, k in ipairs({ "vs", "ps", "fog", "ztest", "zwrite", "ablend", "src", "dst", "atest", "aref" }) do
							check(p[k] == wp[k], ("%s/%s E%d %s = %s, stock %s"):format(r, name, i, k, tostring(p[k]), tostring(wp[k])))
						end
						check(p.colorwrite == nil, r .. "/" .. name .. " colour writes left alone")
						local tex = {}
						for _, t in ipairs(p.textures) do tex[t[1]] = t[2] end
						check(tex.s_base == TBASE and p.samplers[1][1] == "s_base" and p.samplers[1][2] == true,
							r .. "/" .. name .. ": s_base = t_base, clamped")
						if r == "r2" then
							check(tex.s_position == "$user$position" and #p.samplers == 2, name .. ": R2 soft particles (s_position)")
						else
							check(#p.samplers == 1, name .. ": R1 binds s_base only")
						end
					end
				end
			end
		end
	end
end
if #legacy_missing == 0 then
	print("  r1\\ and r2\\ zgo_particle_*.s match the stock DX8 / DX9 particle blender")
elseif state == "applied" then
	table.sort(legacy_missing)
	print("  WARNING: gamedata/shaders/" .. table.concat(legacy_missing, ", ") .. " missing: with gory effects on")
	print("  zgo\\particle_* the DX8 / DX9 exes stop at start-up. Run: python3 dev/shadercheck/kidfx_pe.py shaders")
	print("  --legacy --write (docs/integration/kidfx.md, request 1), or kidfx_pe.py revert.")
end

------------------------------------------------------------------------
section("The pixel shaders are the stock ones plus the two kid-mode lines")
for _, ps in ipairs({ { "zgo_particle_kid.ps", "particle.ps" }, { "zgo_particle_kid_deffer.ps", "deffer_particle.ps" } }) do
	local src = K.read(R3 .. ps[1])
	if check(src, ps[1] .. " missing") then
		check(src:find("shadercheck%-baseline: " .. ps[2]:gsub("%.", "%%.")), ps[1] .. " names its stock file")
		check(src:find("\nuniform float4 bus_zgo_view;"), ps[1] .. " declares the lane")
		local n = 0
		for _ in src:gmatch("bus_zgo_view%.x > 0%.5 && abs%(bus_zgo_view%.w %- 1%.0%) < 0%.001%) discard;") do n = n + 1 end
		check(n == 1, ps[1] .. " has the one discard")
		local added = 0
		for line in src:gmatch("[^\n]+") do if line:find("ZGO kid mode") then added = added + 1 end end
		check(added == 2, ps[1] .. ": exactly two added lines are marked")
	end
end

------------------------------------------------------------------------
section("Kid mode: the GPU drops the gory sprites, sparks / dust / armour still draw")
local ON, OFF, NOT_ARMED = { 1, 0, 0, 1 }, { 0, 0, 0, 1 }, { 1, 0, 0, 0 }
local hid, kept = 0, 0
for rel, e in pairs(fx) do
	local s = e.snap
	if e.shader and s.cls ~= "group" then
		local h = K.hidden(e.shader, ON)
		if s.cls == "gore" and K.MAP[s.stock:lower()] and state == "applied" then
			check(h, rel .. " (gory) still draws in kid mode")
			hid = hid + 1
		else
			check(not h, rel .. " (" .. s.cls .. ") vanishes in kid mode")
			kept = kept + 1
		end
		check(not K.hidden(e.shader, OFF), rel .. " vanishes with kid mode off")
		check(not K.hidden(e.shader, NOT_ARMED), rel .. " vanishes although the experimental option is off")
		check(not K.hidden(e.shader, nil), rel .. " vanishes with the lane never set")
	end
end
print(("  kid mode: %d gory sprites dropped, %d others still drawn"):format(hid, kept))
-- what ZGO plays on a flesh hit, and what the engine plays (knife on flesh, anomalies tearing a body)
local function tally(name)
	local h, v = 0, 0
	for _, x in ipairs(K.sprites(name)) do
		check(not x.missing, name .. ": " .. x.name .. " is missing")
		if not x.missing and not x.carrier then
			if K.hidden(x.shader, ON) then h = h + 1 else v = v + 1 end
		end
	end
	return h, v
end
if state == "applied" then
	for _, n in ipairs({ "srbd\\srbd_hit_flesh_00", "srbd\\srbd_hit_flesh_01", "srbd\\srbd_hit_flesh_02", "srbd\\srbd_hit_flesh_02a",
		"srbd\\fingers\\fractional\\5\\5\\srbd_hit_finger_out", "zgo\\exit_spray_heavy", "zgo\\gush", "zgo\\drip_fall",
		"hit_fx\\effects\\hit_bb_07_knife", "anomaly2\\effects\\body_tear_blood_16" }) do
		if K.effect(n) then
			local h, v = tally(n)
			check(h > 0, n .. ": nothing of it vanishes in kid mode")
			print(("  %-50s %2d sprites dropped, %2d kept"):format(n, h, v))
		end
	end
	for _, n in ipairs({ "srbd\\hit\\body_impact_sparks_00", "srbd\\fingers\\fractional\\5\\5\\srbd_hit_finger_out_armor" }) do
		local h, v = tally(n)
		check(h == 0 and v > 0, n .. ": armour feedback must stay visible in kid mode")
	end
end

------------------------------------------------------------------------
section("Kid mode drives the shader bus lane")
OVR = OVR or {}
local old_setting = zgo_util.setting
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return old_setting(k) end
local ZS = zgo_settings
ZS.reset()
OVR["general/kid_mode"] = false
ZS.update()
check(BUS.lanes.zgo_view and BUS.lanes.zgo_view[1] == 0, "lane zgo_view registered and 0 with kid mode off")
OVR["general/kid_mode"] = true
ZS.update()
local lane = BUS.lanes.zgo_view or { 0, 0, 0, 0 }
check(lane[1] == 1, "kid mode on: lane x = 1")
local armed_opt = ZS.default and ZS.default("particles/kid_shader") ~= nil
if armed_opt then
	-- integrated: the experimental option arms the particle discard through w
	OVR["particles/kid_shader"] = true
	ZS.update()
	lane = BUS.lanes.zgo_view
	check(lane[1] == 1 and lane[4] == 1, "option on + kid mode: lane (1, ., ., 1)")
	check(K.hidden("zgo\\particle_blend", lane), "gory particles vanish")
	OVR["particles/kid_shader"] = false
	ZS.update()
	check(BUS.lanes.zgo_view[4] == 0, "option off: w = 0, particles draw as stock")
	OVR["particles/kid_shader"] = nil
else
	check(not K.hidden("zgo\\particle_blend", lane), "without the experimental option the particle shaders stay stock")
	print("  the experimental option particles/kid_shader is not in zgo_settings yet: particles stay as stock (see docs/integration/kidfx.md)")
end
OVR["general/kid_mode"] = false
ZS.update()
check(BUS.lanes.zgo_view[1] == 0, "kid mode off again: lane x = 0")
OVR["general/kid_mode"] = nil

------------------------------------------------------------------------
section("Errors")
for _, l in ipairs(LOG) do if l:find("error") then fails = fails + 1 print("  ERR " .. l) end end
if fails > 0 then
	print(("\n%d KIDFX CHECKS FAILED"):format(fails))
	os.exit(1)
end
print("\nALL KIDFX TESTS PASSED")
