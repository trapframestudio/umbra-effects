-- LuaJIT mock of the bits of the X-Ray script API that Zone Gore Overhaul uses.
-- Room: floor y=0, wall z=-2 (facing +z), wall x=3 (facing -x).
local DIR = arg[1]
local MODE = arg[2] or "sp"

-------------------------------------------------------------- vectors
local V = {}; V.__index = V
function vector() return setmetatable({ x = 0, y = 0, z = 0 }, V) end
function V:set(x, y, z)
	if type(x) == "table" then self.x, self.y, self.z = x.x, x.y, x.z else self.x, self.y, self.z = x, y, z end
	return self
end
function V:distance_to(o) return math.sqrt((self.x - o.x) ^ 2 + (self.y - o.y) ^ 2 + (self.z - o.z) ^ 2) end
function V:distance_to_sqr(o) return (self.x - o.x) ^ 2 + (self.y - o.y) ^ 2 + (self.z - o.z) ^ 2 end
local function vv(x, y, z) return vector():set(x, y, z) end

-------------------------------------------------------------- matrices (rows i,j,k = axes, c = origin)
local M = {}
M.__index = function(t, k)
	return M[k]
end
function matrix()
	return setmetatable({ i = vv(1, 0, 0), j = vv(0, 1, 0), k = vv(0, 0, 1), c = vv(0, 0, 0), _14_ = 0, _24_ = 0, _34_ = 0, _44_ = 1 }, M)
end
local function tdir(m, v) return vv(v.x * m.i.x + v.y * m.j.x + v.z * m.k.x, v.x * m.i.y + v.y * m.j.y + v.z * m.k.y, v.x * m.i.z + v.y * m.j.z + v.z * m.k.z) end
local function tpt(m, v) local d = tdir(m, v) return vv(d.x + m.c.x, d.y + m.c.y, d.z + m.c.z) end
function M:identity() self.i, self.j, self.k, self.c = vv(1, 0, 0), vv(0, 1, 0), vv(0, 0, 1), vv(0, 0, 0) return self end
function M:set(a) self.i, self.j, self.k, self.c = vv(a.i.x, a.i.y, a.i.z), vv(a.j.x, a.j.y, a.j.z), vv(a.k.x, a.k.y, a.k.z), vv(a.c.x, a.c.y, a.c.z) return self end
function M:scale(x, y, z) self:identity(); self.i.x, self.j.y, self.k.z = x, y, z return self end
function M:mul_43(A, B)
	local i, j, k, c = tdir(A, B.i), tdir(A, B.j), tdir(A, B.k), tpt(A, B.c)
	self.i, self.j, self.k, self.c = i, j, k, c
	return self
end
function M:invert(A)
	-- general 3x3 inverse of the row matrix R (v' = v R + c)
	local a, b, c = A.i, A.j, A.k
	local det = a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x)
	assert(math.abs(det) > 1e-12, "singular matrix")
	local inv = {
		{ (b.y * c.z - b.z * c.y) / det, -(a.y * c.z - a.z * c.y) / det, (a.y * b.z - a.z * b.y) / det },
		{ -(b.x * c.z - b.z * c.x) / det, (a.x * c.z - a.z * c.x) / det, -(a.x * b.z - a.z * b.x) / det },
		{ (b.x * c.y - b.y * c.x) / det, -(a.x * c.y - a.y * c.x) / det, (a.x * b.y - a.y * b.x) / det },
	}
	self.i, self.j, self.k = vv(inv[1][1], inv[1][2], inv[1][3]), vv(inv[2][1], inv[2][2], inv[2][3]), vv(inv[3][1], inv[3][2], inv[3][3])
	local nc = tdir(self, A.c)
	self.c = vv(-nc.x, -nc.y, -nc.z)
	return self
end
MAT_TPT = tpt

-------------------------------------------------------------- world / rays
rq_target = { rqtStatic = 1, rqtObj = 2, rqtBoth = 3 }
local function trace(pos, dir, range)
	local best
	if dir.z < -1e-6 then local t = (-2 - pos.z) / dir.z; if t > 0 then best = t end end
	if dir.x > 1e-6 then local t = (3 - pos.x) / dir.x; if t > 0 and (not best or t < best) then best = t end end
	if dir.y < -1e-6 then local t = (0 - pos.y) / dir.y; if t > 0 and (not best or t < best) then best = t end end
	if best and best <= range then return best end
