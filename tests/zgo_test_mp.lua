-- S: this folder (scratch files are written here); the mod scripts are in ../gamedata/scripts
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local role = ...
arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(11)
local WIRE = S .. "/zgo_wire.txt"

local function npcs()
	-- same ids / sections on both machines (xrRazom keeps host ids for NPCs)
	return NEW_NPC(10, "stalker", VV(0, 0, -1.2)), NEW_NPC(20, "stalker", VV(1, 0, -1.2)), NEW_NPC(30, "stalker", VV(-1, 0, -1.2)),
		NEW_NPC(40, "stalker", VV(2, 0, 1)), NEW_NPC(50, "stalker", VV(-2, 0, 1)), NEW_NPC(60, "stalker", VV(2.2, 0, -1))
end

-- where every flying limb / gib ended up (world position of each attachment)
local function rest_positions()
	local out = {}
	for name, a in pairs(LEVEL_ATT) do
		local id = name:find("limb") and BONE_ID["bip01_l_forearm"] or nil
		local p = id and ATT_WORLD(a, id) or a.pos
		out[#out + 1] = ("%s %.3f %.3f %.3f"):format(name:match("^zgo_(%a+)") or name, p.x, p.y, p.z)
	end
	table.sort(out)
	return out
end

if role == "host" then
	local a, b, c, d, e, f = npcs()
	PLACED, BODY, FX = {}, {}, {}
	for i = 1, 10 do shoot(a, "bip01_spine1", "ammo_5_45x39_fmj") end
	-- a co-op peer (dummy id 77) shoots b with buckshot: only the hit reaches the host,
	-- the bullet info comes from the peer a moment later
	for i = 1, 6 do
		CB.on_before_hit_after_calcs({ power = 0.0001, type = hit.fire_wound, draftsman = NEW_NPC(77, "stalker", VV(0, 0, 5)),
			direction = VV(0, 0, -1), weapon_id = 999 }, b, BONE_ID["bip01_spine2"])
		frame()
		local bp = b:bone_position("bip01_spine2")
		DISPATCH(zgo_sync.EVT_UP, table.concat({ "H", 20, "ammo_12x70_buck", 380, bp.x, bp.y, bp.z, 0, 0, -1, BONE_ID["bip01_spine2"], 0 }, "|"), "2")
		run(250)
	end
	-- forced dismember on c
	local old = zgo_util.setting
	zgo_util.setting = function(k) if k == "dismember/chance" then return 50 end return old(k) end
	shoot(c, "bip01_l_forearm", "ammo_12x76_zhekan", { kill = true })
	zgo_util.setting = old
	-- neck shot (arterial jets), explosion overkill
	shoot(d, "bip01_neck", "ammo_5_45x39_fmj")
	shoot(e, "bip01_spine1", nil, { htype = hit.explosion, kill = true, power = 2.5 })
	-- the host's grenade into a corpse
	f._alive = false
	explode(VV(2.2, 0.1, -0.6), { f })
	run(12000)
	local cats = count_by_cat(PLACED)
	print("host decals " .. #PLACED .. ": " .. cats)
	print("host body " .. #BODY .. " fx " .. #FX .. " severed forearm=" .. tostring(c._hidden["bip01_l_forearm"]))
	assert(cats:find("buckshot"), "peer buckshot profile not applied")
	local n, kinds = 0, {}
	local f = io.open(WIRE, "w")
	for _, msg in ipairs(SENT) do
		f:write(msg:gsub("\n", "\1"), "\n")
		for line in msg:gmatch("[^\n]+") do n = n + 1; local k = line:sub(1, 1); kinds[k] = (kinds[k] or 0) + 1 end
	end
	f:close()
	local ks = {}
	for k, v in pairs(kinds) do ks[#ks + 1] = k .. "=" .. v end
	table.sort(ks)
	print(("sent %d events in %d messages: %s"):format(n, #SENT, table.concat(ks, " ")))
	local longest = 0
	for _, m in ipairs(SENT) do longest = math.max(longest, #m) end
	print("longest message " .. longest .. " bytes")
	-- host-side tallies for the client to compare
	local h = io.open(S .. "/zgo_host_counts.txt", "w")
	h:write(#PLACED, " ", #BODY, "\n")
	for _, r in ipairs(rest_positions()) do h:write(r, "\n") end
	h:close()
	print("host debris at rest: " .. #rest_positions())
else
	local a, b, c, d, e, f = npcs()
	f._alive = false
	PLACED, BODY, FX = {}, {}, {}
	-- the client's own grenade fragment: never forwarded (the host sees all fragments)
	CB.bullet_on_impact({ position = VV(0, 1, -1.2), direction = VV(0, 0, -1), speed = 200, element = 4,
		parent_id = 0, target_id = 10, weapon_id = 905 })
	assert(#UP == 0, "fragments must not be forwarded")
	-- the client's own shot: no local effects, impact forwarded to the host
	shoot(a, "bip01_spine1", "ammo_5_45x39_fmj")
	print(("client own shot -> local decals %d, forwarded %d: %s"):format(#PLACED, #UP, UP[1] or "-"))
	assert(#PLACED == 0 and #UP == 1)
	-- the client's copy of the bodies is a few cm off (network / ragdoll drift)
	c._pos = VV(c._pos.x + 0.03, c._pos.y, c._pos.z + 0.02)
	e._pos = VV(e._pos.x - 0.025, e._pos.y, e._pos.z + 0.03)
	-- a host on the old protocol: its lines (here naming a particle and a decal
	-- this client doesn't have, fatal in the engine) must never be replayed
	do
		local before = #FX
		DISPATCH("zgo:sync", "F|zgo\\no_such_effect|0|1|0|0|0|1|1\nW|zgo_no_such_mark|0|0|0|0|-1|0|0.5|900|0", "host")
		DISPATCH("zgo:sync", "F|zgo\\no_such_effect|0|1|0|0|0|1|1", "host")
		run(100)
		local warned = 0
		for _, l in ipairs(LOG) do if l:find("older Umbra Gore & Effects", 1, true) then warned = warned + 1 end end
		print(("old-protocol host: %d effects replayed, warned %d time(s)"):format(#FX - before, warned))
		assert(#FX == before and warned == 1)
	end
	for msg in io.lines(WIRE) do
		local body = msg:gsub("\1", "\n")
		-- (baked: the host's kill reaches this machine with its cut, and the cut
		-- waits for this copy's ragdoll. Un-baked, a cut that arrives after this
		-- copy became a ragdoll can't be shown: see "late cut" below)
		for l in (BAKED and body or ""):gmatch("[^\n]+") do
			local did = tonumber(l:match("^D|(%d+)|") or "")
			local o = did and OBJ[did]
			if o and o._alive then o._alive, o._died_at, o.health = false, T_NOW, 0 end
		end
		DISPATCH(zgo_sync.EVT, body, "host")
		frame()
	end
	run(12000)
	local hf = io.open(S .. "/zgo_host_counts.txt")
	local hc = hf:read("*l")
	local host_rest = {}
	for l in hf:lines() do host_rest[#host_rest + 1] = l end
	hf:close()
	print("client decals " .. #PLACED .. ": " .. count_by_cat(PLACED))
	print("client body " .. #BODY .. " fx " .. #FX .. " severed forearm=" .. tostring(c._hidden["bip01_l_forearm"]))
	print("host decals/body: " .. hc)
	local limb = false
	for name in pairs(LEVEL_ATT) do if name:find("limb") then limb = true end end
	print("client spawned severed limb: " .. tostring(limb))
	assert(c._hidden["bip01_l_forearm"] and limb)
	-- same seeds + fixed-step physics: debris comes to rest in the same places
	local mine = rest_positions()
	print(("debris at rest: host %d, client %d"):format(#host_rest, #mine))
	assert(#mine == #host_rest, "debris count differs")
	-- each client piece against the nearest unused host piece of the same kind
	local function parse(l)
		local k, x, y, z = l:match("(%S+) (%S+) (%S+) (%S+)")
		return k, VV(tonumber(x), tonumber(y), tonumber(z))
	end
	local used, worst = {}, 0
	for _, l in ipairs(mine) do
		local k1, p1 = parse(l)
		local best, bi
		for j, hl in ipairs(host_rest) do
			if not used[j] then
				local k2, p2 = parse(hl)
				if k1 == k2 and (not best or p1:distance_to(p2) < best) then best, bi = p1:distance_to(p2), j end
			end
		end
		assert(bi, "client piece with no host counterpart: " .. l)
		used[bi] = true
		worst = math.max(worst, best)
	end
	print(("largest host/client rest difference %.3f m"):format(worst))
	assert(worst < 0.05, "debris should land in the same place on every machine")
	local jets = 0
	for _, f in ipairs(FX) do if f:find("zgo\\jet_", 1, true) then jets = jets + 1 end end
	print("client arterial jets " .. jets)
	assert(jets >= 4, "arterial sequence should replay on the client")
	local gibbed = 0
	for b, h in pairs(e._hidden) do if h then gibbed = gibbed + 1 end end
	print("client gibbed body parts removed " .. gibbed)
	assert(gibbed >= 3)
	local fg = 0
	for _, h in pairs(f._hidden) do if h then fg = fg + 1 end end
	print("client: grenaded corpse parts removed " .. fg)
	if BAKED then assert(fg >= 3) else assert(fg == 0, "the host cut an un-baked ragdoll") end
	-- the host's cut reaches this machine after its copy of the body is a ragdoll
	do
		local g = NEW_NPC(16, "stalker", VV(-2, 0, 2))
		g._alive, g._died_at = false, T_NOW - 5000
		local seen = {}
		for name in pairs(LEVEL_ATT) do seen[name] = true end
		DISPATCH(zgo_sync.EVT, "D|16|" .. g:section() .. "|bip01_r_upperarm|1|1|0|0|1|4242", "host")
		run(3000, 33)
		-- (a new piece may push the oldest one out: count new names)
		local new = 0
		for name in pairs(LEVEL_ATT) do if name:find("limb") and not seen[name] then new = new + 1 end end
		print(("late cut on a client ragdoll: hidden %s, new limbs %d"):format(tostring(g._hidden["bip01_r_upperarm"]), new))
		-- (un-baked: one log line says why, and the upkeep stops trying)
		local said = 0
		for _, l in ipairs(LOG) do
			if l:find("host cut bip01_r_upperarm on " .. g:section() .. " (id 16) not shown on this machine", 1, true) then said = said + 1 end
		end
		if BAKED then
			assert(g._hidden["bip01_r_upperarm"] and new == 1)
			assert(said == 0, "a cut shown here is not reported")
		else
			assert(not g._hidden["bip01_r_upperarm"] and new == 0, "client showed a cut its ragdoll keeps on screen")
			assert(said == 1, "the client says once why it can't show the host's cut, got " .. said)
		end
		CHECK_CUTS("client late cut")
	end
	local errs = 0
	for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") then errs = errs + 1; print("  " .. l) end end
	print("errors: " .. errs .. "  misses: " .. (MISSES or 0))
end
print(role:upper() .. " OK")
