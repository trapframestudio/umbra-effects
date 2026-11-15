-- Engine mocks for the probe workstream (zgo_probe, tests/zgo_test_probe.lua).
-- Active only when the test sets PROBE_MOCKS = true before loading the
-- harness, so the other suites run exactly as without this file.
--
--   level.iterate_nearest(pos, radius, fn)   nearest first, fn returning true stops
--   o:get_shaders / get_default_shaders / set_shader / reset_shader
--       as CScriptGameObject (script_game_object.cpp): a table by child id
--       (OGF child index + 1), child id < 1 = every child, an empty texture
--       keeps the current one; a visual change drops the overrides
--   o:bone_visible(name)
--   getFS(): update_path (into PROBE_TMP), r_open / r_close on fake OGF files
--       (PROBE_MESHES), exist for those, ZGO's own probe shaders and textures
--       (the real files in gamedata/) and PROBE_TEXTURES
--   NEW_PROP(id, pos, visual)   a loose physics object (clsid.obj_physic)
if not PROBE_MOCKS then return end

local ffi = require("ffi")
local HERE = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local GAMEDATA = HERE .. "/../../gamedata"
PROBE_TMP = PROBE_TMP or os.getenv("TMPDIR") or "/tmp"

local W1, W2, W3, W4 = 0x12071980, 0x240E3300, 0x481C6600, 0x5A237F80
local function key(v) return (string.gsub(string.gsub(string.lower(v or ""), "/", "\\"), "%.ogf$", "")) end
PROBE_KEY = key

-- fake models: type (3 = animated skeleton, 10 = rigid skeleton, 4 = static),
-- bone count, and per child { texture, shader, vertex format, bind-pose box }
local function kid(tex, shader, fmt, y0, y1, w)
	w = w or 0.3
	return { tex = tex, shader = shader or "models\\model", fmt = fmt, bb = { -w, y0, -w, w, y1, w } }
