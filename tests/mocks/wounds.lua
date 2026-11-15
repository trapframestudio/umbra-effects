-- Engine and bake mocks for the wounds workstream (zgo_wounds,
-- tests/zgo_test_wounds.lua). Active only when the test sets
-- WOUNDS_MOCKS = true before loading the harness, so the other suites run
-- exactly as without this file. The shader API (get_shaders, set_shader,
-- reset_shader) comes from mocks/cuts.lua: the test sets CUTS_MOCKS too.
--
--   get_console_cmd(0, "renderer")   WOUNDS_RENDERER ("renderer_r4"; nil = no such command)
--   getFS():exist                    ZGO's wound shader and textures are looked up as the
--                                    real files in gamedata/ (shaders\r3\zgo_dmg*,
--                                    textures\zgo\wounds\...); WOUNDS_FILES[root|path] adds others
--   WOUNDS_BAKE{ damage = bool, visual = name, id = bake id, sections = { [root] = true },
--                shift = metres (every site moved along x: another bake of the model) }
--       installs a bake for the harness's stalker model, made the way bake.py
--       writes it (zgo_bake_index / _parts / _wounds with one bake_id): the
--       harness skeleton as the bind pose, wound sites on every section,
--       14 intact sub-meshes and, with damage, 10 damage meshes (ids 15-24)
--       whose default shader is zgo\off; CUTS_MODELS gets the same 24
--       children. Returns { names, sites = { [section] = { site spec } } }.
--   WOUNDS_FIXTURE()                 installs the baker's own fixture bake
--                                    (tests/baker/fixtures, synthetic model)
--   WOUNDS_UNBAKE()                  back to what the harness had (ZGO_BAKED)
if not WOUNDS_MOCKS then return end

local HERE = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local GAMEDATA = HERE .. "/../../gamedata"

WOUNDS_RENDERER = "renderer_r4"
WOUNDS_FILES = {}
function get_console_cmd(kind, name)
	if name == "renderer" then
		if WOUNDS_RENDERER == nil then error("no such console command") end
		return WOUNDS_RENDERER
	end
	return nil
end

local function real(rel)
	local f = io.open(GAMEDATA .. "/" .. rel:gsub("\\", "/"), "rb")
	if f then f:close() return true end
	return false
end

local base_getFS = getFS
function getFS()
	local fs = base_getFS()
	local exist = fs.exist
	function fs:exist(root, p)
		if exist(self, root, p) or WOUNDS_FILES[root .. "|" .. p] then return true end
		if root == "$game_shaders$" and p:match("^r3\\zgo_dmg") then return real("shaders/" .. p) end
		if root == "$game_textures$" and p:match("^zgo\\wounds\\") then return real("textures/" .. p) end
		return false
	end
	return fs
end

------------------------------------------------------------------ a bake for the harness model
WOUNDS_VISUAL = "actors\\stalker_neutral\\stalker_neutral_1"
local BODY_TEX, FACE_TEX = "act\\act_stalker_neutral", "act\\act_face_1"

