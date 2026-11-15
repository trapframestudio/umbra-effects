/*
 * zgo_native.dll: exports (zgo_native.h), the three engine hooks and the
 * log the Lua side drains. Everything exported runs on the game's main
 * thread; the detours run on engine threads and never call into Lua.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "zgo_bones.h"
#include "zgo_finder.h"
#include "zgo_hook.h"
#include "zgo_native.h"
#include "zgo_pe.h"

#ifndef ZGO_NATIVE_VERSION
#define ZGO_NATIVE_VERSION "1.0.0"
#endif
#define STR2(x) #x
#define STR(x) STR2(x)

static zgo_image  g_im;
static zgo_finder g_f;
static int        g_init = 1;            /* 1: not run; 0: supported; < 0: unsupported */
static uint32_t   g_caps;
static volatile uint32_t g_hooks;        /* installed capability bits */
static volatile uint32_t g_bones_on;     /* the bone hooks act (else pass through) */
static zgo_hook   g_h[ZGO_T_COUNT];
static char       g_status[256] = "not initialised";
static int        g_pinned;

/* ---------------------------------------------------------------- log (main thread only) */

#define NLOG 32
static char g_log[NLOG][240];
static int  g_log_head, g_log_n;

static void logf_(const char* fmt, ...)
{
	char* line = g_log[(g_log_head + g_log_n) % NLOG];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(line, sizeof g_log[0], fmt, ap);
	va_end(ap);
	if (g_log_n < NLOG) g_log_n++;
	else g_log_head = (g_log_head + 1) % NLOG;
}

/* ---------------------------------------------------------------- detours */

typedef void     (*calc_fn)(void* ik, int force);
typedef uint16_t (*boneid_fn)(void* ik, const char* name);
typedef void     (*depart_fn)(void* vis);

static calc_fn   o_calc;
static boneid_fn o_boneid;
static depart_fn o_depart;

static void d_calc(void* ik, int force)
{
	o_calc(ik, force);
	if (__atomic_load_n(&g_bones_on, __ATOMIC_ACQUIRE)) zgo_bones_post(ik);
}

static uint16_t d_boneid(void* ik, const char* name)
{
	if (name && name[0] == 1 && name[1] == 'z' && name[2] == 'g' && name[3] == 'o' && name[4] == ':' &&
	    __atomic_load_n(&g_bones_on, __ATOMIC_ACQUIRE)) {
		zgo_bones_capture(ik, name + 5);
		return 0xFFFF;   /* BI_NONE, as for any unknown bone name */
	}
	return o_boneid(ik, name);
}

static void d_depart(void* vis)
{
	zgo_bones_departed((uint8_t*)vis + g_f.off.ik_sub);
	o_depart(vis);
}

static void cs_lock(void* cs) { EnterCriticalSection((CRITICAL_SECTION*)cs); }
static void cs_unlock(void* cs) { LeaveCriticalSection((CRITICAL_SECTION*)cs); }

/* ---------------------------------------------------------------- exports */

ZGO_API uint32_t zgo_abi(void) { return ZGO_NATIVE_ABI; }

ZGO_API const char* zgo_version(void)
{
	return "zgo_native " ZGO_NATIVE_VERSION " (abi " STR(ZGO_NATIVE_ABI) ", " __DATE__ ")";
}

static int32_t init_at(const void* base, const char* what)
{
	const char* why = "";
	if (zgo_pe_open(&g_im, base, &why) != 0) {
		snprintf(g_status, sizeof g_status, "unsupported exe: %s", why);
		snprintf(g_f.report, sizeof g_f.report, "zgo_native finder: %s: %s\n", what, why);
		g_caps = 0;
		g_init = ZGO_E_UNSUPPORTED;
		logf_("%s", g_status);
		return g_init;
	}
	zgo_find(&g_im, &g_f);
	if (!g_f.ok) {
		snprintf(g_status, sizeof g_status, "unsupported exe: %s", g_f.why);
		g_caps = 0;
		g_init = ZGO_E_UNSUPPORTED;
		logf_("%s; native features stay off", g_status);
		return g_init;
	}
	zgo_bones_env env;
	memset(&env, 0, sizeof env);
	env.off = g_f.off;
	env.lock = cs_lock;
	env.unlock = cs_unlock;
	zgo_bones_setup(&env);
	g_caps = ZGO_CAP_FINDER | ZGO_CAP_BONES;
	g_init = 0;
	snprintf(g_status, sizeof g_status, "supported exe (timestamp %08x): CalculateBones rva 0x%x, LL_BoneID rva 0x%x, Depart rva 0x%x",
	         g_im.timestamp, g_f.t[ZGO_T_CALC].rva, g_f.t[ZGO_T_BONEID].rva, g_f.t[ZGO_T_DEPART].rva);
	logf_("%s", g_status);
	return 0;
}

