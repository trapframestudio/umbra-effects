-- Zone Gore Overhaul: the wound shader zgo\dmg (PLAN Phase C, zgo_wounds.script)
--
--   npc:set_shader(D, "zgo\\dmg", "<base>,zgo_dmg_<12 hex>[_<bump>]", false)
--
-- D is a baked damage mesh (bake.py --experimental-damage, docs/formats/
-- damage.md) that zgo_wounds switches on in place of its intact sub-mesh
-- (which goes to zgo\off). The second texture name carries this NPC's wounds
-- for this sub-mesh (every NPC owns its sub-meshes; each distinct string
-- builds its own cached Shader, npc.md C1/C3):
--   12 hex digits = four 3-digit numbers, one active wound each (zgo_dmg.h:
--   site, depth in 2 mm steps, bone flag), bound as four 1x1 "number"
--   textures zgo\wounds\n\<3 hex> to the vertex-shader slots s_zgo_w0..3
--   (the vertex shader has four texture slots, R_Backend.h);
--   then, optionally, "_" and the base texture's bump map: Lua can't ask for
--   it (bump_get), zgo_wounds finds "<base>_bump" and passes it here. Without
--   it the flat pair is used.
-- A string that doesn't parse binds number 000 everywhere: the mesh is drawn
-- undisplaced, like its intact twin.
--
-- Like zgo\probe_dmg (probe 2), only "normal" is defined, so the engine builds
-- E[0] and E[1] from it (dx10ResourceManager_Scripting.cpp:535-583): no
-- parallax, no detail texture, no PN tessellation; l_point is the shadow map.
-- Unverified in the game until probes 1-3 pass (MCM Diagnostics); the runtime
-- only uses it behind the experimental option Wounds -> Wound craters.

local SLOTS = 4

-- "zgo_dmg_<12 hex>[_<bump>]" -> { n1, n2, n3, n4 }, bump or nil
local function parse(t_second)
	local hex, bump = string.match(t_second or "", "^zgo_dmg_(%x%x%x%x%x%x%x%x%x%x%x%x)_?(.*)$")
	local nums = {}
	for i = 1, SLOTS do
		nums[i] = hex and string.sub(hex, i * 3 - 2, i * 3) or "000"
	end
	if bump == "" or bump == "null" then bump = nil end
	return nums, bump
end

local function numbers(shader, nums)
	for i = 1, SLOTS do
		shader:dx10texture("s_zgo_w" .. (i - 1), "zgo\\wounds\\n\\" .. nums[i])
	end
end

local function stencil(shader)
	shader:dx10stencil(true, cmp_func.always, 255, 127, stencil_op.keep, stencil_op.replace, stencil_op.keep)
	shader:dx10stencil_ref(1)
end

function normal(shader, t_base, t_second, t_detail)
	local nums, bump = parse(t_second)
	if bump then
		shader:begin("zgo_dmg_bump", "zgo_dmg_bump")
			:fog(false)
			:zb(true, true)
		shader:dx10texture("s_base", t_base)
		shader:dx10texture("s_bumpX", bump .. "#")
		shader:dx10texture("s_bump", bump)
	else
		shader:begin("zgo_dmg_flat", "zgo_dmg_flat")
			:fog(false)
			:zb(true, true)
		shader:dx10texture("s_base", t_base)
	end
	numbers(shader, nums)
	shader:dx10texture("s_zgo_tissue", "zgo\\wounds\\tissue")
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	stencil(shader)
end

-- E[2]: the shadow map, with the same dents (as CBlender_deffer_model's
-- SE_R2_SHADOW, opaque case)
function l_point(shader, t_base, t_second, t_detail)
	local nums = parse(t_second)
	shader:begin("zgo_dmg_shadow", "dumb")
		:fog(false)
		:zb(true, true)
	shader:dx10texture("s_base", t_base)
	numbers(shader, nums)
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	shader:dx10color_write_enable(false, false, false, false)
end
