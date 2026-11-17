-- Body gibs (zgo_debris.spawn_gibs with the bake's pieces, docs/formats/gibs.md).
--   luajit zgo_test_gibs.lua [seed]
-- Runs as a co-op host (so the G line can be read back); the bake's gib set is
-- mocked here: four pieces from the head, chest, left thigh and right calf.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber((...)) or 1
arg = { S .. "/../gamedata/scripts", "host" }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)

local U, D = zgo_util, zgo_debris
local base_setting = U.setting
local OVR = {}
U.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	return base_setting(k)
end
local function section(t) print(("\n== %s"):format(t)) end
local function errs()
	local n = 0
	for _, l in ipairs(LOG) do
		if l:find("error") or l:find("traceback") or l:find("failed") then n = n + 1 print("  ERR " .. l) end
	end
	return n
end

local MODEL = "zgo\\baked\\gibs\\ab\\abcdef123456"
FS_FILES["$game_meshes$|" .. MODEL .. ".ogf"] = true
local function frame_of(cx, cy, cz)
	return { i = { x = 1, y = 0, z = 0 }, j = { x = 0, y = 1, z = 0 }, k = { x = 0, y = 0, z = 1 }, c = { x = cx, y = cy, z = cz } }
end
local SET = { model = MODEL, set = 1, count = 4, pieces = {
	{ bone = "bip01_head", m = frame_of(0, 0.05, 0.08) },
	{ bone = "bip01_spine1", m = frame_of(0, 0, 0.12) },
	{ bone = "bip01_l_thigh", m = frame_of(0.06, -0.2, 0) },
	{ bone = "bip01_r_calf", m = frame_of(-0.05, -0.15, 0) },
} }
local HAS_SET, MATCHES = true, true
zgo_bake.gibs = function(obj) return HAS_SET and SET or nil end
zgo_bake.loaded_matches = function(obj) return MATCHES end
local SITES = { bip01_l_thigh = { { index = 1, bone = "bip01_l_thigh" } } }
local base_sites = zgo_bake.sites
zgo_bake.sites = function(obj, sec) return SITES[sec] or base_sites(obj, sec) end

local npc = NEW_NPC(400, "stalker", VV(2, 0, 2))
npc._alive, npc.health = false, 0