ZGO_API int32_t zgo_init(void)
{
	if (g_init != 1) return g_init;
	char path[MAX_PATH] = "";
	GetModuleFileNameA(NULL, path, sizeof path);
	const char* name = strrchr(path, '\\');
	return init_at(GetModuleHandleW(NULL), name ? name + 1 : path);
}

ZGO_API int32_t zgo_init_module(uint64_t module_base)
{
	if (g_hooks) return ZGO_E_ARG;      /* not while hooks point into the current module */
	return init_at((const void*)(uintptr_t)module_base, "module");
}

ZGO_API uint32_t zgo_caps(void) { return g_init == 0 ? g_caps : 0; }
ZGO_API uint32_t zgo_hooks(void) { return g_hooks; }

static void pin_self(void)
{
	if (g_pinned) return;
	HMODULE h;
	if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN, (LPCWSTR)(void*)&zgo_abi, &h))
		g_pinned = 1;
}

static int remove_bones(void)
{
	char why[200] = "";
	int ok = 1;
	__atomic_store_n(&g_bones_on, 0, __ATOMIC_RELEASE);
	/* CalculateBones first: nothing is applied any more, then the others */
	static const int order[] = { ZGO_T_CALC, ZGO_T_BONEID, ZGO_T_DEPART };
	for (int i = 0; i < 3; i++) {
		zgo_hook* h = &g_h[order[i]];
		if (!h->installed) continue;
		if (!zgo_hook_remove(h, why, sizeof why)) { logf_("%s", why); ok = 0; }
		else logf_("hook removed: %s", h->name);
	}
	zgo_bones_do_clear_all();
	__atomic_and_fetch(&g_hooks, ~ZGO_CAP_BONES, __ATOMIC_RELEASE);
	return ok;
}

static int install_bones(void)
{
	char why[200] = "";
	uint8_t* base = (uint8_t*)g_im.base;
	void* detours[ZGO_T_COUNT] = { (void*)d_calc, (void*)d_boneid, (void*)d_depart };
	void** origs[ZGO_T_COUNT] = { (void**)&o_calc, (void**)&o_boneid, (void**)&o_depart };
	for (int i = 0; i < ZGO_T_COUNT; i++) {
		if (!zgo_hook_prepare(&g_h[i], g_f.t[i].name, base + g_f.t[i].rva, g_f.t[i].steal, detours[i], origs[i], why, sizeof why)) {
			logf_("hook not prepared: %s", why);
			return 0;
		}
	}
	pin_self();
	/* Depart and LL_BoneID first (they only record), CalculateBones last */
	static const int order[] = { ZGO_T_DEPART, ZGO_T_BONEID, ZGO_T_CALC };
	for (int i = 0; i < 3; i++) {
		zgo_hook* h = &g_h[order[i]];
		if (!zgo_hook_install(h, why, sizeof why)) {
			logf_("hook not installed: %s; removing the others", why);
			remove_bones();
			return 0;
		}
		logf_("hook installed: %s at %p", h->name, (void*)h->target);
	}
	zgo_bones_do_clear_all();
	__atomic_or_fetch(&g_hooks, ZGO_CAP_BONES, __ATOMIC_RELEASE);
	__atomic_store_n(&g_bones_on, 1, __ATOMIC_RELEASE);
	return 1;
}

