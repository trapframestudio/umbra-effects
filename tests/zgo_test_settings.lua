-- Settings, presets and kid mode (run: luajit zgo_test_settings.lua [seed])
-- Runs as a co-op host, so what would be sent to partners can be checked too.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 5
arg = { S .. "/../gamedata/scripts", "host" }
NPC_YAW = 0.4

-- shader bus as the exe has it: register a lane, then set (x, y, z, w)
BUS = { lanes = {}, sets = {} }
shader_bus = {
	try_register = function(id, owner, desc) assert(type(id) == "string" and type(owner) == "string" and type(desc) == "string") BUS.lanes[id] = { 0, 0, 0, 0 } return true end,
	has = function(id) return BUS.lanes[id] ~= nil end,
	set = function(id, x, y, z, w) assert(BUS.lanes[id], "set on unregistered lane " .. tostring(id)) BUS.lanes[id] = { x, y, z, w } BUS.sets[#BUS.sets + 1] = x end,
}
-- xrRazom's MCM authority
DECLARED = {}
xrr_mcm_authority = { declare = function(prefix, who) DECLARED[prefix] = who end }

dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local ZS = zgo_settings
local old_setting = zgo_util.setting
OVR = {}
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return old_setting(k) end

local function section(t) print(("\n== %s"):format(t)) end
local function logs(pat) local n = 0 for _, l in ipairs(LOG) do if l:find(pat) then n = n + 1 end end return n end
local function hidden(o) local n = 0 for _, h in pairs(o._hidden) do if h then n = n + 1 end end return n end
local function gore_fx() local n = 0 for _, f in ipairs(FX) do if zgo_fx.is_gore(f) then n = n + 1 end end return n end
local function level_atts() local n = 0 for _ in pairs(LEVEL_ATT) do n = n + 1 end return n end
local function caps_on(o) local n = 0 for _ in pairs(o._att or {}) do n = n + 1 end return n end
local function lines(kind) local n = 0 for _, b in ipairs(SENT) do for l in b:gmatch("[^\n]+") do if l:sub(1, #kind + 1) == kind .. "|" then n = n + 1 end end end return n end

------------------------------------------------------------------------
section("Every option is complete: names and explanations in both languages, sane ranges")
local n_opts, n_perf = 0, 0
for _, page in ipairs(ZS.pages()) do
	assert(page.name and page.name[1] and page.name[2], "page name " .. page.id)
	assert(page.coop == "host" or page.coop == "local", "page coop " .. page.id)
	for _, it in ipairs(page.items) do
		local key = page.id .. "/" .. it.id
		n_opts = n_opts + 1
		for lang = 1, 2 do
			assert(it.name and it.name[lang] and #it.name[lang] > 1, "name missing: " .. key)
			assert(it.desc and it.desc[lang] and #it.desc[lang] >= 15, "explanation missing or too short: " .. key)
		end
		assert(it.type == "check" or it.type == "track" or it.type == "preset" or it.type == "list" or it.type == "button", "type " .. key)
		if it.type == "list" then
			assert(#it.values >= 2, "list values " .. key)
			local has_def = false
			for _, v in ipairs(it.values) do
				if v == it.def then has_def = true end
				assert(it.labels and it.labels[v] and it.labels[v][1] and it.labels[v][2], "list label " .. key .. " " .. tostring(v))
			end
			assert(has_def, "list default is one of its values: " .. key)
		elseif it.type == "button" then
			assert(type(it.action) == "string" and it.action:match("^[%w_]+%.[%w_]+$"), "button action " .. key)
		end
		if it.show_if then assert(ZS.default(it.show_if) ~= nil, "show_if names an unknown option: " .. key) end
		if it.type == "track" then
			assert(it.min < it.max and it.step > 0, "range " .. key)
			local vals = it.perf or { it.def }
			for i, v in ipairs(vals) do
				assert(v >= it.min and v <= it.max, ("%s value %s outside %s..%s"):format(key, v, it.min, it.max))
				local k = (v - it.min) / it.step
				assert(math.abs(k - math.floor(k + 0.5)) < 1e-6, ("%s value %s not on the slider's step"):format(key, v))
				if it.perf and i > 1 then assert(v >= vals[i - 1], key .. ": presets must not get cheaper going up") end
			end
			if it.perf then
				n_perf = n_perf + 1
				assert(#it.perf == #ZS.PRESETS, "a value per preset: " .. key)
				assert(ZS.default(key) == it.perf[4], "default = the High preset: " .. key)
				assert(page.id == "performance", "preset options live on the Performance page (MCM presets work per page): " .. key)
			end
		elseif it.type == "check" then
			assert(type(it.def) == "boolean", "default " .. key)
		elseif it.type == "preset" then
			for _, p in ipairs(ZS.PRESETS) do assert(it.labels[p] and it.labels[p][1] and it.labels[p][2], "preset label " .. p) end
		end
	end
end
print(("  %d options, %d of them set by the quality presets"):format(n_opts, n_perf))

-- every setting the scripts read exists
local used, bad = 0, {}
for _, f in ipairs({ "zgo_main", "zgo_util", "zgo_decals", "zgo_fx", "zgo_debris", "zgo_dismember", "zgo_blast", "zgo_ballistics", "zgo_sync", "zgo_bake", "zgo_settings" }) do
	local h = assert(io.open(S .. "/../gamedata/scripts/" .. f .. ".script"))
	local src = h:read("*a") h:close()
	for key in src:gmatch('setting%("([%w_/]+)"%)') do
		used = used + 1
		if ZS.default(key) == nil then bad[#bad + 1] = f .. ": " .. key end
	end
end
assert(#bad == 0, "scripts read settings that don't exist: " .. table.concat(bad, ", "))
print(("  %d setting reads in the scripts, all known"):format(used))

-- the MCM string tables are generated from the same table and must be current
local root = S .. "/.."
local ok = os.execute(("cd %q && luajit dev/gen_mcm_text.lua --check >/dev/null"):format(root))
assert(ok == 0 or ok == true, "MCM string tables out of date: run luajit dev/gen_mcm_text.lua")
print("  MCM string tables (eng, rus) match")

-- the menu
local op = zgo_mcm.on_mcm_load()
assert(op.id == "zgo" and #op.gr == #ZS.pages())
for _, g in ipairs(op.gr) do
	for _, it in ipairs(g.gr) do
		if it.type == "preset" then
			for _, p in ipairs(ZS.PRESETS) do
				local n = 0
				for id, v in pairs(it.presets[p]) do
					n = n + 1
					assert(ZS.default(g.id .. "/" .. id) ~= nil, "preset sets an unknown option " .. id)
				end
				assert(n == n_perf, ("preset %s sets %d of %d options"):format(p, n, n_perf))
			end
		end
	end
end
local pv = ZS.preset_values("potato")
assert(pv["performance/max_debris"] < ZS.preset_values("ultra")["performance/max_debris"])

------------------------------------------------------------------------
section("Co-op: xrRazom is told which settings the host decides")
for k, v in pairs(DECLARED) do print(("  %-32s %s"):format(k, v)) end
assert(DECLARED["zgo/general"] == "local" and DECLARED["zgo/performance"] == "local")
assert(DECLARED["zgo/general/npc_shooters"] == "host")
assert(DECLARED["zgo/decals"] == "host" and DECLARED["zgo/explosions"] == "host" and DECLARED["zgo/dismember"] == "host")
assert(DECLARED["zgo/dismember/baked_models"] == "local", "baked models depend on each player's files")
assert(ZS.coop_of("general/kid_mode") == "local", "kid mode is per machine")

------------------------------------------------------------------------
section("Performance settings take effect")
local function blood_from(streams)
	OVR["performance/max_streams"] = streams
	PLACED = {}
	local v = NEW_NPC(200 + streams, "stalker", VV(0, 0, -1.2))
	for _ = 1, 6 do shoot(v, "bip01_spine1", "ammo_7.62x54_7h1") end
	run(1500)
	return #PLACED
end
local lo, hi = blood_from(1), blood_from(12)
OVR["performance/max_streams"] = nil
print(("  decals from 6 rifle hits: 1 stream %d, 12 streams %d"):format(lo, hi))
assert(lo < hi)
OVR["performance/max_debris"] = 2
OVR["dismember/chance"] = 3
explode(VV(6, 0.1, 6.4), { NEW_NPC(210, "stalker", VV(6, 0, 6)) }, { armor = 0.05, eid = 960 })
run(400)
print(("  severed parts and gibs with the limit at 2: %d"):format(zgo_debris.count()))
assert(zgo_debris.count() <= 2)
OVR["performance/max_debris"], OVR["dismember/chance"] = nil, nil
zgo_debris.reset()

------------------------------------------------------------------------
section("Kid mode on: blood, parts and caps already there go, the cut body is whole again")
LOG, PLACED, BODY, FX, SENT = {}, {}, {}, {}, {}
OVR["dismember/chance"] = 3
local a = NEW_NPC(300, "stalker", VV(-6, 0, -6))
explode(VV(-6, 0.1, -5.5), { a }, { armor = 0.05, eid = 970 })
run(400)
local cut_before, debris_before = hidden(a), zgo_debris.count()
print(("  before: parts removed %d, debris %d, decals %d, body decals %d, gory fx %d, caps %d"):format(cut_before, debris_before, #PLACED, #BODY, gore_fx(), caps_on(a)))
assert(cut_before > 0 and debris_before > 0 and #PLACED > 0)
assert(BUS.lanes.zgo_view and BUS.lanes.zgo_view[1] == 0, "lane registered and off")

OVR["general/kid_mode"] = true
frame()
print(("  after:  parts hidden %d, debris %d, caps %d, shader lane x = %s"):format(hidden(a), zgo_debris.count(), caps_on(a), BUS.lanes.zgo_view[1]))
assert(BUS.lanes.zgo_view[1] == 1, "the blood shaders are told to draw nothing")
assert(zgo_debris.count() == 0 and level_atts() == 0, "severed parts and gibs removed")
assert(caps_on(a) == 0, "stump caps removed")
if BAKED then
	assert(hidden(a) == 0, "a baked body gets its parts back")
else
	assert(hidden(a) == cut_before, "an unbaked body stays as it was (its ragdoll was built without the parts)")
end
run(3000)
if BAKED then assert(hidden(a) == 0, "and nothing cuts them again while kid mode is on") end

------------------------------------------------------------------------
section("Kid mode on: nothing gory is drawn here, partners still get it")
LOG, PLACED, BODY, FX, SENT = {}, {}, {}, {}, {}
local b = NEW_NPC(301, "stalker", VV(6, 0, -6))
explode(VV(6, 0.1, -5.5), { b }, { armor = 0.05, eid = 971 })
for _ = 1, 4 do shoot(NEW_NPC(302, "stalker", VV(0, 0, -1.2)), "bip01_spine1", "ammo_7.62x54_7h1") end
run(1500)
zgo_sync.flush()
print(("  drawn here: decals %d, body decals %d, gory fx %d, parts hidden %d, debris %d"):format(#PLACED, #BODY, gore_fx(), hidden(b), zgo_debris.count()))
print(("  sent to partners: W %d, S %d, F %d, D %d, P %d"):format(lines("W"), lines("S"), lines("F"), lines("D"), lines("P")))
assert(#PLACED == 0 and #BODY == 0 and gore_fx() == 0 and hidden(b) == 0 and zgo_debris.count() == 0)
assert(not b._alive, "the blast still kills (game behaviour is unchanged)")
assert(lines("W") > 0 and lines("D") > 0 and lines("F") > 0, "co-op partners still get the effects")

-- the same lines arriving from a host: a kid-mode machine draws nothing, others draw them
local batch = SENT
FX, PLACED = {}, {}
for _, msg in ipairs(batch) do DISPATCH(zgo_sync.EVT, msg) end
run(200)
print(("  replayed in kid mode: decals %d, gory fx %d"):format(#PLACED, gore_fx()))
assert(#PLACED == 0 and gore_fx() == 0)

------------------------------------------------------------------------
section("Kid mode off: everything comes back")
OVR["general/kid_mode"] = nil
LOG, PLACED, FX = {}, {}, {}
run(3000)
print(("  shader lane x = %s, parts hidden: first body %d, second body %d"):format(BUS.lanes.zgo_view[1], hidden(a), hidden(b)))
assert(BUS.lanes.zgo_view[1] == 0)
assert(hidden(a) >= cut_before, "the cuts made before kid mode are shown again")
if BAKED then
	assert(hidden(b) > 0, "and the ones decided during it")
	assert(caps_on(b) > 0 or not zgo_settings.get("dismember/stump_caps"), "with their stump caps")
else
	-- an unbaked body killed in kid mode is a ragdoll by now: its parts can't be taken off any more
	assert(hidden(b) == 0, "an unbaked body killed in kid mode stays whole")
end
for _, msg in ipairs(batch) do DISPATCH(zgo_sync.EVT, msg) end
run(200)
print(("  the same lines replayed now: decals %d, gory fx %d"):format(#PLACED, gore_fx()))
assert(#PLACED > 0 and gore_fx() > 0)
OVR["dismember/chance"] = nil

------------------------------------------------------------------------
section("Errors")
local errs = 0
for _, l in ipairs(LOG) do if l:find("error") then errs = errs + 1 print("  ERR " .. l) end end
assert(errs == 0)
print("\nALL SETTINGS TESTS PASSED")