-- per section: { bone, offset from the bone (m), outward normal, thick, radius, depth (mm), hint }
local SPEC = {
	body = {
		{ "bip01_spine1", 0, 0, 0.12, 0, 0, 1, 240, 100, 110, "cF" },
		{ "bip01_spine1", 0, 0, -0.11, 0, 0, -1, 240, 100, 110, "kB" },
		{ "bip01_spine2", 0, 0, 0.11, 0, 0, 1, 230, 100, 100, "cF" },
		{ "bip01_spine", 0, 0, 0.12, 0, 0, 1, 250, 100, 120, "aF" },
		{ "bip01_spine", 0, 0, -0.11, 0, 0, -1, 250, 100, 110, "kB" },
		{ "bip01_pelvis", 0, -0.02, 0.11, 0, 0, 1, 260, 100, 110, "pF" },
		{ "bip01_spine1", 0.16, 0, 0, 1, 0, 0, 280, 90, 120, "cS" },
		{ "bip01_spine1", -0.16, 0, 0, -1, 0, 0, 280, 90, 120, "cS" },
	},
	bip01_head = {
		{ "bip01_head", 0, 0.03, 0.09, 0, 0, 1, 160, 60, 60, "f" },
		{ "bip01_head", 0, 0.03, -0.09, 0, 0, -1, 160, 60, 60, "s" },
		{ "bip01_head", 0.08, 0.03, 0, 1, 0, 0, 150, 60, 60, "s" },
		{ "bip01_head", -0.08, 0.03, 0, -1, 0, 0, 150, 60, 60, "s" },
		{ "bip01_head", 0, 0.11, 0, 0, 1, 0, 160, 60, 60, "s" },
	},
}
for _, side in ipairs({ { "l", 1 }, { "r", -1 } }) do
	local s, x = side[1], side[2]
	local function b(n) return "bip01_" .. s .. "_" .. n end
	SPEC[b("upperarm")] = { { b("upperarm"), 0.10 * x, 0, 0.045, 0, 0, 1, 90, 80, 45, "l" },
		{ b("upperarm"), 0.10 * x, 0, -0.045, 0, 0, -1, 90, 80, 45, "l" } }
	SPEC[b("forearm")] = { { b("forearm"), 0.11 * x, 0, 0.04, 0, 0, 1, 80, 90, 40, "l" } }
	SPEC[b("hand")] = { { b("hand"), 0.05 * x, 0, 0.02, 0, 0, 1, 40, 50, 20, "x" } }
	SPEC[b("thigh")] = { { b("thigh"), 0, -0.12, 0.07, 0, 0, 1, 150, 100, 70, "l" },
		{ b("thigh"), 0, -0.12, -0.07, 0, 0, -1, 150, 100, 70, "l" }, { b("thigh"), 0.07 * x, -0.12, 0, x, 0, 0, 150, 100, 70, "l" } }
	SPEC[b("calf")] = { { b("calf"), 0, -0.12, 0.055, 0, 0, 1, 110, 100, 50, "l" },
		{ b("calf"), 0, -0.12, -0.055, 0, 0, -1, 110, 100, 50, "l" } }
	SPEC[b("foot")] = { { b("foot"), 0, -0.04, 0.06, 0, 0, 1, 60, 60, 30, "x" } }
end
WOUNDS_SPEC = SPEC

-- child ids: the intact sub-meshes C_s 1..14, damage meshes D_s 15..24
local NAMES = { "body", "bip01_head", "bip01_l_upperarm", "bip01_l_forearm", "bip01_l_hand", "bip01_r_upperarm",
	"bip01_r_forearm", "bip01_r_hand", "bip01_l_thigh", "bip01_l_calf", "bip01_l_foot", "bip01_r_thigh", "bip01_r_calf", "bip01_r_foot" }
local DMG = { body = 15, bip01_head = 16, bip01_l_upperarm = 17, bip01_l_forearm = 18, bip01_r_upperarm = 19,
	bip01_r_forearm = 20, bip01_l_thigh = 21, bip01_l_calf = 22, bip01_r_thigh = 23, bip01_r_calf = 24 }
WOUNDS_NAMES, WOUNDS_DMG = NAMES, DMG

local saved = {}
for _, n in ipairs({ "zgo_bake_index", "zgo_bake_parts", "zgo_bake_wounds" }) do
	saved[n] = { ns = rawget(_G, n), file = FS_FILES["$game_scripts$|" .. n .. ".script"] }
end

local function install(index, parts, wounds)
	rawset(_G, "zgo_bake_index", index)
	rawset(_G, "zgo_bake_parts", parts)
	rawset(_G, "zgo_bake_wounds", wounds)
	FS_FILES["$game_scripts$|zgo_bake_index.script"] = index ~= nil or nil
	FS_FILES["$game_scripts$|zgo_bake_parts.script"] = parts ~= nil or nil
	FS_FILES["$game_scripts$|zgo_bake_wounds.script"] = wounds ~= nil or nil
	zgo_bake.reset()
end

function WOUNDS_UNBAKE()
	for n, s in pairs(saved) do
		rawset(_G, n, s.ns)
		FS_FILES["$game_scripts$|" .. n .. ".script"] = s.file
	end
	CUTS_MODELS[WOUNDS_VISUAL] = nil
	zgo_bake.reset()
end

