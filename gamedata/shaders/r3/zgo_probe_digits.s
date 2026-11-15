-- Umbra Gore & Effects: probe 3, per-NPC numbers through "digit" textures
-- (set_shader(child, "zgo\\probe_digits", "<base>,zgo_dg_<10 hex digits>") from zgo_probe)
--
-- The second texture string is per NPC (each NPC owns its sub-meshes; every
-- distinct string builds its own cached Shader). This file parses it and binds
-- one 1x1 single-mip texture per digit (zgo\probe\d00..d15: red = digit / 15),
-- four to vertex-shader slots and six to pixel-shader slots, which the
-- shaders read with Load (zgo_probe_digits.vs / .ps). Phase C sends wound
-- stages this way.
--
-- A string that doesn't parse binds d00 everywhere: the vertex check then
-- fails on purpose (the part vanishes), so a broken hand-over is visible.

local VS_SLOTS, PS_SLOTS = 4, 6

local function digits(code)
	local hex = string.match(code or "", "zgo_dg_(%x+)$")
	local out = {}
	for i = 1, VS_SLOTS + PS_SLOTS do
		local ch = hex and string.sub(hex, i, i) or ""
		out[i] = tonumber(ch, 16) or 0
	end
	return out
end

local function digit_texture(d)
	return string.format("zgo\\probe\\d%02d", d)
end

function normal(shader, t_base, t_second, t_detail)
	local d = digits(t_second)
	shader:begin("zgo_probe_digits", "zgo_probe_digits")
		:fog(false)
		:zb(true, true)
	shader:dx10texture("s_base", t_base)
	for i = 0, VS_SLOTS - 1 do
		shader:dx10texture("s_zgo_v" .. i, digit_texture(d[i + 1]))
	end
	for i = 0, PS_SLOTS - 1 do
		shader:dx10texture("s_zgo_p" .. i, digit_texture(d[VS_SLOTS + i + 1]))
	end
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	shader:dx10stencil(true, cmp_func.always, 255, 127, stencil_op.keep, stencil_op.replace, stencil_op.keep)
	shader:dx10stencil_ref(1)
end

-- E[2]: the stock shadow-map pass, so the part keeps its shadow whatever the
-- digit check above does
function l_point(shader, t_base, t_second, t_detail)
	shader:begin("shadow_direct_model", "dumb")
		:fog(false)
		:zb(true, true)
	shader:dx10texture("s_base", t_base)
	shader:dx10sampler("smp_base")
	shader:dx10sampler("smp_linear")
	shader:dx10color_write_enable(false, false, false, false)
end
