function normal(shader, t_base, t_second, t_detail)
  -- Zone Gore Overhaul: textures under zgo\impacts\deep\ (MCM World impacts ->
  -- Deep impact marks, experimental) go to its parallax decal shader; everything
  -- else is the stock shader below, byte for byte (base shaders.db0).
  if t_base and string.find(string.lower(t_base), "zgo\\impacts\\deep\\", 1, true) then
    shader:begin("zgo_wm_deep","zgo_wm_deep")
      : blend   (true,blend.destcolor,blend.srccolor)
      : zb      (true,false)
    shader:dx10texture ("s_base", t_base)
    shader:dx10sampler ("smp_base")
    shader:dx10color_write_enable( true, true, true, false)
    return
  end
  shader:begin("effects_wallmark","stub_default_ma")
		: blend		(true,blend.destcolor,blend.srccolor)
		: zb 		(true,false)
	shader:dx10texture	("s_base", t_base)
	shader:dx10sampler	("smp_rtlinear")
	shader:dx10color_write_enable( true, true, true, false)
end