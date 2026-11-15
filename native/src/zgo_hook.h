/*
 * Inline hooks for x64 Windows, written for the case at hand rather than in
 * general: the target's first instruction is known from a verified byte
 * pattern (no length disassembler), is at least 5 bytes long and position
 * independent, and the target is 8-byte aligned. Installing replaces those
 * 5 bytes with a jmp in one 8-byte compare-and-swap, so a thread running
 * the function at that moment sees either the old instruction or the jmp,
 * never half of each; the CAS also refuses if the bytes changed since they
 * were verified. Removing swaps the original bytes back the same way.
 *
 * Trampolines live in one page allocated within +-2 GB of the targets and
 * are never freed, and the DLL pins itself, so a thread still inside a
 * hook or trampoline after removal always returns safely.
 */
#ifndef ZGO_HOOK_H
#define ZGO_HOOK_H

#include <stdint.h>

typedef struct zgo_hook {
	const char* name;
	uint8_t*    target;
	int         steal;        /* bytes of whole instructions moved to the trampoline (>= 5) */
	void*       detour;
	void**      orig;         /* receives the callable original (the trampoline) */
	uint8_t     saved[8];     /* the target's first 8 bytes before patching */
	uint8_t     patched[8];
	uint8_t*    tramp;
	int         installed;
} zgo_hook;

/* builds the trampoline (once); expect = the 8 bytes the finder verified */
int  zgo_hook_prepare(zgo_hook* h, const char* name, uint8_t* target, int steal, void* detour, void** orig, char* why, int whylen);
int  zgo_hook_install(zgo_hook* h, char* why, int whylen);
int  zgo_hook_remove(zgo_hook* h, char* why, int whylen);

#endif
