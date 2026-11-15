# Umbra Gore & Effects tests

LuaJIT suites that run the real mod scripts (`../gamedata/scripts`) against a
mock of the X-Ray engine API (`zgo_harness.lua`). The mock follows the engine
where it matters (xray-monolith b86d733f4a): attachment transforms, bone
matrices, the explosion's fragment / blast-wave delivery, wallmark sections
that must exist (the engine R_ASSERTs), particles that must exist.

    cd tests
    luajit zgo_test_sp.lua              # single player: hits, streams, pools, drips, trails, limbs, caps
    luajit zgo_test_blast.lua [seed]    # explosions: gibs, shrapnel, corpses, throw direction
    luajit zgo_test_edge.lua [seed]     # every option off, mutants, offline objects, level change,
                                        # save/load, id reuse, late blast waves, particle lifetime
    luajit zgo_test_mp.lua host && luajit zgo_test_mp.lua client
                                        # co-op: the client replays the host's wire and must match
    luajit zgo_test_settings.lua [seed] # every option complete (texts, ranges, presets), co-op
                                        # authority, performance limits, kid mode (runs as a host)

Every suite also runs in baked-model mode (`ZGO_BAKED=1 luajit ...`): the
mock visual is listed in a fake `zgo_bake_index`. The mock models the death
ragdoll (built RAGDOLL_MS after death, without elements for bones hidden
before that) and the save (`SAVE_GAME()`: hidden-bone masks are captured
inside `exec_console_cmd("save ...")`, `RESPAWN()` restores them), and
`CHECK_CUTS()` fails on a cut part still on screen or a pinched joint. Run
both modes over several seeds before a release:

    dev/test-all.sh

The mock is not the engine: anything about rendering, real physics or
performance still needs an in-game test (enable "Debug log" in the MCM menu;
the log is appdata/logs/xray_<user>.log).

Not part of the release zip.
