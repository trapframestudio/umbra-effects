-- zgo_native: a Lua stand-in for bin/zgo_native.dll (the C ABI in
-- native/include/zgo_native.h) for tests/zgo_test_native.lua, which hands
-- it to zgo_native._test.set_loader. The real DLL is tested on the real
-- engine code under Wine (native/tests). Inert in every other suite: the
-- only thing it adds is the LL_BoneID capture on mock NPCs, and that only
-- acts while a test has set NATIVE_MOCK_LIB.
local ffi = require("ffi")

-- the engine's LL_BoneID hook: obj:get_bone_id("\1zgo:<token>")
NPC_HOOKS[#NPC_HOOKS + 1] = function(o)
	local orig = o.get_bone_id
	function o:get_bone_id(n)
		local lib = rawget(_G, "NATIVE_MOCK_LIB")
		if lib and type(n) == "string" and n:byte(1) == 1 then return lib._capture(self, n) end
		return orig(self, n)
	end
end

-- opts: abi (default 1), unsupported (zgo_init fails), hook_fail (zgo_enable fails)
function NATIVE_MOCK(opts)
	opts = opts or {}
	local L = { calls = {}, log = {}, hooks = 0, init = 1, slots = {}, cap = {}, kin_of = {}, next_kin = 0x10000 }
	local function count(n) L.calls[n] = (L.calls[n] or 0) + 1 end
	local function put(buf, size, s)
		s = s:sub(1, size - 1)
		ffi.copy(buf, s)
		return #s
	end
	L.kin = function(o)
		local k = L.kin_of[o]
		if not k then L.next_kin = L.next_kin + 0x1000 k = L.next_kin L.kin_of[o] = k end
		return k
	end
	-- the engine's model pool handed the object a new model instance
	L.new_model = function(o) L.kin_of[o] = nil end
	L._capture = function(o, n)
		count("capture_call")
		local t = tonumber(n:match("^\1zgo:(%d+)$"))
		if t and L.hooks % 4 >= 2 then
			L.cap[t % 16] = { token = t, kin = L.kin(o), obj = o }
			count("captured")
		end
		return 65535
	end
	-- Depart: the engine released the object's model
	L.depart = function(o)
		local k = L.kin_of[o]
		for _, s in pairs(L.slots) do if s.kin == k then s.dead = true end end
	end
	local function slot_of(h)
		local s = L.slots[h % 256]
		if not s or s.kin == 0 or s.gen ~= math.floor(h / 256) then return nil end
		return s
	end
	L.ops_of = function(o)
		local k = L.kin_of[o]
		for _, s in pairs(L.slots) do if s.kin == k and k then return s.ops, s end end
	end

	function L.zgo_abi() count("abi") return opts.abi or 1 end
	function L.zgo_version() return "zgo_native mock (abi " .. (opts.abi or 1) .. ")" end
	function L.zgo_init()
		count("init")
		if L.init == 1 then
			L.init = opts.unsupported and -1 or 0
			L.log[#L.log + 1] = opts.unsupported and "unsupported exe: mock" or "supported exe (mock)"
		end
		return L.init
	end
	function L.zgo_init_module() return -5 end
	function L.zgo_caps() return L.init == 0 and 3 or 0 end
	function L.zgo_hooks() return L.hooks end
	function L.zgo_enable(caps)
		count("enable")
		L.last_enable = caps
		if L.init == 1 then return -2 end
		if L.init ~= 0 then return -1 end
		if opts.hook_fail and caps % 4 >= 2 then return -6 end
		L.hooks = caps % 4 >= 2 and 2 or 0
		if L.hooks == 0 then for _, s in pairs(L.slots) do s.kin = 0 end end
		L.log[#L.log + 1] = "hooks " .. L.hooks
		return L.hooks + 1
	end
	function L.zgo_shutdown() L.hooks = 0 end
	function L.zgo_status() return L.init == 0 and "supported exe (mock)" or (L.init == 1 and "not initialised" or "unsupported exe: mock") end
	function L.zgo_report(buf, size) return put(buf, size, "zgo_native finder: mock\n  result: " .. (L.init == 0 and "SUPPORTED" or "UNSUPPORTED")) end
	function L.zgo_log_next(buf, size)
		local line = table.remove(L.log, 1)
		if not line then return 0 end
		return put(buf, size, line)
	end
	function L.zgo_get_stats(st)
		local n = 0
		for _, s in pairs(L.slots) do if s.kin ~= 0 and not s.dead then n = n + 1 end end
		st.bound = n
		st.hooks = L.hooks
		st.captures = L.calls.captured or 0
	end
	function L.zgo_capture_take(token)
		local c = L.cap[token % 16]
		if not c or c.token ~= token then return 0 end
		L.cap[token % 16] = nil
		return c.kin
	end
	local function ready()
		if L.init == 1 then return -2 end
		if L.init ~= 0 then return -1 end
		if L.hooks % 4 < 2 then return -7 end
		return 0
	end
	function L.zgo_bones_bind(kin)
		count("bind")
		local r = ready()
		if r ~= 0 then return r end
		kin = tonumber(kin)
		if not kin or kin == 0 then return -5 end
		local idx
		for i = 0, 31 do
			local s = L.slots[i]
			if s and s.kin == kin then
				if not s.dead then return i + s.gen * 256 end
				idx = i
				break
			end
		end
		if not idx then for i = 0, 31 do if not L.slots[i] or L.slots[i].kin == 0 then idx = i break end end end
		if not idx then return -4 end
		local obj
		for o, k in pairs(L.kin_of) do if k == kin then obj = o end end
		local old = L.slots[idx]
		local n = 0
		for _ in pairs(obj and obj:list_bones() or {}) do n = n + 1 end
		L.slots[idx] = { kin = kin, gen = (old and old.gen or 0) + 1, dead = false, ops = {}, stage = nil, count = n }
		return idx + L.slots[idx].gen * 256
	end
	function L.zgo_bones_state(h)
		local s = slot_of(h)
		if not s then return -3 end
		return s.dead and 0 or 1
	end
	function L.zgo_bones_begin(h)
		local r = ready()
		if r ~= 0 then return r end
		local s = slot_of(h)
		if not s then return -3 end
		if s.dead then return -8 end
		s.stage = {}
		return 0
	end
	function L.zgo_bones_group(h, driver, l12, members, n)
		local r = ready()
		if r ~= 0 then return r end
		local s = slot_of(h)
		if not s then return -3 end
		if not s.stage then return -5 end
		if #s.stage >= 12 then return -4 end
		if driver >= s.count then return -5 end
		local g = { driver = driver, l = {}, members = {} }
		for i = 0, 11 do
			local v = l12[i]
			if v ~= v or math.abs(v) > 1e5 then return -5 end
			g.l[i + 1] = v
		end
		for i = 0, n - 1 do
			if members[i] >= s.count then return -5 end
			g.members[#g.members + 1] = members[i]
		end
		s.stage[#s.stage + 1] = g
		return #s.stage
	end
	function L.zgo_bones_commit(h)
		local r = ready()
		if r ~= 0 then return r end
		local s = slot_of(h)
		if not s then return -3 end
		if not s.stage then return -5 end
		s.ops, s.stage = s.stage, nil
		count("commit")
		return s.dead and -8 or 0
	end
	function L.zgo_bones_unbind(h)
		local s = slot_of(h)
		if not s then return -3 end
		s.kin, s.dead, s.stage = 0, false, nil
		count("unbind")
		return 0
	end
	function L.zgo_bones_clear_all()
		count("clear_all")
		for _, s in pairs(L.slots) do s.kin, s.dead, s.stage = 0, false, nil end
	end
	return L
end
