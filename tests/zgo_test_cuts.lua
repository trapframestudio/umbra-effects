-- How cuts are drawn with the 1.7 bake (zgo_dismember, zgo_debris):
-- off-shader cuts, fitted stump caps, caps inside the model, light limb
-- pieces, and that none of it changes anything while the options are off or
-- there is no 1.7 bake. Engine parts: tests/mocks/cuts.lua.
--   luajit zgo_test_cuts.lua [seed]             single player, then itself as a
--                                               co-op host and a co-op client
--   luajit zgo_test_cuts.lua host|client seed   one co-op role (ZGO_CUTS_WIRE: the wire file)
-- ZGO_BAKED=1 starts from a bake from before 1.7 (index only) instead of none.
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 5

CUTS_MOCKS = true
arg = { S .. "/../gamedata/scripts", role }
dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)

local D, B = zgo_dismember, zgo_bake
local base_setting = zgo_util.setting
local OVR = {}
zgo_util.setting = function(k)
	if OVR[k] ~= nil then return OVR[k] end
	if k == "general/debug" then return true end   -- debug lines are formatted too
	return base_setting(k)
end

local function section(t) print(("\n== [%s] %s"):format(role, t)) end
local function errs()
	local out = {}
	for _, l in ipairs(LOG) do if l:find("error") or l:find("failed") or l:find("traceback") then out[#out + 1] = l end end
	return out
end
local function no_errs(label)
	local e = errs()
	assert(#e == 0, (label or "") .. ": " .. table.concat(e, " | "))
end
local function logged(pat)
	for _, l in ipairs(LOG) do if l:find(pat, 1, true) then return true end end
	return false
end

------------------------------------------------------------------------
-- The skeleton (from the mock body) and a synthetic bake of its model
------------------------------------------------------------------------
local SV = "actors\\stalker_neutral\\stalker_neutral_1"
local SECS = { "bip01_head", "bip01_l_upperarm", "bip01_l_forearm", "bip01_l_hand", "bip01_r_upperarm", "bip01_r_forearm",
	"bip01_r_hand", "bip01_l_thigh", "bip01_l_calf", "bip01_l_foot", "bip01_r_thigh", "bip01_r_calf", "bip01_r_foot" }
local BONES, PARENT, ID = {}, {}, {}
do
	local probe = NEW_NPC(9999, "stalker", VV(50, 0, 50))
	for id, n in pairs(probe:list_bones()) do BONES[id] = n ID[n] = id end
	for id, n in pairs(BONES) do
		local p = probe:bone_parent(id)
		PARENT[n] = p ~= 65535 and BONES[p] or nil
	end
	OBJ[9999] = nil
end
local function under(root)        -- root and its subtree, in the model's bone order
	local set = { [root] = true }
	local out = {}
	for id = 0, #BONES do
		local n = BONES[id]
		local p = PARENT[n]
		if n == root or (p and set[p]) then set[n] = true out[#out + 1] = n end
	end
	return out, set
end

local KIDS_OF, KCAP_OF, CAP, PIECE, BONESET = { body = { 1, 15 } }, {}, {}, {}, {}
local function model_path(dir, h) return dir .. h:sub(1, 2) .. "\\" .. h end
for i, s in ipairs(SECS) do
	KIDS_OF[s] = s == "bip01_head" and { 2, 16 } or { i + 1 }
	KCAP_OF[s] = { 16 + 2 * i - 1, 16 + 2 * i }
	local set = { PARENT[s], s }
	for id = 0, #BONES do if PARENT[BONES[id]] == s then set[#set + 1] = BONES[id] end end
	BONESET[s] = set
	CAP[s] = model_path("zgo\\baked\\caps\\", string.format("ca%010x", i))
	PIECE[s] = model_path("zgo\\baked\\pieces\\", string.format("be%010x", i))
	-- the cap: bone 0 = the parent bone, the rest hang off it
	local cparents = {}
	for k = 2, #set do cparents[k] = 0 end
	CUTS_ATT_MODELS[CAP[s]] = { bones = set, parents = cparents }
	-- the piece: the section and everything below it, same names, the model's order
	local list = under(s)
	local pid, pparents = {}, {}
	for k, n in ipairs(list) do pid[n] = k - 1 end
	for k, n in ipairs(list) do if k > 1 then pparents[k] = pid[PARENT[n]] end end
	CUTS_ATT_MODELS[PIECE[s]] = { bones = list, parents = pparents }
end

-- opts: kcaps (in-model caps), no_cap / no_piece = { [section] = true }
local function bake(opts)
	opts = opts or {}
	local names, bonesets, toks = { "body" }, {}, { "1:1,15/-/-" }
	local idx = {}
	for i, s in ipairs(SECS) do
		names[i + 1] = s
		bonesets[i] = table.concat(BONESET[s], " ")
		idx[s] = true
		local kids = table.concat(KIDS_OF[s], ",")
		local cap = (opts.no_cap and opts.no_cap[s]) and "-" or (CAP[s]:match("[^\\]+$") .. "." .. i)
		local piece = (opts.no_piece and opts.no_piece[s]) and "-" or PIECE[s]:match("[^\\]+$")
		local tok = string.format("%d:%s/%s/%s", i + 1, kids, cap, piece)
		if opts.kcaps then tok = tok .. "/k:" .. table.concat(KCAP_OF[s], ",") end
		toks[#toks + 1] = tok
	end
	local index = { bake_id = "cuts-test-1", features = { caps = true, pieces = true, wounds = false, kcaps = opts.kcaps or false, damage = false },
		models = { [SV] = idx } }
	local parts = { bake_id = "cuts-test-1", names = names, bonesets = bonesets, models = { [SV] = table.concat(toks, " ") } }
	-- what the game loads: base children, then the caps inside the model (zgo\off until a cut)
	local def = {}
	if opts.kcaps then for i = 17, 42 do def[i] = { "zgo\\off", "food\\food_raw_flesh" } end end
	return index, parts, { n = opts.kcaps and 42 or 16, def = def }
end

local saved_index = rawget(_G, "zgo_bake_index")
local function install(index, parts, model)
	rawset(_G, "zgo_bake_index", index)
	rawset(_G, "zgo_bake_parts", parts)
	FS_FILES["$game_scripts$|zgo_bake_index.script"] = index ~= nil or nil
	FS_FILES["$game_scripts$|zgo_bake_parts.script"] = parts ~= nil or nil
	CUTS_MODELS[SV] = model
	-- (a level change: every cache goes)
	CB.on_level_changing()
end
local function install_17(opts)
	install(bake(opts))
	BAKED = true   -- (harness: hidden sections drop out of view; hidden before the ragdoll = pinched)
end
local function model_files(on)
	for _, s in ipairs(SECS) do
		FS_FILES["$game_meshes$|" .. CAP[s] .. ".ogf"] = on or nil
		FS_FILES["$game_meshes$|" .. PIECE[s] .. ".ogf"] = on or nil
	end
end
model_files(true)
-- the off shader ships with the mod (the probe workstream's file)
do
	local f = io.open(S .. "/../gamedata/shaders/r3/zgo_off.s", "r")
	assert(f, "gamedata/shaders/r3/zgo_off.s is part of the mod")
	f:close()
	FS_FILES["$game_shaders$|r3\\zgo_off.s"] = true
end

------------------------------------------------------------------------
-- What is on screen
------------------------------------------------------------------------
-- a section is drawn while one of its sub-meshes has a visible shader and
-- its bones are not hidden (the renderer drops a child whose bones all are)
local function drawn(o, sec)
	if o._hidden[sec] then return false end
	for _, cid in ipairs(KIDS_OF[sec]) do if CUTS_SHADER(o, cid) ~= "zgo\\off" then return true end end
	return false
end
local function off_sections(o)
	local t = {}
	for _, s in ipairs(SECS) do if not drawn(o, s) then t[#t + 1] = s end end
	return table.concat(t, ",")
end
local function hidden_list(o)
	local t = {}
	for b, h in pairs(o._hidden) do if h then t[#t + 1] = b end end
	table.sort(t)
	return table.concat(t, ",")
end
local function overrides(o) local n = 0 for _ in pairs(o._sh_over or {}) do n = n + 1 end return n end
local function atts(o) local n = 0 for _ in pairs(o._att) do n = n + 1 end return n end
local function caps(o) return zgo_debris.caps_of(o:id()) end
local function cap_for(o, cut)
	for _, c in ipairs(caps(o)) do if c.cut == cut then return c, o._att[c.name] end end
end
local function limbs()
	local t = {}
	for name, a in pairs(LEVEL_ATT) do if name:find("limb") then t[#t + 1] = a end end
	return t
end
local function clear_level()
	zgo_debris.reset()
	for n in pairs(LEVEL_ATT) do LEVEL_ATT[n] = nil end
end

local function kill(o) o._alive = false o.health = 0 o._died_at = T_NOW end
local function ev(cls) return { prof = { energy = 2.5, cls = cls or 2, kind = "bullet" }, dir = VV(0, 0, -1), dead = true } end
local function cut(o, root, cls) D.sever(o, root, ev(cls), root == "bip01_head", false) end
local function ragdoll(o) return o:get_physics_shell() end
local function frames(n) for _ = 1, n or 1 do frame() end end

local nid = 100
local function body(dead, settle)
	nid = nid + 1
	local o = NEW_NPC(nid, "stalker", VV((nid % 7) - 3, 0, -1.5))
	if dead then
		kill(o)
		if settle then o._died_at = -1e9 assert(ragdoll(o)) end
	end
	return o
end

------------------------------------------------------------------------
-- (shared by every role)
local function option_names()
	local seen = {}
	for _, pg in ipairs(zgo_settings_cuts.SETTINGS) do for _, it in ipairs(pg.items) do seen[it.id] = it end end
	assert(seen.offshader_cuts and seen.offshader_cuts.def == false and seen.offshader_cuts.coop == "local")
	assert(seen.baked_pieces and seen.baked_pieces.def == false and seen.baked_pieces.coop == "local")
	assert(seen.cap_style and seen.cap_style.def == "meat" and seen.cap_style.coop == "local")
	assert(zgo_settings.get("dismember/offshader_cuts") == false and zgo_settings.get("dismember/baked_pieces") == false
		and zgo_settings.get("dismember/cap_style") == "meat", "every new way of drawing is off by default")
end

if role == "sp" then
------------------------------------------------------------------------
section("Defaults: the options exist, are off and are each player's own")
option_names()
print("  offshader_cuts, baked_pieces off, cap_style = meat")

------------------------------------------------------------------------
section(BAKED and "A bake from before 1.7, options off: cut as in 1.6" or "No bake, options off: cut as in 1.6")
LOG = {}
local function as_before(label)
	clear_level()
	CUTS_SET_CALLS, CUTS_LOADS = 0, {}
	local a = body(true, true)                -- a corpse lying as a ragdoll
	cut(a, "bip01_r_forearm")
	local b = body(true, false)               -- shot dead this moment
	cut(b, "bip01_l_forearm")
	local waited = BAKED and not b._hidden.bip01_l_forearm
	frames(3)
	print(("  %s: corpse hidden [%s], fresh kill %s, caps %s / %s, limbs %d, set_shader calls %d, baked models loaded %d"):format(label,
		hidden_list(a), waited and "waited for its ragdoll" or "cut at once", #caps(a), #caps(b), #limbs(), CUTS_SET_CALLS, #CUTS_LOADS))
	assert(CUTS_SET_CALLS == 0 and #CUTS_LOADS == 0, "nothing new touched")
	assert(overrides(a) == 0 and overrides(b) == 0)
	if BAKED then
		assert(a._hidden.bip01_r_forearm and a._hidden.bip01_r_hand, "a baked corpse's part is hidden")
		assert(waited and b._hidden.bip01_l_forearm, "a baked body hides the part once its ragdoll exists")
	else
		assert(not a._hidden.bip01_r_forearm, "an unbaked ragdoll can't lose the forearm (physics keeps it)")
		assert(b._hidden.bip01_l_forearm, "an unbaked body cut before its ragdoll")
	end
	for _, o in ipairs({ a, b }) do
		for _, c in ipairs(caps(o)) do
			assert(c.kind == "meat" and c.parent == PARENT[c.cut], "meat caps as before")
			local at = o._att[c.name]
			assert(at and at.parent_bone == c.parent and at.model:find("dynamics\\zpf\\", 1, true))
		end
	end
	for _, l in ipairs(limbs()) do
		assert(l.model == SV, "the flying limb is the whole model")
		assert(l.cbs[0] and l.cbs[0](matrix()).i.x < 0.01, "with everything but the limb collapsed")
	end
	CHECK_CUTS(label)
	return a, b
end
as_before("options off")

section("The new options on, but no 1.7 bake: nothing changes")
OVR["dismember/offshader_cuts"], OVR["dismember/baked_pieces"], OVR["dismember/cap_style"] = true, true, "fitted"
as_before("options on")
OVR["dismember/cap_style"] = "in_model"
as_before("in-model caps asked for")
no_errs("no 1.7 bake")

------------------------------------------------------------------------
section("A 1.7 bake, options off: still cut as in 1.6")
OVR["dismember/offshader_cuts"], OVR["dismember/baked_pieces"], OVR["dismember/cap_style"] = nil, nil, nil
install_17()
assert(B.cap(SV, "bip01_r_forearm").model == CAP.bip01_r_forearm and B.piece(SV, "bip01_r_forearm").model == PIECE.bip01_r_forearm)
assert(B.expected_children(SV) == 16)
LOG = {}
as_before("1.7 bake, options off")
no_errs("1.7 bake, options off")

------------------------------------------------------------------------
section("Off-shader cuts: a part goes at once, before the ragdoll, and nothing pinches")
OVR["dismember/offshader_cuts"] = true
clear_level()
LOG, CUTS_SET_CALLS = {}, 0
local a = body(true, false)
cut(a, "bip01_r_forearm")
print(("  shot dead, no ragdoll yet: off [%s], hidden [%s], shown by %s, limbs %d"):format(off_sections(a), hidden_list(a),
	tostring(D.shown(a, "bip01_r_forearm")), #limbs()))
assert(D.shown(a, "bip01_r_forearm") == "shader", "drawn through the off shader")
assert(not drawn(a, "bip01_r_forearm") and not drawn(a, "bip01_r_hand") and drawn(a, "bip01_r_upperarm"), "the forearm and the hand are gone at once")
assert(hidden_list(a) == "", "no bone is hidden before the ragdoll exists")
assert(#limbs() == 1, "the limb flies off at once (no wait)")
frames(3)
local sh = ragdoll(a)
print(("  ragdoll built: elements for the forearm %s, the hand %s; hidden now [%s]"):format(tostring(sh.el.bip01_r_forearm ~= nil),
	tostring(sh.el.bip01_r_hand ~= nil), hidden_list(a)))
assert(sh.el.bip01_r_forearm and sh.el.bip01_r_hand, "the ragdoll keeps every element: the elbow doesn't pinch")
assert(a._hidden.bip01_r_forearm and a._hidden.bip01_r_hand, "then the bones are hidden too (no hits or wallmarks on the missing part)")
assert(not drawn(a, "bip01_r_forearm"))
CHECK_CUTS("off-shader cut before the ragdoll")
local c1 = cap_for(a, "bip01_r_forearm")
assert(c1 and c1.kind == "meat" and c1.parent == "bip01_r_upperarm", "the meat cap at the elbow")

-- a corpse that already lies as a ragdoll: shader and bones at once
local c = body(true, true)
cut(c, "bip01_l_upperarm")
assert(not drawn(c, "bip01_l_upperarm") and not drawn(c, "bip01_l_forearm") and not drawn(c, "bip01_l_hand"))
assert(c._hidden.bip01_l_upperarm and D.shown(c, "bip01_l_upperarm") == "shader")
-- the same arm further up: the elbow cap goes, a shoulder cap comes
cut(a, "bip01_r_upperarm")
assert(not drawn(a, "bip01_r_upperarm") and drawn(a, "bip01_l_upperarm"))
assert(not cap_for(a, "bip01_r_forearm") and cap_for(a, "bip01_r_upperarm"), "the elbow cap went with the arm")
assert(atts(a) == #caps(a), "no stray attachments")
-- a head bursting off a body that is still falling
local h = body(true, false)
cut(h, "bip01_head", 4)
assert(not drawn(h, "bip01_head") and hidden_list(h) == "")
frames(3)
assert(h._hidden.bip01_head)
-- a cut that isn't a section (the jaw) is hidden as always
local j = body(true, true)
D.apply_local(j, "jaw_1", nil)
assert(j._hidden.jaw_1 and D.shown(j, "jaw_1") == "bones")
CHECK_CUTS("off-shader cuts")
print(("  corpse: off [%s]; arm cut twice: off [%s], caps %d; burst head: off [%s]; set_shader calls %d"):format(off_sections(c),
	off_sections(a), #caps(a), off_sections(h), CUTS_SET_CALLS))
no_errs("off-shader cuts")

------------------------------------------------------------------------
section("Off-shader cuts are kept: someone else resets the shaders, offline / online, load, model change")
LOG = {}
local k = body(true, false)
cut(k, "bip01_l_thigh")
frames(3)
-- another mod resets every shader on the body
k:reset_shader(-1, false)
assert(drawn(k, "bip01_l_thigh") == false, "(the bones hold it meanwhile on a ragdoll)")
run(2600)
assert(CUTS_SHADER(k, KIDS_OF.bip01_l_thigh[1]) == "zgo\\off", "put back within a few seconds")
-- the body goes offline and comes back (a new object: no overrides, no hidden bones)
OBJ[k:id()] = nil
run(2600)
OBJ[k:id()] = k
RESPAWN(k, false)
k._sh_over = {}
k._died_at = T_NOW             -- (its ragdoll is built again a moment later)
run(2600)
print(("  back online: off [%s], hidden [%s]"):format(off_sections(k), hidden_list(k)))
assert(not drawn(k, "bip01_l_thigh") and not drawn(k, "bip01_l_foot"))
CHECK_CUTS("back online")
-- offline and back between two checks, the ragdoll not there yet
RESPAWN(k, false)
k._sh_over = {}
k._died_at = T_NOW + 200
run(2600, 16)
assert(not drawn(k, "bip01_l_thigh"), "the shader comes back first")
run(400)
assert(k._hidden.bip01_l_thigh, "the bones once the ragdoll is there")
CHECK_CUTS("quick offline / online")
-- its model changes (an outfit swap): the overrides went with the old one
k._visual = "actors\\stalker_neutral\\stalker_neutral_2"
run(2600)
k._visual = nil
k._sh_over = {}
RESPAWN(k, false)
run(2600)
assert(not drawn(k, "bip01_l_thigh"), "cut again on the model it wears now")
CHECK_CUTS("model change")
no_errs("kept")

-- save and load
LOG = {}
local m_data = SAVE_GAME()
assert(m_data.zgo_severed[a:id()] and m_data.zgo_severed[k:id()], "saved")
assert(not SAVED_MASK[a:id()].bip01_r_upperarm and not SAVED_MASK[k:id()].bip01_l_thigh,
	"the save stores no hidden part of a baked body (its ragdoll is rebuilt whole)")
assert(a._hidden.bip01_r_upperarm and k._hidden.bip01_l_thigh, "hidden again right after the save")
CB.on_level_changing()
for id in pairs(m_data.zgo_severed) do
	local o = OBJ[id]
	if o then RESPAWN(o) o._sh_over = {} end
end
CB.load_state(m_data)
run(100)
print(("  loaded: arm off [%s], thigh off [%s]"):format(off_sections(a), off_sections(k)))
assert(not drawn(a, "bip01_r_upperarm") and not drawn(k, "bip01_l_thigh") and not drawn(c, "bip01_l_upperarm"))
assert(D.shown(a, "bip01_r_upperarm") == "shader")
CHECK_CUTS("loaded")
no_errs("save / load")

------------------------------------------------------------------------
section("Off-shader cuts fall back to hiding bones when they can't be used")
-- the game wears another model than the bake's (another mod's file wins)
-- (it is cut like an un-baked body: at once, before its ragdoll exists;
-- hidden on the ragdoll its part would stay on screen)
LOG = {}
CUTS_MODELS[SV] = { n = 20 }
B.reset()
local m = body(true, false)
m._wears_unbaked = true
cut(m, "bip01_r_thigh")
assert(D.shown(m, "bip01_r_thigh") == "bones" and overrides(m) == 0, "another model: bones, at once")
frames(3)
assert(m._hidden.bip01_r_thigh)
assert(logged("the game loaded 20 sub-meshes, the bake has 16"), "said once in the log")
local m2 = body(true, true)
m2._wears_unbaked = true
cut(m2, "bip01_l_thigh")
assert(D.shown(m2, "bip01_l_thigh") == nil and not m2._hidden.bip01_l_thigh, "another model's ragdoll: not cut")
OBJ[m2:id()] = nil   -- (gone: the checks below put the baked model back on every body)
CHECK_CUTS("another model")
OBJ[m:id()] = nil   -- (gone: the checks below put the baked model back on every body)
CUTS_MODELS[SV] = select(3, bake())
B.reset()
-- set_shader raises: bones for the rest of the level, nothing left half done
LOG = {}
CUTS_SHADER_ERROR = true
local e = body(true, false)
cut(e, "bip01_l_calf")
assert(overrides(e) == 0 and D.shown(e, "bip01_l_calf") == "waiting")
frames(3)
assert(e._hidden.bip01_l_calf and logged("set_shader failed"))
CUTS_SHADER_ERROR = nil
local e2 = body(true, false)
cut(e2, "bip01_l_calf")
assert(D.shown(e2, "bip01_l_calf") == "waiting", "still bones until the next level")
frames(3)
CHECK_CUTS("set_shader failing")
-- the files: no zgo_off.s, or an engine without the shader functions
CB.on_level_changing()
FS_FILES["$game_shaders$|r3\\zgo_off.s"] = nil
local f1 = body(true, false)
cut(f1, "bip01_r_calf")
assert(D.shown(f1, "bip01_r_calf") == "waiting" and overrides(f1) == 0)
FS_FILES["$game_shaders$|r3\\zgo_off.s"] = true
CB.on_level_changing()
CUTS_NO_SHADER_API = true
local f2 = body(true, false)
CUTS_NO_SHADER_API = nil
cut(f2, "bip01_r_calf")
assert(D.shown(f2, "bip01_r_calf") == "waiting" and f2.set_shader == nil)
frames(3)
CHECK_CUTS("fallbacks")
print("  another model, set_shader failing, no zgo_off.s, no shader API: hidden bones after the ragdoll each time")

------------------------------------------------------------------------
section("Switching the off shader off puts the cuts back on bones")
LOG = {}
local w = body(true, false)
cut(w, "bip01_r_forearm")
assert(D.shown(w, "bip01_r_forearm") == "shader")
OVR["dismember/offshader_cuts"] = nil
frame()
assert(overrides(w) == 0, "its overrides are gone")
run(2600)
assert(D.shown(w, "bip01_r_forearm") == "bones" and not drawn(w, "bip01_r_forearm"))
CHECK_CUTS("option off")
OVR["dismember/offshader_cuts"] = true
run(2600)
assert(not drawn(w, "bip01_r_forearm"))
no_errs("switch")

------------------------------------------------------------------------
section("Kid mode: off-shader cuts are put back, and come back when it is off")
LOG = {}
local kb = body(true, false)
cut(kb, "bip01_l_forearm")
frames(3)
assert(not drawn(kb, "bip01_l_forearm") and #caps(kb) == 1)
OVR["general/kid_mode"] = true
frame()
print(("  kid mode on: off [%s], overrides %d, hidden [%s], caps %d"):format(off_sections(kb), overrides(kb), hidden_list(kb), #caps(kb)))
assert(off_sections(kb) == "" and overrides(kb) == 0 and hidden_list(kb) == "" and atts(kb) == 0, "the body is whole")
local calls = CUTS_SET_CALLS
local kc = body(true, false)
cut(kc, "bip01_r_hand")                -- decided, recorded, not drawn
run(3000)
assert(CUTS_SET_CALLS == calls and off_sections(kb) == "" and off_sections(kc) == "", "nothing cut while kid mode is on")
assert(D.get_state()[kc:id()], "the cut is still recorded")
OVR["general/kid_mode"] = nil
run(2600)
print(("  kid mode off: off [%s] and [%s], caps %d"):format(off_sections(kb), off_sections(kc), #caps(kb)))
assert(not drawn(kb, "bip01_l_forearm") and not drawn(kc, "bip01_r_hand") and #caps(kb) == 1)
CHECK_CUTS("kid mode")
no_errs("kid mode")

------------------------------------------------------------------------
section("Fitted caps: the bake's cap for the cut, every bone following the body")
OVR["dismember/cap_style"] = "fitted"
LOG, CUTS_LOADS = {}, {}
for _, shader in ipairs({ false, true }) do
	OVR["dismember/offshader_cuts"] = shader
	local fb = body(true, true)
	cut(fb, "bip01_r_forearm")
	cut(fb, "bip01_l_thigh")
	cut(fb, "bip01_r_thigh")
	frames(3)
	local list = caps(fb)
	assert(#list == 3 and atts(fb) == 3, "one cap per cut (both thighs hang on the pelvis): " .. #list)
	for _, cc in ipairs(list) do
		local at = fb._att[cc.name]
		assert(cc.kind == "fitted" and cc.model == CAP[cc.cut] and cc.parent == PARENT[cc.cut], cc.cut)
		assert(at.model == CAP[cc.cut] and at.parent_bone == cc.parent and at.type == 1, "world attachment on the parent bone")
		assert(at.pos.x == 0 and at.pos.y == 0 and at.pos.z == 0 and at.rot == nil and at.scale == nil, "in the parent's bind frame, no offset")
		for _, bn in ipairs(BONESET[cc.cut]) do assert(at.cb_names[bn] == bn, "bone " .. bn .. " follows the body") end
		assert(#at.cb_bad == 0, table.concat(at.cb_bad, ", "))
	end
	-- the arm comes off at the shoulder now: the elbow cap goes
	cut(fb, "bip01_r_upperarm")
	frames(3)
	assert(not cap_for(fb, "bip01_r_forearm") and cap_for(fb, "bip01_r_upperarm").kind == "fitted" and atts(fb) == #caps(fb))
	CHECK_CUTS("fitted caps")
	print(("  %s: caps %s"):format(shader and "off shader" or "bones", (function()
		local t = {} for _, cc in ipairs(caps(fb)) do t[#t + 1] = cc.cut .. "=" .. cc.kind end table.sort(t) return table.concat(t, " ") end)()))
end
assert(#CUTS_LOADS >= 7)
for _, l in ipairs(CUTS_LOADS) do assert(l.owner ~= "level", "caps hang on the body") end
-- fixed to the joint
OVR["dismember/cap_style"] = "fitted_rigid"
local rb = body(true, true)
cut(rb, "bip01_l_forearm")
local rc, ra = cap_for(rb, "bip01_l_forearm")
assert(rc.kind == "rigid" and ra.parent_bone == "bip01_l_upperarm" and next(ra.cb_names) == nil, "rigid: on the parent bone only")
no_errs("fitted caps")
-- an engine without bone_callback(name, name): rigid, said once
OVR["dismember/cap_style"] = "fitted"
LOG = {}
zgo_debris.reset()
CUTS_NO_NAMED_CB = true
local nb = body(true, true)
cut(nb, "bip01_r_forearm")
cut(nb, "bip01_l_forearm")
assert(cap_for(nb, "bip01_r_forearm").kind == "rigid" and cap_for(nb, "bip01_l_forearm").kind == "rigid" and atts(nb) == 2)
assert(logged("no bone_callback(bone, bone, true)"))
CUTS_NO_NAMED_CB = nil
-- no cap in the bake for that cut, its file missing, another model: meat
CB.on_level_changing()
install_17({ no_cap = { bip01_r_hand = true } })
FS_FILES["$game_meshes$|" .. CAP.bip01_l_hand .. ".ogf"] = nil
local mb = body(true, true)
cut(mb, "bip01_r_hand")
cut(mb, "bip01_l_hand")
cut(mb, "bip01_head", 4)
assert(cap_for(mb, "bip01_r_hand").kind == "meat" and cap_for(mb, "bip01_l_hand").kind == "meat" and cap_for(mb, "bip01_head").kind == "fitted")
assert(logged(CAP.bip01_l_hand .. ".ogf is missing"))
FS_FILES["$game_meshes$|" .. CAP.bip01_l_hand .. ".ogf"] = true
CUTS_MODELS[SV] = { n = 30 }
B.reset()
local ob = body(true, false)   -- (another model is cut before its ragdoll exists)
ob._wears_unbaked = true
cut(ob, "bip01_r_forearm")
assert(cap_for(ob, "bip01_r_forearm").kind == "meat", "another model: meat")
frames(3)
CHECK_CUTS("another model, meat cap")
OBJ[ob:id()] = nil   -- (gone: the checks below put the baked model back on every body)
CUTS_MODELS[SV] = select(3, bake())
B.reset()
-- caps off, kid mode
OVR["dismember/stump_caps"] = false
local xb = body(true, true)
cut(xb, "bip01_r_forearm")
assert(#caps(xb) == 0 and atts(xb) == 0)
OVR["dismember/stump_caps"] = nil
local yb = body(true, true)
cut(yb, "bip01_r_calf")
assert(cap_for(yb, "bip01_r_calf").kind == "fitted")
OVR["general/kid_mode"] = true
frame()
assert(#caps(yb) == 0 and atts(yb) == 0, "kid mode: no caps")
OVR["general/kid_mode"] = nil
run(2600)
assert(cap_for(yb, "bip01_r_calf").kind == "fitted", "back with kid mode off")
print("  rigid caps, no named callbacks, missing cap / file, another model, caps off and kid mode: as expected")

------------------------------------------------------------------------
section("Caps inside the model (--experimental-caps bake, with the off shader)")
CB.on_level_changing()
install_17({ kcaps = true })
OVR["dismember/cap_style"], OVR["dismember/offshader_cuts"] = "in_model", true
LOG = {}
assert(B.expected_children(SV) == 42)
local ib = body(true, false)
cut(ib, "bip01_r_forearm")
local K = KCAP_OF.bip01_r_forearm
assert(CUTS_SHADER(ib, K[1]) == "models\\model" and CUTS_SHADER(ib, K[2]) == "models\\model", "the wrist... the elbow's cap shows")
assert(ib:get_shaders(false)[K[1]].texture == "food\\food_raw_flesh", "with the baked texture")
assert(#caps(ib) == 0 and atts(ib) == 0, "no attachment")
cut(ib, "bip01_r_upperarm")
local K2 = KCAP_OF.bip01_r_upperarm
assert(CUTS_SHADER(ib, K[1]) == "zgo\\off" and CUTS_SHADER(ib, K2[1]) == "models\\model", "the elbow cap goes with the arm, the shoulder's shows")
frames(3)
ib:reset_shader(-1, false)
run(2600)
assert(CUTS_SHADER(ib, K2[1]) == "models\\model" and CUTS_SHADER(ib, K[1]) == "zgo\\off" and not drawn(ib, "bip01_r_upperarm"), "kept up")
OVR["general/kid_mode"] = true
frame()
assert(CUTS_SHADER(ib, K2[1]) == "zgo\\off" and drawn(ib, "bip01_r_upperarm"), "kid mode: whole, cap hidden")
OVR["general/kid_mode"] = nil
run(2600)
assert(CUTS_SHADER(ib, K2[1]) == "models\\model" and not drawn(ib, "bip01_r_upperarm"))
-- without the off shader: the fitted caps instead
OVR["dismember/offshader_cuts"] = nil
local ub = body(true, true)
cut(ub, "bip01_l_forearm")
assert(cap_for(ub, "bip01_l_forearm").kind == "fitted" and CUTS_SHADER(ub, KCAP_OF.bip01_l_forearm[1]) == "zgo\\off")
CHECK_CUTS("in-model caps")
no_errs("in-model caps")
print("  shown through set_shader, moved up the arm, kept up, hidden in kid mode; fitted caps without the off shader")

------------------------------------------------------------------------
section("Light severed limbs: the bake's piece, posed where the limb was")
CB.on_level_changing()
install_17()
OVR["dismember/cap_style"], OVR["dismember/baked_pieces"] = nil, true
LOG, CUTS_LOADS = {}, {}
local pb = body(true, true)
cut(pb, "bip01_r_hand")
clear_level()
cut(pb, "bip01_r_upperarm")
local L = limbs()
assert(#L == 1 and L[1].model == PIECE.bip01_r_upperarm, "the piece model")
local pa = L[1]
local worst = 0
for id, n in pairs(pa:list_bones()) do
	assert(pa.cbs[id], "every piece bone is posed, bone 0 too: " .. n)
	local mm = pa.cbs[id](matrix())
	local at = VV(pa.pos.x + mm.c.x, pa.pos.y + mm.c.y, pa.pos.z + mm.c.z)
	worst = math.max(worst, at:distance_to(pb:bone_position(n)))
	assert(math.abs(mm.i.x * mm.i.x + mm.i.y * mm.i.y + mm.i.z * mm.i.z - 1) < 1e-6, "not collapsed")
end
print(("  %s: %d bones, worst distance from the body's bone %.6f m; hand hidden on the piece %s"):format(pa.model, #CUTS_ATT_MODELS[pa.model].bones,
	worst, tostring(pa.vis[pa:bone_id("bip01_r_hand")] == false)))
assert(worst < 1e-4, "starts exactly where the limb was")
assert(pa.vis[pa:bone_id("bip01_r_hand")] == false and pa.vis[pa:bone_id("bip01_r_finger0")] == false, "the hand shot off before is missing")
run(2000)
assert(pa.pos.y == pa.pos.y and pa.pos.y < 1.5, "it flew and fell")
-- no piece for that section, the file missing, another model, option off: the whole model
clear_level()
CB.on_level_changing()
install_17({ no_piece = { bip01_l_calf = true } })
FS_FILES["$game_meshes$|" .. PIECE.bip01_l_forearm .. ".ogf"] = nil
local qb = body(true, true)
cut(qb, "bip01_l_calf")
cut(qb, "bip01_l_forearm")
cut(qb, "bip01_head")   -- whole or burst: whichever it is, no error
for _, l in ipairs(limbs()) do
	if l.model ~= PIECE.bip01_head then assert(l.model == SV and l.cbs[0](matrix()).i.x < 0.01, "the whole model, collapsed") end
end
FS_FILES["$game_meshes$|" .. PIECE.bip01_l_forearm .. ".ogf"] = true
CUTS_MODELS[SV] = { n = 21 }
B.reset()
clear_level()
local ab = body(true, false)   -- (another model is cut before its ragdoll exists)
ab._wears_unbaked = true
cut(ab, "bip01_r_forearm")
assert(limbs()[1].model == SV, "another model: the whole model")
OBJ[ab:id()] = nil   -- (gone: the checks below put the baked model back on every body)
CUTS_MODELS[SV] = select(3, bake())
B.reset()
OVR["dismember/baked_pieces"] = nil
clear_level()
cut(body(true, true), "bip01_r_forearm")
assert(limbs()[1].model == SV, "option off: the whole model")
OVR["dismember/baked_pieces"] = true
OVR["dismember/severed_limbs"] = false
clear_level()
cut(body(true, true), "bip01_r_forearm")
assert(#limbs() == 0)
OVR["dismember/severed_limbs"] = nil
CHECK_CUTS("pieces")
no_errs("pieces")

------------------------------------------------------------------------
section("Co-op: host and client")
local ok = true
local wire = os.tmpname()
for _, rr in ipairs({ "host", "client" }) do
	local p = io.popen(('ZGO_CUTS_WIRE="%s" luajit "%s/zgo_test_cuts.lua" %s %d 2>&1'):format(wire, S, rr, seed))
	local out = p:read("*a")
	p:close()
	local last = out:match("([^\n]*)\n?$") or ""
	for l in out:gmatch("[^\n]+") do
		if l:find("luajit:") or l:find("ERR") or l:find("traceback") or l:find("^  ") then print("  [" .. rr .. "] " .. l) end
	end
	print(("  %s: %s"):format(rr, last))
	ok = ok and last:find("OK") ~= nil
end
os.remove(wire)
os.remove(wire .. ".state")
assert(ok, "co-op roles failed")
no_errs("sp")
print("\nALL CUTS TESTS PASSED")

------------------------------------------------------------------------
else
-- co-op roles: the same bodies on both machines (ids 40..), the host cuts,
-- the client replays the host's wire
local WIRE = assert(os.getenv("ZGO_CUTS_WIRE"), "ZGO_CUTS_WIRE")
option_names()
install_17()
OVR["dismember/offshader_cuts"] = true
LOG = {}
local SEC = "sim_default_stalker_1"
local bodies = {}
for i = 40, 44 do bodies[i] = NEW_NPC(i, "stalker", VV(i - 42, 0, -1.5)) kill(bodies[i]) end
frames(3)

if role == "host" then
	section("Host: decides, sends D as it cuts and Q in rounds")
	SENT = {}
	cut(bodies[40], "bip01_r_forearm")
	cut(bodies[40], "bip01_l_thigh")
	cut(bodies[41], "bip01_head", 4)
	cut(bodies[42], "bip01_l_hand")
	frames(2)
	assert(not drawn(bodies[40], "bip01_r_forearm") and not drawn(bodies[41], "bip01_head"))
	-- kid mode on the host: nothing drawn here, the client still gets the cut
	OVR["general/kid_mode"] = true
	frame()
	cut(bodies[43], "bip01_r_calf")
	frames(2)
	assert(drawn(bodies[43], "bip01_r_calf") and overrides(bodies[43]) == 0)
	OVR["general/kid_mode"] = nil
	run(21000, 100)
	D.forget(42)
	frames(2)
	local lines = {}
	for _, msg in ipairs(SENT) do for l in msg:gmatch("[^\n]+") do lines[#lines + 1] = l end end
	local function has(pat) for _, l in ipairs(lines) do if l:find(pat) then return true end end return false end
	local nd, nq = 0, 0
	for _, l in ipairs(lines) do if l:find("^D|") then nd = nd + 1 elseif l:find("^Q|") then nq = nq + 1 end end
	print(("  sent: %d lines, D %d, Q %d"):format(#lines, nd, nq))
	assert(has("^D|40|" .. SEC .. "|bip01_r_forearm|") and has("^D|43|" .. SEC .. "|bip01_r_calf|"), "a D line per cut, kid mode or not")
	assert(has("^Q|40|" .. SEC .. "|bip01_r_forearm,bip01_l_thigh$") and has("^Q|41|" .. SEC .. "|bip01_head$"), "Q rounds: every cut of a body")
	assert(has("^Q|42|" .. SEC .. "|%-$"), "a forgotten body: Q with no cuts")
	for _, l in ipairs(lines) do assert(not l:find("zgo\\", 1, true) and not l:find("cuts-test", 1, true), "no sub-mesh ids or bake ids on the wire: " .. l) end
	-- the host's state as the client should end up with it
	local f = assert(io.open(WIRE, "w"))
	for _, msg in ipairs(SENT) do f:write((msg:gsub("\n", "\t")), "\n") end
	f:close()
	f = assert(io.open(WIRE .. ".state", "w"))
	for id, st in pairs(D.get_state()) do f:write(id, " ", table.concat(st.b, ","), "\n") end
	f:close()
	CHECK_CUTS("host")
	no_errs("host")
	print("\nCUTS HOST OK")
else
	section("Client: replays the host's lines, each machine with its own bake and method")
	for l in io.lines(WIRE) do DISPATCH(zgo_sync.EVT, (l:gsub("\t", "\n")), "host") frames(1) end
	run(600)
	local want = {}
	for l in io.lines(WIRE .. ".state") do
		local id, roots = l:match("^(%d+) (.*)$")
		want[tonumber(id)] = roots
	end
	local st = D.get_state()
	for id, roots in pairs(want) do
		assert(st[id] and table.concat(st[id].b, ",") == roots, ("body %d: host %s, client %s"):format(id, roots, st[id] and table.concat(st[id].b, ",") or "-"))
	end
	assert(not st[42] and drawn(bodies[42], "bip01_l_hand") and overrides(bodies[42]) == 0, "the forgotten body is whole again")
	assert(not drawn(bodies[40], "bip01_r_forearm") and not drawn(bodies[40], "bip01_l_thigh") and not drawn(bodies[41], "bip01_head"))
	assert(not drawn(bodies[43], "bip01_r_calf"), "the cut made in the host's kid mode is drawn here")
	assert(D.shown(bodies[40], "bip01_r_forearm") == "shader")
	print(("  replayed: 40 off [%s], 41 off [%s], 43 off [%s], 42 forgotten"):format(off_sections(bodies[40]), off_sections(bodies[41]), off_sections(bodies[43])))
	CHECK_CUTS("client replay")
	-- a missed D comes in with the next round; a cut the host no longer has goes
	DISPATCH(zgo_sync.EVT, "Q|40|" .. SEC .. "|bip01_r_forearm,bip01_r_thigh", "host")
	run(200)
	assert(not drawn(bodies[40], "bip01_r_thigh") and not drawn(bodies[40], "bip01_r_forearm") and drawn(bodies[40], "bip01_l_thigh"),
		"Q: the thigh the host lacks is back, the missed one is cut: off [" .. off_sections(bodies[40]) .. "]")
	CHECK_CUTS("client Q")
	-- this client draws with bones
	OVR["dismember/offshader_cuts"] = nil
	run(2700)
	assert(overrides(bodies[40]) == 0 and not drawn(bodies[40], "bip01_r_forearm") and bodies[40]._hidden.bip01_r_forearm)
	CHECK_CUTS("client on bones")
	OVR["dismember/offshader_cuts"] = true
	-- kid mode on the client: the host's cut is kept, drawn when it is off
	OVR["general/kid_mode"] = true
	frame()
	DISPATCH(zgo_sync.EVT, "D|44|" .. SEC .. "|bip01_l_forearm|1|1|0|0|1|4242", "host")
	run(300)
	assert(st[44] and drawn(bodies[44], "bip01_l_forearm") and #limbs() == 0, "kid mode: kept, not drawn")
	OVR["general/kid_mode"] = nil
	run(2700)
	assert(not drawn(bodies[44], "bip01_l_forearm"))
	CHECK_CUTS("client kid mode")
	no_errs("client")
	print("\nCUTS CLIENT OK")
end
end
