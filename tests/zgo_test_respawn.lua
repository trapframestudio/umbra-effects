-- A cut body going offline and coming back (zgo_dismember.on_net_destroy,
-- wired to npc_on_net_destroy / monster_on_net_destroy in zgo_main): the
-- player walked away and back, or a co-op client's copy was made again. The
-- object made again has none of the old one's hidden bones or stump caps.
-- The game raises net_destroy for every stalker and monster but
-- npc_on_net_spawn only for living stalkers (xr_motivator returns before it
-- for the dead), so a dead stalker comes back with no callback at all, maybe
-- within one upkeep round. The cut must come back with its cap (baked), and
-- nothing stale may stay (a cap entry for an attachment that died with the
-- old object, a cap on a whole limb, a second "not shown" line).
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local role = ...

if role == nil then
	local ok = true
	for _, r in ipairs({ { "sp", 1 }, { "host", 1 }, { "client", 1 }, { "sp", 0 }, { "client", 0 } }) do
		local p = io.popen(('ZGO_BAKED=%d luajit "%s/zgo_test_respawn.lua" %s 2>&1'):format(r[2], S, r[1]))
		local out = p:read("*a")
		p:close()
		local last = out:match("([^\n]*)\n*$") or ""
		for l in out:gmatch("[^\n]+") do if not l:match("^%[ZGO%]") then print(l) end end
		if not last:find("OK", 1, true) then ok = false print(("%s (baked %d) FAILED"):format(r[1], r[2])) break end
	end
	if not ok then print("RESPAWN TESTS FAILED") os.exit(1) end
	print("ALL RESPAWN TESTS PASSED")
	return
end

arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(1)
print(("\n== [%s, baked %s] a cut body goes offline and comes back"):format(role, tostring(BAKED)))
assert(CB.npc_on_net_destroy and CB.monster_on_net_destroy, "zgo_main listens to both net_destroy callbacks")

local ID, ROOT = 30, "bip01_l_forearm"
local function corpse(fresh)
	local o = NEW_NPC(ID, "stalker", VV(-1, 0, -1.2))
	o._alive, o._died_at, o.health = false, fresh and T_NOW or T_NOW - 5000, 0
	return o
end
local function caps_on(o)
	local n, name = 0
	for k in pairs(o._att) do if k:find("cap") then n, name = n + 1, k end end
	return n, name
end
local function said()
	local n = 0
	for _, l in ipairs(LOG) do
		if l:find(("host cut %s on "):format(ROOT), 1, true) and l:find(("(id %d) not shown"):format(ID), 1, true) then n = n + 1 end
	end
	return n
end

-- the cut: decided here, or the host's D line (the client's copy is a ragdoll
-- already, or, un-baked single player, a fresh kill whose ragdoll comes next)
local o = corpse(role == "sp" and not BAKED)
if role == "client" then
	DISPATCH(zgo_sync.EVT, ("D|%d|%s|%s|1|1|0|0|1|4242"):format(ID, o:section(), ROOT), "host")
else
	zgo_dismember.sever(o, ROOT, { prof = { energy = 3, cls = 3, kind = "bullet" }, dir = VV(0, 0, 1) }, false, false)
end
run(3000)
local shown = BAKED or role ~= "client"
if shown then
	assert(VISIBLY_GONE(o, ROOT) or (not BAKED and o._hidden[ROOT]), "the cut is shown")
	assert(caps_on(o) == 1 and #zgo_debris.caps_of(ID) == 1, "one stump cap")
else
	assert(not o._hidden[ROOT] and caps_on(o) == 0 and said() == 1, "an un-baked ragdoll here: not shown, said once")
end
print(("  before: hidden %s, caps %d"):format(tostring(o._hidden[ROOT]), caps_on(o)))

-- offline (the game: the binder's net_destroy, then the object is gone) and
-- straight back, between two upkeep rounds, as a new object with its ragdoll
-- built with every part; no npc_on_net_spawn for the dead
local function offline_online(wait)
	CB.npc_on_net_destroy(OBJ[ID])
	OBJ[ID] = nil
	if wait then run(wait) end
	return corpse(false)
end
local function check(o2, what)
	run(3000)
	local n, name = caps_on(o2)
	if BAKED then
		assert(o2._hidden[ROOT] and VISIBLY_GONE(o2, ROOT), what .. ": the cut is shown again on the new object")
		assert(n == 1, what .. ": its stump cap is back, once: " .. n)
		local c = zgo_debris.caps_of(ID)
		assert(#c == 1 and c[1].name == name, what .. ": the cap list names the new attachment only")
	else
		-- (an un-baked ragdoll keeps the part on screen: no cap on a whole limb,
		-- no stale cap entry, and a client doesn't say it again)
		assert(n == 0 and #zgo_debris.caps_of(ID) == 0, what .. ": no cap on a whole limb, no stale cap entry")
		if role == "client" then assert(said() == 1, what .. ": still said once, got " .. said()) end
	end
	assert(zgo_dismember.get_state()[ID], what .. ": the cut itself is kept")
	print(("  %s: hidden %s, caps %d"):format(what, tostring(o2._hidden[ROOT]), n))
end
check(offline_online(), "back within one upkeep round")
check(offline_online(5000), "back after a while")
-- net_destroy twice before it comes back: the same
CB.npc_on_net_destroy(OBJ[ID])
CB.npc_on_net_destroy(OBJ[ID])
check(corpse(false), "net_destroy twice")

-- a monster nobody cut: nothing happens
CB.monster_on_net_destroy(NEW_NPC(31, "monster", VV(1, 0, 1)))
run(100)
local errs = 0
for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") then errs = errs + 1 print("  " .. l) end end
assert(errs == 0, "errors in the log")
-- a broken object (during a level change, say) can't throw out of the callback
local n0 = #LOG
CB.npc_on_net_destroy(setmetatable({}, { __index = function() error("object gone") end }))
assert(#LOG == n0 + 1 and LOG[#LOG]:find("net destroy", 1, true), "one [ZGO] line, no error raised")
print(("RESPAWN %s OK"):format(role))
