#!/bin/bash
# Regenerate the 12 rail matrices that are NOT in git (218 MB — too big to commit).
# The other 36 the study needs are tracked, so they arrive with the clone.
#
# Both generators are deterministic (no RNG), so this reproduces the files
# BYTE-FOR-BYTE — verified against the originals with cmp. Each file is checked
# against the connection count MANIFEST.csv expects, so a silent mismatch cannot
# slip through.
#
#   usage:  HTSIM_ROOT=/path/to/HTSIM/htsim  bash bin/regen_matrices.sh
#   time:   ~2 minutes
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HTSIM_ROOT="${HTSIM_ROOT:-$HOME/HTSIM/htsim}"
CM="${CM:-$HTSIM_ROOT/sim/datacenter/connection_matrices}"
OUT="$FID/matrices/rail"

for g in gen_rail_aware_allreduce.py gen_rail_aware_alltoall.py; do
  [ -f "$CM/$g" ] || { echo "FATAL: generator not found: $CM/$g  (set HTSIM_ROOT or CM)" >&2; exit 2; }
done
mkdir -p "$OUT"

# expected Connections per file, taken from MANIFEST.csv itself
expected () { awk -F, -v b="$1" 'NR>1 && $2 ~ b {print $6; exit}' "$FID/MANIFEST.csv"; }

fail=0
for N in 1024 2048; do
  for MB in 16 64 100; do
    B=$((MB * 1000000))
    for kind in allreduce alltoall_moe; do
      case "$kind" in
        allreduce)    gen=gen_rail_aware_allreduce.py; f="rail_allreduce_${N}gpu_${MB}MB.cm" ;;
        alltoall_moe) gen=gen_rail_aware_alltoall.py;  f="rail_alltoall_moe_${N}gpu_${MB}MB.cm" ;;
      esac
      printf "  %-38s " "$f"
      python3 "$CM/$gen" "$OUT/$f" "$N" 8 "$B" > /dev/null 2>&1 || { echo "GENERATOR FAILED"; fail=1; continue; }
      got=$(grep -m1 -oE '^Connections [0-9]+' "$OUT/$f" | awk '{print $2}')
      want=$(expected "$f")
      if [ -z "$want" ]; then echo "$got flows (not in manifest — skipped check)"
      elif [ "$got" = "$want" ]; then echo "$got flows  OK"
      else echo "MISMATCH: got $got, manifest expects $want"; fail=1; fi
    done
  done
done

echo
if [ "$fail" = 0 ]; then
  echo "All 12 regenerated and verified against MANIFEST.csv."
  du -sh "$OUT" | awk '{print "  matrices/rail is now "$1}'
else
  echo "REGENERATION FAILED — do not start the sweep."; exit 1
fi
