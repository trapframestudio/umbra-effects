// Umbra Gore & Effects: wound shader zgo\dmg, deferred (flat) vertex shader.
// The stock deffer_model_flat.vs (whichever mod's copy wins: SSS, Atmospherics...) under a
// ZGO name, its entry point wrapped once per skinning variant (SKIN_NONE,
// SKIN_0 = RM_SINGLE, SKIN_1..4 = 1W..4W; the engine defines one per compile).
// Before the stock code skins the vertex, zgo_dent (zgo_dmg.h) moves the
// bind-pose position into the active wounds; the output adds what the wound
// pixel shader needs (ZGO_WOUND, ZGO_BIND) after the stock struct, so the
// stock interpolants keep their registers.
// SKIN_NONE (a static model, never a damage mesh) passes through unchanged.
#define ZGO_DMG_VS
#define main zgo_stock_main
#include "deffer_model_flat.vs"
#undef main
#include "zgo_dmg.h"

struct v2p_zgo_flat
{
	v2p_flat	base;
	float4	wound	: ZGO_WOUND;	// moved, depth, bone, inside
	float4	bind	: ZGO_BIND;	// bind-space position, thickness
};

v2p_zgo_flat zgo_out(v2p_flat b, zgo_wound w)
{
	v2p_zgo_flat O;
	O.base = b;
	O.wound = w.info;
	O.bind = w.bind;
	return O;
}

#ifdef SKIN_NONE
v2p_zgo_flat main(v_model v) { zgo_wound w = zgo_none(v.P.xyz); return zgo_out(zgo_stock_main(v), w); }
#endif

#ifdef SKIN_0
v2p_zgo_flat main(v_model_skinned_0 v)
{
	zgo_wound w = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy);
	v.P.xyz = w.P;
	return zgo_out(zgo_stock_main(v), w);
}
#endif

#ifdef SKIN_1
v2p_zgo_flat main(v_model_skinned_1 v)
{
	zgo_wound w = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy);
	v.P.xyz = w.P;
	return zgo_out(zgo_stock_main(v), w);
}
#endif

#ifdef SKIN_2
v2p_zgo_flat main(v_model_skinned_2 v)
{
	zgo_wound w = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy);
	v.P.xyz = w.P;
	return zgo_out(zgo_stock_main(v), w);
}
#endif

#ifdef SKIN_3
v2p_zgo_flat main(v_model_skinned_3 v)
{
	zgo_wound w = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy);
	v.P.xyz = w.P;
	return zgo_out(zgo_stock_main(v), w);
}
#endif

#ifdef SKIN_4
v2p_zgo_flat main(v_model_skinned_4 v)
{
	zgo_wound w = zgo_dent(v.P.xyz, unpack_normal(v.N.zyx), v.tc.xy);
	v.P.xyz = w.P;
	return zgo_out(zgo_stock_main(v), w);
}
#endif
