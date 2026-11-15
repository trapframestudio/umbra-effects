-- In-game probes (zgo_probe, MCM -> Diagnostics) for Zone Gore Overhaul.
--   luajit zgo_test_probe.lua [seed]             single player, then itself as a
--                                                co-op host and a co-op client
--   luajit zgo_test_probe.lua host|client seed   one co-op role
-- Every probe runs to its end in each role, writes the report, and leaves
-- nothing changed (shaders, models, kid mode, its own state). The engine
-- parts the probes read (shader API, OGF files, the shader bus, nearest
-- objects, loose props) are mocked in mocks/probe.lua and below.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 1

-- mocks/probe.lua switches on, the report goes to a scratch folder
PROBE_MOCKS = true
PROBE_TMP = os.tmpname()
os.remove(PROBE_TMP)
do local r = os.execute(('mkdir -p "%s"'):format(PROBE_TMP)) assert(r == 0 or r == true, "scratch folder") end

-- the shader bus as lua_help_ex.script documents it: set() takes the token
-- that register / try_register returned; get() is (ok, x, y, z, w), latched
-- from the pending value once per frame
BUS = { lanes = {}, tokens = {}, next = 0 }
local function lane(id) return BUS.lanes[id] end
shader_bus = {
	version = function() return 2 end,
	try_register = function(id, owner, desc)
		assert(type(id) == "string" and type(owner) == "string" and type(desc) == "string")
		local l = BUS.lanes[id]
		if l and l.owner ~= owner then return nil end
		if not l then
			BUS.next = BUS.next + 1
			l = { owner = owner, desc = desc, token = BUS.next, v = { 0, 0, 0, 0 }, pending = { 0, 0, 0, 0 }, writes = 0 }
			BUS.lanes[id], BUS.tokens[l.token] = l, l
		end
		return l.token
	end,
	has = function(id) return BUS.lanes[id] ~= nil end,
	owner_of = function(id) return lane(id) and lane(id).owner end,
	describe = function(id) return lane(id) and lane(id).desc end,
	set = function(token, x, y, z, w)
		if type(token) ~= "number" then error("No matching overload found, candidates: bool set(number,number,number,number,number)") end
		local l = BUS.tokens[token]
		if not l then return false end
		l.pending = { x, y, z, w }
		l.writes = l.writes + 1
		return true
	end,
	get = function(id) local l = lane(id) if not l then return true, 0, 0, 0, 0 end return true, unpack(l.v) end,
	get_pending = function(id) local l = lane(id) if not l then return true, 0, 0, 0, 0 end return true, unpack(l.pending) end,
	stats = function(id) local l = lane(id) if not l then return false, 0, 0, 0, 0 end return true, 0, 0, 0, l.writes end,
}

arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
RegisterScriptCallback("actor_on_update", function()
	for _, l in pairs(BUS.lanes) do l.v = { unpack(l.pending) } end
end)

local P = zgo_probe
local base_setting = zgo_util.setting
OVR = { ["general/debug"] = true, ["diagnostics/hold"] = 2 }
zgo_util.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	return base_setting(k)
end
local function section(t) print(("\n== [%s] %s"):format(role, t)) end
local function short(s) s = tostring(s) return #s > 230 and (s:sub(1, 227) .. "...") or s end

