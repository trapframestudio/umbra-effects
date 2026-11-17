-- Co-op with a baked host and a client whose bake is not in use (zgo_dismember
-- not_shown, zgo_bake.why_not_baked): the host's cuts reach the client after
-- its copy of the body is a ragdoll, which keeps an un-baked part on screen.
-- The client must show nothing half (no flying piece, no cap on a whole
-- body), say why once per body and cut, and stop trying until the reason
-- goes away ("Use baked models" switched).
--   luajit zgo_test_mp_mixed.lua [seed]              runs both roles as subprocesses
--   luajit zgo_test_mp_mixed.lua host|client seed wire   one role (the driver sets ZGO_BAKED)
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2, a3 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 1
local WIRE = a3

if role == "sp" then
	local wire = os.tmpname()
	local function go(r, env)
		local p = io.popen(('%s luajit "%s/zgo_test_mp_mixed.lua" %s %d "%s" 2>&1'):format(env, S, r, seed, wire))
		local out = p:read("*a")
		p:close()
		return out, out:match("([^\n]*)\n*$") or ""
	end
	local ok = true
	for _, r in ipairs({ { "host", "ZGO_BAKED=1" }, { "client", "ZGO_BAKED=0" } }) do
		local out, last = go(r[1], r[2])
		local good = last:find("OK", 1, true) ~= nil
		print(out)
		if not good then ok = false print(("%s (%s) FAILED"):format(r[1], r[2])) break end
	end
	os.remove(wire)
	if not ok then print("MIXED CO-OP TESTS FAILED") os.exit(1) end
	print("ALL MIXED CO-OP TESTS PASSED")
	return
end

arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local function section(t) print(("\n== [%s] %s"):format(role, t)) end

if role == "host" then
	section("A baked host cuts a fresh kill and a grenaded corpse")
	assert(BAKED, "the host wears baked models (ZGO_BAKED=1)")
	local c = NEW_NPC(30, "stalker", VV(-1, 0, -1.2))
	local f = NEW_NPC(60, "stalker", VV(2.2, 0, -1))
	local old = zgo_util.setting
	zgo_util.setting = function(k) if k == "dismember/chance" then return 50 end return old(k) end
	shoot(c, "bip01_l_forearm", "ammo_12x76_zhekan", { kill = true })
	zgo_util.setting = old
	f._alive = false
	explode(VV(2.2, 0.1, -0.6), { f })
	-- (long enough for two Q rounds)
	run(25000)
	assert(c._hidden["bip01_l_forearm"], "the baked host shows its cut")
	CHECK_CUTS("host")
	local w = assert(io.open(WIRE, "w"))
	local d, q = 0, 0
	for _, msg in ipairs(SENT) do
		w:write((msg:gsub("\n", "\1")), "\n")
		for l in msg:gmatch("[^\n]+") do
			if l:match("^D|") then d = d + 1 elseif l:match("^Q|%d+|[^|]+|[^-]") then q = q + 1 end
		end
	end
	w:close()
	print(("  sent %d D and %d Q lines"):format(d, q))
	assert(d >= 1 and q >= 1, "cuts and Q rounds went out")
	print("MIXED HOST OK")
	return
end

------------------------------------------------------------------------
-- client: no zgo_bake_index.script (ZGO_BAKED=0)
------------------------------------------------------------------------
assert(not BAKED, "the client has no bake in use (ZGO_BAKED=0)")
local D = zgo_dismember
local OVR = {}
local base_setting = zgo_util.setting
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return base_setting(k) end
local SV = "actors\\stalker_neutral\\stalker_neutral_1"

-- how often each body's cuts are looked at (the upkeep and Q rounds must stop)
local asked = 0
local orig_can = D.can_show_cut
D.can_show_cut = function(o, r) asked = asked + 1 return orig_can(o, r) end

local function said(id, root)
	local n, last = 0
	for _, l in ipairs(LOG) do
		if l:find(("host cut %s on "):format(root), 1, true) and l:find(("(id %d) not shown on this machine"):format(id), 1, true) then
			n, last = n + 1, l
		end
	end
	return n, last
end
local function limbs()
	local t = {}
	for name in pairs(LEVEL_ATT) do if name:find("limb") then t[name] = true end end
	return t
end
local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
local function corpse(id)
	local o = NEW_NPC(id, "stalker", VV((id % 5) - 2, 0, 2))
	o._alive, o._died_at, o.health = false, T_NOW - 5000, 0   -- a ragdoll for a while
	return o
end
local function cut_line(o, root) return ("D|%d|%s|%s|1|1|0|0|1|4242"):format(o:id(), o:section(), root) end

