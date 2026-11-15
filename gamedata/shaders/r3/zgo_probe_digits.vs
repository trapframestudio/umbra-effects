// Umbra Gore & Effects: probe 3 (per-NPC digit textures), vertex shader.
// The stock flat skinned model vertex shader, wrapped (see zgo_probe_dmg_bump.vs).
// zgo_probe_digits.s binds four 1x1 "digit" textures (zgo\probe\d00..d15, value
// = digit / 15 in red) to the vertex-shader slots below, chosen from the second
// texture string zgo_probe gave this NPC. The probe always sets
//   v3 = (v0 + v1 + v2 + 7) mod 16
// so with the slots read correctly the part draws normally; if they come back
// wrong (or as zeros: nothing bound) every vertex collapses to one point and
// the part vanishes from the G-buffer while its shadow (stock pass) stays.
#define main zgo_stock_main
#include "deffer_model_flat.vs"
#undef main

Texture2D s_zgo_v0;
Texture2D s_zgo_v1;
Texture2D s_zgo_v2;
Texture2D s_zgo_v3;

#define ZGO_DIGIT(t) ((int)round((t).Load(int3(0, 0, 0)).r * 15.0))

v2p_flat zgo_check(v2p_flat O)
{
	int a = ZGO_DIGIT(s_zgo_v0);
	int b = ZGO_DIGIT(s_zgo_v1);
	int c = ZGO_DIGIT(s_zgo_v2);
	int d = ZGO_DIGIT(s_zgo_v3);
	if (d != (a + b + c + 7) % 16)
		O.hpos = float4(0.0, 0.0, 0.0, 1.0);
	return O;
}

#ifdef SKIN_NONE
v2p_flat main(v_model v) { return zgo_check(zgo_stock_main(v)); }
#endif

#ifdef SKIN_0
v2p_flat main(v_model_skinned_0 v) { return zgo_check(zgo_stock_main(v)); }
#endif

#ifdef SKIN_1
v2p_flat main(v_model_skinned_1 v) { return zgo_check(zgo_stock_main(v)); }
#endif

#ifdef SKIN_2
v2p_flat main(v_model_skinned_2 v) { return zgo_check(zgo_stock_main(v)); }
#endif

#ifdef SKIN_3
v2p_flat main(v_model_skinned_3 v) { return zgo_check(zgo_stock_main(v)); }
#endif

#ifdef SKIN_4
v2p_flat main(v_model_skinned_4 v) { return zgo_check(zgo_stock_main(v)); }
#endif
