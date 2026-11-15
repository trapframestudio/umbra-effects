// Umbra Gore & Effects: probe 2, pass-through shadow-map vertex shader.
// The stock shadow_direct_model.vs (whichever mod's copy wins) under a ZGO name, with its
// entry point wrapped once per skinning variant (SKIN_NONE, SKIN_0 = RM_SINGLE,
// SKIN_1..4 = 1W..4W; the engine defines one of them per compile).
// Phase C (zgo_dmg) moves v.P, still in bind space, before the stock code
// skins it, so position, normal and the previous-frame position (SSS TAA)
// all follow; here the vertex is passed through untouched.
#define main zgo_stock_main
#include "shadow_direct_model.vs"
#undef main

#ifdef SKIN_NONE
v2p_shadow_direct main(v_model v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_0
v2p_shadow_direct main(v_model_skinned_0 v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_1
v2p_shadow_direct main(v_model_skinned_1 v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_2
v2p_shadow_direct main(v_model_skinned_2 v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_3
v2p_shadow_direct main(v_model_skinned_3 v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_4
v2p_shadow_direct main(v_model_skinned_4 v) { return zgo_stock_main(v); }
#endif