ZGO_API int32_t zgo_enable(uint32_t caps)
{
	if (g_init == 1) return ZGO_E_NOT_INIT;
	if (g_init != 0) return ZGO_E_UNSUPPORTED;
	caps &= g_caps;
	int want = (caps & ZGO_CAP_BONES) != 0;
	int have = (g_hooks & ZGO_CAP_BONES) != 0;
	if (want && !have && !install_bones()) return ZGO_E_HOOK;
	if (!want && have) remove_bones();
	return (int32_t)(g_hooks | (g_caps & ZGO_CAP_FINDER));
}

ZGO_API void zgo_shutdown(void)
{
	if (g_hooks & ZGO_CAP_BONES) remove_bones();
	zgo_bones_do_clear_all();
}

ZGO_API const char* zgo_status(void) { return g_status; }

ZGO_API int32_t zgo_report(char* buf, int32_t size)
{
	const char* r = g_f.report[0] ? g_f.report : "zgo_native finder: not run\n";
	int32_t n = (int32_t)strlen(r);
	if (buf && size > 0) {
		int32_t c = n < size - 1 ? n : size - 1;
		memcpy(buf, r, (size_t)c);
		buf[c] = 0;
	}
	return n;
}

ZGO_API int32_t zgo_log_next(char* buf, int32_t size)
{
	if (!g_log_n || !buf || size <= 0) return 0;
	const char* line = g_log[g_log_head];
	g_log_head = (g_log_head + 1) % NLOG;
	g_log_n--;
	int32_t n = (int32_t)strlen(line);
	int32_t c = n < size - 1 ? n : size - 1;
	memcpy(buf, line, (size_t)c);
	buf[c] = 0;
	return c > 0 ? c : 1;
}

ZGO_API void zgo_get_stats(zgo_stats* out)
{
	if (!out) return;
	memset(out, 0, sizeof *out);
	zgo_bones_stats(out);
	out->hooks = g_hooks;
}

/* ---------------------------------------------------------------- bones */

ZGO_API uint64_t zgo_capture_take(uint32_t token) { return zgo_bones_take(token); }

static int32_t bones_ready(void)
{
	if (g_init == 1) return ZGO_E_NOT_INIT;
	if (g_init != 0) return ZGO_E_UNSUPPORTED;
	if (!(g_hooks & ZGO_CAP_BONES)) return ZGO_E_NOT_ENABLED;
	return 0;
}

ZGO_API int32_t zgo_bones_bind(uint64_t kin)
{
	int32_t r = bones_ready();
	return r ? r : zgo_bones_do_bind(kin);
}
ZGO_API int32_t zgo_bones_state(int32_t h) { return zgo_bones_do_state(h); }
ZGO_API int32_t zgo_bones_begin(int32_t h)
{
	int32_t r = bones_ready();
	return r ? r : zgo_bones_do_begin(h);
}
ZGO_API int32_t zgo_bones_group(int32_t h, uint16_t driver, const float* l12, const uint16_t* members, int32_t n)
{
	int32_t r = bones_ready();
	return r ? r : zgo_bones_do_group(h, driver, l12, members, n);
}
ZGO_API int32_t zgo_bones_commit(int32_t h)
{
	int32_t r = bones_ready();
	return r ? r : zgo_bones_do_commit(h);
}
ZGO_API int32_t zgo_bones_unbind(int32_t h) { return zgo_bones_do_unbind(h); }
ZGO_API void    zgo_bones_clear_all(void) { zgo_bones_do_clear_all(); }

/* ---------------------------------------------------------------- DllMain */

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
	(void)inst;
	if (reason == DLL_PROCESS_ATTACH) {
		DisableThreadLibraryCalls(inst);
	} else if (reason == DLL_PROCESS_DETACH) {
		/* game exit (or an unpinned unload, which can only happen with no hooks):
		   put the engine's bytes back; every other thread is gone by now */
		__atomic_store_n(&g_bones_on, 0, __ATOMIC_RELEASE);
		char why[200];
		for (int i = 0; i < ZGO_T_COUNT; i++) if (g_h[i].installed) zgo_hook_remove(&g_h[i], why, sizeof why);
		(void)reserved;
	}
	return TRUE;
}
