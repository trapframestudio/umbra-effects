/*
 * zgo_native tests (run under Wine by native/tests/run.sh).
 *
 *   zgo_native_test.exe finder <exe>...      the finder on each exe, mapped two ways
 *                                            (LoadLibraryEx as image resource, manual map);
 *                                            prefix a path with '-' to expect "unsupported"
 *   zgo_native_test.exe mutate <exe>         one-byte corruptions must all fail closed
 *   zgo_native_test.exe math                 the bone maths against a double-precision reference
 *   zgo_native_test.exe e2e <exe> <dll>      the shipped DLL on the real engine code: the exe is
 *                                            mapped at its preferred base, the hooks go into its
 *                                            real CalculateBones / LL_BoneID / Depart, and fake
 *                                            kinematics objects run through them (also with
 *                                            threads while the hooks are put in and taken out)
 *
 * Every mode prints PASS or FAIL lines and exits 0 only if everything passed.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "zgo_bones.h"
#include "zgo_finder.h"
#include "zgo_native.h"
#include "zgo_pe.h"

static int g_fail, g_pass;
#define CHECK(cond, ...) do { if (cond) { g_pass++; } else { g_fail++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---------------------------------------------------------------- mapping */

typedef struct file_buf { uint8_t* p; size_t n; } file_buf;

static int read_file(const char* path, file_buf* f)
{
	FILE* h = fopen(path, "rb");
	if (!h) return 0;
	fseek(h, 0, SEEK_END);
	long n = ftell(h);
	fseek(h, 0, SEEK_SET);
	f->p = (uint8_t*)malloc((size_t)n);
	f->n = (size_t)n;
	int ok = f->p && fread(f->p, 1, (size_t)n, h) == (size_t)n;
	fclose(h);
	return ok;
}

static uint32_t r32(const uint8_t* p) { uint32_t v; memcpy(&v, p, 4); return v; }
static uint16_t r16(const uint8_t* p) { uint16_t v; memcpy(&v, p, 2); return v; }

