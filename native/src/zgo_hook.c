/* Inline hooks; see zgo_hook.h */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdio.h>
#include <string.h>

#include "zgo_hook.h"

#define TRAMP_SIZE 64
#define RELAY_AT   32

static uint8_t* g_page;      /* trampolines, near the exe's code */
static int      g_page_used;
static uint8_t* g_page_lo;   /* the targets the page must reach */

static int near(const uint8_t* a, const uint8_t* b)
{
	int64_t d = (int64_t)(a - b);
	return d > -0x7FF00000LL && d < 0x7FF00000LL;
}

static uint8_t* alloc_near(uint8_t* target)
{
	SYSTEM_INFO si;
	GetSystemInfo(&si);
	uintptr_t gran = si.dwAllocationGranularity ? si.dwAllocationGranularity : 0x10000;
	uintptr_t t = (uintptr_t)target & ~(gran - 1);
	uintptr_t lo_lim = (uintptr_t)si.lpMinimumApplicationAddress;
	uintptr_t hi_lim = (uintptr_t)si.lpMaximumApplicationAddress;
	/* below the target first (the exe sits at 0x140000000 with free space under it), then above */
	for (int dir = -1; dir <= 1; dir += 2) {
		uintptr_t a = dir < 0 ? t - gran : t + gran;
		while (a > lo_lim && a < hi_lim && near((uint8_t*)a, target)) {
			MEMORY_BASIC_INFORMATION mbi;
			if (!VirtualQuery((void*)a, &mbi, sizeof mbi)) break;
			if (mbi.State == MEM_FREE) {
				uintptr_t start = ((uintptr_t)mbi.BaseAddress + gran - 1) & ~(gran - 1);
				if (dir < 0) {
					uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
					start = (end - gran) & ~(gran - 1);
				}
				if (start >= (uintptr_t)mbi.BaseAddress && near((uint8_t*)start, target)) {
					void* p = VirtualAlloc((void*)start, 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
					if (p) return (uint8_t*)p;
				}
			}
			if (dir < 0) {
				uintptr_t base = (uintptr_t)mbi.AllocationBase ? (uintptr_t)mbi.AllocationBase : (uintptr_t)mbi.BaseAddress;
				if (base < gran) break;
				a = (base - 1) & ~(gran - 1);
			} else {
				a = ((uintptr_t)mbi.BaseAddress + mbi.RegionSize + gran - 1) & ~(gran - 1);
			}
		}
	}
	return NULL;
}

static void put_abs_jmp(uint8_t* at, const void* to)
{
	at[0] = 0xFF; at[1] = 0x25; at[2] = at[3] = at[4] = at[5] = 0;   /* jmp [rip+0] */
	uint64_t v = (uint64_t)(uintptr_t)to;
	memcpy(at + 6, &v, 8);
}

int zgo_hook_prepare(zgo_hook* h, const char* name, uint8_t* target, int steal, void* detour, void** orig, char* why, int whylen)
{
	if (h->tramp) return 1;
	memset(h, 0, sizeof *h);
	h->name = name;
	h->target = target;
	h->steal = steal;
	h->detour = detour;
	h->orig = orig;
	if (((uintptr_t)target & 7) || steal < 5 || steal > 16) { snprintf(why, whylen, "%s: bad target", name); return 0; }
	memcpy(h->saved, target, 8);
	if (!g_page || g_page_used + TRAMP_SIZE > 0x1000 || !near(g_page, target)) {
		g_page = alloc_near(target);
		g_page_used = 0;
		g_page_lo = target;
		if (!g_page) { snprintf(why, whylen, "%s: no memory within 2 GB of the target", name); return 0; }
	}
	(void)g_page_lo;
	uint8_t* t = g_page + g_page_used;
	g_page_used += TRAMP_SIZE;
	memset(t, 0xCC, TRAMP_SIZE);
	memcpy(t, target, (size_t)steal);                 /* the first instruction (position independent) */
	put_abs_jmp(t + steal, target + steal);           /* ... then back into the function */
	put_abs_jmp(t + RELAY_AT, detour);                /* the jmp at the target lands here */
	FlushInstructionCache(GetCurrentProcess(), t, TRAMP_SIZE);
	int64_t rel = (int64_t)((t + RELAY_AT) - (target + 5));
	int32_t rel32 = (int32_t)rel;
	h->patched[0] = 0xE9;
	memcpy(h->patched + 1, &rel32, 4);
	memcpy(h->patched + 5, h->saved + 5, 3);
	h->tramp = t;
	*orig = t;
	return 1;
}

static int swap8(uint8_t* at, const uint8_t* from, const uint8_t* to)
{
	DWORD old = 0, tmp;
	if (!VirtualProtect(at, 8, PAGE_EXECUTE_READWRITE, &old)) return 0;
	uint64_t f, t;
	memcpy(&f, from, 8);
	memcpy(&t, to, 8);
	int ok = __sync_bool_compare_and_swap((volatile uint64_t*)at, f, t);
	VirtualProtect(at, 8, old, &tmp);
	FlushInstructionCache(GetCurrentProcess(), at, 8);
	return ok;
}

int zgo_hook_install(zgo_hook* h, char* why, int whylen)
{
	if (h->installed) return 1;
	if (!h->tramp) { snprintf(why, whylen, "%s: not prepared", h->name); return 0; }
	if (!swap8(h->target, h->saved, h->patched)) {
		snprintf(why, whylen, "%s: the code changed since it was verified (another hook?)", h->name);
		return 0;
	}
	h->installed = 1;
	return 1;
}

int zgo_hook_remove(zgo_hook* h, char* why, int whylen)
{
	if (!h->installed) return 1;
	if (!swap8(h->target, h->patched, h->saved)) {
		snprintf(why, whylen, "%s: someone hooked over ours; left in place (it passes through)", h->name);
		return 0;
	}
	h->installed = 0;
	return 1;
}
