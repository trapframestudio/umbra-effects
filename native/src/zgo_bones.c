/* Bone post-processing; see zgo_bones.h */
#include "zgo_bones.h"

#include <math.h>
#include <string.h>

#define MAXB      ZGO_MAX_BONES
#define MAXG      ZGO_MAX_GROUPS
#define MAXM      96          /* members over all groups */
#define NCAPTURE  16

typedef struct grp { uint8_t driver, first, count, pad; float l[12]; } grp;

typedef struct ops {
	uint8_t  n_groups, n_bones, n_members, pad;
	uint16_t bone[MAXB];
	grp      g[MAXG];
	uint8_t  member[MAXM];     /* indices into bone[] */
} ops;

typedef struct cache_e {
	uint16_t bone;
	uint8_t  valid;
	float    in_m[12], out_m[12], in_r[12], out_r[12];
} cache_e;

typedef struct slot {
	volatile uint64_t kin;     /* IKinematics*; 0 = free */
	volatile uint32_t gen;     /* bumped on every bind */
	volatile uint32_t dead;    /* the engine released the model (Depart) */
	volatile uint32_t seq;     /* seqlock over pub */
	volatile uint32_t busy;    /* applier / binder exclusion */
	uint32_t bone_count;
	ops      pub;              /* published op set (seqlock) */
	ops      stage;            /* being built on the main thread */
	int      staging;
	cache_e  cache[MAXB];      /* applier only, under busy */
} slot;

static zgo_bones_env g_env;
static slot g_slot[ZGO_MAX_BOUND];
static volatile uint32_t g_any;       /* bound slots */
static volatile uint64_t g_bloom;     /* quick reject for unbound objects */

static struct { volatile uint32_t token; volatile uint64_t kin; } g_cap[NCAPTURE];

static volatile uint64_t st_calls, st_matched, st_written, st_kept, st_rejected, st_captures, st_departs;
#define BUMP(x, n) __atomic_fetch_add(&(x), (uint64_t)(n), __ATOMIC_RELAXED)

void zgo_bones_setup(const zgo_bones_env* env) { g_env = *env; }

/* ---------------------------------------------------------------- maths */

void zgo_m_compose(float* out, const float* a, const float* b)
{
	float r[12];
	for (int row = 0; row < 4; row++) {
		const float* v = b + row * 3;
		for (int c = 0; c < 3; c++)
			r[row * 3 + c] = v[0] * a[c] + v[1] * a[3 + c] + v[2] * a[6 + c] + (row == 3 ? a[9 + c] : 0.0f);
	}
	memcpy(out, r, sizeof r);
}

int zgo_m_invert(float* out, const float* m)
{
	const float a = m[0], b = m[1], c = m[2], d = m[3], e = m[4], f = m[5], g = m[6], h = m[7], i = m[8];
	float det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
	if (!(fabsf(det) > 1e-12f) || !isfinite(det)) return 0;
	float r[12];
	float k = 1.0f / det;
	r[0] = (e * i - f * h) * k; r[1] = (c * h - b * i) * k; r[2] = (b * f - c * e) * k;
	r[3] = (f * g - d * i) * k; r[4] = (a * i - c * g) * k; r[5] = (c * d - a * f) * k;
	r[6] = (d * h - e * g) * k; r[7] = (b * g - a * h) * k; r[8] = (a * e - b * d) * k;
	for (int col = 0; col < 3; col++)
		r[9 + col] = -(m[9] * r[col] + m[10] * r[3 + col] + m[11] * r[6 + col]);
	memcpy(out, r, sizeof r);
	return 1;
}

static int finite12(const float* m)
{
	for (int i = 0; i < 12; i++) if (!isfinite(m[i]) || fabsf(m[i]) > 1e5f) return 0;
	return 1;
}

/* engine Fmatrix (16 floats, rows i j k c with a w column) <-> 12 floats */
static void rd12(float* d, const float* m) { memcpy(d, m, 12); memcpy(d + 3, m + 4, 12); memcpy(d + 6, m + 8, 12); memcpy(d + 9, m + 12, 12); }
static void wr12(float* m, const float* s) { memcpy(m, s, 12); memcpy(m + 4, s + 3, 12); memcpy(m + 8, s + 6, 12); memcpy(m + 12, s + 9, 12); }
static int  eq12(const float* a, const float* b) { return memcmp(a, b, 48) == 0; }