/* sections at their RVAs; at = NULL: anywhere (malloc), else VirtualAlloc at that address */
static uint8_t* manual_map(const file_buf* f, void* at, uint32_t* size_out)
{
	const uint8_t* nt = f->p + r32(f->p + 0x3c);
	uint16_t nsec = r16(nt + 6), optsz = r16(nt + 20);
	const uint8_t* opt = nt + 24;
	uint32_t size = r32(opt + 56), hdrs = r32(opt + 60);
	uint8_t* m;
	if (at) m = (uint8_t*)VirtualAlloc(at, size, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
	else m = (uint8_t*)calloc(1, size);
	if (!m || (at && m != at)) return NULL;
	memcpy(m, f->p, hdrs < f->n ? hdrs : f->n);
	const uint8_t* sh = opt + optsz;
	for (int i = 0; i < nsec; i++, sh += 40) {
		uint32_t vsz = r32(sh + 8), rva = r32(sh + 12), rawsz = r32(sh + 16), raw = r32(sh + 20);
		uint32_t n = rawsz < vsz ? rawsz : vsz;
		if (raw + (size_t)n <= f->n && rva + (size_t)n <= size) memcpy(m + rva, f->p + raw, n);
	}
	*size_out = size;
	return m;
}

/* ---------------------------------------------------------------- finder mode */

static int same_result(const zgo_finder* a, const zgo_finder* b)
{
	if (a->ok != b->ok) return 0;
	if (!a->ok) return 1;
	for (int i = 0; i < ZGO_T_COUNT; i++) if (a->t[i].rva != b->t[i].rva) return 0;
	return memcmp(&a->off, &b->off, sizeof a->off) == 0 && a->rva_time_global == b->rva_time_global;
}

static zgo_finder g_fa, g_fb;

static void finder_one(const char* arg)
{
	int expect_ok = arg[0] != '-';
	const char* path = expect_ok ? arg : arg + 1;
	const char* name = strrchr(path, '/');
	if (!name) name = strrchr(path, '\\');
	name = name ? name + 1 : path;
	printf("\n=== %s (expect %s)\n", name, expect_ok ? "supported" : "unsupported");

	/* 1: the Windows loader maps it as an image resource (read only, no code runs) */
	HMODULE h = LoadLibraryExA(path, NULL, LOAD_LIBRARY_AS_IMAGE_RESOURCE);
	CHECK(h != NULL, "%s: LoadLibraryEx(AS_IMAGE_RESOURCE) failed (%lu)", name, GetLastError());
	if (!h) return;
	const uint8_t* base = (const uint8_t*)((uintptr_t)h & ~(uintptr_t)3);
	zgo_image im;
	const char* why;
	int pe = zgo_pe_open(&im, base, &why);
	CHECK(pe == 0, "%s: PE: %s", name, why);
	DWORD t0 = GetTickCount();
	zgo_find(&im, &g_fa);
	DWORD t1 = GetTickCount();
	fputs(g_fa.report, stdout);
	printf("  (finder took %lu ms)\n", (unsigned long)(t1 - t0));
	CHECK(g_fa.ok == expect_ok, "%s: finder said %s (%s)", name, g_fa.ok ? "supported" : "unsupported", g_fa.why);
	if (!g_fa.ok) CHECK(g_fa.why[0] != 0, "%s: an unsupported result names its reason", name);

	/* 2: manual map: the same answer at a different base */
	file_buf f;
	CHECK(read_file(path, &f), "%s: read", name);
	uint32_t sz;
	uint8_t* m = manual_map(&f, NULL, &sz);
	CHECK(m != NULL, "%s: manual map", name);
	if (m) {
		zgo_image im2;
		zgo_pe_open(&im2, m, &why);
		zgo_find(&im2, &g_fb);
		CHECK(same_result(&g_fa, &g_fb), "%s: manual map gives another result (%s)", name, g_fb.why);
		free(m);
	}
	free(f.p);
	FreeLibrary(h);
}

/* ---------------------------------------------------------------- mutate mode */

static void mutate(const char* path)
{
	file_buf f;
	uint32_t sz;
	CHECK(read_file(path, &f), "read %s", path);
	uint8_t* m = manual_map(&f, NULL, &sz);
	zgo_image im;
	const char* why;
	zgo_pe_open(&im, m, &why);
	zgo_finder ref;
	zgo_find(&im, &ref);
	CHECK(ref.ok, "the unmodified exe is supported");
	if (!ref.ok) return;

	struct { const char* what; uint32_t rva; } cases[] = {
		{ "CalculateBones first byte", ref.t[ZGO_T_CALC].rva },
		{ "CalculateBones UCalc_Time offset", ref.t[ZGO_T_CALC].rva + 17 },
		{ "CalculateBones mutex offset", ref.t[ZGO_T_CALC].rva + 41 },
		{ "LL_BoneID prologue", ref.t[ZGO_T_BONEID].rva + 3 },
		{ "Depart prologue", ref.t[ZGO_T_DEPART].rva + 9 },
		{ "Depart first byte", ref.t[ZGO_T_DEPART].rva },
		{ "IKinematics vtable slot 35 (CKinematicsAnimated)", ref.vt_ik[1] + 35 * 8 + 1 },
		{ "IKinematics vtable slot 5 (CKinematics)", ref.vt_ik[0] + 5 * 8 },
		{ "primary vtable slot 26 (CKinematics)", ref.vt_pr[0] + 26 * 8 },
		{ "CKinematics type descriptor name", ref.td[0] + 16 + 6 },
		{ "IKinematics vtable end (47th slot appears)", ref.vt_ik[0] + 46 * 8 },
	};
	for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; i++) {
		uint32_t at = cases[i].rva;
		uint8_t keep[8];
		memcpy(keep, m + at, 8);
		if (strstr(cases[i].what, "47th")) {
			uint64_t fn = im.pref + ref.t[ZGO_T_CALC].rva;   /* any code pointer */
			memcpy(m + at, &fn, 8);
		} else {
			m[at] ^= 0x01;
		}
		zgo_finder t;
		zgo_find(&im, &t);
		CHECK(!t.ok && t.why[0], "corrupting %s must fail closed", cases[i].what);
		printf("  %-50s -> %s\n", cases[i].what, t.ok ? "SUPPORTED (bad)" : t.why);
		memcpy(m + at, keep, 8);
	}
	/* the import name of EnterCriticalSection */
	{
		uint8_t* p = NULL;
		for (uint32_t a = 0; a + 21 < sz && !p; a++) if (memcmp(m + a, "EnterCriticalSection", 21) == 0) p = m + a;
		CHECK(p != NULL, "found the import name");
		if (p) {
			p[0] = 'X';
			zgo_finder t;
			zgo_find(&im, &t);
			CHECK(!t.ok, "renaming the EnterCriticalSection import must fail closed");
			printf("  %-50s -> %s\n", "EnterCriticalSection import renamed", t.ok ? "SUPPORTED (bad)" : t.why);
			p[0] = 'E';
		}
	}
	/* broken images never crash */
	{
		zgo_image bad;
		const char* w;
		uint8_t junk[4096];
		for (int i = 0; i < 4096; i++) junk[i] = (uint8_t)(i * 37 + 11);
		CHECK(zgo_pe_open(&bad, junk, &w) != 0, "junk is not a PE");
		uint32_t keep = r32(m + r32(m + 0x3c) + 24 + 56);
		uint32_t small = 0x2000;
		memcpy(m + r32(m + 0x3c) + 24 + 56, &small, 4);
		CHECK(zgo_pe_open(&bad, m, &w) != 0, "SizeOfImage smaller than the sections is refused (%s)", w);
		memcpy(m + r32(m + 0x3c) + 24 + 56, &keep, 4);
		zgo_finder t;
		zgo_find(&im, &t);
		CHECK(t.ok, "restored image is supported again");
	}
	free(m);
	free(f.p);
}

/* ---------------------------------------------------------------- maths */

typedef struct dm { double v[12]; } dm;

static dm d_compose(dm a, dm b)
{
	dm r;
	for (int row = 0; row < 4; row++)
		for (int c = 0; c < 3; c++)
			r.v[row * 3 + c] = b.v[row * 3] * a.v[c] + b.v[row * 3 + 1] * a.v[3 + c] + b.v[row * 3 + 2] * a.v[6 + c] + (row == 3 ? a.v[9 + c] : 0);
	return r;
}

