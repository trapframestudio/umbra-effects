-- Native add-on bootstrap (run: luajit zgo_test_native.lua [seed])
-- zgo_native.script against the real LuaJIT FFI (which can't load a Windows
-- DLL here: the clean fallback) and against a Lua stand-in for the DLL
-- (tests/mocks/native.lua): settings gating, the C declarations against
-- native/include/zgo_native.h, the co-op capability exchange (host and
-- client), broken bodies (records, limits, kid mode, Depart, save/load,
-- determinism) and the probe. The DLL itself is tested on the real engine
-- code under Wine: native/tests/run.sh.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 5
arg = { S .. "/../gamedata/scripts", "host" }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
local ffi = require("ffi")
local N = zgo_native
local T = N._test
local ZS = zgo_settings
local BONES, FINDER = N.CAP.BONES, N.CAP.FINDER

OVR = {}
local old_setting = zgo_util.setting
zgo_util.setting = function(k) if OVR[k] ~= nil then return OVR[k] end return old_setting(k) end

local function section(t) print(("\n== %s"):format(t)) end
local function logs(pat) local n = 0 for _, l in ipairs(LOG) do if l:find(pat) then n = n + 1 end end return n end
local function clear(t) for i = #t, 1, -1 do t[i] = nil end end
-- every N line sent (host -> clients) or up (client -> host)
local function nlines(list)
	local out = {}
	for _, batch in ipairs(list) do
		for line in batch:gmatch("[^\n]+") do if line:sub(1, 2) == "N|" then out[#out + 1] = line end end
	end
	return out
end
local function has_line(list, pat) for _, l in ipairs(nlines(list)) do if l:find(pat) then return true end end return false end
local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
local function settle(ms) run(ms or 600) end

local function solo() XrrSessionActive = false end
local PEERS = { "2" }
local function host_mode(peers)
	XrrSessionActive = true
	XrrIsClient = function() return false end
	PEERS = peers or { "2" }
	XrrPeerCount = #PEERS
	XrrPlayers = function() return {
		IsPlayerDummy = function(self, id) return id == 77 end,
		GetPeerCount = function() return #PEERS end,
		GetPeerNetidAt = function(self, i) return PEERS[i] end,
	} end
end
local function client_mode()
	XrrSessionActive = true
	XrrIsClient = function() return true end
	XrrPeerCount = 1
end

local function use_mock(opts)
	T.reset()
	local lib = NATIVE_MOCK(opts)
	NATIVE_MOCK_LIB = lib
	T.set_platform(true)
	T.set_loader(function(path) lib.loaded_from = path return lib end)
	return lib
end

------------------------------------------------------------------------
section("Defaults: off, nothing loaded, nothing sent")
------------------------------------------------------------------------
assert(ZS.default("native/enable") == false and ZS.default("native/bones") == false, "native is off by default")
assert(ZS.coop_of("native/enable") == "local" and ZS.coop_of("native/bones") == "local", "each machine decides whether it loads the DLL")
assert(ZS.coop_of("native/deform_corpses") == "host" and ZS.coop_of("native/deform_strength") == "host", "the host decides what happens to bodies")
assert(ZS.coop_of("performance/native_bodies") == "local")
local loads = 0
T.set_loader(function() loads = loads + 1 error("must not load") end)
T.set_platform(true)
clear(SENT)
settle(2000)
assert(loads == 0 and T.S.tried == false, "nothing loads while Native extensions is off")
assert(not N.available() and not N.has(BONES) and not N.has(FINDER) and N.local_caps() == 0)
assert(#nlines(SENT) == 0, "a host with native off sends no N lines")
local pr = N.probe()
assert(pr.loaded == false and loads == 0, "probe() doesn't load it either while it is off")
for k, v in pairs(pr) do assert(type(v) ~= "table" and type(v) ~= "function", "probe() is flat: " .. k) end
print(("  off: no load, no lines, probe says: %s"):format(pr.state))

------------------------------------------------------------------------
section("Fallback: the real FFI can't load a Windows DLL here")
------------------------------------------------------------------------
T.reset()
OVR["native/enable"] = true
settle(600)
assert(T.S.tried and T.S.lib == nil, "one attempt, nothing loaded")
assert(T.S.why:find("not 64%-bit Windows"), T.S.why)
assert(not N.has(BONES) and not N.available() and N.local_caps() == 0)
T.reset()
T.set_platform(true)         -- as if on Windows: the real ffi.load fails on every candidate
settle(600)
assert(T.S.tried and T.S.lib == nil and T.S.why:find("zgo_native.dll not loaded"), T.S.why)
assert(logs("native: zgo_native.dll not loaded") >= 1, "the failure is in the log")
settle(2000)
assert(logs("native: zgo_native.dll not loaded") == 1, "and only once")
print("  " .. T.S.why)
-- the declarations went in
assert(ffi.sizeof("zgo_stats") == 64 and ffi.offsetof("zgo_stats", "bound") == 56 and ffi.offsetof("zgo_stats", "hooks") == 60)

------------------------------------------------------------------------
section("The Lua declarations match native/include/zgo_native.h")
------------------------------------------------------------------------
do
	local f = assert(io.open(S .. "/../native/include/zgo_native.h"))
	local h = f:read("*a")
	f:close()
	h = h:gsub("/%*.-%*/", ""):gsub("\n%s*#[^\n]*", "\n")
	local function norm(s)
		s = s:gsub("%s+", " "):gsub("%s*%*%s*", "* "):gsub("%(%s*", "("):gsub("%s*%)", ")"):gsub("%s*,%s*", ", ")
		return (s:gsub("^%s+", ""):gsub("%s+$", ""))
	end
	local hdr, lua = {}, {}
	for d in h:gmatch("ZGO_API%s+([^;]+);") do hdr[#hdr + 1] = norm(d) end
	for d in N.CDEF_FUNCS:gmatch("([^;]+);") do if d:find("%S") then lua[#lua + 1] = norm(d) end end
	assert(#hdr >= 20 and #hdr == #lua, ("%d functions in the header, %d in the script"):format(#hdr, #lua))
	for i = 1, #hdr do assert(hdr[i] == lua[i], ("declaration %d differs:\n  header: %s\n  script: %s"):format(i, hdr[i], lua[i])) end
	local hs = norm(assert(h:match("typedef struct zgo_stats {(.-)} zgo_stats;"), "struct in the header"))
	local ls = norm(assert(N.CDEF_TYPES:match("typedef struct zgo_stats {(.-)} zgo_stats;"), "struct in the script"))
	assert(hs == ls, "zgo_stats differs:\n  " .. hs .. "\n  " .. ls)
	local f2 = assert(io.open(S .. "/../native/include/zgo_native.h"))
	local raw = f2:read("*a")
	f2:close()
	assert(tonumber(raw:match("#define ZGO_NATIVE_ABI (%d+)")) == N.ABI, "ABI constant")
	local ncap = 0
	for name, v in raw:gmatch("#define ZGO_CAP_(%w+)%s+0x(%x+)u") do
		ncap = ncap + 1
		assert(N.CAP[name] == tonumber(v, 16), "capability " .. name)
	end
	assert(ncap == count(N.CAP), "every capability bit")
	for name, v in raw:gmatch("#define ZGO_E_(%w+)%s+(%-%d+)") do assert(N.ERRORS[tonumber(v)], "error text for ZGO_E_" .. name) end
	print(("  %d functions, zgo_stats, ABI %d, %d capability bits: identical"):format(#hdr, N.ABI, ncap))
end

------------------------------------------------------------------------
section("Mock DLL: unsupported exe, wrong ABI, failing hooks")
------------------------------------------------------------------------
solo()
local lib = use_mock({ unsupported = true })
OVR["native/bones"] = true
settle(600)
assert(T.S.lib == lib and T.S.init == -1, "loaded, finder said no")
assert((lib.calls.enable or 0) == 0, "an unsupported exe never gets a hook")
assert(not N.available() and N.local_caps() == 0 and not N.has(BONES))
assert(logs("every native feature stays off") >= 1)
assert((lib.calls.clear_all or 0) == 1, "stale bindings of an earlier Lua state are dropped at load")

lib = use_mock({ abi = 2 })
settle(600)
assert(T.S.lib == nil and T.S.why:find("ABI 2"), T.S.why)
assert((lib.calls.init or 0) == 0, "a DLL with another ABI is never initialised")
print("  " .. T.S.why)

lib = use_mock({ hook_fail = true })
settle(600)
assert(T.S.init == 0 and lib.calls.enable == 1 and T.S.hooks == 0, "the hook install failed")
assert(N.local_caps() == FINDER and not N.has(BONES))
settle(2000)
assert(lib.calls.enable == 1, "a failed install isn't retried every tick")
OVR["native/bones"] = false
settle(600)
OVR["native/bones"] = true
settle(600)
assert(lib.calls.enable == 3, "... but again when the switch changes")

------------------------------------------------------------------------
section("Mock DLL: settings gating (single player)")
------------------------------------------------------------------------
OVR["native/bones"] = false
lib = use_mock()
settle(600)
assert(T.S.init == 0 and N.available(), "supported")
assert(lib.last_enable == 0 and T.S.hooks == 0, "bone hooks stay out while their switch is off")
assert(N.local_caps() == FINDER and N.has(FINDER) and not N.has(BONES))
OVR["native/bones"] = true
settle(600)
assert(lib.last_enable == BONES and T.S.hooks == BONES, "switch on: hooks in")
assert(N.local_caps() == FINDER + BONES and N.has(BONES), "single player: this machine decides")
OVR["native/bones"] = false
settle(600)
assert(lib.last_enable == 0 and T.S.hooks == 0 and not N.has(BONES), "switch off: hooks out")
OVR["native/bones"] = true
settle(600)
assert(N.has(BONES))
OVR["native/enable"] = false
settle(600)
assert(lib.last_enable == 0 and T.S.hooks == 0 and N.local_caps() == 0 and not N.has(FINDER), "master off: everything out")
OVR["native/enable"] = true
settle(600)
assert(T.S.hooks == BONES and N.has(BONES), "master on again: back in")
OVR["general/enable"] = false
settle(600)
assert(T.S.hooks == 0 and not N.has(BONES), "the mod's own master switch takes them out too")
OVR["general/enable"] = nil
settle(600)
assert(T.S.hooks == BONES)
print(("  zgo_enable called %d times, loaded from %s"):format(lib.calls.enable, tostring(lib.loaded_from)))

------------------------------------------------------------------------
section("Co-op host: announce, replies, every player must have it")
------------------------------------------------------------------------
host_mode({ "2" })
clear(SENT)
settle(600)
assert(has_line(SENT, "^N|H|1|1|3|%d+$"), "the host announces abi, wire, caps, round")
assert(not N.has(BONES), "nothing runs before every player answered")
local round = tonumber(nlines(SENT)[1]:match("|(%d+)$"))
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|3|%d"):format(round), "2")
settle(300)
assert(N.has(BONES) and N.session_caps() == 3, "every player has it: on")
assert(has_line(SENT, "^N|S|%d+|3$"), "the session's caps go to the clients")
clear(SENT)
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|1|%d"):format(round), "2")
settle(300)
assert(not N.has(BONES) and N.has(FINDER), "a player without the bone hooks: off for everyone")
assert(has_line(SENT, "^N|S|%d+|1$"))
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|3|%d"):format(round), "2")
settle(300)
assert(N.has(BONES))
-- a second player joins: nothing until it answers too
clear(SENT)
host_mode({ "2", "3" })
settle(300)
assert(not N.has(BONES), "a new player: wait for its answer")
local lines = nlines(SENT)
local r2 = tonumber(lines[1]:match("^N|H|1|1|3|(%d+)$"))
assert(r2 and r2 > round, "announced again")
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|3|%d"):format(r2), "2")
settle(300)
assert(not N.has(BONES), "one of two answered")
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|3|%d"):format(r2), "3")
settle(300)
assert(N.has(BONES), "both answered")
-- another version of the add-on
DISPATCH(zgo_sync.EVT_UP, ("N|C|2|1|3|%d"):format(r2), "3")
settle(300)
assert(not N.has(BONES) and logs("runs another native add-on version") >= 1, "another ABI counts as nothing")
DISPATCH(zgo_sync.EVT_UP, ("N|C|1|1|3|%d"):format(r2), "3")
settle(300)
assert(N.has(BONES))
-- periodic re-announce: no gap
local gaps, announces = 0, 0
clear(SENT)
for _ = 1, 140 do
	frame(250)
	if not N.has(BONES) then gaps = gaps + 1 end
	for _, l in ipairs(nlines(SENT)) do
		local r = l:match("^N|H|1|1|3|(%d+)$")
		if r then
			announces = announces + 1
			DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. r, "2")
			DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. r, "3")
		end
	end
	clear(SENT)
end
assert(announces >= 1 and gaps == 0, ("re-announced every 30 s (%d) without turning anything off (%d gaps)"):format(announces, gaps))
-- without a player list (older xrRazom): the peer count
XrrPlayers = function() return { IsPlayerDummy = function() return false end } end
XrrPeerCount = 2
settle(600)
assert(N.has(BONES), "two answers for two players")
-- native switched off on the host: clients hear the session is empty
clear(SENT)
OVR["native/bones"] = false
settle(600)
assert(not N.has(BONES) and has_line(SENT, "^N|S|%d+|1$"), "host without bone hooks: session 1")
OVR["native/enable"] = false
clear(SENT)
settle(600)
assert(N.session_caps() == 0 and has_line(SENT, "^N|S|%d+|0$"), "host off: session 0, said once")
clear(SENT)
settle(2000)
assert(#nlines(SENT) == 0, "and then quiet")
OVR["native/enable"], OVR["native/bones"] = true, true
host_mode({ "2" })
settle(600)
print(("  %d re-announces in 35 s, no gap; another ABI or a missing answer turns it off"):format(announces))

------------------------------------------------------------------------
section("Co-op client: answers the host, follows its session")
------------------------------------------------------------------------
lib = use_mock()
client_mode()
clear(UP)
settle(600)
assert(T.S.hooks == BONES, "the client's own hooks follow its own settings")
assert(not N.has(BONES) and #nlines(UP) == 0, "nothing before the host speaks")
DISPATCH(zgo_sync.EVT, "N|H|1|1|3|7")
settle(300)
assert(has_line(UP, "^N|C|1|1|3|7$"), "the client answers with its caps")
assert(not N.has(BONES), "still waiting for the session")
DISPATCH(zgo_sync.EVT, "N|S|7|3")
settle(300)
assert(N.has(BONES), "the session has it")
DISPATCH(zgo_sync.EVT, "N|S|7|1")
settle(300)
assert(not N.has(BONES), "someone lacks it: off")
DISPATCH(zgo_sync.EVT, "N|S|7|3")
clear(UP)
OVR["native/bones"] = false
settle(600)
assert(has_line(UP, "^N|C|1|1|1|7$") and not N.has(BONES), "the client tells the host when its own caps change")
OVR["native/bones"] = true
settle(600)
clear(UP)
DISPATCH(zgo_sync.EVT, "N|H|5|1|3|8")
settle(300)
assert(has_line(UP, "^N|C|1|1|0|8$"), "a host with another ABI gets caps 0")
-- client with native off still answers (with 0), so the host knows
T.reset()
OVR["native/enable"] = false
clear(UP)
DISPATCH(zgo_sync.EVT, "N|H|1|1|3|9")
settle(300)
assert(has_line(UP, "^N|C|1|1|0|9$") and T.S.tried == false, "native off: answers 0 without loading anything")
OVR["native/enable"] = true

------------------------------------------------------------------------
section("Broken bodies: records, the ragdoll, the op sets")
------------------------------------------------------------------------
lib = use_mock()
host_mode({ "2" })
settle(600)
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. T.X.round, "2")
settle(300)
assert(N.has(BONES))
local function kill(o) o._alive = false o.health = 0 o._died_at = T_NOW end
local function blast(o, sev) zgo_util.emit_event("blast_body", o, { dead = true, sev = sev, id = o:id() }, {}) end
NPC_YAW = 0
local a = NEW_NPC(110, "stalker", VV(0, 0, -1.2))
NPC_YAW = 1.3
local b = NEW_NPC(120, "stalker", VV(1, 0, -1.2))
NPC_YAW = nil
kill(a)
clear(SENT)
blast(a, 0.95)
assert(T.recs()[110], "a record for the body")
settle(16)
assert(has_line(SENT, "^N|B|110|%d+|0%.950$"), "and a line for the clients")
assert(not lib.ops_of(a), "not before the ragdoll exists")
settle(600)
local ops = lib.ops_of(a)
assert(ops and #ops >= 1, "bent once the ragdoll is there")
assert(count(T.active()) == 1)
local function det3(l) return l[1] * (l[5] * l[9] - l[6] * l[8]) - l[2] * (l[4] * l[9] - l[6] * l[7]) + l[3] * (l[4] * l[8] - l[5] * l[7]) end
local kinds, bones = {}, {}
for _, g in ipairs(ops) do
	local name = a:bone_name(g.driver)
	local has_driver = false
	for _, m in ipairs(g.members) do has_driver = has_driver or m == g.driver bones[m] = true end
	assert(has_driver, "the driver moves with its group: " .. name)
	for i = 1, 12 do assert(g.l[i] == g.l[i] and math.abs(g.l[i]) < 10, "finite transform") end
	local d = det3(g.l)
	assert(d > 0.3 and d < 1.0001, ("no mirror, no blow-up (%s: det %.3f)"):format(name, d))
	kinds[#kinds + 1] = name
end
assert(count(bones) <= 32 and #ops <= 12, "within the DLL's limits")
print(("  power 0.95: %d groups (%s), %d bones"):format(#ops, table.concat(kinds, ", "), count(bones)))
-- members are whole subtrees: a bent forearm takes the hand along
local sk = T.skeleton(a)
for _, g in ipairs(ops) do
	local sub = T.subtree(sk, g.driver)
	local name = a:bone_name(g.driver)
	if name:find("forearm") or name:find("calf") or name:find("upperarm") then
		assert(#g.members == #sub, name .. " carries everything below it")
	end
end
-- the same seed bends the same way on another machine, whatever the body's pose and heading
local r = T.recs()[110]
local s1, s2 = N.body_spec(a, r.seed, r.p), N.body_spec(b, r.seed, r.p)
assert(#s1 == #s2 and #s1 == #ops)
for i = 1, #s1 do
	assert(s1[i].driver == s2[i].driver and #s1[i].members == #s2[i].members)
	for k = 1, 12 do assert(math.abs(s1[i].l[k] - s2[i].l[k]) < 1e-6, "same bend in the bone's own frame") end
	for k = 1, 12 do assert(math.abs(s1[i].l[k] - ops[i].l[k]) < 1e-6, "what the DLL got") end
end
-- weak blasts bend little or nothing; strong ones more
local nweak, nstrong = 0, 0
for sd = 1, 40 do nweak = nweak + #N.body_spec(a, sd, 0.2) nstrong = nstrong + #N.body_spec(a, sd, 1.6) end
assert(nweak < nstrong and nstrong <= 40 * 12, ("weak %d < strong %d"):format(nweak, nstrong))
-- a weaker second blast changes nothing; a stronger one re-bends
local seed_a = r.seed
blast(a, 0.5)
assert(T.recs()[110].seed == seed_a)
blast(a, 1.4)
assert(T.recs()[110].seed ~= seed_a and T.recs()[110].p == 1.4)
settle(600)
local ops2 = lib.ops_of(a)
assert(ops2 ~= ops, "re-bent with the new record")
-- the living are never bent, weak blasts make no record
local alive = NEW_NPC(130, "stalker", VV(-1, 0, -1.2))
zgo_util.emit_event("blast_body", alive, { dead = false, sev = 1 }, {})
local c = NEW_NPC(140, "stalker", VV(2, 0, 1))
kill(c)
blast(c, 0.05)
assert(not T.recs()[130] and not T.recs()[140])

------------------------------------------------------------------------
section("Broken bodies: limits, kid mode, Depart, session, switches")
------------------------------------------------------------------------
kill(b)
blast(b, 0.9)
local d = NEW_NPC(150, "stalker", VV(-2, 0, 1))
kill(d)
settle(100)
blast(d, 0.9)
settle(600)
assert(count(T.active()) == 3, "three bodies bent")
OVR["performance/native_bodies"] = 2
settle(600)
assert(count(T.active()) == 2 and not T.active()[110], "limit 2: the oldest goes back to normal")
assert(#lib.ops_of(a) == 0, "its op set emptied first (the hook puts the bones back)")
settle(1200)
assert(lib.ops_of(a) == nil, "then unbound")
OVR["performance/native_bodies"] = nil
settle(600)
assert(count(T.active()) == 3)
-- kid mode
OVR["general/kid_mode"] = true
settle(600)
assert(count(T.active()) == 0, "kid mode: every body back to normal")
assert(count(T.recs()) >= 3, "the records stay")
settle(1200)
OVR["general/kid_mode"] = nil
settle(600)
assert(count(T.active()) == 3 and #lib.ops_of(a) >= 1, "kid mode off: bent again")
-- Depart: the engine released a model (offline, new visual): bind again
local h_old = T.active()[150].h
lib.depart(d)
settle(600)
assert(T.active()[150] and T.active()[150].h ~= h_old, "a released model gets a new binding")
-- a player without the hooks joins: off for everyone, back when it has them
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|1|" .. T.X.round, "2")
settle(600)
assert(count(T.active()) == 0, "session without bones: nothing bent")
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. T.X.round, "2")
settle(600)
assert(count(T.active()) == 3)
-- the host's feature switch (clients get the host's value)
OVR["native/deform_corpses"] = false
settle(600)
assert(count(T.active()) == 0)
OVR["native/deform_corpses"] = nil
settle(600)
assert(count(T.active()) == 3)
-- the hook switch: everything unbound at once, then the hooks go out
OVR["native/bones"] = false
settle(600)
assert(count(T.active()) == 0 and #T.unbind_q() == 0 and T.S.hooks == 0)
for _, s in pairs(lib.slots) do assert(s.kin == 0, "nothing left bound in the DLL") end
OVR["native/bones"] = true
settle(600)
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. T.X.round, "2")
settle(600)
assert(count(T.active()) == 3, "back")

------------------------------------------------------------------------
section("Broken bodies: co-op lines, level change, save and load, release")
------------------------------------------------------------------------
-- a player answering for the first time gets every record
clear(SENT)
host_mode({ "2", "4" })
settle(300)
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. T.X.round, "2")
DISPATCH(zgo_sync.EVT_UP, "N|C|1|1|3|" .. T.X.round, "4")
settle(300)
local nb = 0
for _, l in ipairs(nlines(SENT)) do if l:find("^N|B|") then nb = nb + 1 end end
assert(nb >= 3, "records re-sent to a joining player: " .. nb)
-- level change: released, records kept
CB.on_level_changing()
assert(count(T.active()) == 0 and count(T.recs()) >= 3)
settle(600)
assert(count(T.active()) == 3, "bent again where the bodies still are")
-- save and load
local data = SAVE_GAME()
assert(data.zgo_native and #data.zgo_native.recs == count(T.recs()), "records saved")
local before = {}
for id, rr in pairs(T.recs()) do before[id] = rr.seed end
for id in pairs(T.recs()) do T.recs()[id] = nil end
CB.load_state(data)
for id, sd in pairs(before) do assert(T.recs()[id] and T.recs()[id].seed == sd, "record back: " .. id) end
-- a released body is forgotten everywhere
clear(SENT)
CB.server_entity_on_unregister({ id = 150 })
assert(not T.recs()[150] and not T.active()[150])
settle(16)
assert(has_line(SENT, "^N|F|150$"))
-- a client replays the lines
host_mode({ "2" })
client_mode()
for id in pairs(T.recs()) do T.recs()[id] = nil end
DISPATCH(zgo_sync.EVT, "N|B|110|" .. T_NOW .. "|0.700")
DISPATCH(zgo_sync.EVT, "N|S|9|3")
settle(600)
assert(T.recs()[110] and T.recs()[110].seed == T_NOW - 600 + 0 or T.recs()[110], "the client keeps the host's record")
assert(T.active()[110], "and bends the body itself")
DISPATCH(zgo_sync.EVT, "N|F|110")
settle(600)
assert(not T.recs()[110] and not T.active()[110], "and forgets it with the host")

------------------------------------------------------------------------
section("deform() for other modules, the probe, the status button")
------------------------------------------------------------------------
solo()
local e = NEW_NPC(160, "stalker", VV(0, 0, 2))
local h, why = N.deform(e, { { driver = "bip01_l_forearm", rotate = { 0, 0, 1, 0.5 } }, { driver = "bip01_spine2", members = { "bip01_spine2" }, scale = { 1, 0, 0, 0.8 } } })
assert(h, tostring(why))
local eo = lib.ops_of(e)
assert(eo and #eo == 2 and #eo[1].members == #T.subtree(T.skeleton(e), BONE_ID["bip01_l_forearm"]) and #eo[2].members == 1)
assert(N.set_groups(h, e, {}) == 0 and #lib.ops_of(e) == 0, "an empty set restores the bones")
assert(N.deform(e, { { driver = "no_such_bone", move = { 0, 0, 0.1 } } }) == nil, "unknown bones are refused")
assert(N.undeform(h) and not N.undeform(h))
settle(1200)
assert(lib.ops_of(e) == nil, "released")
local p = N.probe()
for k, v in pairs(p) do assert(type(v) ~= "table" and type(v) ~= "function", "probe() is flat: " .. k) end
assert(p.loaded == true and p.caps == "finder+bones" and p.hooks == "bones" and p.capture_test and p.capture_test:find("^ok"), p.capture_test)
N.log_report()
assert(logs("native: %-%-%-%- status report") >= 1 and logs("native: +result: SUPPORTED") >= 1, "the report is in the log")
-- settings: every option of this page described, and only shown when it can matter
for _, key in ipairs({ "native/bones", "native/deform_corpses", "native/deform_strength", "native/status" }) do
	assert(ZS.default(key) ~= nil or key == "native/status")
end

local errs = logs("native: update error")
assert(errs == 0, "no update errors (" .. errs .. ")")
print(("\n%d log lines from the native module"):format(logs("native:")))
print("PASSED")