/* ---------------------------------------------------------------- slots */

static uint64_t bloom_bit(uint64_t k) { return 1ull << ((k >> 4) * 0x9E3779B97F4A7C15ull >> 58); }

static void refresh_index(void)
{
	uint64_t bloom = 0;
	uint32_t any = 0;
	for (int i = 0; i < ZGO_MAX_BOUND; i++) {
		uint64_t k = __atomic_load_n(&g_slot[i].kin, __ATOMIC_ACQUIRE);
		if (k) { bloom |= bloom_bit(k); any++; }
	}
	__atomic_store_n(&g_bloom, bloom, __ATOMIC_RELEASE);
	__atomic_store_n(&g_any, any, __ATOMIC_RELEASE);
}

static int try_busy(slot* s)
{
	uint32_t z = 0;
	return __atomic_compare_exchange_n(&s->busy, &z, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED);
}
static void drop_busy(slot* s) { __atomic_store_n(&s->busy, 0, __ATOMIC_RELEASE); }

static int wait_busy(slot* s)
{
	for (long i = 0; i < 50000000L; i++) {
		if (try_busy(s)) return 1;
		__builtin_ia32_pause();
	}
	return 0;
}

static uint32_t bone_count(const uint8_t* ik)
{
	const uint8_t* const* vec = *(const uint8_t* const* const*)(ik + g_env.off.bones);
	if (!vec) return 0;
	const uint8_t* b = vec[0];
	const uint8_t* e = vec[1];
	if (!b || e < b) return 0;
	return (uint32_t)((e - b) / 8);
}

static slot* lookup(int32_t h)
{
	if (h <= 0) return NULL;
	int idx = (h & 0xff) - 1;
	if (idx < 0 || idx >= ZGO_MAX_BOUND) return NULL;
	slot* s = &g_slot[idx];
	if (!s->kin || (uint32_t)(h >> 8) != (s->gen & 0x7fffff)) return NULL;
	return s;
}

static int32_t handle_of(int idx) { return (int32_t)((idx + 1) | (g_slot[idx].gen & 0x7fffff) << 8); }

/* ---------------------------------------------------------------- seqlock */

static void publish(slot* s, const ops* o)
{
	uint32_t q = s->seq;
	__atomic_store_n(&s->seq, q + 1, __ATOMIC_RELAXED);
	__atomic_thread_fence(__ATOMIC_RELEASE);
	memcpy((void*)&s->pub, o, sizeof *o);
	__atomic_store_n(&s->seq, q + 2, __ATOMIC_RELEASE);
}

static int valid_ops(const ops* o)
{
	if (o->n_groups > MAXG || o->n_bones > MAXB || o->n_members > MAXM) return 0;
	for (int g = 0; g < o->n_groups; g++) {
		const grp* p = &o->g[g];
		if (p->driver >= o->n_bones || p->first + p->count > o->n_members) return 0;
	}
	for (int m = 0; m < o->n_members; m++) if (o->member[m] >= o->n_bones) return 0;
	return 1;
}

static int read_ops(slot* s, ops* o)
{
	for (int tries = 0; tries < 64; tries++) {
		uint32_t q1 = __atomic_load_n(&s->seq, __ATOMIC_ACQUIRE);
		if (q1 & 1) { __builtin_ia32_pause(); continue; }
		memcpy(o, (const void*)&s->pub, sizeof *o);
		__atomic_thread_fence(__ATOMIC_ACQUIRE);
		if (__atomic_load_n(&s->seq, __ATOMIC_RELAXED) == q1) return valid_ops(o);
	}
	return 0;
}

/* ---------------------------------------------------------------- applying (engine thread) */

static cache_e* cache_find(slot* s, uint16_t bone)
{
	for (int i = 0; i < MAXB; i++) if (s->cache[i].valid && s->cache[i].bone == bone) return &s->cache[i];
	return NULL;
}

static cache_e* cache_new(slot* s, uint16_t bone)
{
	for (int i = 0; i < MAXB; i++) if (!s->cache[i].valid) { s->cache[i].bone = bone; s->cache[i].valid = 1; return &s->cache[i]; }
	return NULL;
}

