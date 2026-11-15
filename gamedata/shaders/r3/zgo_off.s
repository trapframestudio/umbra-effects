-- Zone Gore Overhaul: the "off" shader (set_shader(child, "zgo\\off", ...))
--
-- A sub-mesh drawn with this shader is skipped by every pass of the renderer:
-- (line numbers: xray-monolith b86d733f4a, src/Layers/xrRender*)
--   * CResourceManager::_lua_HasShader accepts a .s that defines only
--     l_special (dx10ResourceManager_Scripting.cpp:499-512), so the name
--     resolves here and never falls back to stub_default (which would draw).
--   * _lua_Create compiles only the elements a .s defines (:514-616): E[0]
--     (deferred HQ), E[1] (deferred LQ), E[2] (shadow map, l_point) and E[3]
--     stay null; E[4] is this l_special.
--   * r_dsgraph_insert_dynamic picks E[0] / E[1] in the normal phase and E[2]
--     in the shadow phase (CRender::rimp_select_sh_dynamic, r4.cpp:71-79) and
--     returns at once on a null element (r__dsgraph_build.cpp:69-70): no
--     G-buffer, no shadow, no forward, no HUD pass.
--   * Before that return E[4] is only queued for the distortion pass, and only
--     with the distort flag (r__dsgraph_build.cpp:56-66); its other uses
--     (emissive, :132-216) sit behind the null return. This element sets
--     neither flag, so it is never drawn either.
--   * Skeleton wallmarks, picking and physics read the vertex data, not the
--     shader, so they keep working (a decal still lands on a hidden part).
--
-- The pass below is still a complete, harmless pass in case some path we
-- haven't read does draw E[4]: the stock skinned shadow-map pair every model
-- already compiles (same name and skinning, so it comes from the shader
-- cache), colour writes off and a depth test that never passes.
--
-- Unverified in the game until probe 1 (zgo_probe, MCM Diagnostics) passes.

function l_special(shader, t_base, t_second, t_detail)
	shader:begin("shadow_direct_model", "dumb")
		:fog(false)
		:zb(true, false)
	shader:dx10color_write_enable(false, false, false, false)
	shader:dx10zfunc(cmp_func.never)
end