section("The host's cuts arrive after this copy of the body is a ragdoll")
local c = NEW_NPC(30, "stalker", VV(-1, 0, -1.2))
local f = NEW_NPC(60, "stalker", VV(2.2, 0, -1))
f._alive = false   -- a corpse here too (a ragdoll)
local cuts, qlines = {}, {}
for msg in io.lines(WIRE) do
	local body = msg:gsub("\1", "\n")
	for l in body:gmatch("[^\n]+") do
		local did, root = l:match("^D|(%d+)|[^|]+|([^|]+)|")
		did = tonumber(did)
		if did then
			cuts[did .. "|" .. root] = { id = did, root = root }
			-- the host's kill reached this machine first: the body is a ragdoll by now
			local o = OBJ[did]
			if o and o._alive then o._alive, o._died_at, o.health = false, T_NOW - 200, 0 end
		end
		if l:match("^Q|") then qlines[#qlines + 1] = l end
	end
	DISPATCH(zgo_sync.EVT, body, "host")
	frame()
end
run(3000)
assert(count(cuts) >= 1, "the wire has the host's cuts")
assert(not c._hidden["bip01_l_forearm"], "a cut this ragdoll keeps on screen is not hidden")
assert(count(limbs()) == 0, "no flying piece next to a whole body")
assert(#zgo_debris.caps_of(30) == 0 and #zgo_debris.caps_of(60) == 0, "no stump cap on a whole body")
for _, e in pairs(cuts) do
	local n, l = said(e.id, e.root)
	assert(n == 1, ("cut %s on %d: said %d times"):format(e.root, e.id, n))
	assert(l:find("no zgo_bake_index.script", 1, true), "the reason: no bake here: " .. l)
end
print("  " .. select(2, said(30, "bip01_l_forearm")))

section("Nothing retries: the upkeep and the Q rounds leave those cuts alone")
local before, lines = asked, #LOG
run(12000)   -- (the upkeep runs every 2.5 s)
for _, l in ipairs(qlines) do DISPATCH(zgo_sync.EVT, l, "host") end
DISPATCH(zgo_sync.EVT, ("Q|30|%s|bip01_l_forearm"):format(c:section()), "host")
run(200)
assert(asked == before, ("the cuts were looked at again %d times"):format(asked - before))
for _, e in pairs(cuts) do assert(said(e.id, e.root) == 1, "still said once") end
print(("  %d cut(s), each said once, none looked at again in 12 s and %d Q lines"):format(count(cuts), #qlines + 1))

section("Each reason in words")
-- an index without this model
FS_FILES["$game_scripts$|zgo_bake_index.script"] = true
rawset(_G, "zgo_bake_index", { models = { ["actors\\other\\model"] = { bip01_l_forearm = true } } })
zgo_bake.reset()
local m1 = corpse(17)
DISPATCH(zgo_sync.EVT, cut_line(m1, "bip01_r_forearm"), "host")
run(100)
local n, l = said(17, "bip01_r_forearm")
assert(n == 1 and l:find("its model " .. SV .. " is not in this machine's bake", 1, true), tostring(l))
print("  " .. l)
-- the model is in the index, but the game wears another one (B2: cut like an un-baked body)
rawset(_G, "zgo_bake_index", { models = { [SV] = { bip01_l_forearm = true, bip01_r_forearm = true } } })
zgo_bake.reset()
local real_matches = zgo_bake.loaded_matches
zgo_bake.loaded_matches = function() return false end
local m2 = corpse(18)
local had = limbs()
DISPATCH(zgo_sync.EVT, cut_line(m2, "bip01_r_forearm"), "host")
run(2000)
n, l = said(18, "bip01_r_forearm")
assert(n == 1 and l:find("the game wears another model than the baked " .. SV, 1, true), tostring(l))
assert(not m2._hidden["bip01_r_forearm"] and count(limbs()) == count(had), "another model is not cut like a baked one")
print("  " .. l)
zgo_bake.loaded_matches = real_matches
zgo_bake.reset()
-- "Use baked models" off
OVR["dismember/baked_models"] = false
run(3000)   -- (the switch clears what was said: the cuts above are looked at once more, in one upkeep)
local m3 = corpse(19)
DISPATCH(zgo_sync.EVT, cut_line(m3, "bip01_r_forearm"), "host")
run(100)
n, l = said(19, "bip01_r_forearm")
assert(n == 1 and l:find("\"Use baked models\" is off on this machine", 1, true), tostring(l))
print("  " .. l)
before = asked
run(6000)
assert(asked == before, "still nothing retried while the reason holds")

section("Switched on with a bake that fits: the host's cuts show after all")
OVR["dismember/baked_models"] = nil
run(3000)
assert(c._hidden["bip01_l_forearm"] and m3._hidden["bip01_r_forearm"], "the cuts this machine can show now are shown")
assert(said(30, "bip01_l_forearm") == 2, "said once more while the option was off, nothing since")

local errs = 0
for _, x in ipairs(LOG) do if x:find("error") or x:find("failed") then errs = errs + 1 print("  " .. x) end end
assert(errs == 0, "errors in the log")
print("MIXED CLIENT OK")