local function gib_atts()
	local out = {}
	for name, a in pairs(LEVEL_ATT) do
		if name:find("gib") then out[#out + 1] = a end
	end
	table.sort(out, function(x, y) return x.name < y.name end)
	return out
end
local function shown_piece(a)
	local id
	for k in pairs(a.cbs) do assert(not id, "one driven bone") id = k end
	return id
end
local function clear()
	D.reset()
	for name in pairs(LEVEL_ATT) do LEVEL_ATT[name] = nil end
end

------------------------------------------------------------------------
section("Pieces of the body: nearest the blast, set up as one piece each, placed where they were")
clear()
local head = npc:bone_position("bip01_head")
local used = D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 12345)
assert(type(used) == "table" and #used == 2, "two body pieces")
assert(used[1] == 1, "the head's piece comes first next to the head")
local atts = gib_atts()
assert(#atts == 2, "two attachments, no meat beside them")
for _, a in ipairs(atts) do
	assert(a.model == MODEL and a.type ~= nil)
	local i = shown_piece(a)
	assert(i and i >= 1 and i <= SET.count)
	for b = 1, SET.count do
		if b == i then assert(a.vis[b] == nil, "its own bone stays visible")
		else assert(a.vis[b] == false, "every other piece hidden") end
	end
	local pc = SET.pieces[i]
	local rel = matrix():identity()
	rel.i, rel.j, rel.k, rel.c = VV(pc.m.i.x, pc.m.i.y, pc.m.i.z), VV(pc.m.j.x, pc.m.j.y, pc.m.j.z),
		VV(pc.m.k.x, pc.m.k.y, pc.m.k.z), VV(pc.m.c.x, pc.m.c.y, pc.m.c.z)
	local want = matrix():mul_43(npc:bone_transform(pc.bone), rel).c
	local got = ATT_WORLD(a, i)
	assert(got:distance_to(want) < 1e-4, ("piece %d starts where it was on the body (%.4f off)"):format(i, got:distance_to(want)))
end
local y0 = {}
for _, a in ipairs(atts) do y0[a.name] = ATT_WORLD(a, shown_piece(a)).y end
run(3000)
for _, a in ipairs(atts) do
	if LEVEL_ATT[a.name] then assert(ATT_WORLD(a, shown_piece(a)).y < y0[a.name], "fell") end
end
assert(errs() == 0)
print(("  pieces %s; placed on the body, then fell"):format(table.concat(used, ",")))

section("A second blast on the same body throws the pieces still left first")
local again = D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 999)
assert(#again == 2 and again[1] ~= used[1] and again[1] ~= used[2] and again[2] ~= used[1] and again[2] ~= used[2])
local third = D.spawn_gibs(head, VV(0, 1, 0), 3, npc, 7)
assert(#third == 3, "once all have flown, pieces are thrown again")
print(("  then %s, then %s"):format(table.concat(again, ","), table.concat(third, ",")))

section("More gibs than pieces: the rest are meat models")
clear()
local npc2 = NEW_NPC(401, "stalker", VV(-2, 0, 2))
npc2._alive, npc2.health = false, 0
local u2 = D.spawn_gibs(npc2:bone_position("bip01_spine1"), VV(0, 1, 0), 6, npc2, 3)
local meat = 0
for _, a in ipairs(gib_atts()) do if a.model ~= MODEL then meat = meat + 1 end end
assert(#u2 == 4 and meat == 2, ("4 pieces + 2 meat, got %d + %d"):format(#u2, meat))

section("Wound chunks take pieces from the wounded part first")
clear()
local npc3 = NEW_NPC(402, "stalker", VV(4, 0, 2))
npc3._alive, npc3.health = false, 0
D.spawn_chunks(npc3, "bip01_l_thigh", nil, npc3:bone_position("bip01_head"), VV(0, 1, 0), 1, 11)
local a3 = gib_atts()
assert(#a3 == 1 and shown_piece(a3[1]) == 3, "the thigh's piece, even next to the head")

section("Co-op: the host sends its pieces, a client throws the same ones")
clear()
SENT = {}
zgo_dismember.spawn_gibs(head, VV(0, 1, 0), 2, npc)
zgo_sync.flush()
local gline
for _, batch in ipairs(SENT) do
	for l in (batch .. "\n"):gmatch("([^\n]*)\n") do if l:sub(1, 2) == "G|" then gline = l end end
end
assert(gline, "a G line went out")
local f = {}
for x in (gline .. "|"):gmatch("([^|]*)|") do f[#f + 1] = x end
assert(#f == 11 and f[11]:match("^%d+,%d+$"), "field 11 lists the pieces: " .. gline)
print("  sent: " .. gline)
clear()
f[11] = "4,2"
DISPATCH(zgo_sync.EVT, table.concat(f, "|"))
frame(16)
local got = {}
for _, a in ipairs(gib_atts()) do got[#got + 1] = shown_piece(a) end
table.sort(got)
assert(#got == 2 and got[1] == 2 and got[2] == 4, "exactly the host's pieces")
clear()
DISPATCH(zgo_sync.EVT, table.concat(f, "|", 1, 10))
frame(16)
assert(#gib_atts() == 2, "a line from an older host (10 fields): chosen here")
clear()
f[11] = "-"
DISPATCH(zgo_sync.EVT, table.concat(f, "|"))
frame(16)
assert(#gib_atts() == 2, "'-' (the host threw meat): this machine picks")
assert(errs() == 0)

section("Meat models: picked in MCM, no bake, another model, a living body's id, kid mode")
local function only_meat(label)
	local n = 0
	for _, a in ipairs(gib_atts()) do
		assert(a.model ~= MODEL, label .. ": no body pieces")
		n = n + 1
	end
	assert(n == 2, label .. ": two meat gibs, got " .. n)
end
clear()
OVR["dismember/gib_style"] = "meat"
assert(D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5) == nil)
only_meat("MCM meat")
OVR["dismember/gib_style"] = nil
clear()
HAS_SET = false
D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5)
only_meat("no bake")
HAS_SET = true
clear()
MATCHES = false
D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5)
only_meat("another mod's model")
MATCHES = true
clear()
D.spawn_gibs(head, VV(0, 1, 0), 2, nil, 5)
only_meat("no body given")
clear()
FS_FILES["$game_meshes$|" .. MODEL .. ".ogf"] = nil
D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5)
FS_FILES["$game_meshes$|" .. MODEL .. ".ogf"] = true
for _, a in ipairs(gib_atts()) do assert(a.model ~= MODEL, "missing file: meat") end
clear()
OVR["general/kid_mode"] = true
assert(D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5) == nil and #gib_atts() == 0, "kid mode: nothing")
OVR["general/kid_mode"] = nil
clear()
OVR["dismember/gibs"] = false
assert(D.spawn_gibs(head, VV(0, 1, 0), 2, npc, 5) == nil and #gib_atts() == 0, "Gibs off: nothing")
OVR["dismember/gibs"] = nil
assert(errs() == 0)

------------------------------------------------------------------------
section("Co-op: a client given the host's pieces throws them the same way, and remembers them")
-- where every gib of the last burst is after a while in the air
local function flight()
	local out = {}
	for _, it in ipairs(zgo_debris.list()) do
		out[#out + 1] = ("%s@%.4f,%.4f,%.4f"):format(tostring(next(it.mats) or it.kind), it.body.a.x, it.body.a.y, it.body.a.z)
	end
	table.sort(out)
	return table.concat(out, " ")
end
local function burst_pieces()
	local out = {}
	for _, a in ipairs(gib_atts()) do out[#out + 1] = shown_piece(a) end
	table.sort(out)
	return table.concat(out, ",")
end
local function lines(kind)
	local out = {}
	for _, b in ipairs(SENT) do
		for l in (b .. "\n"):gmatch("([^\n]*)\n") do if l:sub(1, #kind) == kind then out[#out + 1] = l end end
	end
	return out
end
-- a fresh body (nothing thrown from it yet) on a fresh module, then the
-- same lines on another fresh module (a client: no choosing, its own memory)
local npc5 = NEW_NPC(401, "stalker", VV(2, 0, 2))
npc5._alive, npc5.health = false, 0
local function fresh_debris()
	zgo_debris.reset()
	for name in pairs(LEVEL_ATT) do LEVEL_ATT[name] = nil end
	rawset(_G, "zgo_debris", nil)   -- (loaded again on the next use: empty memory)
end
fresh_debris()
SENT = {}
-- host: a head burst (G), then a wound's chunk burst on the same body (Y|g:
-- every machine chooses those itself, from the pieces already thrown)
U.defer(zgo_dismember.spawn_gibs, npc5:bone_position("bip01_head"), VV(0, 1, 0), 2, npc5)
frame(0)
zgo_sync.flush()
run(300)
local host_flight = flight()
local g = lines("G|")[1]
assert(g, "a G line went out")
for name in pairs(LEVEL_ATT) do LEVEL_ATT[name] = nil end
zgo_debris.reset()
local p = npc5:bone_position("bip01_spine1")
zgo_debris.spawn_chunks(npc5, nil, nil, p, VV(0, 1, 0), 2, 777)
local host_chunks = burst_pieces()
-- client
fresh_debris()
DISPATCH(zgo_sync.EVT, g)
frame(0)
run(300)
local client_flight = flight()
print("  host   " .. host_flight .. "\n  client " .. client_flight)
assert(host_flight ~= "" and client_flight == host_flight, "the host's pieces fly the same way on the client")
for name in pairs(LEVEL_ATT) do LEVEL_ATT[name] = nil end
zgo_debris.reset()
DISPATCH(zgo_sync.EVT, ("Y|g|401|%.3f|%.3f|%.3f|0|1|0|2|777"):format(p.x, p.y, p.z))
frame(0)
local client_chunks = burst_pieces()
print(("  then a chunk burst: host pieces %s, client %s"):format(host_chunks, client_chunks))
assert(host_chunks ~= "" and client_chunks == host_chunks, "the same pieces after the G line")
assert(errs() == 0)

print("\nALL GIBS TESTS PASSED")