static dm d_invert(dm m)
{
	/* Gauss-Jordan on the 3x3, then the translation */
	double a[3][6];
	for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) { a[i][j] = m.v[i * 3 + j]; a[i][3 + j] = i == j; }
	for (int c = 0; c < 3; c++) {
		int p = c;
		for (int r = c + 1; r < 3; r++) if (fabs(a[r][c]) > fabs(a[p][c])) p = r;
		for (int j = 0; j < 6; j++) { double t = a[c][j]; a[c][j] = a[p][j]; a[p][j] = t; }
		double d = a[c][c];
		for (int j = 0; j < 6; j++) a[c][j] /= d;
		for (int r = 0; r < 3; r++) if (r != c) { double k = a[r][c]; for (int j = 0; j < 6; j++) a[r][j] -= k * a[c][j]; }
	}
	dm r;
	for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) r.v[i * 3 + j] = a[i][3 + j];
	for (int c = 0; c < 3; c++) r.v[9 + c] = -(m.v[9] * r.v[c] + m.v[10] * r.v[3 + c] + m.v[11] * r.v[6 + c]);
	return r;
}

static dm d_from(const float* f) { dm r; for (int i = 0; i < 12; i++) r.v[i] = f[i]; return r; }
static double d_diff(dm a, const float* f) { double e = 0; for (int i = 0; i < 12; i++) e = fmax(e, fabs(a.v[i] - f[i])); return e; }

static void rot(float* l, double ax, double ay, double az, double ang, double sx, double sy, double sz, double tx, double ty, double tz)
{
	double n = sqrt(ax * ax + ay * ay + az * az);
	ax /= n; ay /= n; az /= n;
	double c = cos(ang), s = sin(ang), t = 1 - c;
	/* rows = images of the local axes (row-vector convention) */
	double R[3][3] = {
		{ t * ax * ax + c,      t * ax * ay + s * az, t * ax * az - s * ay },
		{ t * ax * ay - s * az, t * ay * ay + c,      t * ay * az + s * ax },
		{ t * ax * az + s * ay, t * ay * az - s * ax, t * az * az + c },
	};
	double S[3] = { sx, sy, sz };
	for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) l[i * 3 + j] = (float)(R[i][j] * S[i]);
	l[9] = (float)tx; l[10] = (float)ty; l[11] = (float)tz;
}

static void math_tests(void)
{
	srand(7);
	double worst = 0;
	for (int it = 0; it < 2000; it++) {
		float a[12], b[12], o[12], inv[12];
		rot(a, rand() % 100 - 50, rand() % 100 - 50, rand() % 100 + 1, (rand() % 628) / 100.0,
		    0.5 + (rand() % 100) / 100.0, 0.5 + (rand() % 100) / 100.0, 0.5 + (rand() % 100) / 100.0,
		    (rand() % 200 - 100) / 50.0, (rand() % 200 - 100) / 50.0, (rand() % 200 - 100) / 50.0);
		rot(b, rand() % 100 + 1, rand() % 100 - 50, rand() % 100 - 50, (rand() % 628) / 100.0, 1, 1, 1,
		    (rand() % 200 - 100) / 50.0, 0, (rand() % 200 - 100) / 50.0);
		zgo_m_compose(o, a, b);
		worst = fmax(worst, d_diff(d_compose(d_from(a), d_from(b)), o));
		CHECK(zgo_m_invert(inv, a), "invertible");
		worst = fmax(worst, d_diff(d_invert(d_from(a)), inv));
		float id[12];
		zgo_m_compose(id, a, inv);
		dm I = { { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 } };
		worst = fmax(worst, d_diff(I, id));
	}
	printf("  compose / invert: worst error %.2e over 2000 random affine pairs\n", worst);
	CHECK(worst < 2e-4, "matrix maths within 2e-4 (%.2e)", worst);
	float z[12] = { 0 }, inv[12];
	CHECK(!zgo_m_invert(inv, z), "a singular matrix is refused");
}

/* ---------------------------------------------------------------- e2e */

/* fake engine objects in the layout the finder read out of the exe */
#define NBONES 12
typedef struct fake {
	uint8_t*          p;          /* CKinematics* (primary base) */
	uint8_t*          ik;         /* IKinematics* = p + ik_sub */
	uint8_t*          inst;       /* bone_instances */
	void*             bones_vec[3];
	void*             bone_data[NBONES];
	void*             accel[3];
	CRITICAL_SECTION  cs;
	void*             vt_ik[64];
	void*             vt_pr[64];
	volatile LONG     recomputes, callbacks;
	int               seed;
} fake;

static const zgo_finder* E;     /* the finder result on the mapped exe */
static volatile uint32_t* g_time_global;
static volatile LONG g_fresh_calls;

static void fresh_m(int seed, int frame, int b, float* m16)
{
	/* "animation": some rotation and translation per bone and frame */
	float l[12];
	rot(l, 0.3 + b, 1.0, 0.2 * seed + 0.1, 0.01 * frame + 0.2 * b, 1, 1, 1, 0.1 * b, 0.05 * seed, 0.001 * frame);
	memset(m16, 0, 64);
	memcpy(m16, l, 12); memcpy(m16 + 4, l + 3, 12); memcpy(m16 + 8, l + 6, 12); memcpy(m16 + 12, l + 9, 12);
	m16[15] = 1;
}

