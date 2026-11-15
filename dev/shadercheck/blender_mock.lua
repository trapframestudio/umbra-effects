-- Offline stand-in for the engine's shader-script VM (Lua .s files), after
-- xray-monolith b86d733f4a src/Layers/xrRenderDX10/dx10ResourceManager_Scripting.cpp
-- and the CBlender_Compile pass setters they call (Blender_Recorder*.cpp).
--
-- In the game every r3\*.s file is loaded at start-up into one Lua state
-- (base, table, string, math, jit + luabind; no io, no os), each into a global
-- table named after the file. A particle or model asking for shader "a\b"
-- uses the .s whose name is "a_b" when it has a normal() or l_special()
-- function; normal() builds elements 0 and 1, l_point 2, l_spot 3, l_special 4.
-- A Lua or luabind error while doing so is fatal (LuaError -> Debug.fatal),
-- so this mock is strict about argument counts and types, like luabind's
-- overload matching.
--
--   local M = dofile("dev/shadercheck/blender_mock.lua")
--   local s, err = M.load_file("gamedata/shaders/r3/zgo_particle_blend.s")
--   local el, err = M.element(s, "normal", "fx\\fx_blood", "null", "null")
--
-- luajit dev/shadercheck/blender_mock.lua <file.s> [t_base]  prints every element.
local M = {}

-- d3d9types.h values, as the engine's enums expose them
M.BLEND = { zero = 1, one = 2, srccolor = 3, invsrccolor = 4, srcalpha = 5, invsrcalpha = 6, destalpha = 7,
	invdestalpha = 8, destcolor = 9, invdestcolor = 10, srcalphasat = 11 }
M.CMP = { never = 1, less = 2, equal = 3, lessequal = 4, greater = 5, notequal = 6, greaterequal = 7, always = 8 }
M.STENCIL = { keep = 1, zero = 2, replace = 3, incrsat = 4, decrsat = 5, invert = 6, incr = 7, decr = 8 }
M.BLEND_NAME, M.CMP_NAME = {}, {}
for k, v in pairs(M.BLEND) do M.BLEND_NAME[v] = k end
for k, v in pairs(M.CMP) do M.CMP_NAME[v] = k end

M.ELEMENTS = { "normal_hq", "normal", "l_point", "l_spot", "l_special" }

local function argerr(fn, i, want, got)
	error(string.format("luabind: no match for %s: argument %d must be %s, got %s", fn, i, want, got), 3)
end

