-- Engine mocks for the props workstream (zgo_props*): physics objects with
-- shells, hanging lamps, destroyables, level.iterate_nearest, alife release,
-- sounds, the vanilla physics binder. Loaded by zgo_harness.lua before any
-- object is made. Prop objects come from NEW_PROP below (not NPC_HOOKS).
local here = debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or "."
local ROOT = here .. "/../.."

-- distinct class ids (the harness's generated ones collide by name length)
rawset(clsid, "script_phys", 9001)
rawset(clsid, "destrphys_s", 9002)
rawset(clsid, "hlamp_s", 9003)
rawset(clsid, "inventory_box_s", 9004)
rawset(clsid, "car_s", 9005)

callback = callback or { death = 7001, hit = 7002, use_object = 7003 }

-- wallmark sections of the props configs (the harness reads only the core files)
do
	local f = io.open(ROOT .. "/gamedata/configs/mod_system_zgo_props.ltx", "r")
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

-- the game's part models and break sounds exist
for _, m in ipairs({
	"dynamics\\box\\part\\box_wood_01_part_1", "dynamics\\box\\part\\box_wood_01_part_2", "dynamics\\box\\part\\box_wood_01_part_3",
	"dynamics\\box\\part\\box_wood_01_part_4", "dynamics\\box\\part\\box_wood_01_part_5", "dynamics\\box\\part\\box_wood_01_part_6",
	"dynamics\\box\\part\\box_wood_01_part_7",
	"dynamics\\kitchen_room\\part\\bottle_3l_part_0", "dynamics\\kitchen_room\\part\\bottle_3l_part_1",
	"dynamics\\kitchen_room\\part\\bottle_3l_part_2", "dynamics\\kitchen_room\\part\\bottle_3l_part_3",
	"dynamics\\kitchen_room\\part\\bottle_3l_part_4", "dynamics\\kitchen_room\\part\\bottle_3l_part_5",
	"dynamics\\kitchen_room\\part\\bottle_3l_part_6", "dynamics\\kitchen_room\\part\\bottle_3l_part_7",
	"dynamics\\stul\\stul_school_01_br",
}) do FS_FILES["$game_meshes$|" .. m .. ".ogf"] = true end
for _, s in ipairs({ "material\\wood\\wood_crash_hl2", "material\\wood\\wood_crash1_hl2", "material\\wood\\wood_big_hard_1",
	"material\\bottle\\collide\\bottle_break_1" }) do FS_FILES["$game_sounds$|" .. s .. ".ogg"] = true end

-- sounds
SOUNDS = {}
sound_object = setmetatable({ s3d = 0 }, { __call = function(_, path)
	return { play_at_pos = function(self, obj, pos) SOUNDS[#SOUNDS + 1] = { path = path, pos = pos } end }
end })

-- alife: release records the id and takes the object out of the level
RELEASED = {}
function alife_object(id) return OBJ[id] and { id = id } or nil end
function alife_release(se, msg)
	assert(se and se.id, "release without a server object")
	RELEASED[#RELEASED + 1] = se.id
	OBJ[se.id] = nil
end
STORY = {}
function get_object_story_id(id) return STORY[id] end

-- nearest objects, sorted by distance (return true from fn to stop)
function level.iterate_nearest(pos, radius, fn)
	local list = {}
	for id, o in pairs(OBJ) do
		if type(o) == "table" and type(o.position) == "function" then
			local ok, p = pcall(o.position, o)
			if ok and p and p:distance_to(pos) <= radius then list[#list + 1] = { o = o, d = p:distance_to(pos), id = id } end
		end
	end
	table.sort(list, function(a, b) if a.d ~= b.d then return a.d < b.d end return a.id < b.id end)
	for _, e in ipairs(list) do if fn(e.o) then return end end
end

-- the vanilla physics binder (bind_physic_object.generic_physics_binder)
BINDER_DEATHS = 0
bind_physic_object = { generic_physics_binder = {
	death_callback = function(self, victim, who) BINDER_DEATHS = BINDER_DEATHS + 1 end,
} }

-- forces the props module applies through physics shells
FORCES, TORQUES = {}, {}

local function rot_rows(yaw)
	-- engine setHPB(yaw, 0, 0)
	local c, s = math.cos(yaw), math.sin(yaw)
	return VV and nil, c, s
end

--[[ NEW_PROP(id, { vis, sec, kind = "phys"|"destr"|"lamp", pos, yaw, mass,
     binder = true, on = true (lamps) }) ]]
function NEW_PROP(id, t)
	local o = { _id = id, _vis = t.vis, _sec = t.sec or "physic_object", _kind_p = t.kind or "phys",
		_pos = vector():set(t.pos.x, t.pos.y, t.pos.z), _yaw = t.yaw or 0, _mass = t.mass or 20,
		_binder = t.binder, _cb = {}, _on = t.on ~= false, _lamp_alive = true }
	function o:id() return self._id end
	function o:section() return self._sec end
	function o:clsid()
		return (self._kind_p == "lamp" and clsid.hlamp_s) or (self._kind_p == "destr" and clsid.destrphys_s) or clsid.script_phys
	end
	function o:position() return vector():set(self._pos.x, self._pos.y, self._pos.z) end
	function o:get_visual_name() return self._vis end
	function o:alive() return true end
	function o:xform()
		local m = matrix()
		local c, s = math.cos(self._yaw), math.sin(self._yaw)
		-- Fmatrix::setHPB(yaw, 0, 0): i = (cos, 0, sin), k = (-sin, 0, cos)
		m.i, m.j, m.k = vector():set(c, 0, s), vector():set(0, 1, 0), vector():set(-s, 0, c)
		m.c = self:position()
		return m
	end
	function o:binded_object() return self._binder and {} or nil end
	function o:set_callback(kind, fn) self._cb[kind] = fn end
	function o:get_physics_shell()
		local me = self
		local el = {
			get_mass = function() return me._mass end,
			apply_torque = function(_, x, y, z) TORQUES[#TORQUES + 1] = { id = me._id, x = x, y = y, z = z } end,
		}
		return {
			get_elements_number = function() return 1 end,
			get_element_by_order = function(_, i) return el end,
			apply_force = function(_, x, y, z)
				assert(x == x and y == y and z == z, "nan force")
				FORCES[#FORCES + 1] = { id = me._id, x = x, y = y, z = z, m = me._mass }
			end,
		}
	end
	if o._kind_p == "lamp" then
		local lamp = {
			is_on = function() return o._on end,
			turn_on = function() if o._lamp_alive then o._on = true end end,
			turn_off = function() o._on = false end,
		}
		function o:get_hanging_lamp() return lamp end
	end
	OBJ[id] = o
	return o
end
