// Zone Gore Overhaul: wound shader zgo\dmg, shadow-map vertex shader.
// The stock shadow_direct_model.vs (whichever mod's copy wins) under a ZGO
// name, its entry point wrapped once per skinning variant. The vertex moves
// into the wounds exactly as in zgo_dmg_bump.vs / zgo_dmg_flat.vs (zgo_dent,
// zgo_dmg.h, the same four number textures), so the shadow has the same dents.
#define ZGO_DMG_VS
#define main zgo_stock_main
#include "shadow_direct_model.vs"
#undef main
#include "zgo_dmg.h"

#ifdef SKIN_NONE
v2p_shadow_direct main(v_model v) { return zgo_stock_main(v); }
#endif

#ifdef SKIN_0
v2p_shadow_direct main(v_model_skinned_0 v)
{
	v.P.xyz = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy).P;
	return zgo_stock_main(v);
}
#endif

#ifdef SKIN_1
v2p_shadow_direct main(v_model_skinned_1 v)
{
	v.P.xyz = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy).P;
	return zgo_stock_main(v);
}
#endif

#ifdef SKIN_2
v2p_shadow_direct main(v_model_skinned_2 v)
{
	v.P.xyz = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy).P;
	return zgo_stock_main(v);
}
#endif

#ifdef SKIN_3
v2p_shadow_direct main(v_model_skinned_3 v)
{
	v.P.xyz = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy).P;
	return zgo_stock_main(v);
}
#endif

#ifdef SKIN_4
v2p_shadow_direct main(v_model_skinned_4 v)
{
	v.P.xyz = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy).P;
	return zgo_stock_main(v);
}
#endif