static const float M2B[12] = { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0.0f, 0.0f, -0.05f };

static void m16_to12(float* d, const float* m) { memcpy(d, m, 12); memcpy(d + 3, m + 4, 12); memcpy(d + 6, m + 8, 12); memcpy(d + 9, m + 12, 12); }
static void m12_to16(float* m, const float* s) { memcpy(m, s, 12); memcpy(m + 4, s + 3, 12); memcpy(m + 8, s + 6, 12); memcpy(m + 12, s + 9, 12); }

static fake* fake_of(void* ik) { return *(fake**)((uint8_t*)ik + E->off.cb_param); }

/* IKinematics::Bone_Calculate(CBoneData*, Fmatrix*): writes every bone as the engine would */
static void stub_bone_calculate(void* ik, void* bd, void* parent)
{
	fake* f = fake_of(ik);
	uint32_t now = *g_time_global;
	for (int b = 0; b < NBONES; b++) {
		float* M = (float*)(f->inst + (size_t)b * E->off.bone_stride);
		float* R = (float*)(f->inst + (size_t)b * E->off.bone_stride + E->off.render_xf);
		fresh_m(f->seed, (int)now, b, M);
		float m[12], r[12];
		m16_to12(m, M);
		zgo_m_compose(r, m, M2B);
		m12_to16(R, r);
		R[15] = 1;
	}
	InterlockedIncrement(&f->recomputes);
	InterlockedIncrement(&g_fresh_calls);
}

static void stub_update_callback(void* ik) { InterlockedIncrement(&fake_of(ik)->callbacks); }

static void* g_trap_name;
static void trap_import(void)
{
	printf("FAIL: the engine code called an import the test did not provide\n");
	fflush(stdout);
	ExitProcess(99);
}

static fake* fake_new(const uint8_t* exe, int seed)
{
	const zgo_offsets* o = &E->off;
	fake* f = (fake*)calloc(1, sizeof *f);
	f->seed = seed;
	f->p = (uint8_t*)_aligned_malloc(0x400, 16);
	memset(f->p, 0, 0x400);
	f->ik = f->p + o->ik_sub;
	f->inst = (uint8_t*)_aligned_malloc((size_t)NBONES * o->bone_stride, 16);
	memset(f->inst, 0, (size_t)NBONES * o->bone_stride);
	for (int b = 0; b < NBONES; b++) f->bone_data[b] = calloc(1, 256);
	f->bones_vec[0] = &f->bone_data[0];
	f->bones_vec[1] = &f->bone_data[NBONES];
	f->bones_vec[2] = &f->bone_data[NBONES];
	f->accel[0] = f->accel[1] = f->accel[2] = &f->accel[2];   /* an empty name map */
	InitializeCriticalSection(&f->cs);
	/* vtables: copies of the real ones, Bone_Calculate swapped for the stub */
	const uint8_t* vik = exe + E->vt_ik[1];
	const uint8_t* vpr = exe + E->vt_pr[1];
	memcpy(f->vt_ik, vik, E->ik_slots * 8);
	memcpy(f->vt_pr, vpr, 33 * 8);
	f->vt_ik[0] = (void*)stub_bone_calculate;
	*(void**)f->p = f->vt_pr;
	*(void**)f->ik = f->vt_ik;
	*(void**)(f->ik + o->mutex) = &f->cs;
	*(void**)(f->ik + o->bone_inst) = f->inst;
	*(void**)(f->ik + o->bones) = f->bones_vec;
	*(void**)(f->ik + 0xe0) = f->accel;                 /* LL_BoneID(LPCSTR)'s name map */
	*(int32_t*)(f->ik + 0xf8) = -1000000000;            /* UCalc_Visibox: never the box update */
	*(void**)(f->ik + o->cb) = (void*)stub_update_callback;
	*(void**)(f->ik + o->cb_param) = f;
	return f;
}

typedef void     (*calc_fn)(void* ik, int force);
typedef uint16_t (*boneid_fn)(void* ik, const char* name);
typedef void     (*depart_fn)(void* p);

static void calc(fake* f, int force) { ((calc_fn)f->vt_ik[35])(f->ik, force); }
static uint16_t bone_id(fake* f, const char* n) { return ((boneid_fn)f->vt_ik[5])(f->ik, n); }
static void depart(fake* f) { ((depart_fn)f->vt_pr[26])(f->p); }

/* the DLL's exports */
static uint32_t    (*x_abi)(void);
static const char* (*x_version)(void);
static int32_t     (*x_init)(void);
static int32_t     (*x_init_module)(uint64_t);
static uint32_t    (*x_caps)(void);
static uint32_t    (*x_hooks)(void);
static int32_t     (*x_enable)(uint32_t);
static void        (*x_shutdown)(void);
static const char* (*x_status)(void);
static int32_t     (*x_report)(char*, int32_t);
static int32_t     (*x_log_next)(char*, int32_t);
static void        (*x_stats)(zgo_stats*);
static uint64_t    (*x_take)(uint32_t);
static int32_t     (*x_bind)(uint64_t);
static int32_t     (*x_state)(int32_t);
static int32_t     (*x_begin)(int32_t);
static int32_t     (*x_group)(int32_t, uint16_t, const float*, const uint16_t*, int32_t);
static int32_t     (*x_commit)(int32_t);
static int32_t     (*x_unbind)(int32_t);
static void        (*x_clear_all)(void);