end
local stalker_kids = {
	kid("act\\act_stalker_neutral_1", nil, W2, 0, 1.5, 0.4),          -- body (biggest)
	kid("act\\act_face_1", nil, W1, 1.5, 1.8, 0.15),                   -- head (highest)
	kid("act\\act_hands_1", nil, W2, 0.9, 1.5, 0.2),
}
if BAKED then
	-- the baker's output: body part, then each severable section
	for i = 1, 11 do stalker_kids[#stalker_kids + 1] = kid("act\\act_stalker_neutral_1", nil, W2, 0.1 * i, 0.1 * i + 0.3, 0.1) end
end
PROBE_MESHES = PROBE_MESHES or {
	["actors\\stalker_neutral\\stalker_neutral_1"] = { type = 3, bones = 47, kids = stalker_kids },
	["actors\\stalker_bandit\\bandit_2"] = { type = 3, bones = 47, kids = {
		kid("act\\act_bandit_2", nil, W4, 0, 1.5, 0.4), kid("act\\act_face_2", nil, W1, 1.5, 1.8, 0.15),
		kid("act\\act_bandit_glass", "models\\model_aref", W2, 1.6, 1.7, 0.1) } },
	["monsters\\dog\\dog_1"] = { type = 3, bones = 30, kids = { kid("monsters\\dog\\dog", nil, W3, 0, 0.8, 0.6) } },
	["dynamics\\devices\\dev_vodka\\dev_vodka"] = { type = 10, bones = 1, kids = { kid("prop\\vodka", "models\\model", W1, 0, 0.3, 0.05) } },
	["dynamics\\box\\box_paper"] = { type = 10, bones = 1, kids = { kid("prop\\box_paper", "models\\model", W1, 0, 0.4, 0.3) } },
	["dynamics\\balon\\kanistra"] = { type = 10, bones = 1, kids = { kid("prop\\kanistra", "models\\model", W1, 0, 0.5, 0.2) } },
	["dynamics\\barrel\\bochka_close_1"] = { type = 10, bones = 3, kids = { kid("prop\\bochka", "models\\model", W1, 0, 1, 0.4) } },
	["dynamics\\static\\lamp_static"] = { type = 4, bones = 0, kids = {} },
}
-- textures that "exist" besides ZGO's own: the stalker's bump pair
PROBE_TEXTURES = PROBE_TEXTURES or { ["act\\act_stalker_neutral_1_bump.dds"] = true, ["act\\act_stalker_neutral_1_bump#.dds"] = true }
PROBE_OPENED = 0

------------------------------------------------------------------ OGF bytes
local function u16(n) return string.char(n % 256, math.floor(n / 256) % 256) end
local function u32(n) return string.char(n % 256, math.floor(n / 256) % 256, math.floor(n / 65536) % 256, math.floor(n / 16777216) % 256) end
local function f32(x) local b = ffi.new("float[1]", x) return ffi.string(b, 4) end
local function chunk(id, payload) return u32(id) .. u32(#payload) .. payload end
local function header(typ, bb)
	local s = string.char(4, typ) .. u16(0)
	for i = 1, 6 do s = s .. f32(bb[i]) end
	return s .. f32(0) .. f32(1) .. f32(0) .. f32(1)
end
function PROBE_OGF(spec)
	local kids = {}
	for i, k in ipairs(spec.kids) do
		kids[#kids + 1] = chunk(i - 1, chunk(1, header(5, k.bb)) .. chunk(2, k.tex .. "\0" .. k.shader .. "\0") .. chunk(3, u32(k.fmt) .. u32(100)))
	end
	local s = chunk(1, header(spec.type, { -1, 0, -1, 1, 2, 1 }))
	if #kids > 0 then s = s .. chunk(9, table.concat(kids)) end
	if spec.bones > 0 then s = s .. chunk(13, u32(spec.bones) .. "bone\0") end
	return s
end

local function reader(b)
	local r = { pos = 0 }
	local function take(n)
		assert(r.pos + n <= #b, "read past the end of the file")
		local s = b:sub(r.pos + 1, r.pos + n)
		r.pos = r.pos + n
		return s
	end
	function r:r_tell() return self.pos end
	function r:r_elapsed() return #b - self.pos end
	function r:r_seek(p) assert(p >= 0 and p <= #b, "seek outside the file") self.pos = p end
	function r:r_advance(n) self:r_seek(self.pos + n) end
	function r:r_eof() return self.pos >= #b end
	function r:r_u8() return take(1):byte() end
	function r:r_u16() local a, c = take(2):byte(1, 2) return a + c * 256 end
	function r:r_u32() local a, c, d, e = take(4):byte(1, 4) return a + c * 256 + d * 65536 + e * 16777216 end
	function r:r_float() local f = ffi.new("float[1]") ffi.copy(f, take(4), 4) return f[0] end
	function r:r_stringZ()
		local e = b:find("\0", self.pos + 1, true)
		assert(e, "unterminated string")
		local s = b:sub(self.pos + 1, e - 1)
		self.pos = e
		return s
	end
	return r
end

------------------------------------------------------------------ file system
local function real(rel)
	local f = io.open(GAMEDATA .. "/" .. rel:gsub("\\", "/"), "rb")
	if f then f:close() return true end
	return false
end

local function probe_exist(root, p)
	p = string.lower(p)
	if root == "$game_meshes$" then return PROBE_MESHES[key(p)] ~= nil end
	if root == "$game_shaders$" then
		if p:match("^r3\\zgo_off%.s$") or p:match("^r3\\zgo_probe_") then return real("shaders/" .. p) end
		return false
	end
	if root == "$game_textures$" then
		if p:match("^zgo\\probe\\") then return real("textures/" .. p) end
		return PROBE_TEXTURES[p] or false
	end
	return false
end

local base_getFS = getFS
function getFS()
	local fs = base_getFS()
	local exist = fs.exist
	function fs:exist(root, p) return exist(self, root, p) or probe_exist(root, p) end
	fs.update_path = fs.update_path or function(self, root, file) return PROBE_TMP .. "/" .. file end
	fs.r_open = fs.r_open or function(self, root, p)
		if root ~= "$game_meshes$" then return nil end
		local spec = PROBE_MESHES[key(p)]
		if not spec then return nil end
		PROBE_OPENED = PROBE_OPENED + 1
		return reader(PROBE_OGF(spec))
	end
	fs.r_close = fs.r_close or function(self, r) end
	return fs
end

------------------------------------------------------------------ nearest objects
if level.iterate_nearest == nil then
	function level.iterate_nearest(pos, radius, fn)
		local list = {}
		for _, o in pairs(OBJ) do
			if type(o) == "table" and type(o.position) == "function" then
				local p = o:position()
				local d = math.sqrt((p.x - pos.x) ^ 2 + (p.y - pos.y) ^ 2 + (p.z - pos.z) ^ 2)
				if d <= radius then list[#list + 1] = { o = o, d = d } end
			end
		end
		table.sort(list, function(a, b) return a.d < b.d end)
		for _, e in ipairs(list) do if fn(e.o) then return end end
	end
end

------------------------------------------------------------------ shader API, bone_visible
local function shader_api(o)
	if o.get_shaders or o.set_shader or o.reset_shader or o.get_default_shaders then return end
	o._probe_over = {}
	local function spec(self)
		local s = PROBE_MESHES[key(self:get_visual_name())]
		if self._probe_vis ~= key(self:get_visual_name()) then
			self._probe_vis = key(self:get_visual_name())
			self._probe_over = {}       -- a new visual: new children, no overrides
		end
		return s
	end
	local function count(self)
		local s = spec(self)
		return self._kids_n or (s and #s.kids) or 1
	end
	local function default(self, i)
		local s = spec(self)
		local k = s and s.kids[i]
		return k and k.shader or "models\\model", k and k.tex or "act\\act_default"
	end
	function o:get_default_shaders(hud)
		local s = spec(self)
		if s and s.type == 4 then return { error = true } end
		local t = {}
		for i = 1, count(self) do local sh, tx = default(self, i) t[i] = { shader = sh, texture = tx } end
		return t
	end
	function o:get_shaders(hud)
		local t = self:get_default_shaders(hud)
		if t.error then return t end
		for i, ov in pairs(self._probe_over) do if t[i] then t[i] = { shader = ov.shader, texture = ov.texture } end end
		return t
	end
	function o:set_shader(id, shader, tex, hud)
		assert(type(id) == "number" and type(shader) == "string" and type(hud) == "boolean", "luabind: no overload for set_shader")
		spec(self)
		local n = count(self)
		local function one(i)
			local cur = self._probe_over[i]
			local _, dtx = default(self, i)
			local keep = cur and cur.texture or dtx
			self._probe_over[i] = { shader = shader, texture = (tex ~= nil and tex ~= "") and tex or keep }
		end
		if id < 1 then for i = 1, n do one(i) end elseif id <= n then one(id) end
	end
	function o:reset_shader(id, hud)
		assert(type(id) == "number" and type(hud) == "boolean", "luabind: no overload for reset_shader")
		spec(self)
		if id < 1 then self._probe_over = {} else self._probe_over[id] = nil end
	end
end

NPC_HOOKS[#NPC_HOOKS + 1] = function(o)
	shader_api(o)
	if not o.bone_visible then
		function o:bone_visible(name) return not self._hidden[name] end
	end
end

------------------------------------------------------------------ loose props
PROP_SWAPS = {}
function NEW_PROP(id, pos, visual)
	local o = { _id = id, _pos = pos, _visual = key(visual), _sec = "probe_prop" }
	function o:id() return self._id end
	function o:section() return self._sec end
	function o:clsid() return clsid.obj_physic end
	function o:position() return vector():set(self._pos.x, self._pos.y, self._pos.z) end
	function o:get_visual_name() return self._visual .. ".ogf" end
	function o:list_bones()
		local s = PROBE_MESHES[self._visual]
		local t = {}
		for i = 0, (s and s.bones or 1) - 1 do t[i] = "bone" .. i end
		return t
	end
	-- CScriptGameObject::set_visual_name: GE_CHANGE_VISUAL to the server, then
	-- CalculateBones on the new visual's kinematics (null for a static model)
	function o:set_visual_name(v, force)
		assert(type(v) == "string" and type(force) == "boolean", "luabind: no overload for set_visual_name")
		local s = PROBE_MESHES[key(v)]
		assert(s and (s.type == 3 or s.type == 10), "engine would crash: set_visual_name to a model without a skeleton: " .. v)
		self._visual = key(v)
		PROP_SWAPS[#PROP_SWAPS + 1] = { id = self._id, vis = self._visual }
	end
	shader_api(o)
	OBJ[id] = o
	return o
end
