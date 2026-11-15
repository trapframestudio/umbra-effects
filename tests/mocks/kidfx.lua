-- kidfx (kid mode for particles): what the GPU draws of a particle effect.
--
-- Reads effects the way the engine does ($game_particles$: loose .pe / .pg
-- files in gamedata/particles; a group's effects and every on_*_child are
-- played too) and models the zgo_particle_kid*.ps discard: a sprite whose
-- [sprite] shader is zgo\particle_* draws nothing while the shader bus lane
-- zgo_view has x > 0.5 and w = 1. Every other sprite draws as it always did.
-- Pure helpers: nothing here changes how the other suites run.
KIDFX = {}
local here = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
KIDFX.GAMEDATA = here .. "/../../gamedata"
KIDFX.PART = KIDFX.GAMEDATA .. "/particles"
KIDFX.MAP = { ["particles\\blend"] = "zgo\\particle_blend", ["particles\\add"] = "zgo\\particle_add",
	["particles\\alpha_add"] = "zgo\\particle_aadd", ["particles\\set"] = "zgo\\particle_set" }
KIDFX.REVERSE = {}
for k, v in pairs(KIDFX.MAP) do KIDFX.REVERSE[v] = k end
-- textures that draw nothing (one transparent texel): carriers for child effects
KIDFX.CARRIER = { ["srbd\\srbd-finger-tracer"] = true }

function KIDFX.read(path)
	local f = io.open(path, "rb")
	if not f then return nil end
	local s = f:read("*a")
	f:close()
	return s
end

-- [sprite] shader / texture, and where the shader value sits in the file
function KIDFX.sprite(data)
	local s, e = data:find("\n[ \t]*%[sprite%][^\n]*\n")
	if not s then
		s, e = data:find("^[ \t]*%[sprite%][^\n]*\n")
		if not s then return nil end
	end
	local body_end = data:find("\n[ \t]*%[", e) or #data
	local body = data:sub(e + 1, body_end)
	local shader, texture
	local vs, ve
	for line_start, line in body:gmatch("()([^\n]*)") do
		local key, val = line:match("^[ \t]*(%w+)[ \t]*=[ \t]*([^\r]-)[ \t]*\r?$")
		if key and key:lower() == "shader" and not shader then
			shader = val
			local off = line:find("=[ \t]*") + #line:match("=[ \t]*") - 1
			vs = e + line_start + off
			ve = vs + #val - 1
		elseif key and key:lower() == "texture" and not texture then
			texture = val
		end
	end
	return shader, texture, vs, ve
end

-- the file with the stock shader line (what the snapshot hashes)
function KIDFX.normalized(data)
	local shader, _, vs, ve = KIDFX.sprite(data)
	if shader and KIDFX.REVERSE[shader:lower()] then
		return data:sub(1, vs - 1) .. KIDFX.REVERSE[shader:lower()] .. data:sub(ve + 1)
	end
	return data
end