static void drain_log(void)
{
	char line[256];
	while (x_log_next(line, sizeof line) > 0) printf("  [dll] %s\n", line);
}

/* the op set the e2e uses: bend (with followers), crush, move */
typedef struct opdef { uint16_t driver; float l[12]; uint16_t members[6]; int n; } opdef;
static opdef OPS_A[3], OPS_B[1];

static void make_ops(void)
{
	rot(OPS_A[0].l, 0, 0, 1, 0.6, 1, 1, 1, 0, 0, 0);
	OPS_A[0].driver = 2; OPS_A[0].members[0] = 2; OPS_A[0].members[1] = 3; OPS_A[0].members[2] = 4; OPS_A[0].n = 3;
	rot(OPS_A[1].l, 1, 0, 0, 0.0, 1, 0.5, 1, 0, 0, 0);
	OPS_A[1].driver = 5; OPS_A[1].members[0] = 5; OPS_A[1].n = 1;
	rot(OPS_A[2].l, 0, 1, 0, 0.3, 1, 1, 1, 0, 0.1, 0);
	OPS_A[2].driver = 6; OPS_A[2].members[0] = 6; OPS_A[2].members[1] = 7; OPS_A[2].members[2] = 3; OPS_A[2].n = 3;
	rot(OPS_B[0].l, 1, 1, 0, -0.9, 1, 1, 1, 0, 0, 0);
	OPS_B[0].driver = 9; OPS_B[0].members[0] = 9; OPS_B[0].members[1] = 10; OPS_B[0].n = 2;
}

static int commit_ops(int32_t h, const opdef* ops, int n)
{
	if (x_begin(h) != 0) return 0;
	for (int i = 0; i < n; i++) if (x_group(h, ops[i].driver, ops[i].l, ops[i].members, ops[i].n) <= 0) return 0;
	return x_commit(h) == 0;
}

/* expected matrices: fresh ones for the frame, the groups applied in order (double precision) */
static void expected(int seed, int frame, const opdef* ops, int n, dm* em, dm* er)
{
	for (int b = 0; b < NBONES; b++) {
		float m16[16], m[12];
		fresh_m(seed, frame, b, m16);
		m16_to12(m, m16);
		em[b] = d_from(m);
		er[b] = d_compose(em[b], d_from(M2B));
	}
	for (int g = 0; g < n; g++) {
		dm drv = em[ops[g].driver];
		dm d = d_compose(drv, d_compose(d_from(ops[g].l), d_invert(drv)));
		for (int j = 0; j < ops[g].n; j++) {
			int b = ops[g].members[j];
			em[b] = d_compose(d, em[b]);
			er[b] = d_compose(d, er[b]);
		}
	}
}

static double check_bones(fake* f, int frame, const opdef* ops, int n)
{
	dm em[NBONES], er[NBONES];
	expected(f->seed, frame, ops, n, em, er);
	double worst = 0;
	for (int b = 0; b < NBONES; b++) {
		float m[12], r[12];
		m16_to12(m, (float*)(f->inst + (size_t)b * E->off.bone_stride));
		m16_to12(r, (float*)(f->inst + (size_t)b * E->off.bone_stride + E->off.render_xf));
		worst = fmax(worst, fmax(d_diff(em[b], m), d_diff(er[b], r)));
	}
	return worst;
}

static int32_t bind_fake(fake* f, uint32_t token)
{
	char name[32];
	snprintf(name, sizeof name, "\1zgo:%u", token);
	uint16_t r = bone_id(f, name);
	if (r != 0xFFFF) return -100;
	uint64_t k = x_take(token);
	if (k != (uint64_t)(uintptr_t)f->ik) return -101;
	return x_bind(k);
}

/* threads for the stress run */
static volatile LONG g_stop;
static fake* g_tf[4];
static DWORD WINAPI ticker(LPVOID p)
{
	(void)p;
	while (!g_stop) { InterlockedIncrement((volatile LONG*)g_time_global); Sleep(0); }
	return 0;
}
static DWORD WINAPI caller(LPVOID p)
{
	fake* f = g_tf[(intptr_t)p % 4];
	LONG n = 0;
	while (!g_stop) {
		calc(f, (n & 1));
		if ((n & 63) == 0) bone_id(f, "bip01_head");
		n++;
	}
	return (DWORD)n;
}