static void apply(slot* s, uint8_t* ik, const ops* o)
{
	const zgo_offsets* off = &g_env.off;
	uint32_t count = bone_count(ik);
	uint8_t* inst = *(uint8_t**)(ik + off->bone_inst);
	if (count != s->bone_count || !inst) { BUMP(st_rejected, 1); return; }

	float cm[MAXB][12], cr[MAXB][12], fm[MAXB][12], fr[MAXB][12], wm[MAXB][12], wr[MAXB][12];
	cache_e* ce[MAXB];
	for (int b = 0; b < o->n_bones; b++) {
		uint16_t id = o->bone[b];
		if (id >= count) { BUMP(st_rejected, 1); return; }
		const float* M = (const float*)(inst + (size_t)id * off->bone_stride);
		const float* R = (const float*)(inst + (size_t)id * off->bone_stride + off->render_xf);
		rd12(cm[b], M);
		rd12(cr[b], R);
		ce[b] = cache_find(s, id);
		if (ce[b] && eq12(cm[b], ce[b]->out_m) && eq12(cr[b], ce[b]->out_r)) {
			/* still what we wrote: the engine skipped this recompute */
			memcpy(fm[b], ce[b]->in_m, 48);
			memcpy(fr[b], ce[b]->in_r, 48);
		} else {
			memcpy(fm[b], cm[b], 48);
			memcpy(fr[b], cr[b], 48);
		}
		memcpy(wm[b], fm[b], 48);
		memcpy(wr[b], fr[b], 48);
	}
	for (int g = 0; g < o->n_groups; g++) {
		const grp* p = &o->g[g];
		float inv[12], t[12], d[12], x[12];
		if (!zgo_m_invert(inv, wm[p->driver])) continue;
		zgo_m_compose(t, p->l, inv);
		zgo_m_compose(d, wm[p->driver], t);
		if (!finite12(d)) continue;
		for (int j = 0; j < p->count; j++) {
			int b = o->member[p->first + j];
			zgo_m_compose(x, d, wm[b]); memcpy(wm[b], x, 48);
			zgo_m_compose(x, d, wr[b]); memcpy(wr[b], x, 48);
		}
	}
	/* bones that left the op set go back to what the engine computed */
	for (int i = 0; i < MAXB; i++) {
		cache_e* c = &s->cache[i];
		if (!c->valid) continue;
		int keep = 0;
		for (int b = 0; b < o->n_bones && !keep; b++) keep = o->bone[b] == c->bone;
		if (keep) continue;
		if (c->bone < count) {
			float* M = (float*)(inst + (size_t)c->bone * off->bone_stride);
			float* R = (float*)(inst + (size_t)c->bone * off->bone_stride + off->render_xf);
			float m[12], r[12];
			rd12(m, M);
			rd12(r, R);
			if (eq12(m, c->out_m) && eq12(r, c->out_r)) { wr12(M, c->in_m); wr12(R, c->in_r); BUMP(st_written, 1); }
		}
		c->valid = 0;
	}
	for (int b = 0; b < o->n_bones; b++) {
		uint16_t id = o->bone[b];
		if (!finite12(wm[b]) || !finite12(wr[b])) { memcpy(wm[b], fm[b], 48); memcpy(wr[b], fr[b], 48); }
		if (!eq12(wm[b], cm[b]) || !eq12(wr[b], cr[b])) {
			wr12((float*)(inst + (size_t)id * off->bone_stride), wm[b]);
			wr12((float*)(inst + (size_t)id * off->bone_stride + off->render_xf), wr[b]);
			BUMP(st_written, 1);
		} else {
			BUMP(st_kept, 1);
		}
		cache_e* c = ce[b] ? ce[b] : cache_new(s, id);
		if (c) {
			memcpy(c->in_m, fm[b], 48); memcpy(c->in_r, fr[b], 48);
			memcpy(c->out_m, wm[b], 48); memcpy(c->out_r, wr[b], 48);
		}
	}
}

