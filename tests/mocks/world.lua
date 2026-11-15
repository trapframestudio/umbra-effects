-- World impacts (zgo_impacts*): the engine bits the shared harness does not model.
-- Loaded by zgo_harness.lua for every suite, before any mod script runs.
--
--  * ray_pick: the same room as the harness (floor y=0, wall z=-2, wall x=3),
--    plus get_result().material_name and get_normal() for the triangle hit,
--    and an optional ceiling (WORLD_CEILING = its height, nil = none).
--    Surface materials are in WORLD_MAT (tests change them).
--  * the wallmark sections of mod_system_zgo_impacts.ltx join WM_SECTIONS
--    (the harness asserts every placed section exists).
--  * zgo_world_* marks are recorded in WORLD_PLACED and zgo\world\ effects in
--    WORLD_FX / WORLD_FXDIR instead of PLACED / FX: the other suites count
--    gore decals and gory effects (kid mode must leave none), and impacts and
--    craters are not gore. The harness checks still run on them.
--  * particle objects get stop_deffered (recorded in WORLD_STOPPED).

WORLD_MAT = { floor = "materials\\earth", wall = "materials\\concrete", side = "materials\\bricks", ceiling = "materials\\stucco" }
WORLD_CEILING = nil
WORLD_PLACED, WORLD_FX, WORLD_FXDIR, WORLD_STOPPED = {}, {}, {}, {}
WORLD_PICKS = 0

local NORMAL = { floor = { 0, 1, 0 }, wall = { 0, 0, 1 }, side = { -1, 0, 0 }, ceiling = { 0, -1, 0 } }

local function wtrace(pos, dir, range)
	local best, which
	local function try(t, w) if t > 0 and (not best or t < best) then best, which = t, w end end
	if dir.z < -1e-6 then try((-2 - pos.z) / dir.z, "wall") end
	if dir.x > 1e-6 then try((3 - pos.x) / dir.x, "side") end
	if dir.y < -1e-6 then try((0 - pos.y) / dir.y, "floor") end
	if WORLD_CEILING and dir.y > 1e-6 then try((WORLD_CEILING - pos.y) / dir.y, "ceiling") end
	if best and best <= range then return best, which end
end

function ray_pick(pos, dir, range, flags, ignore)
	WORLD_PICKS = WORLD_PICKS + 1
	assert(pos.x == pos.x and dir.x == dir.x and range == range, "nan ray")
	local d, which = wtrace(pos, dir, range)
	local rq = {}
	function rq:query() return d ~= nil end
	function rq:get_distance() return d end
	function rq:get_object() return nil end
	function rq:get_element() return d and 1 or 0 end
	function rq:get_result()
		return { range = d or 0, object = nil, element = d and 1 or 0, material_name = which and WORLD_MAT[which] or nil }
	end
	function rq:get_normal()
		-- the triangle's own normal (the engine's: not turned to face the ray)
		local n = NORMAL[which] or { 0, 1, 0 }
		return vector():set(n[1], n[2], n[3])
	end
	return rq
end

do
	local CDIR = (arg and arg[1] or "."):gsub("/scripts$", "/configs")
	local f = io.open(CDIR .. "/mod_system_zgo_impacts.ltx", "r")
	if f then
		local cur
		for line in f:lines() do
			local sec = line:match("^%[([%w_]+)%]")
			if sec then cur = sec
			elseif cur and line:match("^%s*wallmarks%s*=") then WM_SECTIONS[cur] = true end
		end
		f:close()
	end
end

do
	local mgr = wallmarks_manager()
	local wrapped = {
		place = function(self, dir, pos, range, size, sec, ign, ttl, rot)
			local n = #PLACED
			mgr:place(dir, pos, range, size, sec, ign, ttl, rot)
			if type(sec) == "string" and sec:sub(1, 10) == "zgo_world_" and #PLACED > n then
				local p = table.remove(PLACED)
				p.ttl = ttl
				WORLD_PLACED[#WORLD_PLACED + 1] = p
			end
		end,
		place_skeleton = function(self, ...) return mgr:place_skeleton(...) end,
	}
	wallmarks_manager = function() return wrapped end
end

do
	local base = particles_object
	function particles_object(name)
		local o = base(name)
		local world = type(name) == "string" and name:sub(1, 10) == "zgo\\world\\"
		-- an emitter with a long time limit (crater smoke) plays until it is stopped
		local endless = world and name:find("crater_smoke", 1, true) ~= nil
		local play, playing, stop = o.play_at_pos, o.playing, o.stop
		local live = false
		function o:play_at_pos(p)
			play(self, p)
			live = true
			if world then
				WORLD_FX[#WORLD_FX + 1] = table.remove(FX)
				WORLD_FXDIR[#WORLD_FXDIR + 1] = table.remove(FXDIR)
			end
		end
		function o:playing()
			if endless and live then return true end
			return playing(self)
		end
		function o:stop()
			live = false
			return stop(self)
		end
		function o:stop_deffered()
			WORLD_STOPPED[#WORLD_STOPPED + 1] = name
			self:stop()
		end
		return o
	end
end