end
function ray_pick(pos, dir, range)
	local d = trace(pos, dir, range)
	return { query = function() return d ~= nil end, get_distance = function() return d end, get_object = function() return nil end }
end
PLACED, BODY, FX = {}, {}, {}
-- wallmark sections defined by the mod's configs (the engine R_ASSERTs on anything else)
WM_SECTIONS = {}
do
	local CDIR = DIR:gsub("/scripts$", "/configs")
	for _, fname in ipairs({ "mod_system_zgo.ltx", "mod_system_zgo_engine_marks.ltx" }) do
		local f = io.open(CDIR .. "/" .. fname, "r")
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
end
WM_PLACED_SECS = {}
local function wm_section_ok(sec)
	assert(type(sec) == "string" and WM_SECTIONS[sec], "engine would R_ASSERT: unknown wallmark section " .. tostring(sec))
	WM_PLACED_SECS[sec] = true
end
local mgr = {
	place = function(self, dir, pos, range, size, sec, ign, ttl, rot)
		wm_section_ok(sec)
		local d = trace(pos, dir, range)
		if not d then MISSES = (MISSES or 0) + 1 return end
		assert(size > 0 and size < 5, "bad size " .. tostring(size))
		assert(rot == rot, "nan rot")
		PLACED[#PLACED + 1] = { sec = sec, size = size, rot = rot, x = pos.x + dir.x * d, y = pos.y + dir.y * d, z = pos.z + dir.z * d }
	end,
	place_skeleton = function(self, obj, sec, pos, dir, size, ttl) wm_section_ok(sec) BODY[#BODY + 1] = { sec = sec, size = size } end,
}
wallmarks_manager = function() return mgr end
-- every particle the mod plays must exist as a .pe / .pg in the mod (or be listed as external)
local PDIR = DIR:gsub("/scripts$", "/particles")
local pcache = {}
EXTERNAL_PARTICLES = {}
local function particle_exists(name)
	if pcache[name] ~= nil then return pcache[name] end
	local base = PDIR .. "/" .. name:gsub("\\", "/")
	local ok = false
	for _, ext in ipairs({ ".pe", ".pg" }) do
		local f = io.open(base .. ext, "r")
		if f then f:close() ok = true end
	end
	pcache[name] = ok or EXTERNAL_PARTICLES[name] or false
	return pcache[name]
end
FXDIR = {}
function particles_object(name)
	assert(type(name) == "string" and not name:find("nil"), "bad particle " .. tostring(name))
	assert(particle_exists(name), "missing particle " .. name)
	local playing = false   -- start time while playing (effects last ~2.5 s)
	local o = { dir = nil }
	function o:set_direction(d) assert(math.abs(d.x * d.x + d.y * d.y + d.z * d.z - 1) < 0.01, "direction not unit") self.dir = d end
	function o:play_at_pos(p) assert(p.x == p.x, "nan particle pos") playing = T_NOW; FX[#FX + 1] = name; FXDIR[#FXDIR + 1] = { name = name, pos = p, dir = self.dir } end
	function o:playing() return playing ~= false and T_NOW - playing < 2500 end
	function o:stop() playing = false end
	return o
end

-------------------------------------------------------------- engine globals
T_NOW = 1000
function time_global() return T_NOW end
LOG = {}
function printf(fmt, ...) local s = select("#", ...) > 0 and string.format(fmt:gsub("%%s", "%%s"), ...) or fmt; LOG[#LOG + 1] = s end
-- several scripts can register the same callback (as in the game); cbs[name](...)
-- calls them all in order and returns the last result
local cbs, cb_lists = {}, {}
function RegisterScriptCallback(n, f)
	local l = cb_lists[n]
	if not l then
		l = {}
		cb_lists[n] = l
		cbs[n] = function(...)
			local r
			for _, fn in ipairs({ unpack(l) }) do r = fn(...) end
			return r
		end
	end
	for _, fn in ipairs(l) do if fn == f then return end end
	l[#l + 1] = f
end
function UnregisterScriptCallback(n, f)
	local l = cb_lists[n]
	if not l then return end
	for i = #l, 1, -1 do if l[i] == f then table.remove(l, i) end end
end
CB_LISTS = cb_lists
hit = { burn = 0, shock = 1, chemical_burn = 2, radiation = 3, telepatic = 4, wound = 5, fire_wound = 6, strike = 7, explosion = 8 }
clsid = setmetatable({}, { __index = function(t, k) local v = 100 + #k; rawset(t, k, v) return v end })
FS_FILES = { ["$game_meshes$|dynamics\\zpf\\raw_flesh.ogf"] = true, ["$game_meshes$|dynamics\\zpf\\raw_dog.ogf"] = true }
-- BAKED = true before loading the harness: the mock visual is a baked ZGO model
BAKED = BAKED or os.getenv("ZGO_BAKED") == "1"
if BAKED then
	FS_FILES["$game_scripts$|zgo_bake_index.script"] = true
	rawset(_G, "zgo_bake_index", { models = { ["actors\\stalker_neutral\\stalker_neutral_1"] =
		{ bip01_head = true, bip01_l_upperarm = true, bip01_l_forearm = true, bip01_l_hand = true, bip01_r_upperarm = true, bip01_r_forearm = true, bip01_r_hand = true, bip01_l_thigh = true, bip01_l_calf = true, bip01_l_foot = true, bip01_r_thigh = true, bip01_r_calf = true, bip01_r_foot = true } } })
end
function getFS() return { exist = function(self, root, p) return FS_FILES[root .. "|" .. p] or false end } end
local AMMO = { grenade_f1 = { blast = 3, blast_r = 8 }, wpn_rpg7_missile = { blast = 4.3, blast_r = 7.2 }, ied_new_blow = { blast = 5.7, blast_r = 12.9 },
	mine_new_blow = { blast = 3.18, blast_r = 2.26 }, test_exo_outfit = { explosion_protection = 1.6 }, test_exo_helmet = { explosion_protection = 0.5 }, ["ammo_vog-25"] = { blast = 4.6, blast_r = 6.4 }, ammo_5_45x39_fmj = { k_impulse = 1.0 }, ["ammo_7.62x54_7h1"] = { k_impulse = 1.5 }, ammo_12x70_buck = { k_impulse = 0.5, buck_shot = 9 },
	ammo_9x18_fmj = { k_impulse = 0.6 }, ammo_12x76_zhekan = { k_impulse = 1.9 } }
ini_sys = {
	section_exist = function(self, s) return AMMO[s] ~= nil or WM_SECTIONS[s] == true end,
	r_float_ex = function(self, s, k) return AMMO[s] and AMMO[s][k] end,
	r_string_ex = function(self, s, k) return nil end,
	line_exist = function() return false end,
}
-- Wepl armour table: visual name -> { armorType, helmetType }
VISUAL_ARMOR = { ["actors\\stalker_neutral\\stalker_neutral_exo"] = { "exo ", "helmet " } }
function ini_file(name)
	return {
		section_exist = function(self, s) return VISUAL_ARMOR[s] ~= nil end,
		line_exist = function(self, s, k) return VISUAL_ARMOR[s] ~= nil end,
		r_string_ex = function(self, s, k) local a = VISUAL_ARMOR[s] return a and (k == "armorType" and a[1] or a[2]) end,
	}
end

-------------------------------------------------------------- objects
OBJ = {}
LEVEL_ATT = {}
level = { object_by_id = function(id) return OBJ[id] end }
function level.add_attachment(name, model) local a = NEW_ATT(name, model) a.owner = "level" LEVEL_ATT[name] = a return a end
function level.get_attachment(name) return LEVEL_ATT[name] end
function level.remove_attachment(name) if type(name) == "table" then name = name.name end LEVEL_ATT[name] = nil end
function alife_object(id) return OBJ[id] and {} or nil end
function IsStalker(o) return o and o._kind == "stalker" end
function IsMonster(o) return o and o._kind == "monster" end
function IsWeapon(o) return o and (o._weapon or o._grenade) or false end
function IsGrenade(o) return o and o._grenade or false end

local SKEL = { -- name, parent, model-space position (T-pose)
	{ "root_stalker", nil, 0, 0, 0 }, { "bip01", 0, 0, 0.95, 0 }, { "bip01_pelvis", 1, 0, 1.0, 0 },
	{ "bip01_spine", 2, 0, 1.1, 0 }, { "bip01_spine1", 3, 0, 1.25, 0 }, { "bip01_spine2", 4, 0, 1.4, 0 },
	{ "bip01_neck", 5, 0, 1.55, 0 }, { "bip01_head", 6, 0, 1.65, 0 }, { "jaw_1", 7, 0, 1.6, 0.05 },
	{ "bip01_l_clavicle", 5, 0.1, 1.45, 0 }, { "bip01_l_upperarm", 9, 0.2, 1.45, 0 }, { "bip01_l_forearm", 10, 0.45, 1.45, 0 },
	{ "bip01_l_hand", 11, 0.7, 1.45, 0 }, { "bip01_l_finger0", 12, 0.8, 1.45, 0 },
	{ "bip01_r_clavicle", 5, -0.1, 1.45, 0 }, { "bip01_r_upperarm", 14, -0.2, 1.45, 0 }, { "bip01_r_forearm", 15, -0.45, 1.45, 0 },
	{ "bip01_r_hand", 16, -0.7, 1.45, 0 }, { "bip01_r_finger0", 17, -0.8, 1.45, 0 },
	{ "bip01_l_thigh", 2, 0.1, 1.0, 0 }, { "bip01_l_calf", 19, 0.1, 0.55, 0 }, { "bip01_l_foot", 20, 0.1, 0.1, 0 }, { "bip01_l_toe0", 21, 0.1, 0.05, 0.1 },
	{ "bip01_r_thigh", 2, -0.1, 1.0, 0 }, { "bip01_r_calf", 23, -0.1, 0.55, 0 }, { "bip01_r_foot", 24, -0.1, 0.1, 0 }, { "bip01_r_toe0", 25, -0.1, 0.05, 0.1 },
}
local BID = {}
for i, b in ipairs(SKEL) do BID[b[1]] = i - 1 end
local KIDS = {}
for i, b in ipairs(SKEL) do if b[2] then KIDS[b[2]] = KIDS[b[2]] or {} table.insert(KIDS[b[2]], i - 1) end end

-- The death ragdoll (CCharacterPhysicsSupport::ActivateShell) is built a
-- frame or two after the killing hit (GE_DIE goes through the server), from
-- the bones visible at that moment. Bones with a physics element are then
-- written by the physics every frame: hiding them changes nothing on screen.
RAGDOLL_MS = 24
local SHAPED = { "bip01_pelvis", "bip01_spine", "bip01_spine1", "bip01_spine2", "bip01_head",
	"bip01_l_upperarm", "bip01_l_forearm", "bip01_l_hand", "bip01_r_upperarm", "bip01_r_forearm", "bip01_r_hand",
	"bip01_l_thigh", "bip01_l_calf", "bip01_l_foot", "bip01_r_thigh", "bip01_r_calf", "bip01_r_foot" }
local SHAPED_SET = {}
for _, n in ipairs(SHAPED) do SHAPED_SET[n] = true end
-- is bone b of o gone from view? (hidden, and not held by a physics element)
-- On a baked model a hidden section is dropped by the renderer, but a part
-- hidden before the ragdoll existed has no element: the joint above it
-- pinches (counted as a failure).
function VISIBLY_GONE(o, b)
	if not o._hidden[b] then return false end
	local sh = o:get_physics_shell()
	if BAKED then
		if SHAPED_SET[b] and sh and not sh.el[b] then return false, "pinched" end
		return true
	end
	return not (sh and sh.el[b])
end
local function chain(b)
	local out, q = {}, { BID[b] }
	while #q > 0 do
		local i = table.remove(q)
		out[#out + 1] = SKEL[i + 1][1]
		for _, k in ipairs(KIDS[i] or {}) do q[#q + 1] = k end
	end
	return out
end
CHAIN = chain
-- a save/load or offline/online round trip: the object is spawned again and
-- its death ragdoll rebuilt. For a saved corpse the engine restores the
-- hidden-bone mask first (CPHSkeleton::Spawn); keep_mask == false is a body
-- that comes back without it (ZGO has to hide the parts again).
function RESPAWN(o, keep_mask)
	o._att = {}
	if keep_mask == false then
		o._hidden = {}
	elseif SAVED_MASK and SAVED_MASK[o:id()] then
		-- (the mask as it was at the moment of the save)
		o._hidden = {}
		for b in pairs(SAVED_MASK[o:id()]) do o._hidden[b] = true end
	end
	o._shell = nil
	if not o._alive then o._died_at = -1e9 end
end

-- nothing may be hidden while its ragdoll keeps it on screen: a cut that is
-- made (bone hidden, piece flying) must actually be gone from the body
function CHECK_CUTS(label)
	local n = 0
	for id, o in pairs(OBJ) do
		if type(o) == "table" and o._hidden and not o._alive then
			for b in pairs(o._hidden) do
				local gone, why = VISIBLY_GONE(o, b)
				assert(gone, ("%s: %s hidden on %d but %s"):format(label or "check", b, id, why or "still on screen"))
				n = n + 1
			end
		end
	end
	return n
end

local function new_attachment(name, model)
	local a = { name = name, model = model, cbs = {}, pos = vv(0, 0, 0), hidden = {}, vis = {} }
	function a:set_parent_level()
		-- engine: leaves the parent's list WITHOUT destroying, joins the level list
		if self.parent_obj then self.parent_obj._att[self.name] = nil; self.parent_obj = nil end
		self.owner = "level"
		LEVEL_ATT[self.name] = self
	end
	function a:set_parent(o) end
	function a:set_bone_visible(id, v, rec) self.vis[id] = v end
	function a:set_parent_bone(b) self.parent_bone = b end
	function a:set_type(t) self.type = t end
	function a:set_scale(s) self.scale = s end
	function a:set_rotation(r) assert(r.x == r.x, "nan rotation") self.rot = r end
	function a:set_position(p) assert(p.x == p.x and p.y == p.y, "nan position") self.pos = vv(p.x, p.y, p.z) end
	function a:list_bones() local t = {} for i, b in ipairs(SKEL) do t[i - 1] = b[1] end return t end
	function a:bone_parent(id) local p = SKEL[id + 1][2] return p or 65535 end
	function a:bone_callback(id, fn, ow) assert(ow == true, "expected overwrite callbacks") self.cbs[id] = fn end
	return a
end
NEW_ATT = new_attachment

-- what the engine renders: mTransform per bone (callback result, or parent * bind
-- local), then renderable.xform = translate(position) (no rotation / scale used here)
function ATT_WORLD(a, id)
	local mt = {}
	local function calc(i)
		if mt[i] then return mt[i] end
		local m
		if a.cbs[i] then
			m = matrix():set(a.cbs[i](matrix(), SKEL[i + 1][1]))
		else
			local s, p = SKEL[i + 1], SKEL[i + 1][2]
			local loc = matrix()
			if p then
				local ps = SKEL[p + 1]
				loc.c = vv(s[3] - ps[3], s[4] - ps[4], s[5] - ps[5])
				m = matrix():mul_43(calc(p), loc)
			else
				loc.c = vv(s[3], s[4], s[5])
				m = loc
			end
		end
		mt[i] = m
		return m
	end
	local m = calc(id)
	return vv(a.pos.x + m.c.x, a.pos.y + m.c.y, a.pos.z + m.c.z), m
end

NPC_HOOKS = NPC_HOOKS or {}
local function new_npc(id, kind, pos, sec)
	local o = { _id = id, _kind = kind, _pos = pos, _alive = true, health = 1, _hidden = {}, _att = {}, _sec = sec or "sim_default_stalker_1",
		_yaw = NPC_YAW or 0, bleeding = 0 }
	function o:id() return self._id end
	function o:section() return self._sec end
	function o:clsid() return self._kind == "stalker" and clsid.script_stalker or clsid.dog_s end
	function o:alive() return self._alive end
	function o:invulnerable() return self._invulnerable or false end
	-- worn armour: o._outfit / o._helmet = section (explosion_protection in AMMO below)
	function o:item_in_slot(slot)
		local sec = (slot == 7 and self._outfit) or (slot == 12 and self._helmet) or nil
		if not sec then return nil end
		return { section = function() return sec end, condition = function() return 1 end }
	end
	function o:position() return vv(self._pos.x, self._pos.y, self._pos.z) end
	function o:get_visual_name() return (self._visual or "actors\\stalker_neutral\\stalker_neutral_1") .. ".ogf" end
	function o:get_bone_id(n) return BID[n] or 65535 end
	function o:bone_name(i) return SKEL[i + 1] and SKEL[i + 1][1] or "" end
	function o:bone_parent(b) local i = type(b) == "string" and BID[b] or b local p = SKEL[i + 1][2] return p or 65535 end
	function o:xform()
		local m = matrix()
		local c, s = math.cos(self._yaw), math.sin(self._yaw)
		m.i, m.k = vv(c, 0, -s), vv(s, 0, c)
		m.c = vv(self._pos.x, self._pos.y, self._pos.z)
		return m
	end
	-- engine (CScriptGameObject::bone_transform): WORLD transform = XFORM * model bone
	function o:bone_transform(b)
		local i = type(b) == "string" and BID[b] or b
		local s = SKEL[i + 1]
		local mm = matrix() mm.c = vv(s[3], s[4], s[5])
		return matrix():mul_43(self:xform(), mm)
	end
	function o:bone_position(b) return self:bone_transform(b).c end
	function o:set_bone_visible(b, vis, rec)
		local name = type(b) == "number" and SKEL[b + 1][1] or b
		for _, n in ipairs(rec and chain(name) or { name }) do self._hidden[n] = not vis or nil end
	end
	function o:list_bones() local t = {} for i, b in ipairs(SKEL) do t[i - 1] = b[1] end return t end
	function o:get_physics_shell()
		if self._alive then return nil end
		if T_NOW - (self._died_at or -1e9) < RAGDOLL_MS then return nil end
		if not self._shell then
			local el = {}
			for _, n in ipairs(SHAPED) do if not self._hidden[n] then el[n] = { bone = n } end end
			self._shell = { el = el, get_element_by_bone_name = function(sh, n) return sh.el[n] end }
		end
		return self._shell
	end
	function o:add_attachment(name, model) local a = new_attachment(name, model) a.parent_obj = self self._att[name] = a return a end
	function o:remove_attachment(name) self._att[name] = nil end
	OBJ[id] = o
	-- mock files (tests/mocks/*.lua) add object methods here
	for _, hook in ipairs(NPC_HOOKS) do hook(o) end
	return o
end

-- extra engine mocks, one file per feature (tests/mocks/*.lua, alphabetical):
-- new globals, or object methods through NPC_HOOKS
do
	local here = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
	local p = io.popen('ls "' .. here .. '/mocks" 2>/dev/null')
	local files = {}
	for f in p:lines() do if f:match("%.lua$") then files[#files + 1] = f end end
	p:close()
	table.sort(files)
	for _, f in ipairs(files) do dofile(here .. "/mocks/" .. f) end
end

ACTOR = new_npc(0, "actor", vv(0, 0, 6))
db = { actor = ACTOR }

-------------------------------------------------------------- xrRazom mock
SENT, UP = {}, {}
local evreg = {}
if MODE ~= "sp" then
	XrrSessionActive = true
	XrrPeerCount = 1
	XrrIsClient = function() return MODE == "client" end
	XrrPlayers = function() return { IsPlayerDummy = function(self, id) return id == 77 end } end
	xrr_script_event = {
		register = function(name, fn) evreg[name] = fn end,
		send = function(name, target, args) if name:find("^zgo:up") then UP[#UP + 1] = args else SENT[#SENT + 1] = args end return true end,
	}
end
function DISPATCH(name, args, sender) evreg[name](args, sender) end

-------------------------------------------------------------- module loader (Anomaly-style namespaces)
setmetatable(_G, { __index = function(t, k)
	local path = DIR .. "/" .. k .. ".script"
	local f = io.open(path, "r")
	if not f then return nil end
	f:close()
	local env = setmetatable({}, { __index = _G })
	rawset(_G, k, env)
	local chunk = assert(loadfile(path))
	setfenv(chunk, env)
	chunk()
	return env
end })

-- Anomaly's _g.exec_console_cmd; a save stores every object's hidden-bone
-- mask (CLevel::ClientSave) and then runs the save_state callbacks
SAVED_MASK, SAVE_DATA = nil, nil
function exec_console_cmd(cmd)
	if cmd == "save" or cmd:sub(1, 5) == "save " then
		SAVED_MASK = {}
		for id, o in pairs(OBJ) do
			if type(o) == "table" and o._hidden then
				local m = {}
				for b, h in pairs(o._hidden) do if h then m[b] = true end end
				SAVED_MASK[id] = m
			end
		end
		SAVE_DATA = {}
		cbs.save_state(SAVE_DATA)
	end
end
function SAVE_GAME()
	exec_console_cmd("save test")
	return SAVE_DATA
end

-- the game calls on_game_start in every script; zgo_main first, then the
-- feature modules that exist (alphabetical)
zgo_main.on_game_start()
do
	local names = {}
	local p = io.popen('ls "' .. DIR .. '"')
	for f in p:lines() do
		local n = f:match("^(zgo_[%w_]+)%.script$")
		if n and n ~= "zgo_main" and n ~= "zgo_bake_index" and n ~= "zgo_tables" and not n:match("^zgo_settings") then names[#names + 1] = n end
	end
	p:close()
	table.sort(names)
	for _, n in ipairs(names) do
		local m = _G[n]
		if type(m) == "table" and type(rawget(m, "on_game_start")) == "function" then m.on_game_start() end
	end
end
CB = cbs
cbs.actor_on_first_update()

function frame(ms)
	T_NOW = T_NOW + (ms or 16)
	cbs.actor_on_update()
end
function run(ms, step) step = step or 16 for _ = 1, math.floor(ms / step) do frame(step) end end

function shoot(target, bone, ammo, opts)
	opts = opts or {}
	local bp = target:bone_position(bone)
	local dir = opts.dir or vv(0, 0, -1)
	if ammo then
		cbs.bullet_on_impact({ position = bp, direction = dir, speed = opts.speed or 800, section = ammo, element = BID[bone],
			parent_id = opts.shooter or 0, target_id = target:id(), weapon_id = 500 })
	end
	if target._alive then
		if opts.kill then target.health = 0 end
		if not opts.kill and (opts.htype or hit.fire_wound) == hit.fire_wound then target.bleeding = (target.bleeding or 0) + 0.25 end
		cbs.on_before_hit_after_calcs({ power = opts.power or 0.0001, type = opts.htype or hit.fire_wound, draftsman = OBJ[opts.shooter or 0],
			direction = dir, weapon_id = 500 }, target, BID[bone])
		if opts.kill then target._alive = false; target._died_at = T_NOW; cbs.npc_on_death_callback(target, ACTOR) end
	end
	frame()
	-- a kill: the death ragdoll is built a frame or two later (GE_DIE round trip)
	if opts.kill and opts.settle ~= false then frame() frame() end
end

function count_by_cat(list)
	local c = {}
	for _, p in ipairs(list) do
		local k = p.sec:match("^zgo_fx_(%a+)_") or p.sec:match("^zgo_(p_%a+)_") or p.sec:match("^zgo_(pool_grow)_") or p.sec:match("^zgo_(pool)_")
			or p.sec:match("^zgo_(drip_grow)_") or p.sec:match("^zgo_(drip)_%d") or p.sec
		c[k] = (c[k] or 0) + 1
	end
	local keys = {}
	for k in pairs(c) do keys[#keys + 1] = k end
	table.sort(keys)
	local out = {}
	for _, k in ipairs(keys) do out[#out + 1] = k .. "=" .. c[k] end
	return table.concat(out, " ")
end
NEW_NPC = new_npc
VV = vv
BONE_ID = BID


-- A grenade going off at center, the way the engine reports it:
--   every fragment: bullet_on_init from the centre (no ammo section);
--   fragments that hit a body: bullet_on_impact (+ a fire_wound hit if alive);
--   then the blast wave: one explosion hit per body on bone 0, corpses too
--   (opts.no_corpse_blast drops it for corpses, opts.no_init drops the inits).
-- Fragments per body follow the cross-section: 0.5 m^2 / (4 pi d^2) of them.
function explode(center, targets, opts)
	opts = opts or {}
	local eid = opts.eid or 900
	local thrower = opts.thrower or 0
	OBJ[eid] = { _grenade = true, id = function() return eid end, section = function() return opts.sec or "grenade_f1" end,
		position = function() return vv(center.x, center.y, center.z) end }
	local N = opts.frags or 127
	if not opts.no_init then
		for i = 1, N do
			cbs.bullet_on_init({ position = vv(center.x, center.y, center.z), direction = vv(0, 0, 1), speed = 200,
				weapon_id = eid, parent_id = thrower, target_id = 65535 })
		end
	end
	frame()
	local hitbones = { "bip01_spine1", "bip01_spine2", "bip01_l_thigh", "bip01_r_thigh", "bip01_l_upperarm", "bip01_r_forearm",
		"bip01_l_calf", "bip01_head", "bip01_neck", "bip01_pelvis" }
	local fired = {}
	for _, o in ipairs(targets) do
		local torso = o:bone_position("bip01_spine1")
		local d = torso:distance_to(center)
		local n = math.floor(N * 0.5 / (4 * math.pi * d * d) + 0.5)
		fired[o:id()] = n
		for k = 1, n do
			local bone = hitbones[(k * 7 + o:id()) % #hitbones + 1]
			local bp = o:bone_position(bone)
			local dx, dy, dz = bp.x - center.x, bp.y - center.y, bp.z - center.z
			local l = math.sqrt(dx * dx + dy * dy + dz * dz)
			local dir = vv(dx / l, dy / l, dz / l)
			cbs.bullet_on_impact({ position = vv(bp.x - dir.x * 0.08, bp.y - dir.y * 0.08, bp.z - dir.z * 0.08), direction = dir, speed = 200,
				element = BID[bone], parent_id = thrower, target_id = o:id(), weapon_id = eid })
			if o._alive then
				cbs.on_before_hit_after_calcs({ power = opts.frag_power or 0.12, type = hit.fire_wound, draftsman = OBJ[thrower],
					direction = dir, weapon_id = eid }, o, BID[bone])
			end
		end
	end
	frame()
	for _, o in ipairs(targets) do
		local torso = o:bone_position("bip01_spine1")
		local d = torso:distance_to(center)
		local power = (opts.blast or 3) * math.max(0, 1 - d / 8) * (opts.armor or 0.6)
		if o._alive or not opts.no_corpse_blast then
			local dx, dy, dz = torso.x - center.x, torso.y - center.y + 1.2, torso.z - center.z
			local l = math.sqrt(dx * dx + dy * dy + dz * dz)
			local h = { power = power, type = hit.explosion, draftsman = OBJ[thrower],
				direction = vv(dx / l, dy / l, dz / l), weapon_id = eid }
			local was_alive = o._alive
			cbs.on_before_hit_after_calcs(h, o, 0)
			o._blast_power = h.power
			-- (health lost: the engine takes it after the callbacks)
			local kill = was_alive and (opts.kill or h.power >= (o.health or 1) * 0.9)
			if kill then
				o.health = 0
				o._alive = false; o._died_at = T_NOW; cbs.npc_on_death_callback(o, OBJ[thrower])
			elseif was_alive then
				o.health = math.max(0.01, (o.health or 1) - h.power)
			end
		end
	end
	OBJ[eid] = nil
	frame()
	return fired
end