-- luabind matches bool only on booleans, numbers only on numbers, strings only on strings
local function check(fn, args, types)
	if #types ~= args.n then
		error(string.format("luabind: no match for %s: %d arguments, expected %d", fn, args.n, #types), 3)
	end
	for i, t in ipairs(types) do
		local v = args[i]
		local lt = type(v)
		if t == "bool" and lt ~= "boolean" then argerr(fn, i, "a boolean", lt) end
		if t == "num" and lt ~= "number" then argerr(fn, i, "a number", lt) end
		if t == "str" and lt ~= "string" then argerr(fn, i, "a string", lt) end
	end
end

local function pack(...) return { n = select("#", ...), ... } end

-- a fresh pass, as CBlender_Compile::r_Pass(vs, ps, bFog = true) leaves it
local function new_pass(vs, gs, ps, index)
	return {
		vs = vs, gs = gs or "null", ps = ps,
		fog = true, ztest = true, zfunc = "lessequal", zwrite = index == 1, ablend = false,
		src = "one", dst = "zero", atest = false, aref = nil,
		colorwrite = nil, stencil = nil, stencil_ref = nil, cull = nil, atoc = nil,
		textures = {}, samplers = {},
	}
end

function M.new_compiler(opts)
	opts = opts or {}
	local el = { priority = 1, strict = false, emissive = false, distort = false, wmark = false, scopelense = 0,
		passes = {}, log = {} }
	local C = {}
	local mt = { __index = C, __tostring = function() return "_compiler" end }
	local self = setmetatable({}, mt)
	local function cur(fn)
		local p = el.passes[#el.passes]
		if not p then error("engine: " .. fn .. " before begin(): no pass to set up (would write into garbage)", 3) end
		return p
	end
	local function me(fn, s)
		if getmetatable(s) ~= mt then error("luabind: " .. fn .. " must be called with ':' on the compiler", 3) end
	end
	function C.begin(s, ...)
		me("begin", s)
		local a = pack(...)
		if a.n == 2 then check("begin(vs, ps)", a, { "str", "str" })
			el.passes[#el.passes + 1] = new_pass(a[1]:lower(), nil, a[2]:lower(), #el.passes + 1)
		elseif a.n == 3 then check("begin(vs, gs, ps)", a, { "str", "str", "str" })
			el.passes[#el.passes + 1] = new_pass(a[1]:lower(), a[2]:lower(), a[3]:lower(), #el.passes + 1)
		else
			error("luabind: no match for begin: " .. a.n .. " arguments", 2)
		end
		return s
	end
	function C.sorting(s, ...) me("sorting", s) local a = pack(...) check("sorting", a, { "num", "bool" })
		el.priority, el.strict = a[1], a[2]
		if a[2] and math.floor(a[1] / 2) ~= 1 then
			el.log[#el.log + 1] = "VERIFY: strict sorting needs priority 2 or 3 (debug builds assert)"
		end
		return s end
	function C.emissive(s, ...) me("emissive", s) local a = pack(...) check("emissive", a, { "bool" }) el.emissive = a[1] return s end
	function C.distort(s, ...) me("distort", s) local a = pack(...) check("distort", a, { "bool" }) el.distort = a[1] return s end
	function C.wmark(s, ...) me("wmark", s) local a = pack(...) check("wmark", a, { "bool" }) el.wmark = a[1] return s end
	function C.scopelense(s, ...) me("scopelense", s) local a = pack(...) check("scopelense", a, { "num" }) el.scopelense = a[1] return s end
	function C.fog(s, ...) me("fog", s) local a = pack(...) check("fog", a, { "bool" }) cur("fog").fog = a[1] return s end
	function C.zb(s, ...) me("zb", s) local a = pack(...) check("zb", a, { "bool", "bool" })
		local p = cur("zb")
		p.ztest, p.zfunc = a[1], a[1] and "lessequal" or "always"
		p.zwrite = a[2] and #el.passes == 1          -- PassSET_ZB: only the first pass writes Z
		return s end
	function C.blend(s, ...) me("blend", s) local a = pack(...) check("blend", a, { "bool", "num", "num" })
		local p = cur("blend")
		local on, src, dst = a[1], a[2], a[3]
		if on and src == M.BLEND.one and dst == M.BLEND.zero then on = false end   -- PassSET_ablend_mode
		if on and not (M.BLEND_NAME[src] and M.BLEND_NAME[dst]) then
			error("engine: blend factor out of range: " .. tostring(src) .. ", " .. tostring(dst), 2)
		end
		p.ablend = on
		p.src = on and M.BLEND_NAME[src] or "one"
		p.dst = on and M.BLEND_NAME[dst] or "zero"
		return s end
	function C.aref(s, ...) me("aref", s) local a = pack(...) check("aref", a, { "bool", "num" })
		local p = cur("aref")
		p.atest = a[1]
		if a[1] then p.aref = math.max(0, math.min(255, a[2])) end
		return s end
	local function cwe(s, ...) local a = pack(...) check("color_write_enable", a, { "bool", "bool", "bool", "bool" })
		cur("color_write_enable").colorwrite = { a[1], a[2], a[3], a[4] } return s end
	function C.color_write_enable(s, ...) me("color_write_enable", s) return cwe(s, ...) end
	function C.dx10color_write_enable(s, ...) me("dx10color_write_enable", s) return cwe(s, ...) end
	function C.dx10texture(s, ...) me("dx10texture", s) local a = pack(...) check("dx10texture", a, { "str", "str" })
		local p = cur("dx10texture")
		p.textures[#p.textures + 1] = { a[1], a[2]:lower() }
		return s end
	function C.dx10stencil(s, ...) me("dx10stencil", s) local a = pack(...)
		check("dx10stencil", a, { "bool", "num", "num", "num", "num", "num", "num" })
		cur("dx10stencil").stencil = { a[1], a[2], a[3], a[4], a[5], a[6], a[7] } return s end
	function C.dx10stencil_ref(s, ...) me("dx10stencil_ref", s) local a = pack(...) check("dx10stencil_ref", a, { "num" })
		cur("dx10stencil_ref").stencil_ref = a[1] return s end
	function C.dx10cullmode(s, ...) me("dx10cullmode", s) local a = pack(...) check("dx10cullmode", a, { "num" })
		cur("dx10cullmode").cull = a[1] return s end
	function C.dx10atoc(s, ...) me("dx10atoc", s) local a = pack(...) check("dx10atoc", a, { "bool" })
		cur("dx10atoc").atoc = a[1] return s end
	function C.dx10zfunc(s, ...) me("dx10zfunc", s) local a = pack(...) check("dx10zfunc", a, { "num" })
		local p = cur("dx10zfunc") p.zfunc = M.CMP_NAME[a[1]] or tostring(a[1]) return s end
	function C.dx10sampler(s, ...) me("dx10sampler", s) local a = pack(...) check("dx10sampler", a, { "str" })
		local p = cur("dx10sampler")
		local rec = { a[1], false }
		p.samplers[#p.samplers + 1] = rec
		local smt = {}
		smt.__index = { clamp = function(ss, ...)
			if getmetatable(ss) ~= smt then error("luabind: clamp must be called with ':'", 2) end
			check("clamp", pack(...), {})
			rec[2] = true
			return ss
		end }
		return setmetatable({}, smt) end
	function C.dx10Options(s, ...) me("dx10Options", s) check("dx10Options", pack(...), {})
		return {
			dx10_msaa_alphatest_atoc = function(o) return opts.atoc and true or false end,
			getLevel = function(o)
				el.log[#el.log + 1] = "getLevel(): needs a loaded level (g_pGameLevel), crashes in the main menu"
				return opts.level or "l01_escape"
			end,
		}
	end
	return self, el
end

-- the shader VM's globals: base, table, string, math, jit, luabind enums, log()
function M.new_globals(logbuf)
	local g = {}
	for _, k in ipairs({ "assert", "error", "ipairs", "next", "pairs", "pcall", "print", "rawequal", "rawget",
		"rawset", "select", "setmetatable", "getmetatable", "tonumber", "tostring", "type", "unpack", "xpcall",
		"_VERSION", "loadstring", "setfenv", "getfenv" }) do
		g[k] = _G[k]
	end
	g.table, g.string, g.math, g.jit = table, string, math, jit
	g.blend, g.cmp_func, g.stencil_op = {}, {}, {}
	for k, v in pairs(M.BLEND) do g.blend[k] = v end
	for k, v in pairs(M.CMP) do g.cmp_func[k] = v end
	for k, v in pairs(M.STENCIL) do g.stencil_op[k] = v end
	g.log = function(...) local a = pack(...) check("log", a, { "str" }) logbuf[#logbuf + 1] = a[1] end
	g._G = g
	return g
end

-- load one .s file into its namespace, as Script::bfLoadFileIntoNamespace does
function M.load_file(path, globals)
	local f, err = io.open(path, "rb")
	if not f then return nil, err end
	local src = f:read("*a")
	f:close()
	local name = path:match("([^/\\]+)%.s$") or path
	local logbuf = {}
	globals = globals or M.new_globals(logbuf)
	local chunk, perr = loadstring(src, "@" .. path)
	if not chunk then return nil, perr end
	local ns = setmetatable({}, { __index = globals })
	setfenv(chunk, ns)
	local ok, rerr = pcall(chunk)
	if not ok then return nil, rerr end
	rawset(globals, name, ns)
	return { name = name:lower(), ns = ns, globals = globals, log = logbuf, path = path }
end

-- _lua_HasShader: the shader name ("zgo\\particle_blend") with '\' -> '_'
function M.lua_name(shader_name)
	return (shader_name:gsub("\\", "_"))
end

function M.has_shader(s)
	return type(rawget(s.ns, "normal")) == "function" or type(rawget(s.ns, "l_special")) == "function"
end

-- compile one element function, as CBlender_Compile::_lua_Compile
function M.element(s, fname, t_base, t_second, t_detail, opts)
	local fn = rawget(s.ns, fname)
	if type(fn) ~= "function" then return nil, "no function " .. fname end
	local comp, el = M.new_compiler(opts)
	local ok, err = pcall(fn, comp, t_base or "null", t_second or "null", t_detail or "null")
	if not ok then return nil, err end
	if #el.passes == 0 then el.empty = true end    -- _CreateElement returns 0: no element
	return el
end

-- every element the engine would build: { [0] = el, [1] = el, [2] = ..., [4] = ... }
function M.shader(s, t_base, t_second, opts)
	local out, errs = {}, {}
	local function try(idx, fname)
		local el, err = M.element(s, fname, t_base, t_second, "null", opts)
		if el then out[idx] = el elseif err and not err:match("^no function") then errs[#errs + 1] = fname .. ": " .. err end
	end
	if rawget(s.ns, "normal_hq") then try(0, "normal_hq") else try(0, "normal") end
	try(1, "normal")
	try(2, "l_point")
	try(3, "l_spot")
	try(4, "l_special")
	return out, (#errs > 0) and table.concat(errs, "; ") or nil
end

-- one line per pass, stable, for diffs and for the Python side
function M.describe(el)
	local lines = {}
	lines[#lines + 1] = string.format("element priority=%d strict=%s emissive=%s distort=%s wmark=%s",
		el.priority, tostring(el.strict), tostring(el.emissive), tostring(el.distort), tostring(el.wmark))
	for i, p in ipairs(el.passes) do
		local tx, sm = {}, {}
		for _, t in ipairs(p.textures) do tx[#tx + 1] = t[1] .. "=" .. t[2] end
		for _, x in ipairs(p.samplers) do sm[#sm + 1] = x[1] .. (x[2] and "(clamp)" or "") end
		lines[#lines + 1] = string.format(
			"pass %d vs=%s gs=%s ps=%s fog=%s ztest=%s zfunc=%s zwrite=%s ablend=%s src=%s dst=%s atest=%s aref=%s"
			.. " colorwrite=%s textures=%s samplers=%s",
			i, p.vs, p.gs, p.ps, tostring(p.fog), tostring(p.ztest), p.zfunc, tostring(p.zwrite), tostring(p.ablend),
			p.src, p.dst, tostring(p.atest), tostring(p.aref),
			p.colorwrite and table.concat({ tostring(p.colorwrite[1]), tostring(p.colorwrite[2]),
				tostring(p.colorwrite[3]), tostring(p.colorwrite[4]) }, ",") or "default",
			table.concat(tx, ","), table.concat(sm, ","))
	end
	for _, l in ipairs(el.log) do lines[#lines + 1] = "note " .. l end
	return lines
end

-- command line: print every element of a .s file
if arg and arg[0] and arg[0]:match("blender_mock%.lua$") and arg[1] then
	local s, err = M.load_file(arg[1])
	if not s then
		print("ERROR load " .. tostring(err))
		os.exit(1)
	end
	print("shader " .. s.name .. " has_shader=" .. tostring(M.has_shader(s)))
	local els, eerr = M.shader(s, arg[2] or "pfx\\pfx_blood", arg[3] or "null")
	if eerr then
		print("ERROR " .. eerr)
		os.exit(1)
	end
	for idx = 0, 5 do
		local el = els[idx]
		if el and not el.empty then
			print("E" .. idx)
			for _, l in ipairs(M.describe(el)) do print("  " .. l) end
		end
	end
	for _, l in ipairs(s.log) do print("log " .. l) end
	os.exit(0)
end

return M
