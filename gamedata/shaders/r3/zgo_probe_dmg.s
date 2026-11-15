-- Umbra Gore & Effects: probe 2, the pass-through "damage" shader
-- (set_shader(child, "zgo\\probe_dmg", "<base>[,<bump>]") from zgo_probe)
--
-- The shape Phase C's zgo_dmg will take, doing nothing yet: the stock skinned
-- model shader rebuilt from Lua, with ZGO's own vertex shaders that wrap the
-- stock ones (whichever mod's copy wins: SSS, Atmospherics...). A body drawn
-- with it must look exactly as before, in every weight format (1W-4W and
-- RM_SINGLE), in the shadow map and under TAA.
--
-- Differences from the C++ model blender (CBlender_deffer_model), on purpose:
--   * Lua can't ask for a texture's bump map (bump_get), so zgo_probe passes
--     it as the second texture ("<base>_bump", when that file exists);
--     without one the flat pair is used.
--   * Only "normal" is defined, so the engine builds E[0] (high quality) and
--     E[1] from it (dx10ResourceManager_Scripting.cpp:535-583): no parallax
--     (the stock "-hq" variant), no detail texture, no PN tessellation.
--   * Alpha-tested materials (models\model_aref) are left alone by the probe.

local function stencil(shader)
	shader:dx10stencil(true, cmp_func.always, 255, 127, stencil_op.keep, stencil_op.replace, stencil_op.keep)
	shader:dx10stencil_ref(1)
end

local function has_bump(t_second)
	return t_second ~= nil and t_second ~= "" and t_second ~= "null"
end

local function deferred(shader, t_base, t_second)
	if has_bump(t_second) then
		shader:begin("zgo_probe_dmg_bump", "deffer_base_bump")
			:fog(false)
			:zb(true, true)
		shader:dx10texture("s_base", t_base)
		shader:dx10texture("s_bumpX", t_second .. "#")
		shader:dx10texture("s_bump", t_second)
	else
		shader:begin("zgo_probe_dmg_flat", "deffer_base_flat")
			:fog(false)
			:zb(true, true)
		shader:dx10texture("s_base", t_base)
	end
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	stencil(shader)
end

function normal(shader, t_base, t_second, t_detail)
	deferred(shader, t_base, t_second)
end

-- E[2]: the shadow map (as CBlender_deffer_model's SE_R2_SHADOW, opaque case)
function l_point(shader, t_base, t_second, t_detail)
	shader:begin("zgo_probe_dmg_shadow", "dumb")
		:fog(false)
		:zb(true, true)
	shader:dx10texture("s_base", t_base)
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	shader:dx10color_write_enable(false, false, false, false)
end
