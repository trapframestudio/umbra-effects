-- Baked parts and wound sites: the zgo_bake.script accessors against the
-- baker's own output for a synthetic model (tests/baker/fixtures, made by
-- python3 tests/baker/fakemo2.py --fixtures). Run: luajit zgo_test_baker2.lua [seed]
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local seed = tonumber(arg and arg[1]) or 5
arg = { S .. "/../gamedata/scripts", "sp" }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)

local B = zgo_bake
local base_setting = zgo_util.setting
local OVR = {}
zgo_util.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	return base_setting(k)
end

local function section(t) print(("\n== %s"):format(t)) end
local function near(a, b, eps) return math.abs(a - b) <= (eps or 1e-6) end
local function vnear(a, b, eps) return near(a.x, b.x, eps) and near(a.y, b.y, eps) and near(a.z, b.z, eps) end
local function dot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end
local function same_list(a, b)
	if #a ~= #b then return false end
	for i = 1, #a do if a[i] ~= b[i] then return false end end
	return true
end

local function fixture(name)
	local env = {}
	local f = assert(loadfile(S .. "/baker/fixtures/" .. name .. ".script"))
	setfenv(f, env)
	f()
	return env
end

local saved_index = rawget(_G, "zgo_bake_index")
local saved_files = {}
local SCR = { "zgo_bake_index", "zgo_bake_parts", "zgo_bake_wounds" }
for _, n in ipairs(SCR) do saved_files[n] = FS_FILES["$game_scripts$|" .. n .. ".script"] end

local function install(index, parts, wounds)
	rawset(_G, "zgo_bake_index", index)
	rawset(_G, "zgo_bake_parts", parts)
	rawset(_G, "zgo_bake_wounds", wounds)
	FS_FILES["$game_scripts$|zgo_bake_index.script"] = index ~= nil or nil
	FS_FILES["$game_scripts$|zgo_bake_parts.script"] = parts ~= nil or nil
	FS_FILES["$game_scripts$|zgo_bake_wounds.script"] = wounds ~= nil or nil
	B.reset()
end

local A, M = "actors\\synth\\synth_a", "monsters\\synth\\synth_m"

------------------------------------------------------------------------
section("No baked models: everything answers nil / false")
install(nil, nil, nil)
assert(B.count() == 0 and not B.is_baked(A) and B.parts(A) == nil and B.cap(A, "bip01_head") == nil)
assert(B.wound_sites(A) == nil and B.bake_id() == nil and not B.has_damage_mesh(A, "body"))
local f = B.features()
assert(f.caps == false and f.pieces == false and f.wounds == false and f.kcaps == false and f.damage == false)

------------------------------------------------------------------------
section("An index from before 1.7 (no bake_id): sub-meshes as before, no parts or sites")
install({ models = { [A] = { bip01_head = true } } }, fixture("zgo_bake_parts"), fixture("zgo_bake_wounds"))
assert(B.is_baked(A) and B.has_section(A, "bip01_head") and not B.has_section(A, "bip01_l_thigh"))
assert(B.parts(A) == nil and B.cap(A, "bip01_head") == nil and B.wound_sites(A) == nil)
assert(B.features().caps == false)
print("  old index: baked, no parts, no sites")

------------------------------------------------------------------------
section("The baker's own output")
local IDX, PARTS, WOUNDS = fixture("zgo_bake_index"), fixture("zgo_bake_parts"), fixture("zgo_bake_wounds")
install(IDX, PARTS, WOUNDS)
assert(B.bake_id() == "fixture-1" and B.count() == 3)
f = B.features()
assert(f.caps and f.pieces and f.wounds and f.kcaps and f.damage)
-- visual names as the engine reports them
assert(B.is_baked("Actors/Synth/Synth_A.ogf") and B.key("actors/synth/synth_a.ogf") == A)
local npc = { get_visual_name = function() return "actors\\synth\\synth_a" end }
assert(B.is_baked(npc) and B.parts(npc) == B.parts(A))