static void e2e(const char* exe_path, const char* dll_path)
{
	file_buf fb;
	CHECK(read_file(exe_path, &fb), "read the exe");
	const uint8_t* nt = fb.p + r32(fb.p + 0x3c);
	uint64_t pref;
	memcpy(&pref, nt + 24 + 24, 8);
	uint32_t size = 0;
	uint8_t* exe = manual_map(&fb, (void*)(uintptr_t)pref, &size);
	CHECK(exe != NULL, "map the exe at its preferred base 0x%llx (relocations are stripped)", (unsigned long long)pref);
	if (!exe) return;
	printf("  exe mapped at %p, 0x%x bytes\n", (void*)exe, size);

	/* imports: kernel32 for real (the critical sections), everything else traps */
	zgo_image im;
	const char* why;
	zgo_pe_open(&im, exe, &why);
	HMODULE k32 = GetModuleHandleA("kernel32.dll");
	int nk = 0, nt_ = 0;
	for (uint32_t d = im.import_rva; ; d += 20) {
		uint32_t oft = zgo_rd32(&im, d), name = zgo_rd32(&im, d + 12), ft = zgo_rd32(&im, d + 16);
		if (!name && !ft) break;
		int is_k32 = _stricmp((const char*)exe + name, "KERNEL32.dll") == 0;
		for (uint32_t i = 0; ; i++) {
			uint64_t e = zgo_rd64(&im, (oft ? oft : ft) + i * 8);
			if (!e) break;
			void* fn = (void*)trap_import;
			if (is_k32 && !(e >> 63)) {
				FARPROC p = GetProcAddress(k32, (const char*)exe + (uint32_t)e + 2);
				if (p) { fn = (void*)p; nk++; }
			}
			memcpy(exe + ft + i * 8, &fn, 8);
			nt_++;
		}
	}
	(void)g_trap_name;
	printf("  imports: %d resolved from kernel32, %d trap\n", nk, nt_ - nk);

	HMODULE dll = LoadLibraryA(dll_path);
	CHECK(dll != NULL, "LoadLibrary %s (%lu)", dll_path, GetLastError());
	if (!dll) return;
#define GET(var, name) do { *(FARPROC*)&var = GetProcAddress(dll, name); CHECK(var != NULL, "export %s", name); if (!var) return; } while (0)
	GET(x_abi, "zgo_abi"); GET(x_version, "zgo_version"); GET(x_init, "zgo_init"); GET(x_init_module, "zgo_init_module");
	GET(x_caps, "zgo_caps"); GET(x_hooks, "zgo_hooks"); GET(x_enable, "zgo_enable"); GET(x_shutdown, "zgo_shutdown");
	GET(x_status, "zgo_status"); GET(x_report, "zgo_report"); GET(x_log_next, "zgo_log_next"); GET(x_stats, "zgo_get_stats");
	GET(x_take, "zgo_capture_take"); GET(x_bind, "zgo_bones_bind"); GET(x_state, "zgo_bones_state");
	GET(x_begin, "zgo_bones_begin"); GET(x_group, "zgo_bones_group"); GET(x_commit, "zgo_bones_commit");
	GET(x_unbind, "zgo_bones_unbind"); GET(x_clear_all, "zgo_bones_clear_all");

	printf("  %s\n", x_version());
	CHECK(x_abi() == ZGO_NATIVE_ABI, "ABI %u", x_abi());

	/* before anything: everything refuses */
	CHECK(x_enable(ZGO_CAP_BONES) == ZGO_E_NOT_INIT, "enable before init is refused");
	CHECK(x_bind(1234) == ZGO_E_NOT_INIT, "bind before init is refused");
	CHECK(x_caps() == 0, "no caps before init");

	/* the test exe itself is not the game: fail closed */
	int32_t r = x_init();
	printf("  zgo_init on the test exe: %d, %s\n", r, x_status());
	CHECK(r == ZGO_E_UNSUPPORTED && strstr(x_status(), "unsupported"), "zgo_init on a foreign exe fails closed");
	CHECK(x_caps() == 0 && x_enable(ZGO_CAP_BONES) == ZGO_E_UNSUPPORTED, "nothing can be enabled on a foreign exe");
	CHECK(x_init() == r, "zgo_init keeps its first answer");
	drain_log();

	/* the mapped game exe */
	r = x_init_module((uint64_t)(uintptr_t)exe);
	CHECK(r == 0, "zgo_init_module on the mapped game exe: %d (%s)", r, x_status());
	char rep[8192];
	x_report(rep, sizeof rep);
	fputs(rep, stdout);
	CHECK(x_caps() == (ZGO_CAP_FINDER | ZGO_CAP_BONES), "caps 0x%x", x_caps());
	drain_log();
	static zgo_finder fres;
	zgo_find(&im, &fres);
	E = &fres;
	CHECK(E->ok, "finder (test copy) agrees");
	if (!E->ok) return;
	g_time_global = (volatile uint32_t*)(exe + E->rva_time_global);
	*(void**)(exe + E->rva_depart_cs) = calloc(1, sizeof(CRITICAL_SECTION));
	InitializeCriticalSection(*(CRITICAL_SECTION**)(exe + E->rva_depart_cs));
	make_ops();

	fake* a = fake_new(exe, 1);
	fake* b = fake_new(exe, 2);
	*g_time_global = 1000;

	/* unhooked: the real code runs our stubs */
	calc(a, 1);
	CHECK(a->recomputes == 1 && a->callbacks == 1, "unhooked CalculateBones recomputes and calls back (%ld, %ld)", a->recomputes, a->callbacks);
	CHECK(*(uint32_t*)(a->ik + E->off.ucalc_time) == 1000, "UCalc_Time set");
	calc(a, 1);
	CHECK(a->recomputes == 1, "same tick: the engine's early-out");
	CHECK(bone_id(a, "\1zgo:5") == 0xFFFF && x_take(5) == 0, "no capture without the hook");
	CHECK(x_bind((uint64_t)(uintptr_t)a->ik) == ZGO_E_NOT_ENABLED, "bind before enable is refused");

	/* hooks in */
	uint8_t before[3][8];
	for (int i = 0; i < 3; i++) memcpy(before[i], exe + E->t[i].rva, 8);
	r = x_enable(ZGO_CAP_BONES);
	drain_log();
	CHECK(r == (int32_t)(ZGO_CAP_FINDER | ZGO_CAP_BONES), "enable -> 0x%x", r);
	for (int i = 0; i < 3; i++) {
		CHECK(exe[E->t[i].rva] == 0xE9, "%s starts with a jmp now", E->t[i].name);
		CHECK(memcmp(exe + E->t[i].rva + 5, before[i] + 5, 3) == 0, "%s: bytes 5..7 untouched", E->t[i].name);
	}

	/* hooked, nothing bound: identical behaviour */
	*g_time_global = 1001;
	calc(a, 1);
	CHECK(a->recomputes == 2 && a->callbacks == 2, "hooked CalculateBones still runs the original (%ld)", a->recomputes);
	CHECK(check_bones(a, 1001, NULL, 0) < 1e-6, "nothing bound: bones untouched");
	CHECK(bone_id(a, "bip01_spine") == 0xFFFF, "LL_BoneID passes other names through");

	/* capture + bind */
	int32_t ha = bind_fake(a, 7);
	CHECK(ha > 0, "capture and bind a: %d", ha);
	CHECK(x_state(ha) == 1, "live");
	CHECK(x_bind((uint64_t)(uintptr_t)a->ik) == ha, "binding again gives the same handle");
	CHECK(commit_ops(ha, OPS_A, 3), "commit bend / crush / move");

	/* not recomputed (same tick): the op set still applies, from the remembered fresh state */
	calc(a, 1);
	double e = check_bones(a, 1001, OPS_A, 3);
	CHECK(e < 1e-4, "ops applied after an early-out (error %.2e)", e);
	calc(a, 1); calc(a, 0); calc(a, 1);
	e = check_bones(a, 1001, OPS_A, 3);
	CHECK(e < 1e-4, "early-outs never apply twice (error %.2e)", e);
	/* recomputed */
	for (int t = 1002; t < 1010; t++) {
		*g_time_global = (uint32_t)t;
		calc(a, 1);
		calc(a, 1);
		e = check_bones(a, t, OPS_A, 3);
		CHECK(e < 1e-4, "frame %d: fresh bones + ops (error %.2e)", t, e);
	}
	/* the object next to it is not touched */
	calc(b, 1);
	CHECK(check_bones(b, 1009, NULL, 0) < 1e-6, "an unbound object is left alone");

	/* a new op set without a recompute: from the fresh state, not on top */
	CHECK(commit_ops(ha, OPS_B, 1), "commit another op set");
	calc(a, 1);
	e = check_bones(a, 1009, OPS_B, 1);
	CHECK(e < 1e-4, "switching op sets restores the dropped bones and applies the new ones (error %.2e)", e);
	/* empty op set: back to the engine's bones */
	CHECK(x_begin(ha) == 0 && x_commit(ha) == 0, "empty op set");
	calc(a, 1);
	CHECK(check_bones(a, 1009, NULL, 0) < 1e-6, "empty op set restores every bone");
	CHECK(commit_ops(ha, OPS_A, 3), "ops again");
	*g_time_global = 1010;
	calc(a, 1);
	CHECK(check_bones(a, 1010, OPS_A, 3) < 1e-4, "applied again");

	/* bad input */
	float l[12] = { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
	uint16_t bad[1] = { NBONES + 3 };
	CHECK(x_begin(ha) == 0, "begin");
	CHECK(x_group(ha, 1, l, bad, 1) == ZGO_E_ARG, "a bone id past the skeleton is refused");
	CHECK(x_group(ha, NBONES, l, bad, 1) == ZGO_E_ARG, "a driver past the skeleton is refused");
	l[0] = NAN;
	uint16_t one[1] = { 1 };
	CHECK(x_group(ha, 1, l, one, 1) == ZGO_E_ARG, "a NaN transform is refused");
	CHECK(x_group(ha + 256, 1, l, one, 1) == ZGO_E_HANDLE, "a stale handle is refused");
	CHECK(commit_ops(ha, OPS_A, 3), "ops again");

	/* Depart: the engine releases the model */
	depart(a);
	CHECK(x_state(ha) == 0, "Depart marks the binding gone");
	*g_time_global = 1011;
	calc(a, 1);
	CHECK(check_bones(a, 1011, NULL, 0) < 1e-6, "a departed model is never touched again");
	CHECK(x_commit(ha) == ZGO_E_ARG || x_begin(ha) == ZGO_E_DEAD, "a departed binding refuses new ops");
	/* the pooled model comes back for someone else: a fresh binding */
	int32_t ha2 = bind_fake(a, 8);
	CHECK(ha2 > 0 && ha2 != ha, "rebinding a returned model gives a new handle (%d, was %d)", ha2, ha);
	CHECK(x_state(ha) == ZGO_E_HANDLE, "the old handle is stale");
	CHECK(x_unbind(ha2) == 0 && x_state(ha2) == ZGO_E_HANDLE, "unbind");

	zgo_stats st;
	x_stats(&st);
	printf("  stats: calls %llu matched %llu written %llu kept %llu rejected %llu captures %llu departs %llu bound %u hooks 0x%x\n",
	       (unsigned long long)st.calc_calls, (unsigned long long)st.calc_matched, (unsigned long long)st.bones_written,
	       (unsigned long long)st.bones_kept, (unsigned long long)st.rejected, (unsigned long long)st.captures,
	       (unsigned long long)st.departs, st.bound, st.hooks);
	CHECK(st.departs >= 1 && st.captures >= 2 && st.bones_written > 0 && st.bones_kept > 0, "stats count");

	/* hooks out: the original bytes, exactly */
	r = x_enable(0);
	drain_log();
	for (int i = 0; i < 3; i++) CHECK(memcmp(exe + E->t[i].rva, before[i], 8) == 0, "%s restored", E->t[i].name);
	CHECK(x_hooks() == 0, "no hooks");

	/* ---- threads: real CalculateBones on 4 objects from 6 threads, hooks in and out 300 times */
	for (int i = 0; i < 4; i++) g_tf[i] = fake_new(exe, 10 + i);
	g_stop = 0;
	HANDLE th[8];
	th[0] = CreateThread(NULL, 0, ticker, NULL, 0, NULL);
	for (int i = 1; i < 7; i++) th[i] = CreateThread(NULL, 0, caller, (LPVOID)(intptr_t)i, 0, NULL);
	int toggles = 0, binds = 0, commits = 0;
	uint32_t token = 100;
	DWORD t0 = GetTickCount();
	for (int round = 0; round < 300; round++) {
		if (x_enable(ZGO_CAP_BONES) != (int32_t)(ZGO_CAP_FINDER | ZGO_CAP_BONES)) { CHECK(0, "re-enable in round %d", round); break; }
		toggles++;
		int32_t hs[4];
		for (int i = 0; i < 4; i++) {
			hs[i] = bind_fake(g_tf[i], ++token);
			if (hs[i] > 0) binds++;
		}
		for (int k = 0; k < 20; k++)
			for (int i = 0; i < 4; i++)
				if (hs[i] > 0 && commit_ops(hs[i], (k & 1) ? OPS_A : OPS_B, (k & 1) ? 3 : 1)) commits++;
		Sleep(round % 3);
		if (round % 7 == 3) x_unbind(hs[round % 4]);
		x_enable(0);
		toggles++;
	}
	DWORD t1 = GetTickCount();
	g_stop = 1;
	WaitForMultipleObjects(7, th, TRUE, 10000);
	LONG calls = 0;
	for (int i = 1; i < 7; i++) { DWORD c; GetExitCodeThread(th[i], &c); calls += (LONG)c; }
	printf("  threads: %d hook toggles, %d binds, %d op commits, %ld CalculateBones calls, %ld recomputes in %lu ms\n",
	       toggles, binds, commits, calls, g_fresh_calls, (unsigned long)(t1 - t0));
	CHECK(toggles == 600 && binds == 1200 && calls > 10000, "the stress run did its work");
	for (int i = 0; i < 3; i++) CHECK(memcmp(exe + E->t[i].rva, before[i], 8) == 0, "%s restored after the stress run", E->t[i].name);
	drain_log();

	/* and a clean, single-threaded check after all that */
	CHECK(x_enable(ZGO_CAP_BONES) > 0, "enable once more");
	int32_t hc = bind_fake(g_tf[0], 9999);
	CHECK(hc > 0 && commit_ops(hc, OPS_A, 3), "bind + ops");
	*g_time_global += 5;
	calc(g_tf[0], 1);
	e = check_bones(g_tf[0], (int)*g_time_global, OPS_A, 3);
	CHECK(e < 1e-4, "exact after the stress run (error %.2e)", e);
	x_shutdown();
	for (int i = 0; i < 3; i++) CHECK(memcmp(exe + E->t[i].rva, before[i], 8) == 0, "%s restored by zgo_shutdown", E->t[i].name);
	CHECK(x_hooks() == 0, "shutdown removes every hook");
	drain_log();
}

int main(int argc, char** argv)
{
	setvbuf(stdout, NULL, _IONBF, 0);
	if (argc < 2) { printf("usage: see the header of zgo_native_test.c\n"); return 2; }
	const char* mode = argv[1];
	if (strcmp(mode, "finder") == 0) for (int i = 2; i < argc; i++) finder_one(argv[i]);
	else if (strcmp(mode, "mutate") == 0 && argc > 2) mutate(argv[2]);
	else if (strcmp(mode, "math") == 0) math_tests();
	else if (strcmp(mode, "e2e") == 0 && argc > 3) e2e(argv[2], argv[3]);
	else { printf("unknown mode\n"); return 2; }
	printf("\n%s: %d checks passed, %d failed\n", mode, g_pass, g_fail);
	printf(g_fail ? "FAILED\n" : "PASSED\n");
	return g_fail ? 1 : 0;
}
