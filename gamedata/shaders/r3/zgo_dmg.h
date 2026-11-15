// Umbra Gore & Effects: the wound shader zgo\dmg (PLAN Phase C), shared code.
//
// Drawn only on a baked damage mesh D_s (bake.py --experimental-damage,
// docs/formats/damage.md) that zgo_wounds switched on in place of its intact
// sub-mesh C_s, on one NPC: set_shader(D, "zgo\\dmg", "<base>,zgo_dmg_<12 hex>[_<bump>]").
//
// Per vertex the damage mesh carries, in the integer part of its UV:
//   u' = u + 4 code     code  = site (1-based wound site of the section, 0 = never
//                            moves) + 32 * (1..7 how far out in the patch; 0 = not given)
//   v' = v + 4 thick    thick = local thickness under the vertex in 2 mm steps
// Per sub-mesh and NPC, zgo_dmg.s binds four "number" textures
// (zgo\wounds\n\000..fff, one texel each, made by tools/zgo_wounds) to the
// vertex-shader slots below; each holds one active wound as 12 bits:
//   bits 0-4  site (1..31; 0 = slot unused)
//   bits 5-10 depth in 2 mm steps (0..126 mm)
//   bit  11   bone shows at the bottom
// The vertex shader pushes every vertex of an active site inward along its
// bind-pose normal, by the wound's depth with a ragged floor, never past 85 %
// of the local thickness. That happens to the bind-pose position BEFORE the
// stock code skins it, so the dent follows animation, ragdolls, the previous
// frame's position (SSS motion vectors / TAA) and the shadow map (the shadow
// vertex shader moves it the same way).
// The pixel shader paints the inside by depth: a blood rim, then fat, then
// muscle, bone at the bottom of a bone-deep wound, a dark cavity in a deep
// one, all wet; the normal comes from the dented surface itself.

#ifndef ZGO_DMG_H
#define ZGO_DMG_H

// 1 = inside an active wound; also the pixel shader's switch
#define ZGO_STEP_M 0.002

#ifdef ZGO_DMG_VS

Texture2D s_zgo_w0;
Texture2D s_zgo_w1;
Texture2D s_zgo_w2;
Texture2D s_zgo_w3;

// one number texture -> its 12-bit value; 0 when the texel isn't one of ours
// (the engine's "texture not found" stand-in, an unbound slot reading 0)
uint zgo_number(Texture2D t)
{
	float4 c = saturate(t.Load(int3(0, 0, 0)));
	uint r = uint(c.r * 255.0 + 0.5);
	uint g = uint(c.g * 255.0 + 0.5);
	uint b = uint(c.b * 255.0 + 0.5);
	uint a = uint(c.a * 255.0 + 0.5);
	uint lo = g / 17u;
	bool ok = (a == 255u) && (lo * 17u == g) && (b == ((r + lo * 3u + 90u) & 255u));
	return ok ? (r * 16u + lo) : 0u;
}

float zgo_hash3(float3 p)
{
	p = frac(p * 0.3183099 + float3(0.11, 0.17, 0.13));
	p *= 17.0;
	return frac(p.x * p.y * p.z * (p.x + p.y + p.z));
}

// smooth value noise in 0..1
float zgo_noise3(float3 x)
{
	float3 i = floor(x);
	float3 f = frac(x);
	f = f * f * (3.0 - 2.0 * f);
	float a = lerp(zgo_hash3(i + float3(0, 0, 0)), zgo_hash3(i + float3(1, 0, 0)), f.x);
	float b = lerp(zgo_hash3(i + float3(0, 1, 0)), zgo_hash3(i + float3(1, 1, 0)), f.x);
	float c = lerp(zgo_hash3(i + float3(0, 0, 1)), zgo_hash3(i + float3(1, 0, 1)), f.x);
	float d = lerp(zgo_hash3(i + float3(0, 1, 1)), zgo_hash3(i + float3(1, 1, 1)), f.x);
	return lerp(lerp(a, b, f.y), lerp(c, d, f.y), f.z);
}

struct zgo_wound
{
	float3 P;      // bind-space position after the dent
	float4 info;   // x = how far this vertex moved (m), y = the wound's depth (m),
	               // z = bone shows (0/1), w = 1 inside an active wound, else 0
	float4 bind;   // xyz = bind-space position before the dent, w = local thickness (m)
};

zgo_wound zgo_none(float3 P)
{
	zgo_wound o;
	o.P = P;
	o.info = float4(0.0, 0.0, 0.0, 0.0);
	o.bind = float4(P, 0.0);
	return o;
}