function KIDFX.children(data)
	local out = {}
	for line in data:gmatch("[^\n]+") do
		local key, val = line:match("^[ \t]*([%w_]+)[ \t]*=[ \t]*([^%s;]+)")
		if key and (key:lower() == "effect_name" or key:lower():match("^on_%w+_child$")) then out[#out + 1] = val end
	end
	return out
end

-- name: "srbd\\srbd_hit_flesh_00" -> { kind, path, data, shader, texture, children }
function KIDFX.effect(name)
	local base = KIDFX.PART .. "/" .. name:gsub("\\", "/"):lower()
	for _, ext in ipairs({ "pe", "pg" }) do
		local data = KIDFX.read(base .. "." .. ext)
		if data then
			local e = { kind = ext, path = base .. "." .. ext, data = data, children = KIDFX.children(data) }
			if ext == "pe" then e.shader, e.texture = KIDFX.sprite(data) end
			return e
		end
	end
	return nil
end

-- what the pixel shader does with the lane (x, y, z, w)
function KIDFX.hidden(shader, lane)
	if not (shader and shader:lower():match("^zgo\\particle_")) then return false end
	lane = lane or { 0, 0, 0, 0 }
	return lane[1] > 0.5 and math.abs(lane[4] - 1) < 0.001
end

-- every sprite (.pe) an effect draws, children included: { name, shader, texture, carrier }
function KIDFX.sprites(name, out, seen)
	out, seen = out or {}, seen or {}
	local key = name:lower()
	if seen[key] then return out end
	seen[key] = true
	local e = KIDFX.effect(name)
	if not e then
		out[#out + 1] = { name = name, missing = true }
		return out
	end
	if e.kind == "pe" then
		out[#out + 1] = { name = name, shader = e.shader, texture = e.texture,
			carrier = e.texture and KIDFX.CARRIER[e.texture:lower()] or false }
	end
	for _, c in ipairs(e.children) do KIDFX.sprites(c, out, seen) end
	return out
end

-- every .pe / .pg under gamedata/particles: { rel = "srbd/x.pe", path = ... }
function KIDFX.files()
	local out = {}
	local p = io.popen('cd "' .. KIDFX.PART .. '" && find . -type f \\( -iname "*.pe" -o -iname "*.pg" \\) | sort')
	for l in p:lines() do out[#out + 1] = { rel = l:gsub("^%./", ""), path = KIDFX.PART .. "/" .. l:gsub("^%./", "") } end
	p:close()
	return out
end

-- SHA-1 (hex), LuaJIT bit ops
local bit = require("bit")
local band, bor, bxor, bnot, rol, tobit = bit.band, bit.bor, bit.bxor, bit.bnot, bit.rol, bit.tobit
local function be32(s, i)
	local a, b, c, d = s:byte(i, i + 3)
	return tobit(a * 16777216 + b * 65536 + c * 256 + d)
end
function KIDFX.sha1(msg)
	local h0, h1, h2, h3, h4 = tobit(0x67452301), tobit(0xEFCDAB89), tobit(0x98BADCFE), tobit(0x10325476), tobit(0xC3D2E1F0)
	local ml = #msg * 8
	msg = msg .. "\128" .. string.rep("\0", (55 - #msg) % 64)
	local hi = math.floor(ml / 4294967296)
	local lo = ml % 4294967296
	msg = msg .. string.char(math.floor(hi / 16777216) % 256, math.floor(hi / 65536) % 256, math.floor(hi / 256) % 256, hi % 256,
		math.floor(lo / 16777216) % 256, math.floor(lo / 65536) % 256, math.floor(lo / 256) % 256, lo % 256)
	local w = {}
	for chunk = 1, #msg, 64 do
		for i = 0, 15 do w[i] = be32(msg, chunk + i * 4) end
		for i = 16, 79 do w[i] = rol(bxor(w[i - 3], w[i - 8], w[i - 14], w[i - 16]), 1) end
		local a, b, c, d, e = h0, h1, h2, h3, h4
		for i = 0, 79 do
			local f, k
			if i < 20 then f, k = bor(band(b, c), band(bnot(b), d)), 0x5A827999
			elseif i < 40 then f, k = bxor(b, c, d), 0x6ED9EBA1
			elseif i < 60 then f, k = bor(band(b, c), band(b, d), band(c, d)), 0x8F1BBCDC
			else f, k = bxor(b, c, d), 0xCA62C1D6 end
			local t = tobit(rol(a, 5) + f + e + k + w[i])
			e, d, c, b, a = d, c, rol(b, 30), a, t
		end
		h0, h1, h2, h3, h4 = tobit(h0 + a), tobit(h1 + b), tobit(h2 + c), tobit(h3 + d), tobit(h4 + e)
	end
	return bit.tohex(h0) .. bit.tohex(h1) .. bit.tohex(h2) .. bit.tohex(h3) .. bit.tohex(h4)
end