function WOUNDS_BAKE(opts)
	opts = opts or {}
	local vis = opts.visual or WOUNDS_VISUAL
	local id = opts.id or "wounds-test-1"
	-- the bind pose: the harness skeleton (identity rotations, T-pose origins)
	local probe = NEW_NPC(64999, "stalker", VV(0, 0, 0))
	OBJ[64999] = nil
	local bones = probe:list_bones()
	local bid, pos, sk = {}, {}, {}
	for i = 0, #bones do
		local n = bones[i]
		local p = probe:bone_transform(i).c
		local par = probe:bone_parent(i)
		bid[n], pos[n] = i, p
		sk[#sk + 1] = string.format("%s,%d,10000,0,0,0,%d,%d,%d", n, par == 65535 and -1 or par,
			math.floor(p.x * 10000 + 0.5), math.floor(p.y * 10000 + 0.5), math.floor(p.z * 10000 + 0.5))
	end
	local site_lines, wmodel, sites = {}, { "1" }, {}
	for i, sec in ipairs(NAMES) do
		local items = {}
		sites[sec] = {}
		for _, s in ipairs(SPEC[sec]) do
			local bp = pos[s[1]]
			local sh = opts.shift or 0       -- another bake of the model: sites elsewhere
			local x, y, z = bp.x + s[2] + sh, bp.y + s[3], bp.z + s[4]
			items[#items + 1] = string.format("%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s", bid[s[1]],
				math.floor(x * 1000 + 0.5), math.floor(y * 1000 + 0.5), math.floor(z * 1000 + 0.5),
				s[5] * 100, s[6] * 100, s[7] * 100, s[8], s[9], s[10], s[11])
			sites[sec][#sites[sec] + 1] = { bone = s[1], pos = { x = x, y = y, z = z }, normal = { x = s[5], y = s[6], z = s[7] },
				thick = s[8] / 1000, radius = s[9] / 1000, depth = s[10] / 1000 }
		end
		site_lines[i] = table.concat(items, ";")
		wmodel[#wmodel + 1] = string.format("%d=%d", i, i)
	end
	local ptoks = {}
	for i, sec in ipairs(NAMES) do
		local t = string.format("%d:%d/-/-", i, i)
		if opts.damage and DMG[sec] then t = t .. string.format("/d:%d=%d", i, DMG[sec]) end
		ptoks[#ptoks + 1] = t
	end
	local roots = opts.sections or { bip01_head = true, bip01_l_upperarm = true, bip01_l_forearm = true, bip01_l_hand = true,
		bip01_r_upperarm = true, bip01_r_forearm = true, bip01_r_hand = true, bip01_l_thigh = true, bip01_l_calf = true,
		bip01_l_foot = true, bip01_r_thigh = true, bip01_r_calf = true, bip01_r_foot = true }
	local index = { version = 2, bake_id = id, models = { [vis] = roots },
		features = { caps = false, pieces = false, wounds = true, kcaps = false, damage = opts.damage and true or false } }
	local parts = { version = 1, bake_id = id, names = NAMES, bonesets = {}, models = { [vis] = table.concat(ptoks, " ") } }
	local wounds = { version = 1, bake_id = id, names = NAMES, skels = { table.concat(sk, ";") }, sites = site_lines,
		models = { [vis] = table.concat(wmodel, " ") } }
	install(index, parts, wounds)
	-- the sub-meshes the game would load for this model
	local def = {}
	for i, sec in ipairs(NAMES) do def[i] = { "models\\model", sec == "bip01_head" and FACE_TEX or BODY_TEX } end
	local n = #NAMES
	if opts.damage then
		for _, sec in ipairs(NAMES) do
			if DMG[sec] then def[DMG[sec]] = { "zgo\\off", sec == "bip01_head" and FACE_TEX or BODY_TEX } n = math.max(n, DMG[sec]) end
		end
	end
	CUTS_MODELS[vis] = { n = n, def = def }
	WOUNDS_FILES["$game_textures$|" .. BODY_TEX .. "_bump.dds"] = true
	return { names = NAMES, sites = sites, children = n }
end

-- the baker's own output for its synthetic model (tests/baker/fixtures)
function WOUNDS_FIXTURE()
	local function load(name)
		local env = {}
		local f = assert(loadfile(HERE .. "/../baker/fixtures/" .. name .. ".script"))
		setfenv(f, env)
		f()
		return env
	end
	install(load("zgo_bake_index"), load("zgo_bake_parts"), load("zgo_bake_wounds"))
end
