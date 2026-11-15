-- Engine mocks for the cuts workstream (zgo_dismember, zgo_debris,
-- tests/zgo_test_cuts.lua). Active only when the test sets CUTS_MOCKS = true
-- before loading the harness, so the other suites run exactly as without it.
--
--   o:get_shaders / get_default_shaders / set_shader / reset_shader
--       as CScriptGameObject (xray-monolith b86d733f4a, script_game_object.cpp
--       :1440-1646, FBasicVisual.cpp SetShaderTexture): a table by child id
--       (OGF child index + 1); id < 1 = every child; an empty texture keeps the
--       current one; a new visual has no overrides. Children per visual come
--       from CUTS_MODELS[visual] = { n = count, def = { [id] = { shader, texture } } }
--       (3 plain children for a visual not listed).
--       CUTS_NO_SHADER_API = true: objects made after it have none of these.
--       CUTS_SHADER_ERROR = true: set_shader raises (a luabind error).
--   attachments of ZGO's baked models (zgo\baked\caps\..., zgo\baked\pieces\...):
--       the file must exist (FS_FILES "$game_meshes$|<model>.ogf"; the engine
--       FATALs on a missing model) and be a skeleton registered in
--       CUTS_ATT_MODELS[model] = { bones = { name, ... }, parents = { [i] = parent index or nil } }
--       (bone 0 first). Such an attachment lists those bones, and
--       bone_callback(bone, parent_bone_name, true) (script_attachment::SetBoneCallback
--       by names) records cb_names[bone] = parent bone; a name missing on either
--       side is recorded in a.cb_bad (the engine only prints a message and then
--       pins the bone to the identity matrix).
--       CUTS_NO_NAMED_CB = true: that overload doesn't exist (raises).
--   CUTS_LOADS: every baked model attached, in order ({ model, owner = "level" | id }).
if not CUTS_MOCKS then return end

local function key(v) return (string.gsub(string.gsub(string.lower(v or ""), "/", "\\"), "%.ogf$", "")) end
CUTS_KEY = key
CUTS_MODELS = CUTS_MODELS or {}
CUTS_ATT_MODELS = CUTS_ATT_MODELS or {}
CUTS_LOADS = {}
CUTS_SET_CALLS = 0

------------------------------------------------------------------ shader API
local function shader_api(o)
	o._sh_over = {}
	local function spec(self)
		local k = key(self:get_visual_name())
		if self._sh_vis ~= k then
			self._sh_vis = k
			self._sh_over = {}           -- a new visual: new children, no overrides
		end
		return CUTS_MODELS[k]
	end
	local function count(self)
		local s = spec(self)
		return s and s.n or 3
	end
	local function default(self, i)
		local s = spec(self)
		local d = s and s.def and s.def[i]
		return d and d[1] or "models\\model", d and d[2] or "act\\act_default"
	end
	function o:get_default_shaders(hud)
		assert(type(hud) == "boolean", "luabind: no overload for get_default_shaders")
		local t = {}
		for i = 1, count(self) do local sh, tx = default(self, i) t[i] = { shader = sh, texture = tx } end
		return t
	end
	function o:get_shaders(hud)
		local t = self:get_default_shaders(hud)
		for i, ov in pairs(self._sh_over) do if t[i] then t[i] = { shader = ov.shader, texture = ov.texture } end end
		return t
	end
	function o:set_shader(id, shader, tex, hud)
		assert(type(id) == "number" and type(shader) == "string" and type(tex) == "string" and type(hud) == "boolean",
			"luabind: no overload for set_shader")
		if CUTS_SHADER_ERROR then error("set_shader: mock engine failure") end
		CUTS_SET_CALLS = CUTS_SET_CALLS + 1
		local n = count(self)
		local function one(i)
			local cur = self._sh_over[i]
			local dsh, dtx = default(self, i)
			self._sh_over[i] = { shader = shader ~= "" and shader or (cur and cur.shader or dsh),
				texture = tex ~= "" and tex or (cur and cur.texture or dtx) }
		end
		if id < 1 then for i = 1, n do one(i) end elseif id <= n then one(id) end
	end
	function o:reset_shader(id, hud)
		assert(type(id) == "number" and type(hud) == "boolean", "luabind: no overload for reset_shader")
		spec(self)
		if id < 1 then self._sh_over = {} else self._sh_over[id] = nil end
	end
end

-- the shader child id currently has on o (what the renderer uses)
function CUTS_SHADER(o, id)
	local t = o:get_shaders(false)
	return t[id] and t[id].shader
end

------------------------------------------------------------------ baked model attachments
local function baked_model(model) return type(model) == "string" and model:find("^zgo\\baked\\") ~= nil end

local function shape(a, model, owner)
	if not baked_model(model) then return a end
	assert(FS_FILES["$game_meshes$|" .. model .. ".ogf"], "engine would FATAL: model file not found: " .. model)
	local spec = assert(CUTS_ATT_MODELS[model], "engine would R_ASSERT (dcast_PKinematics): not a skeleton model: " .. model)
	CUTS_LOADS[#CUTS_LOADS + 1] = { model = model, owner = owner }
	local id_of = {}
	for i, n in ipairs(spec.bones) do id_of[n] = i - 1 end
	a.skel, a.cb_names, a.cb_bad = spec, {}, {}
	function a:list_bones() local t = {} for i, n in ipairs(spec.bones) do t[i - 1] = n end return t end
	function a:bone_parent(id) local p = spec.parents[id + 1] return p or 65535 end
	function a:bone_id(n) return id_of[n] or 65535 end
	-- (recursive: the bone and everything below it, as the engine does)
	function a:set_bone_visible(id, v, rec)
		self.vis[id] = v
		if not rec then return end
		for k = 1, #spec.bones do
			if spec.parents[k] == id then self:set_bone_visible(k - 1, v, rec) end
		end
	end
	function a:bone_callback(b, p, ow)
		assert(ow == true, "expected overwrite callbacks")
		local bid = type(b) == "number" and b or id_of[b]
		if type(p) == "string" then
			if CUTS_NO_NAMED_CB then error("No matching overload found, candidates: void bone_callback(script_attachment&,number,function<matrix>,bool)") end
			if not bid then self.cb_bad[#self.cb_bad + 1] = "attachment has no bone " .. tostring(b) return end
			if not (self.parent_obj and self.parent_obj:get_bone_id(p) ~= 65535) then self.cb_bad[#self.cb_bad + 1] = "parent has no bone " .. p return end
			self.cb_names[spec.bones[bid + 1]] = p
			return
		end
		assert(type(p) == "function", "bone_callback: bad callback")
		if not bid or bid >= #spec.bones then self.cb_bad[#self.cb_bad + 1] = "attachment has no bone " .. tostring(b) return end
		self.cbs[bid] = p
	end
	return a
end

local base_level_add = level.add_attachment
function level.add_attachment(name, model)
	local a = base_level_add(name, model)
	return shape(a, model, "level")
end

NPC_HOOKS[#NPC_HOOKS + 1] = function(o)
	if not CUTS_NO_SHADER_API then shader_api(o) end
	local add = o.add_attachment
	function o:add_attachment(name, model)
		local a = add(self, name, model)
		return shape(a, model, self:id())
	end
end
