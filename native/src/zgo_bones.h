/*
 * Bone post-processing: per-object op sets that Lua publishes (main thread)
 * and the CalculateBones hook applies (any engine thread) right after the
 * engine has computed the skeleton. Platform neutral; the engine lock is
 * reached through two function pointers.
 *
 * Publishing is a seqlock: the hook copies the op set and retries if the
 * writer was in the middle of it, so it sees the old set or the new one,
 * never a mix. Applying is idempotent: for every bone the hook remembers the
 * matrix it found (fresh from the engine) and the one it wrote; if the bone
 * still holds what it wrote (the engine skipped the recompute), it starts
 * again from the fresh one, so nothing is ever applied twice.
 */
#ifndef ZGO_BONES_H
#define ZGO_BONES_H

#include <stdint.h>

#include "zgo_finder.h"
#include "zgo_native.h"

typedef struct zgo_bones_env {
	zgo_offsets off;
	void (*lock)(void* cs);      /* EnterCriticalSection (may be NULL: no engine lock) */
	void (*unlock)(void* cs);    /* LeaveCriticalSection */
} zgo_bones_env;

void     zgo_bones_setup(const zgo_bones_env* env);

/* hook side (any thread) */
void     zgo_bones_post(void* ik);                    /* after the original CalculateBones */
void     zgo_bones_departed(void* ik);                /* the engine releases this model */
void     zgo_bones_capture(void* ik, const char* digits); /* LL_BoneID("\1zgo:<digits>") */

/* main thread */
uint64_t zgo_bones_take(uint32_t token);
int32_t  zgo_bones_do_bind(uint64_t kin);
int32_t  zgo_bones_do_state(int32_t h);
int32_t  zgo_bones_do_begin(int32_t h);
int32_t  zgo_bones_do_group(int32_t h, uint16_t driver, const float* l12, const uint16_t* members, int32_t n);
int32_t  zgo_bones_do_commit(int32_t h);
int32_t  zgo_bones_do_unbind(int32_t h);
void     zgo_bones_do_clear_all(void);
uint32_t zgo_bones_bound(void);
void     zgo_bones_stats(zgo_stats* st);              /* fills the bone counters */

/* 3x4 affine maths on rows i, j, k, c (the engine's Fmatrix), exposed for tests */
void zgo_m_compose(float* out, const float* a, const float* b);   /* out = a after b */
int  zgo_m_invert(float* out, const float* a);                    /* 0 if singular */

#endif
