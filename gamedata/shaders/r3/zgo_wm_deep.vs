/**
 * Zone Gore Overhaul - "Deep impact marks" (experimental), vertex shader.
 *
 * Used only for wallmarks whose texture is under zgo\impacts\deep\ (the
 * world/deep_marks option), through the effects_wallmark.s dispatcher the
 * README describes. Same work as the stock / SSS effects_wallmark.vs (world
 * space TL vertices, m_VP, SSS TAA jitter when the engine provides it) plus
 * the world position for the pixel shader's parallax.
 */
#include "common.h"

#ifndef SSFX_MV_LOADED
uniform float4 ssfx_jitter;     // engine constant (zero without TAA)
#endif

struct zgo_wm_v2p
{
	float2 Tex0  : TEXCOORD0;
	float4 Color : COLOR;
	float3 WPos  : TEXCOORD1;
	float4 HPos  : SV_Position;
};

zgo_wm_v2p main(v_TL I)
{
	zgo_wm_v2p O;
	O.HPos = mul(m_VP, I.P);
	O.HPos.xy += ssfx_jitter.xy * O.HPos.w;
	O.Tex0 = I.Tex0;
	O.Color = I.Color.bgra;          // swizzle vertex colour (as the stock shader)
	O.WPos = I.P.xyz;
	return O;
}
