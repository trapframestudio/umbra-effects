#!/usr/bin/env bash
# Every test suite, plain and baked-model mode, several seeds. Exit 1 on any failure.
#   dev/test-all.sh            (host or inside the container: needs luajit)
set -uo pipefail
cd "$(dirname "$0")/../tests"
seeds="${SEEDS:-1 5 7 42 99}"
fails=0; runs=0
for b in 0 1; do
	for s in $seeds; do
		for t in sp blast edge settings gibs; do
			runs=$((runs+1))
			out=$(ZGO_BAKED=$b luajit "zgo_test_$t.lua" "$s" 2>&1)
			case "$(tail -1 <<<"$out")" in *PASSED*) ;; *) fails=$((fails+1)); echo "FAIL baked=$b seed=$s $t"; grep -m3 "luajit:\|ERR" <<<"$out";; esac
		done
		for r in host client; do
			runs=$((runs+1))
			out=$(ZGO_BAKED=$b luajit zgo_test_mp.lua "$r" "$s" 2>&1 | tail -1)
			case "$out" in *OK*) ;; *) fails=$((fails+1)); echo "FAIL baked=$b seed=$s mp-$r: $out";; esac
		done
	done
done
# co-op with a baked host and a client without a bake in use (sets ZGO_BAKED per role itself)
for s in $seeds; do
	runs=$((runs+1))
	out=$(luajit zgo_test_mp_mixed.lua "$s" 2>&1 | tail -1)
	case "$out" in *PASSED*) ;; *) fails=$((fails+1)); echo "FAIL seed=$s mp-mixed: $out";; esac
done
# a cut body offline and back (every role, baked and not; sets ZGO_BAKED itself)
runs=$((runs+1))
out=$(luajit zgo_test_respawn.lua 2>&1 | tail -1)
case "$out" in *PASSED*) ;; *) fails=$((fails+1)); echo "FAIL respawn: $out";; esac
echo "$runs runs, $fails failures"
[ "$fails" -eq 0 ]
