# Engine mocks per feature

`zgo_harness.lua` runs every `*.lua` here (alphabetical) before the first
object is made. A file adds globals the feature needs (e.g. `shader_bus`) or
object methods through `NPC_HOOKS`:

    NPC_HOOKS[#NPC_HOOKS + 1] = function(o)
        o._shaders = {}
        function o:set_shader(child, shader, tex, fl) self._shaders[child] = shader end
    end

One file per workstream (`world.lua`, `cuts.lua`, ...) so parallel work
doesn't collide in the harness.