void zgo_bones_post(void* ik)
{
	BUMP(st_calls, 1);
	if (!__atomic_load_n(&g_any, __ATOMIC_ACQUIRE) || !ik) return;
	uint64_t k = (uint64_t)(uintptr_t)ik;
	if (!(__atomic_load_n(&g_bloom, __ATOMIC_ACQUIRE) & bloom_bit(k))) return;
	slot* s = NULL;
	for (int i = 0; i < ZGO_MAX_BOUND; i++)
		if (__atomic_load_n(&g_slot[i].kin, __ATOMIC_ACQUIRE) == k) { s = &g_slot[i]; break; }
	if (!s || __atomic_load_n(&s->dead, __ATOMIC_ACQUIRE)) return;
	BUMP(st_matched, 1);
	uint32_t gen = __atomic_load_n(&s->gen, __ATOMIC_ACQUIRE);
	/* the engine's own per-object lock: serialises us with its recomputes */
	void* cs = g_env.lock ? *(void**)((uint8_t*)ik + g_env.off.mutex) : NULL;
	if (cs) g_env.lock(cs);
	if (try_busy(s)) {
		if (__atomic_load_n(&s->kin, __ATOMIC_ACQUIRE) == k && s->gen == gen && !s->dead) {
			ops o;
			if (read_ops(s, &o)) apply(s, (uint8_t*)ik, &o);
			else BUMP(st_rejected, 1);
		}
		drop_busy(s);
	} else {
		BUMP(st_rejected, 1);
	}
	if (cs) g_env.unlock(cs);
}

void zgo_bones_departed(void* ik)
{
	uint64_t k = (uint64_t)(uintptr_t)ik;
	if (!__atomic_load_n(&g_any, __ATOMIC_ACQUIRE)) return;
	for (int i = 0; i < ZGO_MAX_BOUND; i++) {
		if (__atomic_load_n(&g_slot[i].kin, __ATOMIC_ACQUIRE) == k) {
			__atomic_store_n(&g_slot[i].dead, 1, __ATOMIC_RELEASE);
			BUMP(st_departs, 1);
		}
	}
}

void zgo_bones_capture(void* ik, const char* digits)
{
	uint32_t t = 0;
	int n = 0;
	for (; digits[n] >= '0' && digits[n] <= '9' && n < 9; n++) t = t * 10 + (uint32_t)(digits[n] - '0');
	if (!n || digits[n] || !t) return;
	int i = (int)(t % NCAPTURE);
	__atomic_store_n(&g_cap[i].kin, (uint64_t)(uintptr_t)ik, __ATOMIC_RELAXED);
	__atomic_store_n(&g_cap[i].token, t, __ATOMIC_RELEASE);
	BUMP(st_captures, 1);
}

/* ---------------------------------------------------------------- main thread */

uint64_t zgo_bones_take(uint32_t token)
{
	if (!token) return 0;
	int i = (int)(token % NCAPTURE);
	if (__atomic_load_n(&g_cap[i].token, __ATOMIC_ACQUIRE) != token) return 0;
	uint64_t k = __atomic_load_n(&g_cap[i].kin, __ATOMIC_RELAXED);
	__atomic_store_n(&g_cap[i].token, 0, __ATOMIC_RELEASE);
	return k;
}

int32_t zgo_bones_do_bind(uint64_t kin)
{
	if (!kin) return ZGO_E_ARG;
	int idx = -1;
	for (int i = 0; i < ZGO_MAX_BOUND; i++) {
		if (g_slot[i].kin == kin) {
			if (!g_slot[i].dead) return handle_of(i);
			idx = i;                     /* the model came back from the pool: start over */
			break;
		}
	}
	if (idx < 0) for (int i = 0; i < ZGO_MAX_BOUND && idx < 0; i++) if (!g_slot[i].kin) idx = i;
	if (idx < 0) for (int i = 0; i < ZGO_MAX_BOUND && idx < 0; i++) if (g_slot[i].dead) idx = i;
	if (idx < 0) return ZGO_E_FULL;
	uint32_t n = bone_count((const uint8_t*)(uintptr_t)kin);
	if (n == 0 || n > 4096) return ZGO_E_ARG;
	slot* s = &g_slot[idx];
	__atomic_store_n(&s->kin, 0, __ATOMIC_RELEASE);
	if (!wait_busy(s)) return ZGO_E_FULL;
	s->gen = (s->gen + 1) & 0x7fffff;
	if (!s->gen) s->gen = 1;
	s->dead = 0;
	s->bone_count = n;
	memset(s->cache, 0, sizeof s->cache);
	ops empty;
	memset(&empty, 0, sizeof empty);
	publish(s, &empty);
	memset(&s->stage, 0, sizeof s->stage);
	s->staging = 0;
	__atomic_store_n(&s->kin, kin, __ATOMIC_RELEASE);
	drop_busy(s);
	refresh_index();
	return handle_of(idx);
}

