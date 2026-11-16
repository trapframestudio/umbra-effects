#!/usr/bin/env python3
"""
The Python test suites as CI runs them (.github/workflows/build.yml):

    python3 dev/ci_tests.py

The tests listed in STALE fail on the original 1.7.0 files too (CLAUDE.md, "Known stale
failures"). They run as expected failures: CI passes with them, fails on any other
failure, and fails when a stale test starts passing again (then take it off STALE).
The window test (test_drive) needs tkinter and a display, and is skipped without them.
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = ["tests/baker/test_geometry.py", "tests/baker/test_bake.py", "dev/build_setup/test_setup.py",
          "tests/kidfx/test_particles_xr.py"]
STALE = {
    "test_geometry": {"TestDamage.test_damage_mesh"},
    "test_bake": {"TestBake.test_progress_report_manifest_remove"},
    "test_setup": {"TestBakeAndCheck.test_bake_writes_inputs_the_game_can_check",
                   "TestKidfx.test_unticked_elsewhere_or_missing",
                   "TestLuaReader.test_values", "TestLuaReader.test_wanted_and_errors"},
}


def tests_of(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from tests_of(t)
        else:
            yield t


def load(rel):
    path = os.path.join(ROOT, *rel.split("/"))
    name = os.path.splitext(os.path.basename(path))[0]
    sys.path.insert(0, os.path.dirname(path))            # each suite imports its neighbours
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return name, unittest.defaultTestLoader.loadTestsFromModule(mod)


def main():
    os.chdir(ROOT)
    suite, marked = unittest.TestSuite(), set()
    for rel in SUITES:
        name, loaded = load(rel)
        for t in tests_of(loaded):
            short = "%s.%s" % (type(t).__name__, getattr(t, "_testMethodName", "?"))
            if short in STALE.get(name, ()):
                t.__unittest_expecting_failure__ = True   # unittest reads it from the test case too
                marked.add((name, short))
            suite.addTest(t)
    unknown = sorted("%s: %s" % ns for ns in {(n, s) for n, ss in STALE.items() for s in ss} - marked)
    if unknown:
        print("ci_tests: STALE names tests that are not there any more:\n  " + "\n  ".join(unknown))
        return 2
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    if res.unexpectedSuccesses:
        print("ci_tests: these stale tests pass now; take them off STALE in dev/ci_tests.py:\n  " +
              "\n  ".join(t.id() for t in res.unexpectedSuccesses))
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
