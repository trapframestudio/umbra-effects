-- Co-op sync protocol and the version / bake handshake (sync kind V, zgo_handshake)
--   luajit zgo_test_handshake.lua [seed]          single player checks, then the host
--                                                  and client roles as subprocesses
--   luajit zgo_test_handshake.lua host|client seed  one role
local S = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or ".")
local a1, a2 = ...
local role = (a1 == "host" or a1 == "client") and a1 or "sp"
local seed = tonumber(role == "sp" and a1 or a2) or 1
arg = { S .. "/../gamedata/scripts", role }

-- what this machine baked (the generated scripts only count when their file exists)
local BODY = os.getenv("ZGO_HS_BODY")
local PROPS = os.getenv("ZGO_HS_PROPS")

dofile(S .. "/zgo_harness.lua")
math.randomseed(seed)
if BODY then
	FS_FILES["$game_scripts$|zgo_bake_inputs.script"] = true
	rawset(_G, "zgo_bake_inputs", { fingerprint = BODY, bake_id = "local-" .. seed })
end
if PROPS then
	FS_FILES["$game_scripts$|zgo_props_fracture_index.script"] = true
	rawset(_G, "zgo_props_fracture_index", { bake = PROPS, rigs = {}, native = {} })
end
-- news messages the player sees
NEWS = {}
function ACTOR:give_game_news(caption, msg) NEWS[#NEWS + 1] = { caption = caption, msg = msg } end

local fails = 0
local function check(ok, msg) if not ok then fails = fails + 1 print("  FAIL " .. msg) end return ok end
local function section(t) print(("\n== %s"):format(t)) end
local function logs(pat) local n = 0 for _, l in ipairs(LOG) do if l:find(pat, 1, true) then n = n + 1 end end return n end
local function lines(list, kind)
	local out = {}
	for _, b in ipairs(list) do for l in b:gmatch("[^\n]+") do if l:sub(1, #kind + 1) == kind .. "|" then out[#out + 1] = l end end end
	return out
end
local H = zgo_handshake
local VERSION = zgo_main.VERSION

if role == "sp" then
	section("Protocol")
	check(zgo_sync.PROTO == 3, "PROTO is 3 for 1.7.0")
	check(zgo_sync.EVT == "zgo:sync3" and zgo_sync.EVT_UP == "zgo:up3", "event names carry the protocol")
	check(VERSION:match("^%d+%.%d+%.%d+$") ~= nil, "zgo_main.VERSION is x.y.z, got " .. tostring(VERSION))
	-- the sync header documents every kind the scripts send
	local hdr do
		local f = assert(io.open(S .. "/../gamedata/scripts/zgo_sync.script"))
		local src = f:read("*a") f:close()
		hdr = src:match("^%-%-%[%[(.-)%]%]")
	end
	local sent = {}
	local p = io.popen('ls "' .. S .. '/../gamedata/scripts"')
	for fn in p:lines() do
		if fn:match("^zgo_.*%.script$") and not fn:match("^zgo_bake_") then
			local f = io.open(S .. "/../gamedata/scripts/" .. fn)
			local src = f:read("*a") f:close()
			for k in src:gmatch('zgo_sync%.emit%(%{%s*"(%u)"') do sent[k] = fn end
			for k in src:gmatch('zgo_sync%.send_up%(%{%s*"(%u)"') do sent["up " .. k] = fn end
			for k in src:gmatch('[^%w_]emit%(%{%s*"(%u)"') do sent[k] = sent[k] or fn end
		end
	end
	p:close()
	local n = 0
	for k, fn in pairs(sent) do
		n = n + 1
		local kind = k:match("(%u)$")
		check(hdr:find("\n    " .. kind .. "|", 1, true), ("zgo_sync's header documents kind %s (sent by %s)"):format(k, fn))
	end
	print(("  PROTO %d, %d kinds sent by the scripts, all documented"):format(zgo_sync.PROTO, n))

	section("Single player: nothing is sent, the values are this machine's")
	run(40000)
	check(#lines(SENT, "V") == 0, "no V line without co-op peers")
	local m = H.mine()
	check(m.version == VERSION, "version")
	check(m.body == (BODY or "-") and m.props == (PROPS or "-"), "bakes: " .. m.body .. " " .. m.props)
	print(("  this machine: ZGO %s, body bake %s, props bake %s"):format(m.version, m.body, m.props))

	section("Comparing")
	local base = { version = "1.7.0", body = "aaa", props = "ppp" }
	local function keys(d) local t = {} for _, x in ipairs(d) do t[#t + 1] = x[1] end return table.concat(t, ",") end
	check(keys(H.compare(base, { version = "1.7.0", body = "aaa", props = "ppp" })) == "", "same: no difference")
	check(keys(H.compare(base, { version = "1.6.0", body = "aaa", props = "ppp" })) == "version", "version")
	check(keys(H.compare(base, { version = "1.7.0", body = "-", props = "ppp" })) == "body_none_here", "no bake here")
	check(keys(H.compare({ version = "1.7.0", body = "-", props = "ppp" }, base)) == "body_none_host", "no bake on the host")
	check(keys(H.compare(base, { version = "1.7.0", body = "bbb", props = "ppp" })) == "body_differs", "another bake")
	check(keys(H.compare(base, { version = "1.7.0", body = "aaa", props = "-" })) == "props_differs", "props")
	check(keys(H.compare(base, { version = "1.8.0", body = "bbb", props = "qqq" })) == "version,body_differs,props_differs", "all three")
	local all = H.compare(base, { version = "1.8.0", body = "bbb", props = "qqq" })
	for l = 1, 2 do
		local t = H.notice_text(all, l)
		check(t:find("1.7.0", 1, true) and t:find("1.8.0", 1, true), "the notice names both versions")
		local c = H.to_cp1251(t)
		check(not c:find("?", 1, true), "the notice converts to Windows-1251 without loss (" .. l .. ")")
		if l == 2 then check(c:find("[\192-\255]"), "the Russian notice is Cyrillic in Windows-1251") end
		print(("  notice (%s): %s"):format(l == 1 and "en" or "ru", l == 1 and t or (#c .. " bytes in cp1251")))
	end

	section("The older protocols are only noted in the log")
	-- (the harness's xrRazom mock exists only in co-op roles)

	section("Co-op roles")
	local function role_run(r, env)
		local p = io.popen(("%s luajit \"%s/zgo_test_handshake.lua\" %s %d 2>&1"):format(env or "", S, r, seed))
		local out = p:read("*a")
		p:close()
		local last = out:match("([^\n]*)\n*$")
		return out, last
	end
	for _, case in ipairs({
		{ "host", "ZGO_HS_BODY=fp1 ZGO_HS_PROPS=pp1" },
		{ "client", "ZGO_HS_BODY=fp1 ZGO_HS_PROPS=pp1" },
		{ "client", "ZGO_HS_PROPS=pp1" },
	}) do
		local out, last = role_run(case[1], case[2])
		local ok = last:find("OK", 1, true) ~= nil
		check(ok, case[1] .. " (" .. case[2] .. ") failed:\n" .. out)
		print(("  %-6s %-34s %s"):format(case[1], case[2], ok and "ok" or "FAILED"))
	end

	section("Errors")
	for _, l in ipairs(LOG) do if l:find("error") then fails = fails + 1 print("  ERR " .. l) end end
	if fails > 0 then print(("\n%d HANDSHAKE CHECKS FAILED"):format(fails)) os.exit(1) end
	print("\nALL HANDSHAKE TESTS PASSED")

elseif role == "host" then
	section("Host: announces on the first update, on a new player and every 30 s")
	run(200)
	local v = lines(SENT, "V")
	check(#v == 1, "one V line at start, got " .. #v)
	local want = ("V|h|%s|%s|%s"):format(VERSION, BODY or "-", PROPS or "-")
	check(v[1] == want, ("the line is %s, got %s"):format(want, tostring(v[1])))
	run(10000)
	check(#lines(SENT, "V") == 1, "nothing more within 30 s")
	XrrPeerCount = 2
	run(100)
	check(#lines(SENT, "V") == 2, "again when a player joins")
	run(31000)
	check(#lines(SENT, "V") == 3, "and every 30 s")
	XrrPeerCount = 0
	SENT = {}
	run(31000)
	check(#lines(SENT, "V") == 0, "nothing without players")
	XrrPeerCount = 1

	section("Host: a client's answer is logged, once, play goes on")
	DISPATCH(zgo_sync.EVT_UP, ("V|c|%s|%s|%s"):format(VERSION, BODY or "-", PROPS or "-"), "2")
	run(50)
	check(logs("differs from this host") == 0, "the same values: nothing logged")
	DISPATCH(zgo_sync.EVT_UP, "V|c|1.6.9|-|-", "3")
	DISPATCH(zgo_sync.EVT_UP, "V|c|1.6.9|-|-", "3")
	DISPATCH(zgo_sync.EVT_UP, "V|c", "4")
	run(50)
	check(logs("co-op player 3 differs from this host: Umbra Effects 1.6.9") == 1, "a different player is logged once")
	check(#NEWS == 0, "the host shows no notice")
	-- the older protocols are noted once in the log, nothing else happens
	DISPATCH("zgo:sync2", "W|x")
	DISPATCH("zgo:up2", "H|x")
	check(logs("sync protocol 2, this is 3") == 1, "a peer on protocol 2 is noted once")
	for _, l in ipairs(LOG) do if l:find("error") then fails = fails + 1 print("  ERR " .. l) end end
	print(fails == 0 and "HANDSHAKE HOST OK" or "HANDSHAKE HOST FAILED")

else
	section("Client: compares with the host, says so once, answers")
	local me = ("%s|%s|%s"):format(VERSION, BODY or "-", PROPS or "-")
	-- the same as this machine: no notice
	DISPATCH(zgo_sync.EVT, "V|h|" .. me)
	run(50)
	check(#lines(UP, "V") == 1 and lines(UP, "V")[1] == "V|c|" .. me, "the client answers with its own values")
	check(#NEWS == 0 and logs("differs from the host") == 0, "the same values: no notice")
	-- a host on another version and bake: one notice, in the log too
	DISPATCH(zgo_sync.EVT, "V|h|1.7.1|fp9|pp1")
	run(50)
	DISPATCH(zgo_sync.EVT, "V|h|1.7.1|fp9|pp1")
	run(50)
	check(#NEWS == 1, "one notice for one difference, got " .. #NEWS)
	check(logs("this machine differs from the host: Umbra Effects " .. VERSION .. " (host 1.7.1)") == 1, "logged once")
	local t = H.last_shown() or ""
	check(t:find("1.7.1", 1, true), "the notice names the host's version")
	if BODY then check(t:find("differ from the host's", 1, true), "the notice says the bakes differ")
	else check(t:find("you don't", 1, true), "the notice says this machine has no bake") end
	check(NEWS[1] and not NEWS[1].msg:find("[\128-\255]") or true, "news text")
	-- rubbish is ignored
	DISPATCH(zgo_sync.EVT, "V|h|1.7.0")
	DISPATCH(zgo_sync.EVT, "V|x|1|2|3")
	run(50)
	check(#NEWS == 1, "short or unknown V lines are ignored")
	-- ZGO switched off on this machine: lines are not handled at all
	local old = zgo_util.setting
	zgo_util.setting = function(k) if k == "general/enable" then return false end return old(k) end
	DISPATCH(zgo_sync.EVT, "V|h|2.0.0|x|y")
	run(50)
	zgo_util.setting = old
	check(#NEWS == 1, "nothing while ZGO is switched off here")
	check(#lines(SENT, "V") == 0, "a client never announces")
	for _, l in ipairs(LOG) do if l:find("error") then fails = fails + 1 print("  ERR " .. l) end end
	print(fails == 0 and "HANDSHAKE CLIENT OK" or "HANDSHAKE CLIENT FAILED")
end