int32_t zgo_bones_do_state(int32_t h)
{
	slot* s = lookup(h);
	if (!s) return ZGO_E_HANDLE;
	return s->dead ? 0 : 1;
}

int32_t zgo_bones_do_begin(int32_t h)
{
	slot* s = lookup(h);
	if (!s) return ZGO_E_HANDLE;
	if (s->dead) return ZGO_E_DEAD;
	memset(&s->stage, 0, sizeof s->stage);
	s->staging = 1;
	return 0;
}

static int bone_index(ops* o, uint16_t id)
{
	for (int b = 0; b < o->n_bones; b++) if (o->bone[b] == id) return b;
	if (o->n_bones >= MAXB) return -1;
	o->bone[o->n_bones] = id;
	return o->n_bones++;
}

int32_t zgo_bones_do_group(int32_t h, uint16_t driver, const float* l12, const uint16_t* members, int32_t n)
{
	slot* s = lookup(h);
	if (!s) return ZGO_E_HANDLE;
	if (!s->staging) return ZGO_E_ARG;
	if (!l12 || !members || n <= 0) return ZGO_E_ARG;
	ops* o = &s->stage;
	if (o->n_groups >= MAXG || o->n_members + n > MAXM) return ZGO_E_FULL;
	if (driver >= s->bone_count) return ZGO_E_ARG;
	float l[12];
	memcpy(l, l12, sizeof l);
	if (!finite12(l)) return ZGO_E_ARG;
	ops save = *o;
	int d = bone_index(o, driver);
	if (d < 0) { *o = save; return ZGO_E_FULL; }
	grp* g = &o->g[o->n_groups];
	g->driver = (uint8_t)d;
	g->first = o->n_members;
	g->count = 0;
	memcpy(g->l, l, sizeof l);
	for (int i = 0; i < n; i++) {
		if (members[i] >= s->bone_count) { *o = save; return ZGO_E_ARG; }
		int b = bone_index(o, members[i]);
		if (b < 0) { *o = save; return ZGO_E_FULL; }
		o->member[o->n_members++] = (uint8_t)b;
		g->count++;
	}
	o->n_groups++;
	return o->n_groups;
}

int32_t zgo_bones_do_commit(int32_t h)
{
	slot* s = lookup(h);
	if (!s) return ZGO_E_HANDLE;
	if (!s->staging) return ZGO_E_ARG;
	publish(s, &s->stage);
	s->staging = 0;
	return s->dead ? ZGO_E_DEAD : 0;
}

int32_t zgo_bones_do_unbind(int32_t h)
{
	slot* s = lookup(h);
	if (!s) return ZGO_E_HANDLE;
	__atomic_store_n(&s->kin, 0, __ATOMIC_RELEASE);
	s->dead = 0;
	s->staging = 0;
	refresh_index();
	return 0;
}

void zgo_bones_do_clear_all(void)
{
	for (int i = 0; i < ZGO_MAX_BOUND; i++) {
		__atomic_store_n(&g_slot[i].kin, 0, __ATOMIC_RELEASE);
		g_slot[i].dead = 0;
		g_slot[i].staging = 0;
	}
	for (int i = 0; i < NCAPTURE; i++) g_cap[i].token = 0;
	refresh_index();
}

uint32_t zgo_bones_bound(void)
{
	uint32_t n = 0;
	for (int i = 0; i < ZGO_MAX_BOUND; i++) if (g_slot[i].kin && !g_slot[i].dead) n++;
	return n;
}

void zgo_bones_stats(zgo_stats* st)
{
	st->calc_calls = __atomic_load_n(&st_calls, __ATOMIC_RELAXED);
	st->calc_matched = __atomic_load_n(&st_matched, __ATOMIC_RELAXED);
	st->bones_written = __atomic_load_n(&st_written, __ATOMIC_RELAXED);
	st->bones_kept = __atomic_load_n(&st_kept, __ATOMIC_RELAXED);
	st->rejected = __atomic_load_n(&st_rejected, __ATOMIC_RELAXED);
	st->captures = __atomic_load_n(&st_captures, __ATOMIC_RELAXED);
	st->departs = __atomic_load_n(&st_departs, __ATOMIC_RELAXED);
	st->bound = zgo_bones_bound();
}