-- kid mode handlers, spied: probe 8 must hold them, never call them with true
KID_CALLS = {}
for name, m in pairs(P.kid_handlers()) do
	local orig = m.kid_mode
	m.kid_mode = function(kid, ...)
		KID_CALLS[#KID_CALLS + 1] = { name, kid }
		return orig(kid, ...)
	end
end
local ORIG = { gore = zgo_settings.gore, kid = {} }
for name, m in pairs(P.kid_handlers()) do ORIG.kid[name] = m.kid_mode end
PROP_ORIG = {}

local function restored(label)
	for id, o in pairs(OBJ) do
		if type(o) == "table" and o._probe_over then
			assert(next(o._probe_over) == nil, label .. ": a shader override is left on id " .. tostring(id))
		end
	end
	assert(zgo_settings.gore == ORIG.gore, label .. ": zgo_settings.gore not put back")
	for name, f in pairs(ORIG.kid) do assert(_G[name].kid_mode == f, label .. ": " .. name .. ".kid_mode not put back") end
	local l = BUS.lanes.zgo_view
	assert(not l or l.pending[1] == 0, label .. ": the kid mode lane is left on")
	for id, vis in pairs(PROP_ORIG) do assert(OBJ[id]._visual == vis, label .. ": prop " .. id .. " keeps the swapped model") end
	local st = P._test.state()
	assert(st.active == nil and st.queue == 0 and next(st.rounds) == nil and st.prop_swap == nil, label .. ": probe state left over")
end

local function settle(cap)
	local t = 0
	repeat frame(33) t = t + 33 until not P.busy() or t > (cap or 60000)
	assert(not P.busy(), "a probe is still running after " .. t .. " ms")
end

local function run_probe(btn, cap)
	local n0 = #P.results()
	P[btn]()
	settle(cap)
	assert(#P.results() > n0, btn .. " gave no result")
	local r = P.results()[#P.results()]
	print(("  %-22s %-6s %s"):format(r.name, r.status, short(r.details)))
	restored(r.name)
	return r
end

local function log_has(pat)
	for _, l in ipairs(LOG) do if l:find(pat) then return l end end
end

local function errs()
	local n = 0
	for _, l in ipairs(LOG) do
		if l:find("%[ZGO probe%]") and (l:find("traceback") or l:find("probe script stopped") or l:find("runner problem") or l:find("could not undo")) then
			n = n + 1
			print("  ERR " .. l)
		end
	end
	return n
end

------------------------------------------------------------------------
-- The scene: the player at (0, 0, 6); a living stalker, a cut-up body, a
-- dead dog (3 weights per vertex), a living bandit (4 weights), a far NPC,
-- a co-op player's dummy (id 77), a bottle and a barrel
------------------------------------------------------------------------
local function scene()
	local live = NEW_NPC(10, "stalker", VV(0, 0, 3))
	local body = NEW_NPC(11, "stalker", VV(1, 0, 1))
	if role == "client" then
		-- a client gets the kill and the cut from the host
		body._alive, body._died_at, body.health = false, T_NOW - 1000, 0
		DISPATCH(zgo_sync.EVT, "D|11|sim_default_stalker_1|bip01_r_forearm|0|0|0|0|0", "host")
	else
		OVR["dismember/chance"] = 50
		shoot(body, "bip01_r_forearm", "ammo_12x76_zhekan", { kill = true })
		OVR["dismember/chance"] = nil
	end
	run(1500, 33)
	assert(zgo_dismember.get_state()[11], "the body near the player is cut")
	local dog = NEW_NPC(12, "monster", VV(-1, 0, 2))
	dog._visual = "monsters\\dog\\dog_1"
	dog._alive, dog._died_at, dog.health = false, T_NOW - 1000, 0
	local bandit = NEW_NPC(13, "stalker", VV(2, 0, 4))
	bandit._visual = "actors\\stalker_bandit\\bandit_2"
	NEW_NPC(14, "stalker", VV(100, 0, 100))
	NEW_NPC(77, "stalker", VV(0.5, 0, 4.5))
	NEW_PROP(500, VV(0.5, 0, 5.5), "dynamics\\devices\\dev_vodka\\dev_vodka")
	NEW_PROP(501, VV(0.2, 0, 5.8), "dynamics\\barrel\\bochka_close_1")
	PROP_ORIG[500], PROP_ORIG[501] = OBJ[500]._visual, OBJ[501]._visual
	run(200, 33)
	return live, body, dog, bandit
end

------------------------------------------------------------------------
section("Idle: nothing runs, nothing is logged")
LOG = {}
run(1500, 33)
assert(not log_has("%[ZGO probe%]"), "the probe module logs while idle")
assert(not P.busy())

local live, body, dog, bandit = scene()

------------------------------------------------------------------------
section("The Diagnostics page")
do
	local page
	for _, p in ipairs(zgo_settings.pages()) do if p.id == "diagnostics" then page = p end end
	assert(page, "no Diagnostics page")
	assert(page.show_if == "general/debug" and page.coop == "local")
	local buttons, exp = 0, 0
	for _, it in ipairs(page.items) do
		if it.type == "button" then
			buttons = buttons + 1
			local mod, fn = it.action:match("^([%w_]+)%.([%w_]+)$")
			assert(mod == "zgo_probe" and type(P[fn]) == "function", "button action " .. it.action)
			if it.show_if then
				assert(it.show_if == "diagnostics/experimental")
				assert(it.name[1]:find("experimental") and it.name[2]:find("экспериментально"), "experimental in the name: " .. it.id)
				exp = exp + 1
			end
		end
	end
	assert(zgo_settings.default("diagnostics/experimental") == false, "the experimental probes are off by default")
	assert(zgo_settings.default("diagnostics/hold") == 6)
	print(("  %d buttons (%d experimental), shown with %s"):format(buttons, exp, page.show_if))
	assert(buttons == 12 and exp == 4)
	local op = zgo_mcm.on_mcm_load()
	local tree
	for _, g in ipairs(op.gr) do if g.id == "diagnostics" then tree = g end end
	assert(tree and tree.precondition, "the page is hidden without the debug log")
	-- a click from the menu queues the probe; it runs once the menu is closed
	local ffi_btn
	for _, it in ipairs(tree.gr) do if it.id == "ffi" then ffi_btn = it end end
	LOG = {}
	ffi_btn.functor[1]()
	assert(P.busy() and log_has("queued"), "the button queues its probe")
	settle()
	assert(P.results()[#P.results()].name == "4 FFI")
end

------------------------------------------------------------------------
section("The probe shaders and textures")
do
	local GD = S .. "/../gamedata"
	local METHODS = { begin = true, sorting = true, emissive = true, distort = true, wmark = true, fog = true, zb = true, blend = true,
		aref = true, scopelense = true, dx10color_write_enable = true, color_write_enable = true, dx10texture = true, dx10stencil = true,
		dx10stencil_ref = true, dx10cullmode = true, dx10atoc = true, dx10zfunc = true, dx10sampler = true, dx10Options = true }
	local STOCK = { deffer_base_bump = "ps", deffer_base_flat = "ps", shadow_direct_model = "vs", dumb = "ps" }
	local function exists(p) local f = io.open(p, "rb") if f then f:close() return true end end
	-- run one element function of a .s the way the engine's shader VM does
	local function element(file, fn, t0, t1)
		local calls = {}
		local comp = {}
		setmetatable(comp, { __index = function(_, k)
			assert(METHODS[k], file .. ": the engine has no shader method " .. k)
			return function(self, ...)
				assert(self == comp, file .. ": " .. k .. " called on something else than the compiler (chained after dx10sampler?)")
				local a = { ... }
				calls[#calls + 1] = { k, ... }
				if k == "begin" then
					assert(#a == 2 or #a == 3, "begin(vs, ps)")
					local vs, ps = a[1], a[#a]
					for _, x in ipairs({ { vs, "vs" }, { ps, "ps" } }) do
						assert(STOCK[x[1]] == x[2] or exists(GD .. "/shaders/r3/" .. x[1] .. "." .. x[2]), file .. ": no shader " .. x[1] .. "." .. x[2])
					end
				elseif k == "zb" then assert(#a == 2 and type(a[1]) == "boolean" and type(a[2]) == "boolean")
				elseif k == "fog" then assert(#a == 1 and type(a[1]) == "boolean")
				elseif k == "dx10texture" then assert(#a == 2 and type(a[1]) == "string" and type(a[2]) == "string")
				elseif k == "dx10stencil" then assert(#a == 7, "dx10stencil takes 7 arguments")
				elseif k == "dx10stencil_ref" or k == "dx10zfunc" then assert(#a == 1 and type(a[1]) == "number")
				elseif k == "dx10color_write_enable" then assert(#a == 4)
				elseif k == "dx10sampler" then assert(#a == 1) return {}
				end
				return comp
			end
		end })
		local env = { string = string, tonumber = tonumber, tostring = tostring, math = math, table = table, ipairs = ipairs, pairs = pairs, type = type,
			cmp_func = { never = 1, less = 2, equal = 3, lessequal = 4, greater = 5, notequal = 6, greaterequal = 7, always = 8 },
			stencil_op = { keep = 1, zero = 2, replace = 3, incrsat = 4, decrsat = 5, invert = 6, incr = 7, decr = 8 },
			blend = { zero = 1, one = 2, srccolor = 3, invsrccolor = 4, srcalpha = 5, invsrcalpha = 6 } }
		local chunk = assert(loadfile(GD .. "/shaders/r3/" .. file))
		setfenv(chunk, env)
		chunk()
		if fn then assert(type(env[fn]) == "function", file .. " has no " .. fn) env[fn](comp, t0, t1, "null") end
		return calls, env
	end
	local function find(calls, k, a1)
		for _, c in ipairs(calls) do if c[1] == k and (a1 == nil or c[2] == a1) then return c end end
	end
	-- zgo_off: only l_special (so E[0..3] stay null), an inert pass, no distort / emissive
	local calls, env = element("zgo_off.s", "l_special", "act\\x", "null")
	assert(not env.normal and not env.normal_hq and not env.l_point and not env.l_spot, "zgo_off.s defines only l_special")
	assert(find(calls, "begin", "shadow_direct_model") and find(calls, "zfunc") == nil)
	local cw = find(calls, "dx10color_write_enable")
	assert(cw and not cw[2] and not cw[3] and not cw[4] and not cw[5], "no colour writes")
	assert(find(calls, "dx10zfunc")[2] == env.cmp_func.never, "a depth test that never passes")
	assert(not find(calls, "distort") and not find(calls, "emissive"), "never queued for distortion or emissive")
	-- zgo_probe_dmg: bump pair, flat without a bump map, the shadow pass
	calls = element("zgo_probe_dmg.s", "normal", "act\\x", "act\\x_bump")
	assert(find(calls, "begin", "zgo_probe_dmg_bump") and find(calls, "dx10texture", "s_bumpX")[3] == "act\\x_bump#")
	assert(find(calls, "dx10stencil") and find(calls, "dx10stencil_ref")[2] == 1)
	calls = element("zgo_probe_dmg.s", "normal", "act\\x", "null")
	assert(find(calls, "begin", "zgo_probe_dmg_flat") and not find(calls, "dx10texture", "s_bump"))
	calls = element("zgo_probe_dmg.s", "l_point", "act\\x", "null")
	assert(find(calls, "begin", "zgo_probe_dmg_shadow"))
	-- zgo_probe_digits: the digits in the second texture string pick the textures
	calls = element("zgo_probe_digits.s", "normal", "act\\x", P.digit_code(15, 0, 0))
	local want = { s_zgo_v0 = 15, s_zgo_v1 = 0, s_zgo_v2 = 0, s_zgo_v3 = 6, s_zgo_p0 = 15, s_zgo_p1 = 0, s_zgo_p2 = 0, s_zgo_p3 = 6, s_zgo_p4 = 0, s_zgo_p5 = 15 }
	assert(P.digit_code(15, 0, 0) == "zgo_dg_f006f0060f")
	for slot, d in pairs(want) do
		local c = find(calls, "dx10texture", slot)
		assert(c and c[3] == ("zgo\\probe\\d%02d"):format(d), "digit slot " .. slot)
	end
	calls = element("zgo_probe_digits.s", "normal", "act\\x", "null")
	assert(find(calls, "dx10texture", "s_zgo_v3")[3] == "zgo\\probe\\d00", "no digits: zeros (the vertex check fails on purpose)")
	-- the wrapped vertex shaders: one main per skinning variant around the stock file
	for _, f in ipairs({ "zgo_probe_dmg_bump.vs", "zgo_probe_dmg_flat.vs", "zgo_probe_dmg_shadow.vs", "zgo_probe_digits.vs" }) do
		local h = assert(io.open(GD .. "/shaders/r3/" .. f))
		local src = h:read("*a") h:close()
		assert(src:find("#define main zgo_stock_main", 1, true) and src:find("#undef main", 1, true), f .. ": wraps the stock main")
		for _, sk in ipairs({ "SKIN_NONE", "SKIN_0", "SKIN_1", "SKIN_2", "SKIN_3", "SKIN_4" }) do
			assert(src:find("#ifdef " .. sk .. "\n", 1, true), f .. ": no main for " .. sk)
		end
	end
	-- the digit textures: 1x1 A8R8G8B8, one mip level, red = digit * 17
	for d = 0, 15 do
		local h = assert(io.open(("%s/textures/zgo/probe/d%02d.dds"):format(GD, d), "rb"))
		local b = h:read("*a") h:close()
		local function u32(o) local x1, x2, x3, x4 = b:byte(o + 1, o + 4) return x1 + x2 * 256 + x3 * 65536 + x4 * 16777216 end
		assert(#b == 132 and b:sub(1, 4) == "DDS " and u32(4) == 124, "DDS header")
		assert(u32(12) == 1 and u32(16) == 1 and u32(28) == 1, "1x1, one mip level")
		assert(u32(76) == 32 and u32(80) == 0x41 and u32(88) == 32 and u32(92) == 0xFF0000 and u32(104) == 0xFF000000, "A8R8G8B8")
		assert(b:byte(129) == d * 17 and b:byte(130) == d * 17 and b:byte(131) == d * 17 and b:byte(132) == 255, "pixel of d" .. d)
	end
	print("  zgo_off.s, zgo_probe_dmg.s, zgo_probe_digits.s and 16 digit textures as the engine reads them")
end

------------------------------------------------------------------------
section("Reading models through the file system")
do
	local info = P._test.ogf_info("actors\\stalker_bandit\\bandit_2")
	assert(info and info.type == 3 and info.bones == 47 and #info.kids == 3)
	assert(info.kids[1].links == 4 and info.kids[2].links == 1 and info.kids[3].shader == "models\\model_aref")
	assert(math.abs(info.kids[2].bb[5] - 1.8) < 1e-5)
	local opened = PROBE_OPENED
	P._test.ogf_info("actors\\stalker_bandit\\bandit_2")
	assert(PROBE_OPENED == opened, "a model is read once per session")
	assert(P._test.ogf_info("no\\such\\model") == nil)
	print("  OGF header, children, vertex formats and boxes read back")
end

------------------------------------------------------------------------
section("Probes, one by one")
OVR["diagnostics/experimental"] = nil
LOG = {}
P.run_off_shader()
assert(log_has("Allow the experimental probes") and not P.busy(), "the experimental probes need their switch")
OVR["diagnostics/experimental"] = true

local results = {}
local function check(id, r) results[id] = r return r end

-- 9 baked models
local r = check(9, run_probe("run_baked"))
if BAKED then
	assert(r.status == "PASS" and r.details:find("1 of 1 baked"), "the baked stalker is in use")
	-- another mod's bandit model wins; the stalker's file is baked but the game kept the old one
	zgo_bake_index.models["actors\\stalker_bandit\\bandit_2"] = { bip01_head = true, bip01_l_forearm = true, bip01_r_forearm = true, bip01_l_calf = true }
	live._kids_n, body._kids_n = 3, 3
	r = run_probe("run_baked")
	assert(r.status == "FAIL" and r.details:find("bandit_2 %(overridden%)") and r.details:find("stalker_neutral_1 %(stale%)"), "overridden and stale models found")
	zgo_bake_index.models["actors\\stalker_bandit\\bandit_2"] = nil
	live._kids_n, body._kids_n = nil, nil
else
	assert(r.status == "MANUAL" and r.details:find("no baked models"))
end

-- 4 FFI (and the native add-on's own report)
FS_FILES["$game_scripts$|zgo_native.script"] = true
r = check(4, run_probe("run_ffi"))
assert(r.status == "MANUAL" and r.details:find("not Windows") and r.details:find("native add%-on"), "FFI present, not Windows here")
assert(log_has("ffi present") and log_has("LuaJIT"))

-- 8 kid mode lane
KID_CALLS = {}
local debris0 = zgo_debris.count()
P.run_kid_lane()
local held = false
for _ = 1, 60 do
	frame(33)
	if zgo_settings.gore ~= ORIG.gore then
		held = true
		for name, f in pairs(ORIG.kid) do assert(_G[name].kid_mode ~= f, name .. ".kid_mode is held while the probe runs") end
	end
end
settle()
r = P.results()[#P.results()]
print(("  %-22s %-6s %s"):format(r.name, r.status, short(r.details)))
restored(r.name)
check(8, r)
assert(held, "kid mode was flipped for zgo_settings")
for _, c in ipairs(KID_CALLS) do assert(c[2] ~= true, c[1] .. ".kid_mode(true) ran during the probe") end
assert(zgo_debris.count() == debris0, "nothing else changed")
assert(r.status == "PASS" or (r.status == "FAIL" and r.details:find("zgo_settings must pass its token")),
	"the lane flips, or the probe names the cause")
assert(BUS.lanes.zgo_view.writes > 0)

-- 6 co-op (single player: this machine only)
if role == "sp" then
	r = check(6, run_probe("run_coop"))
	assert(r.status == "MANUAL" and r.details:find("single player: view %x+ over 2 bodies"))
end

-- 1 off shader
P.run_off_shader()
for _ = 1, 10 do frame(33) end
assert(live._probe_over[2] and live._probe_over[2].shader == "zgo\\off", "the living NPC's head gets zgo\\off")
assert(body._probe_over[2] and body._probe_over[2].shader == "zgo\\off" and body._probe_over[2].texture == "act\\act_face_1")
assert(next(live._probe_over, 2) == nil and live._probe_over[1] == nil, "only that part")
r = check(1, run_probe("run_off_shader"))
assert(r.status == "MANUAL" and r.details:find("on 2 body"), "both bodies, then restored")
assert(log_has("body %(ragdoll%)"), "the body is a ragdoll")
-- kid mode: the whole body goes, nothing gory is shown
OVR["general/kid_mode"] = true
frame(33)
P.run_off_shader()
for _ = 1, 10 do frame(33) end
local n = 0
for _ in pairs(live._probe_over) do n = n + 1 end
assert(n == #PROBE_MESHES["actors\\stalker_neutral\\stalker_neutral_1"].kids, "kid mode: every sub-mesh")
settle()
restored("1 off shader, kid mode")
OVR["general/kid_mode"] = nil
frame(33)

-- 2 pass-through shader
P.run_dmg_shader()
for _ = 1, 10 do frame(33) end
assert(live._probe_over[1] and live._probe_over[1].texture == "act\\act_stalker_neutral_1,act\\act_stalker_neutral_1_bump", "bump pair")
assert(bandit._probe_over[1] and bandit._probe_over[1].texture == "act\\act_bandit_2", "flat without a bump map")
assert(bandit._probe_over[3] == nil, "alpha-tested materials are left alone")
assert(dog._probe_over[1] and dog._probe_over[1].shader == "zgo\\probe_dmg")
r = check(2, run_probe("run_dmg_shader"))
assert(r.status == "MANUAL" and r.details:find("covered: 1W 2W 3W 4W"), "all four weight formats")

-- 3 digit textures
P.run_digits()
for _ = 1, 10 do frame(33) end
assert(bandit._probe_over[1].texture == "act\\act_bandit_2," .. P.digit_code(15, 0, 0), "the nearest: red")
assert(live._probe_over[1].texture == "act\\act_stalker_neutral_1," .. P.digit_code(0, 15, 0), "then green")
assert(dog._probe_over[1].texture == "monsters\\dog\\dog," .. P.digit_code(0, 0, 15), "then blue")
r = check(3, run_probe("run_digits"))
assert(r.status == "MANUAL" and r.details:find("3 read their own texture string back, 3 different strings"))

-- 7 props
if role == "sp" then
	P.run_props()
	for _ = 1, 10 do frame(33) end
	assert(OBJ[500]._visual == "dynamics\\box\\box_paper", "the bottle (one bone) gets a spare one-bone model; the barrel (3 bones) is left alone")
	-- a save now keeps the swapped model: the probe remembers the real one
	local data = SAVE_GAME()
	assert(data.zgo_probe and data.zgo_probe.prop and data.zgo_probe.prop.id == 500)
	r = check(7, run_probe("run_props"))
	assert(r.status == "MANUAL" and r.details:find("took") and r.details:find("turned back fine"))
	OBJ[500]._visual = "dynamics\\box\\box_paper"           -- (as that save would load)
	CB.load_state(data)
	frame(33)
	assert(OBJ[500]._visual == PROP_ORIG[500], "the model saved during the probe is put back on load")
	assert(log_has("put back the model of id 500"))
	-- interrupted by a level change: put back at once
	P.run_props()
	for _ = 1, 10 do frame(33) end
	assert(OBJ[500]._visual ~= PROP_ORIG[500])
	CB.on_level_changing()
	assert(OBJ[500]._visual == PROP_ORIG[500] and not P.busy())
	r = P.results()[#P.results()]
	assert(r.status == "MANUAL" and r.details:find("interrupted %(level change%)"))
	restored("7 props, interrupted")
else
	r = check(7, run_probe("run_props"))
	assert(r.status == "MANUAL" and r.details:find("single player"))
end

-- 5 save and reload
if role == "client" then
	r = check(5, run_probe("run_save_reload"))
	assert(r.status == "MANUAL" and r.details:find("clients don't save"))
else
	r = run_probe("run_save_reload")
	assert(r.status == "MANUAL" and r.details:find("started: 1 bodies"), "armed with the cut body")
	local data = SAVE_GAME()
	local rec = data.zgo_probe and data.zgo_probe.saveload
	assert(rec and #rec.bodies == 1 and rec.bodies[1].id == 11 and rec.bodies[1].roots[1] == "bip01_r_forearm")
	RESPAWN(body)
	CB.on_level_changing()
	CB.load_state(data)
	settle(20000)
	r = check(5, P.results()[#P.results()])
	print(("  %-22s %-6s %s"):format(r.name, r.status, short(r.details)))
	assert(r.status == "PASS" and r.details:find("1 of 1 recorded bodies came back"), "the cut body came back as saved")
	CHECK_CUTS("after the save probe")
	-- a record that doesn't match what came back fails
	rec.bodies[1].roots[#rec.bodies[1].roots + 1] = "bip01_l_calf"
	CB.load_state(data)
	settle(20000)
	r = P.results()[#P.results()]
	assert(r.status == "FAIL" and r.details:find("bip01_l_calf missing from ZGO's state"))
	restored("5 save and reload")
	assert(SAVE_GAME().zgo_probe == nil, "a later save records nothing")
end

------------------------------------------------------------------------
if role == "host" then
	section("Co-op host: asks the client, compares, tells it the verdict")
	local function question()
		for _, b in ipairs(SENT) do
			for l in b:gmatch("[^\n]+") do
				local nonce, ids = l:match("^Z|q|([^|]+)|([^|]+)$")
				if nonce then return nonce, ids end
			end
		end
	end
	local function answer(nonce, ids, tamper)
		local list = {}
		for v in ids:gmatch("[^,]+") do list[#list + 1] = tonumber(v) end
		local v = P._test.view(list)
		local per = table.concat(v.per)
		if tamper then per = "beef" .. per:sub(5) end
		DISPATCH(zgo_sync.EVT_UP, table.concat({ "Z", "a", nonce, v.n, v.total, per, v.debris, v.decals or "-", v.recv }, "|"), 5)
	end
	local function round(tamper, silent)
		SENT = {}
		local n0 = #P.results()
		P.run_coop()
		local nonce, ids
		for _ = 1, 10 do frame(33) nonce, ids = question() if nonce then break end end
		assert(nonce, "the host asks the clients")
		assert(ids == "11,12", "the bodies near the host: " .. tostring(ids))
		if not silent then answer(nonce, ids, tamper) end
		settle()
		assert(#P.results() > n0)
		local res = P.results()[#P.results()]
		print(("  %-22s %-6s %s"):format(res.name, res.status, short(res.details)))
		restored("6 co-op")
		zgo_sync.flush()
		return res, nonce
	end
	local res, nonce = round()
	assert(res.status == "PASS" and res.details:find("1 of 1 player%(s%) answered over 2 bodies: player 5: match"))
	local verdict = false
	for _, b in ipairs(SENT) do if b:find("Z|r|" .. nonce .. "|5|match|", 1, true) then verdict = true end end
	assert(verdict, "the verdict goes to the clients")
	check(6, res)
	res = round(true)
	assert(res.status == "FAIL" and res.details:find("mismatch") and log_has("differ on ids 11"), "a different cut is found")
	res = round(false, true)
	assert(res.status == "FAIL" and res.details:find("no player answered"))
	-- a client asks for a round
	local n0 = #P.results()
	DISPATCH(zgo_sync.EVT_UP, "Z|run", 5)
	frame(33) frame(33)
	assert(P.busy(), "a client's request starts a round")
	settle()
	assert(#P.results() == n0 + 1)
	OVR["general/debug"] = false
	SENT = {}
	DISPATCH(zgo_sync.EVT_UP, "Z|run", 5)
	frame(33) frame(33)
	zgo_sync.flush()
	assert(not P.busy() and SENT[1] and SENT[1]:find("Z|r|-|all|not run|", 1, true), "no round with the host's debug log off")
	OVR["general/debug"] = true
	-- the dummy of a co-op player is never probed
	assert(not log_has("id 77%]"))
	restored("host")
end

if role == "client" then
	section("Co-op client: answers the host, shows its verdict, asks for a round")
	UP = {}
	DISPATCH(zgo_sync.EVT, "Z|q|nA|11,12", "host")
	frame(33)
	assert(#UP == 1, "the client answers")
	local v = P._test.view({ 11, 12 })
	local t = {}
	for f in UP[1]:gmatch("[^|]+") do t[#t + 1] = f end
	assert(t[1] == "Z" and t[2] == "a" and t[3] == "nA" and t[4] == "2" and t[5] == v.total and t[6] == table.concat(v.per), "its view: " .. UP[1])
	assert(#t == 9)
	UP = {}
	DISPATCH(zgo_sync.EVT, "Z|q|nB|-", "host")
	frame(33)
	assert(UP[1] and UP[1]:find("^Z|a|nB|0|%x+|%-|"), "no bodies: " .. tostring(UP[1]))
	LOG = {}
	DISPATCH(zgo_sync.EVT, "Z|r|nA|5|match|cuts and shaders the same", "host")
	frame(33)
	assert(log_has("the host compared player 5: match"))
	UP = {}
	r = check(6, run_probe("run_coop"))
	assert(r.status == "MANUAL" and r.details:find("asked the host") and UP[1] == "Z|run")
	-- rubbish from the wire does nothing
	DISPATCH(zgo_sync.EVT, "Z|q\nZ|r|x\nZ|zz|1|2|3", "host")
	frame(33)
	restored("client")
end

------------------------------------------------------------------------
section("Run all safe probes")
LOG = {}
local n0 = #P.results()
P.run_all()
settle(120000)
local names = {}
for i = n0 + 1, #P.results() do names[#names + 1] = P.results()[i].name end
print("  " .. table.concat(names, ", "))
assert(table.concat(names, ",") == "9 baked models,4 FFI,8 kid mode lane,6 co-op", "the four safe probes in order")
local sum = log_has("run all safe probes: ")
assert(sum and sum:find("%d PASS, %d FAIL, %d MANUAL"), "a summary")
print("  " .. sum)
restored("run all")

------------------------------------------------------------------------
section("Marks and the report")
P.mark_ok()
P.mark_bad()
local h = assert(io.open(PROBE_TMP .. "/zgo_probe_report.txt"), "the report file")
local rep = h:read("*a")
h:close()
assert(rep:find("==== Zone Gore Overhaul [%d%.]+ probes, ") and rep:find(role == "sp" and "single player" or ("co-op " .. role)))
for id = 1, 9 do
	assert(results[id], "probe " .. id .. " ran")
	assert(rep:find("[ZGO probe] " .. results[id].name .. ": " .. results[id].status, 1, true), "report line for probe " .. id)
end
assert(rep:find("USER says it looked right", 1, true) and rep:find("USER says it looked wrong", 1, true))
assert(rep:find("run all safe probes:", 1, true))
local lines = 0
for _ in rep:gmatch("\n") do lines = lines + 1 end
print(("  %s: %d lines"):format("zgo_probe_report.txt", lines))
os.remove(PROBE_TMP .. "/zgo_probe_report.txt")
os.remove(PROBE_TMP)

section("Errors")
assert(errs() == 0, "the probe module logged errors")
print(("  results: %s"):format((function()
	local t = {}
	for id = 1, 9 do t[#t + 1] = id .. "=" .. results[id].status end
	return table.concat(t, " ")
end)()))

------------------------------------------------------------------------
if role == "sp" then
	section("Co-op: host and client")
	local ok = true
	for _, rr in ipairs({ "host", "client" }) do
		local p = io.popen(('luajit "%s/zgo_test_probe.lua" %s %d 2>&1'):format(S, rr, seed))
		local out = p:read("*a")
		p:close()
		local last = out:match("([^\n]*)\n?$") or ""
		for l in out:gmatch("[^\n]+") do if l:find("luajit:") or l:find("ERR") or l:find("traceback") then print("  [" .. rr .. "] " .. l) end end
		print(("  %s: %s"):format(rr, last))
		ok = ok and last:find("OK") ~= nil
	end
	assert(ok, "co-op roles failed")
	print("\nALL PROBE TESTS PASSED")
else
	print(("\nPROBE %s OK"):format(role:upper()))
end