// P: bind-space position, N: bind-space normal (unpacked), uv: the raw UV
zgo_wound zgo_dent(float3 P, float3 N, float2 uv)
{
	zgo_wound o = zgo_none(P);
	float code = floor((uv.x + 1.5) * 0.25);
	float thick = max(floor((uv.y + 1.5) * 0.25), 0.0) * ZGO_STEP_M;
	o.bind.w = thick;
	if (code < 1.0 || code > 255.0)
		return o;
	// site in bits 0-4; bits 5-7 (docs/formats/damage.md): how far
	// out in the patch the vertex lies, 1 = centre .. 7 = rim, 0 = not given
	uint c = uint(code);
	uint site = c & 31u;
	float rq = float(c >> 5);
	if (site == 0u)
		return o;
	uint w0 = zgo_number(s_zgo_w0);
	uint w1 = zgo_number(s_zgo_w1);
	uint w2 = zgo_number(s_zgo_w2);
	uint w3 = zgo_number(s_zgo_w3);
	uint e = 0u;
	if ((w3 & 31u) == site) e = w3;
	if ((w2 & 31u) == site) e = w2;
	if ((w1 & 31u) == site) e = w1;
	if ((w0 & 31u) == site) e = w0;
	float depth = float((e >> 5) & 63u) * ZGO_STEP_M;
	if (depth <= 0.0)
		return o;
	float3 n = normalize(N);
	// a ragged floor (features about 2 cm), a bowl when the bake gives the
	// distance from the patch centre, never through the far side
	float rough = 0.72 + 0.28 * zgo_noise3(P * 45.0);
	float bowl = rq > 0.0 ? saturate(1.12 - (rq / 7.0) * (rq / 7.0)) : 1.0;
	float limit = thick > 0.0 ? thick * 0.85 : depth;
	float d = min(depth * rough * bowl, limit);
	o.P = P - n * d;
	o.info = float4(d, depth, float((e >> 11) & 1u), 1.0);
	return o;
}

#endif // ZGO_DMG_VS

#ifdef ZGO_DMG_PS

Texture2D s_zgo_tissue;   // zgo\wounds\tissue: R muscle, G fat, B bone, A clot (patterns)

// layer colours (albedo, the game's gamma space)
static const float3 ZGO_BLOOD  = float3(0.30, 0.025, 0.020);
static const float3 ZGO_FAT    = float3(0.86, 0.74, 0.45);
static const float3 ZGO_MUSCLE = float3(0.47, 0.065, 0.055);
static const float3 ZGO_BONE   = float3(0.86, 0.81, 0.70);
static const float3 ZGO_CAVITY = float3(0.09, 0.012, 0.010);

// tissue patterns, projected on the bind pose from three sides (one tile per
// ~6 cm), weighted by the bind-space facet normal
float4 zgo_tissue(float3 bp, float3 bn)
{
	float3 w = abs(bn);
	w = w * w * w * w;
	w /= (w.x + w.y + w.z + 1e-5);
	float s = 16.0;
	float4 a = s_zgo_tissue.Sample(smp_base, bp.yz * s);
	float4 b = s_zgo_tissue.Sample(smp_base, bp.zx * s);
	float4 c = s_zgo_tissue.Sample(smp_base, bp.xy * s);
	return a * w.x + b * w.y + c * w.z;
}

// rewrites the G-buffer the stock pixel shader produced, inside a wound only
// (wound.w == 0: the pixel is left exactly as the stock shader drew it)
// pv: view-space position (the stock interpolant), wound / bind: from the vertex shader
void zgo_paint(inout f_deffer O, float3 pv, float4 wound, float4 bind)
{
	float inside = saturate(wound.w * 6.0);
	// computed for every pixel (derivatives must not sit behind a branch)
	float3 bn = cross(ddx(bind.xyz), ddy(bind.xyz));
	bn = bn / max(length(bn), 1e-9);
	float3 ng = cross(ddy(pv), ddx(pv));
	ng = ng / max(length(ng), 1e-9);
	if (dot(ng, -pv) < 0.0)
		ng = -ng;
	float4 t = zgo_tissue(bind.xyz, bn);
	if (inside <= 0.0)
		return;

	float d = wound.x;
	float full = max(wound.y, 0.001);
	float thick = max(bind.w, 0.01);
	float3 blood = ZGO_BLOOD * (0.7 + 0.6 * t.a);
	float3 fat = ZGO_FAT * (0.65 + 0.5 * t.g);
	float3 muscle = ZGO_MUSCLE * (0.55 + 0.9 * t.r);
	float3 bone = ZGO_BONE * (0.75 + 0.35 * t.b);
	// by depth: blood at the rim, a band of fat, then muscle
	float3 col = lerp(blood, fat, smoothstep(0.002, 0.004, d));
	col = lerp(col, muscle, smoothstep(0.009, 0.013, d));
	// deep in a thick part: a dark cavity
	col = lerp(col, ZGO_CAVITY, smoothstep(0.55, 0.75, d / thick));
	// the bottom of a bone-deep wound
	float bone_k = wound.z * smoothstep(0.80, 0.92, d / full);
	col = lerp(col, bone, bone_k);
	// clotted blood in patches over the rest
	col = lerp(col, blood * 0.6, smoothstep(0.62, 0.85, t.a) * 0.5 * (1.0 - bone_k));

	O.C.rgb = lerp(O.C.rgb, col, inside);
	// wet; bone a little less
	O.C.w = lerp(O.C.w, lerp(0.6, 0.3, bone_k), inside);
	// the dented surface's own normal (the stock one is the intact skin's)
	float3 ne = gbuf_unpack_normal(O.position.xy);
	ne = normalize(lerp(ne, ng, saturate(wound.w * 3.0)));
	O.position.xy = gbuf_pack_normal(ne);
}

#endif // ZGO_DMG_PS

#endif // ZGO_DMG_H