local P = B.parts(A)
local n = 0
for name, e in pairs(P) do
	n = n + 1
	assert(type(e.kids) == "table" and #e.kids >= 1, name)
end
assert(n == 6, "body plus five sections")
assert(same_list(B.submeshes(A, "body"), { 1, 3, 6 }))
assert(same_list(B.submeshes(A, "bip01_head"), { 2 }))

for _, s in ipairs({ "bip01_head", "bip01_l_upperarm", "bip01_l_forearm", "bip01_l_thigh", "bip01_l_calf" }) do
	local c = B.cap(A, s)
	assert(c and c.model:match("^zgo\\baked\\caps\\%x%x\\%x+$"), s)
	local h = c.model:match("\\(%x+)$")
	assert(c.model:sub(-#h - 3, -#h - 2) == h:sub(1, 2), "shard folder is the first two digits")
	assert(c.bones[1] == c.parent and c.bones[#c.bones] == s, s)
	local p = B.piece(A, s)
	assert(p and p.root == s and p.model:match("^zgo\\baked\\pieces\\%x%x\\%x+$"), s)
	assert(#B.kcap_ids(A, s) == 2, s)
	local ch = B.chunks(A, s)
	assert(ch and ch.count >= 1 and ch.model:match("^zgo\\baked\\chunks\\"), s)
end
assert(B.cap(A, "body") == nil and B.piece(A, "body") == nil)
assert(B.cap(A, "bip01_head").parent == "bip01_neck")
assert(B.cap(A, "bip01_l_thigh").parent == "bip01_pelvis")
-- the same seams in another model share the cap file; its own skin texture gives it its own piece
assert(B.cap(M, "bip01_head").model == B.cap(A, "bip01_head").model)
assert(B.piece(M, "bip01_head").model ~= B.piece(A, "bip01_head").model)
-- experimental ids: K and D sub-meshes come after the model's own
local nkids = 0
for _, e in pairs(P) do nkids = nkids + #e.kids end
for _, e in pairs(P) do
	for _, id in ipairs(e.kcap or {}) do assert(id > nkids) end
	for c, d in pairs(e.dmg or {}) do assert(c <= nkids and d > nkids) end
end
assert(B.damage_ids(A, "body")[3] == 19 and B.has_damage_mesh(A, "body") and not B.has_damage_mesh(A, "nope"))
print(("  %d sections, caps / pieces / K / D / chunks found"):format(n))

-- body gibs: one model per baked model, piece i = bone i, each from a bone of the body
local G = B.gibs(A)
assert(G and G.model:match("^zgo\\baked\\gibs\\%x%x\\%x+$"), "gib model")
assert(G.count >= 8 and G.count == #G.pieces, "pieces")
local skel_names = {}
for _, nm in ipairs({ "root", "bip01_pelvis", "bip01_spine", "bip01_neck", "bip01_head", "bip01_l_upperarm",
	"bip01_l_forearm", "bip01_l_hand", "bip01_l_thigh", "bip01_l_calf", "bip01_l_foot" }) do skel_names[nm] = true end
for i, pc in ipairs(G.pieces) do
	assert(skel_names[pc.bone], "piece " .. i .. " comes from a bone of the body: " .. tostring(pc.bone))
	local m = pc.m
	assert(near(dot(m.i, m.i), 1, 1e-6) and near(dot(m.k, m.k), 1, 1e-6) and near(dot(m.i, m.k), 0, 1e-6))
	assert(math.abs(m.c.x) + math.abs(m.c.y) + math.abs(m.c.z) < 1, "frame near its bone")
end
assert(B.gibs(A) == G, "decoded once")
assert(B.gibs(M) and B.gibs(M).model ~= G.model, "another skin, its own pieces")
print(("  body gibs: %d pieces"):format(G.count))

------------------------------------------------------------------------
section("Wound sites and bind poses")
local W = B.wound_sites(A)
assert(W and W.skel and W.skel.count == 11)
local total = 0
for name, list in pairs(W.sections) do
	assert(P[name], name)
	for i, s in ipairs(list) do
		total = total + 1
		assert(s.index == i and type(s.bone) == "string" and W.skel.by_name[s.bone].id == s.bone_id)
		assert(near(dot(s.normal, s.normal), 1, 1e-6))
		assert(s.thick > 0 and s.radius > 0 and s.depth >= 0 and s.depth <= s.thick + 1e-9)
		assert(#s.hint >= 1)
		local hit, d = B.nearest_site(A, name, s.pos)
		assert(hit == s and d == 0)
	end
end
assert(#B.sites(A, "body") >= 12 and #B.sites(A, "body") <= 20)
assert(#B.sites(A, "bip01_head") >= 4 and #B.sites(A, "bip01_head") <= 6)
assert(#B.sites(A, "bip01_l_thigh") >= 1 and #B.sites(A, "bip01_l_thigh") <= 4)
assert(#B.sites(A, "body") == B.chunks(A, "body").count, "one chunk bone per site")
for i = 0, W.skel.count - 1 do
	local m = W.skel.bones[i]
	assert(near(dot(m.i, m.i), 1, 1e-6) and near(dot(m.j, m.j), 1, 1e-6) and near(dot(m.i, m.j), 0, 1e-6))
end
local hb = B.bind(A, "bip01_head")
assert(hb == B.bind(A, 4) and vnear(hb.c, { x = 0, y = 1.7195, z = 0.021 }, 1e-4))
assert(vnear(B.bind(A, "root").c, { x = 0, y = 0, z = 0 }))

-- P_bind = Bind_b * inverse(World_b) * P_world, for a random bone pose
local function rot(ax, ay, az)
	local cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
	-- rows i j k of Rz*Ry*Rx (any rotation will do)
	return {
		i = { x = cy * cz, y = cy * sz, z = -sy },
		j = { x = sx * sy * cz - cx * sz, y = sx * sy * sz + cx * cz, z = sx * cy },
		k = { x = cx * sy * cz + sx * sz, y = cx * sy * sz - sx * cz, z = cx * cy },
	}
end
local function apply(m, p) return {
	x = m.c.x + p.x * m.i.x + p.y * m.j.x + p.z * m.k.x,
	y = m.c.y + p.x * m.i.y + p.y * m.j.y + p.z * m.k.y,
	z = m.c.z + p.x * m.i.z + p.y * m.j.z + p.z * m.k.z } end
local function unapply(m, p)
	local d = { x = p.x - m.c.x, y = p.y - m.c.y, z = p.z - m.c.z }
	return { x = dot(d, m.i), y = dot(d, m.j), z = dot(d, m.k) }
end
for t = 1, 20 do
	local list = B.sites(A, "body")
	local s = list[math.random(#list)]
	local world = rot(math.random() * 6, math.random() * 6, math.random() * 6)
	world.c = { x = math.random() * 200 - 100, y = math.random() * 20, z = math.random() * 200 - 100 }
	local bind = B.bind(A, s.bone)
	local p_world = apply(world, unapply(bind, s.pos))       -- where the engine would show it
	local back = B.to_bind(bind, world, p_world)
	assert(vnear(back, s.pos, 1e-6), "to_bind round trip")
	local hit = B.nearest_site(A, "body", back)
	assert(hit == s)
end
-- shared site tables decode once per model, equal contents
local WM = B.wound_sites(M)
assert(#WM.sections.body == #W.sections.body and vnear(WM.sections.body[1].pos, W.sections.body[1].pos))
print(("  %d sites, %d bones; to_bind and nearest_site agree"):format(total, W.skel.count))

------------------------------------------------------------------------
section("MCM switch off: nil unless raw")
OVR["dismember/baked_models"] = false
assert(B.cap(A, "bip01_head") == nil and B.wound_sites(A) == nil and not B.is_baked(A))
assert(B.cap(A, "bip01_head", true) and B.wound_sites(A, true) and B.is_baked(A, true))
OVR["dismember/baked_models"] = nil
assert(B.cap(A, "bip01_head"))

------------------------------------------------------------------------
section("Companions from another bake are ignored")
local stale = fixture("zgo_bake_parts")
stale.bake_id = "something-else"
install(IDX, stale, WOUNDS)
assert(B.is_baked(A) and B.parts(A) == nil and B.cap(A, "bip01_head") == nil)
assert(B.wound_sites(A) ~= nil, "the wounds file still matches")
local logged = 0
for _, l in ipairs(LOG) do if l:find("another bake", 1, true) then logged = logged + 1 end end
assert(logged == 1, "said once")
install(IDX, nil, WOUNDS)
assert(B.parts(A) == nil and B.wound_sites(A) ~= nil)
install(IDX, PARTS, nil)
assert(B.parts(A) ~= nil and B.wound_sites(A) == nil)

------------------------------------------------------------------------
section("Garbage in the strings does not throw")
assert(next(B.decode_parts("", PARTS.names, PARTS.bonesets)) == nil)
assert(next(B.decode_parts("99:1/-/- x:y nonsense", PARTS.names, PARTS.bonesets)) == nil)
local e = B.decode_parts("2:4/zz/-", PARTS.names, PARTS.bonesets).bip01_head
assert(e and e.cap == nil and e.piece == nil and e.kids[1] == 4)
assert(#B.decode_sites("") == 0)

-- leave the harness as it was
rawset(_G, "zgo_bake_index", saved_index)
rawset(_G, "zgo_bake_parts", nil)
rawset(_G, "zgo_bake_wounds", nil)
for _, nm in ipairs(SCR) do FS_FILES["$game_scripts$|" .. nm .. ".script"] = saved_files[nm] end
B.reset()

------------------------------------------------------------------------
section("Errors")
local errs = 0
for _, l in ipairs(LOG) do if l:find("error") then errs = errs + 1 print("  ERR " .. l) end end
assert(errs == 0)
print("\nALL BAKER2 TESTS PASSED")
