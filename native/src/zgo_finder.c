/* The offset finder; see zgo_finder.h and native/README.md (offset table). */
#include "zgo_finder.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* ---------------------------------------------------------------- patterns */

static int hexv(char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

int zgo_pat_match(const zgo_image* im, uint32_t rva, const char* pat, zgo_match* m)
{
	uint32_t at = rva;
	const char* p = pat;
	memset(m, 0, sizeof(*m));
	while (*p) {
		while (*p == ' ') p++;
		if (!*p) break;
		if (p[0] == '?' && p[1] == '?') {
			if (!zgo_pe_in(im, at, 1)) return 0;
			at += 1; p += 2;
		} else if (p[0] == '?' && p[1] >= '1' && p[1] <= '9') {
			uint32_t n = (uint32_t)(p[1] - '0');
			if (!zgo_pe_in(im, at, n)) return 0;
			at += n; p += 2;
		} else if (p[0] == '%') {
			uint32_t n = (uint32_t)(p[1] - '0');
			int slot = p[2] - 'a';
			if ((n != 1 && n != 2 && n != 4) || slot < 0 || slot >= 26 || !zgo_pe_in(im, at, n)) return 0;
			uint64_t v = 0;
			for (uint32_t i = 0; i < n; i++) v |= (uint64_t)im->base[at + i] << (8 * i);
			m->cap[slot] = v;
			at += n; p += 3;
		} else if (p[0] == '@') {
			int slot = p[1] - 'a';
			if (slot < 0 || slot >= 26 || !zgo_pe_in(im, at, 4)) return 0;
			int32_t d = (int32_t)zgo_rd32(im, at);
			int64_t t = (int64_t)at + 4 + d;
			if (t < 0 || t >= (int64_t)im->size) return 0;
			m->cap[slot] = (uint64_t)t;
			at += 4; p += 2;
		} else {
			int hi = hexv(p[0]), lo = hexv(p[1]);
			if (hi < 0 || lo < 0) return 0;          /* malformed pattern: never matches */
			if (!zgo_pe_in(im, at, 1) || im->base[at] != (uint8_t)(hi << 4 | lo)) return 0;
			at += 1; p += 2;
		}
	}
	m->len = at - rva;
	return 1;
}

uint32_t zgo_pat_find(const zgo_image* im, uint32_t rva, uint32_t range, const char* pat, zgo_match* m)
{
	for (uint32_t a = rva; a < rva + range && zgo_pe_in(im, a, 1); a++)
		if (zgo_pat_match(im, a, pat, m)) return a;
	return 0;
}

/* ---------------------------------------------------------------- the known layout */

/* IKinematics vtable slots (xrRazom develop-mt: 46 slots, see native/README.md) */
#define IK_SLOTS          46
#define IK_LL_BONEID_STR   5   /* u16 LL_BoneID(LPCSTR) */
#define IK_BONE_INSTANCE   9   /* CBoneInstance& LL_GetBoneInstance(u16) */
#define IK_BONE_COUNT     12   /* u16 LL_BoneCount() */
#define IK_TRANSFORM_R    22   /* Fmatrix& LL_GetTransform_R(u16) */
#define IK_CALC_BONES     35   /* void CalculateBones(BOOL) */
#define IK_CALC_INVAL     36   /* void CalculateBones_Invalidate() */
#define IK_SET_CALLBACK   37   /* void Callback(UpdateCallback, void*) */
#define IK_GET_CALLBACK   41
#define IK_GET_CB_PARAM   42
/* primary (IRenderVisual / dxRender_Visual) vtable */
#define PR_MIN_SLOTS      27
#define PR_DCAST_KIN      16   /* IKinematics* dcast_PKinematics() */
#define PR_DEPART         26   /* void Depart() */

static const char P_CALC[] =
	"48 89 5c 24 10 48 89 6c 24 18 56 48 83 ec 20"   /* prologue (first instruction: 5 bytes) */
	" 8b 81 %4t 8b ea 39 05 @g 48 8b d9 0f 84 ?4"     /* if (Device.dwTimeGlobal == UCalc_Time) return */
	" 48 8b 49 %1m 48 89 7c 24 30 ff 15 @e"           /* EnterCriticalSection(UCalc_Mutex) */
	" 48 8b 83 %4a 48 8d 8b %4b ff 90 %4o";           /* OnCalculateBones() on the primary base */
static const char P_CALC_TIME[]  = "89 8b %4t";                  /* UCalc_Time = Device.dwTimeGlobal */
static const char P_CALC_CB[]    = "48 8b 93 %4c 48 85 d2";      /* if (Update_Callback) ... */
static const char P_CALC_LEAVE[] = "48 8b 4b %1m ff 15 @l";      /* LeaveCriticalSection(UCalc_Mutex) */
static const char P_BONEID[] =
	"48 89 4c 24 08 56 41 54 41 55 48 83 ec 40 48 89 6c 24 38 4c 8d 89 %4n 49 8b 01 4c 8b ea";
static const char P_INST[]   = "0f b7 c2 48 69 c0 %4s 48 03 81 %4i c3";
static const char P_COUNT[]  = "48 8b 81 %4b 8b 48 08 2b 08 48 c1 f9 03 0f b7 c1 c3";
static const char P_RENDER[] = "48 83 ec 28 48 8b 01 ff 50 %1s 48 83 e8 %1r 48 83 c4 28 c3";
static const char P_INVAL[]  = "c7 81 %4t 00 00 00 00";
static const char P_SETCB[]  = "48 89 91 %4c 4c 89 81 %4p c3";
static const char P_GET[]    = "48 8b 81 %4v c3";
static const char P_DCAST[]  = "33 d2 48 8d 81 %4k 48 85 c9 48 0f 44 c2 c3";
static const char P_DEPART[] =
	"48 89 5c 24 08 48 89 74 24 10 57 48 83 ec 20 48 8b f9"
	" 48 8b 0d @g ff 15 @e 48 8b b7 ?4 48 8b 9f ?4";        /* lock(wallmarks); ClearWallmarks() */
static const char P_DEPART_LEAVE[] = "48 8b 0d @h ff 15 @l";
static const char P_DEPART_MASK[]  = "33 c0 48 89 87 %4a 48 89 87 %4b";   /* hidden_bones.zero(); visimask.zero() */

/* ---------------------------------------------------------------- report */

static void rep(zgo_finder* f, const char* fmt, ...)
{
	size_t n = strlen(f->report);
	if (n + 1 >= sizeof f->report) return;
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(f->report + n, sizeof f->report - n, fmt, ap);
	va_end(ap);
}

static int fail(zgo_finder* f, const char* fmt, ...)
{
	if (!f->why[0]) {
		va_list ap;
		va_start(ap, fmt);
		vsnprintf(f->why, sizeof f->why, fmt, ap);
		va_end(ap);
	}
	f->ok = 0;
	return 0;
}

/* ---------------------------------------------------------------- RTTI */

static uint32_t find_bytes(const zgo_image* im, uint32_t from, uint32_t to, const void* needle, uint32_t n, int* count)
{
	uint32_t hit = 0;
	*count = 0;
	if (to > im->size) to = im->size;
	for (uint32_t a = from; a + n <= to; a++) {
		if (im->base[a] == ((const uint8_t*)needle)[0] && memcmp(im->base + a, needle, n) == 0) {
			if (!*count) hit = a;
			(*count)++;
		}
	}
	return hit;
}

/* the type descriptor of class name: ".?AV<name>@@" (unique) */
static uint32_t type_descriptor(const zgo_image* im, const char* name)
{
	char s[96];
	int count = 0;
	snprintf(s, sizeof s, ".?AV%s@@", name);
	uint32_t n = (uint32_t)strlen(s) + 1;       /* with the terminating 0 */
	const zgo_section* d = zgo_pe_section(im, ".data");
	uint32_t hit = 0;
	if (d) hit = find_bytes(im, d->rva, d->rva + d->size, s, n, &count);
	if (!hit || count != 1) hit = find_bytes(im, 0x1000, im->size, s, n, &count);
	if (!hit || count != 1 || hit < 16) return 0;
	uint32_t td = hit - 16;
	/* pVFTable points at type_info's vtable inside the image */
	if (!zgo_pe_ptr_rva(im, zgo_rd64(im, td))) return 0;
	return td;
}

typedef struct col { uint32_t rva, offset, chd; } col;

/* complete object locators of a type descriptor (x64: signature 1, self rva) */
static int locators(const zgo_image* im, const zgo_section* rd, uint32_t td, col* out, int max)
{
	int n = 0;
	for (uint32_t a = (rd->rva + 3) & ~3u; a + 24 <= rd->rva + rd->size; a += 4) {
		if (zgo_rd32(im, a) != 1) continue;
		if (zgo_rd32(im, a + 12) != td || zgo_rd32(im, a + 20) != a) continue;
		if (n < max) { out[n].rva = a; out[n].offset = zgo_rd32(im, a + 4); out[n].chd = zgo_rd32(im, a + 16); }
		n++;
	}
	return n;
}

/* the vtable whose [-1] entry points at a locator (exactly one) */
static uint32_t vtable_of(const zgo_image* im, const zgo_section* rd, uint32_t col_rva)
{
	uint64_t want = im->pref + col_rva;
	uint32_t hit = 0;
	int count = 0;
	for (uint32_t a = (rd->rva + 7) & ~7u; a + 16 <= rd->rva + rd->size; a += 8) {
		if (zgo_rd64(im, a) == want) { hit = a + 8; count++; }
	}
	return count == 1 ? hit : 0;
}

static uint32_t slots(const zgo_image* im, uint32_t vt)
{
	uint32_t n = 0;
	while (n < 512 && zgo_pe_in(im, vt + n * 8, 8)) {
		uint32_t r = zgo_pe_ptr_rva(im, zgo_rd64(im, vt + n * 8));
		if (!r || !zgo_pe_is_exec(im, r)) break;
		n++;
	}
	return n;
}

static uint32_t slot_fn(const zgo_image* im, uint32_t vt, int k)
{
	return zgo_pe_ptr_rva(im, zgo_rd64(im, vt + (uint32_t)k * 8));
}

/* mdisp of base class `base` in a class hierarchy descriptor (non-virtual, unique) */
static int base_offset(const zgo_image* im, uint32_t chd, const char* base, uint32_t* off)
{
	char want[96];
	snprintf(want, sizeof want, ".?AV%s@@", base);
	if (!zgo_pe_in(im, chd, 16)) return 0;
	uint32_t nb = zgo_rd32(im, chd + 8), arr = zgo_rd32(im, chd + 12);
	if (nb == 0 || nb > 256 || !zgo_pe_in(im, arr, nb * 4)) return 0;
	int found = 0;
	for (uint32_t i = 0; i < nb; i++) {
		uint32_t bcd = zgo_rd32(im, arr + i * 4);
		if (!zgo_pe_in(im, bcd, 28)) return 0;
		uint32_t td = zgo_rd32(im, bcd);
		if (!zgo_pe_in(im, td + 16, (uint32_t)strlen(want) + 1)) continue;
		if (memcmp(im->base + td + 16, want, strlen(want) + 1) != 0) continue;
		int32_t mdisp = (int32_t)zgo_rd32(im, bcd + 8), pdisp = (int32_t)zgo_rd32(im, bcd + 12);
		if (pdisp != -1 || mdisp <= 0) return 0;
		*off = (uint32_t)mdisp;
		found++;
	}
	return found == 1;
}

/* ---------------------------------------------------------------- checks */

typedef struct cls {
	const char* name;
	uint32_t td, vt_ik, vt_pr, n_ik, n_pr, ik_off;
} cls;

static int find_class(const zgo_image* im, const zgo_section* rd, zgo_finder* f, cls* c)
{
	col cols[8];
	c->td = type_descriptor(im, c->name);
	if (!c->td) return fail(f, "RTTI: no unique type descriptor for %s", c->name);
	int n = locators(im, rd, c->td, cols, 8);
	if (n < 2 || n > 8) return fail(f, "RTTI: %s has %d object locators (expected 2..8)", c->name, n);
	if (!base_offset(im, cols[0].chd, "IKinematics", &c->ik_off))
		return fail(f, "RTTI: %s has no unique IKinematics base", c->name);
	for (int i = 0; i < n; i++) {
		if (cols[i].offset == 0) c->vt_pr = vtable_of(im, rd, cols[i].rva);
		else if (cols[i].offset == c->ik_off) c->vt_ik = vtable_of(im, rd, cols[i].rva);
	}
	if (!c->vt_pr || !c->vt_ik) return fail(f, "RTTI: %s vtables not found (primary %s, IKinematics %s)", c->name,
	                                        c->vt_pr ? "ok" : "missing", c->vt_ik ? "ok" : "missing");
	c->n_ik = slots(im, c->vt_ik);
	c->n_pr = slots(im, c->vt_pr);
	rep(f, "  RTTI %-20s td 0x%07x  IKinematics at +%u: vtable 0x%07x (%u slots), primary vtable 0x%07x (%u slots)\n",
	    c->name, c->td, c->ik_off, c->vt_ik, c->n_ik, c->vt_pr, c->n_pr);
	if (c->n_ik != IK_SLOTS) return fail(f, "%s: IKinematics vtable has %u slots, expected %d (layout changed)", c->name, c->n_ik, IK_SLOTS);
	if (c->n_pr < PR_MIN_SLOTS) return fail(f, "%s: primary vtable has %u slots, expected at least %d", c->name, c->n_pr, PR_MIN_SLOTS);
	return 1;
}

static int need(zgo_finder* f, const zgo_image* im, uint32_t rva, const char* pat, zgo_match* m, const char* what)
{
	if (!rva || !zgo_pat_match(im, rva, pat, m)) {
		char bytes[3 * 24 + 1] = "";
		for (int i = 0; i < 24 && rva && zgo_pe_in(im, rva + (uint32_t)i, 1); i++)
			snprintf(bytes + 3 * i, 4, "%02x ", im->base[rva + i]);
		return fail(f, "%s at rva 0x%x: bytes differ (%s)", what, rva, bytes);
	}
	return 1;
}

static int target(zgo_finder* f, const zgo_image* im, int which, const char* name, uint32_t rva, int steal)
{
	f->t[which].name = name;
	f->t[which].rva = rva;
	f->t[which].steal = steal;
	/* the hook writes 8 bytes atomically: the function must start 8-aligned */
	if (((uintptr_t)(im->base + rva)) & 7) return fail(f, "%s at rva 0x%x is not 8-byte aligned", name, rva);
	return 1;
}

int zgo_find(const zgo_image* im, zgo_finder* f)
{
	zgo_match m;
	memset(f, 0, sizeof(*f));
	f->ok = 1;
	rep(f, "zgo_native finder: module at %p (preferred 0x%llx), size 0x%x, timestamp 0x%08x\n",
	    (const void*)im->base, (unsigned long long)im->pref, im->size, im->timestamp);

	const zgo_section* text = zgo_pe_section(im, ".text");
	const zgo_section* rd = zgo_pe_section(im, ".rdata");
	if (!text || !rd || !zgo_pe_section(im, ".data")) { fail(f, "sections .text/.rdata/.data missing"); goto done; }

	cls k = { "CKinematics" }, a = { "CKinematicsAnimated" };
	if (!find_class(im, rd, f, &k) || !find_class(im, rd, f, &a)) goto done;
	f->td[0] = k.td; f->td[1] = a.td;
	f->vt_ik[0] = k.vt_ik; f->vt_ik[1] = a.vt_ik;
	f->vt_pr[0] = k.vt_pr; f->vt_pr[1] = a.vt_pr;
	f->ik_slots = k.n_ik;
	if (k.ik_off != a.ik_off) { fail(f, "IKinematics offset differs: CKinematics +%u, CKinematicsAnimated +%u", k.ik_off, a.ik_off); goto done; }
	f->off.ik_sub = k.ik_off;

	/* both classes must share the functions we hook / read */
	static const int ik_shared[] = { IK_LL_BONEID_STR, IK_BONE_INSTANCE, IK_BONE_COUNT, IK_TRANSFORM_R, IK_CALC_BONES,
	                                 IK_CALC_INVAL, IK_SET_CALLBACK, IK_GET_CALLBACK, IK_GET_CB_PARAM };
	for (unsigned i = 0; i < sizeof ik_shared / sizeof ik_shared[0]; i++) {
		if (slot_fn(im, k.vt_ik, ik_shared[i]) != slot_fn(im, a.vt_ik, ik_shared[i])) {
			fail(f, "IKinematics slot %d differs between CKinematics and CKinematicsAnimated", ik_shared[i]);
			goto done;
		}
	}
	if (slot_fn(im, k.vt_pr, PR_DEPART) != slot_fn(im, a.vt_pr, PR_DEPART)) {
		fail(f, "Depart (primary slot %d) differs between CKinematics and CKinematicsAnimated", PR_DEPART);
		goto done;
	}

	/* dcast_PKinematics: this + ik_sub, on both */
	for (int c = 0; c < 2; c++) {
		uint32_t vt = c ? a.vt_pr : k.vt_pr;
		if (!need(f, im, slot_fn(im, vt, PR_DCAST_KIN), P_DCAST, &m, "dcast_PKinematics")) goto done;
		if (m.cap['k' - 'a'] != f->off.ik_sub) { fail(f, "dcast_PKinematics adds 0x%llx, RTTI says %u", (unsigned long long)m.cap['k' - 'a'], f->off.ik_sub); goto done; }
	}

	/* CalculateBones */
	uint32_t calc = slot_fn(im, k.vt_ik, IK_CALC_BONES);
	if (!need(f, im, calc, P_CALC, &m, "CalculateBones")) goto done;
	f->off.ucalc_time = (uint32_t)m.cap['t' - 'a'];
	f->off.mutex = (uint32_t)m.cap['m' - 'a'];
	f->rva_time_global = (uint32_t)m.cap['g' - 'a'];
	if (!zgo_pe_iat_is(im, (uint32_t)m.cap['e' - 'a'], "kernel32.dll", "EnterCriticalSection")) { fail(f, "CalculateBones: the lock is not EnterCriticalSection"); goto done; }
	if ((uint32_t)m.cap['a' - 'a'] != (uint32_t)-(int32_t)f->off.ik_sub || (uint32_t)m.cap['b' - 'a'] != (uint32_t)-(int32_t)f->off.ik_sub) {
		fail(f, "CalculateBones: primary base not at -%u", f->off.ik_sub); goto done;
	}
	{
		zgo_match m2;
		uint32_t at = zgo_pat_find(im, calc + m.len, 0x60, P_CALC_TIME, &m2);
		if (!at || m2.cap['t' - 'a'] != f->off.ucalc_time) { fail(f, "CalculateBones: UCalc_Time store not found"); goto done; }
		at = zgo_pat_find(im, calc + m.len, 0x180, P_CALC_CB, &m2);
		if (!at) { fail(f, "CalculateBones: Update_Callback call not found"); goto done; }
		f->off.cb = (uint32_t)m2.cap['c' - 'a'];
		at = zgo_pat_find(im, at, 0x40, P_CALC_LEAVE, &m2);
		if (!at || m2.cap['m' - 'a'] != f->off.mutex || !zgo_pe_iat_is(im, (uint32_t)m2.cap['l' - 'a'], "kernel32.dll", "LeaveCriticalSection")) {
			fail(f, "CalculateBones: LeaveCriticalSection(UCalc_Mutex) not found after the callback"); goto done;
		}
	}
	if (!target(f, im, ZGO_T_CALC, "CalculateBones", calc, 5)) goto done;

	/* member offsets from accessors, cross-checked */
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_CALC_INVAL), P_INVAL, &m, "CalculateBones_Invalidate")) goto done;
	if (m.cap['t' - 'a'] != f->off.ucalc_time) { fail(f, "CalculateBones_Invalidate writes 0x%llx, not UCalc_Time", (unsigned long long)m.cap['t' - 'a']); goto done; }
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_BONE_INSTANCE), P_INST, &m, "LL_GetBoneInstance")) goto done;
	f->off.bone_stride = (uint32_t)m.cap['s' - 'a'];
	f->off.bone_inst = (uint32_t)m.cap['i' - 'a'];
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_BONE_COUNT), P_COUNT, &m, "LL_BoneCount")) goto done;
	f->off.bones = (uint32_t)m.cap['b' - 'a'];
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_TRANSFORM_R), P_RENDER, &m, "LL_GetTransform_R")) goto done;
	if (m.cap['s' - 'a'] != IK_BONE_INSTANCE * 8) { fail(f, "LL_GetTransform_R does not call LL_GetBoneInstance"); goto done; }
	f->off.render_xf = (uint32_t)(-(int32_t)(int8_t)(uint8_t)m.cap['r' - 'a']);
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_SET_CALLBACK), P_SETCB, &m, "Callback")) goto done;
	if (m.cap['c' - 'a'] != f->off.cb) { fail(f, "Callback() writes 0x%llx, CalculateBones calls 0x%x", (unsigned long long)m.cap['c' - 'a'], f->off.cb); goto done; }
	f->off.cb_param = (uint32_t)m.cap['p' - 'a'];
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_GET_CALLBACK), P_GET, &m, "GetUpdateCallback") || m.cap['v' - 'a'] != f->off.cb) { fail(f, "GetUpdateCallback mismatch"); goto done; }
	if (!need(f, im, slot_fn(im, k.vt_ik, IK_GET_CB_PARAM), P_GET, &m, "GetUpdateCallbackParam") || m.cap['v' - 'a'] != f->off.cb_param) { fail(f, "GetUpdateCallbackParam mismatch"); goto done; }
	if (f->off.bone_stride < 0xC0 || f->off.bone_stride > 0x400 || f->off.render_xf + 64 > f->off.bone_stride) {
		fail(f, "CBoneInstance layout implausible (stride 0x%x, render 0x%x)", f->off.bone_stride, f->off.render_xf); goto done;
	}

	/* LL_BoneID(LPCSTR) */
	uint32_t bid = slot_fn(im, k.vt_ik, IK_LL_BONEID_STR);
	if (!need(f, im, bid, P_BONEID, &m, "LL_BoneID(LPCSTR)")) goto done;
	if (!target(f, im, ZGO_T_BONEID, "LL_BoneID(LPCSTR)", bid, 5)) goto done;

	/* Depart */
	uint32_t dep = slot_fn(im, k.vt_pr, PR_DEPART);
	if (!need(f, im, dep, P_DEPART, &m, "Depart")) goto done;
	f->rva_depart_cs = (uint32_t)m.cap['g' - 'a'];
	if (!zgo_pe_iat_is(im, (uint32_t)m.cap['e' - 'a'], "kernel32.dll", "EnterCriticalSection")) { fail(f, "Depart: the lock is not EnterCriticalSection"); goto done; }
	{
		zgo_match m2;
		uint32_t at = zgo_pat_find(im, dep + m.len, 0x60, P_DEPART_LEAVE, &m2);
		if (!at || m2.cap['h' - 'a'] != f->rva_depart_cs || !zgo_pe_iat_is(im, (uint32_t)m2.cap['l' - 'a'], "kernel32.dll", "LeaveCriticalSection")) {
			fail(f, "Depart: LeaveCriticalSection not found"); goto done;
		}
		if (!zgo_pat_find(im, at, 0x30, P_DEPART_MASK, &m2)) { fail(f, "Depart: bone mask reset not found"); goto done; }
	}
	if (!target(f, im, ZGO_T_DEPART, "Depart", dep, 5)) goto done;

done:
	if (f->ok) {
		for (int i = 0; i < ZGO_T_COUNT; i++)
			rep(f, "  hook %-18s rva 0x%07x  (first instruction %d bytes)  verified\n", f->t[i].name, f->t[i].rva, f->t[i].steal);
		rep(f, "  offsets (from IKinematics*): ik_sub 0x%x  UCalc_Time 0x%x  UCalc_Mutex 0x%x  bone_instances 0x%x  bones 0x%x  Update_Callback 0x%x  param 0x%x\n",
		    f->off.ik_sub, f->off.ucalc_time, f->off.mutex, f->off.bone_inst, f->off.bones, f->off.cb, f->off.cb_param);
		rep(f, "  CBoneInstance: size 0x%x, mTransform +0x0, mRenderTransform +0x%x\n", f->off.bone_stride, f->off.render_xf);
		rep(f, "  globals: Device.dwTimeGlobal rva 0x%07x, wallmark lock rva 0x%07x\n", f->rva_time_global, f->rva_depart_cs);
		rep(f, "  result: SUPPORTED\n");
	} else {
		rep(f, "  result: UNSUPPORTED EXE: %s\n", f->why);
	}
	return f->ok;
}
