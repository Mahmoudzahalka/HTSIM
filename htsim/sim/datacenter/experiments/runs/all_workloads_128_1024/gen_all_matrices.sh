#!/bin/bash
# Generate all connection matrices for the workloads_128_1024 sweep.
# 7 patterns x {128,1024} x {16,64,100} MB = 42 matrices.
set -euo pipefail
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
CM=$DC/connection_matrices
OUT=$DC/experiments/runs/all_workloads_128_1024/matrices
SEED=1
mkdir -p "$OUT"

for N in 128 1024; do
  for S_MB in 16 64 100; do
    S=$((S_MB * 1000 * 1000))  # bytes (decimal MB, matches a3 convention)
    tag="${N}n_${S_MB}MB"
    C_INC=$((N - 1))         # random incast: all others -> node 0
    C_REM=$((N / 2))         # remote incast: far-half senders
    C_O1=$((N / 8))          # outcast+incast: fan-in
    C_O2=4                   # outcast+incast: fan-out per sender

    python3 "$CM/gen_permutation.py"                "$OUT/perm_random_${tag}.cm"          "$N" "$N"   "$S" 0 "$SEED"
    python3 "$CM/gen_permutation_full_bisection.py" "$OUT/perm_fullbis_${tag}.cm"         "$N" "$N"   "$S" 0 "$SEED"
    python3 "$CM/gen_incast.py"                     "$OUT/incast_random_${tag}.cm"        "$N" "$C_INC" "$S" 0 "$SEED" 0
    python3 "$CM/gen_incast.py"                     "$OUT/incast_remote_${tag}.cm"        "$N" "$C_REM" "$S" 0 "$SEED" 1
    python3 "$CM/gen_outcast_incast.py"             "$OUT/outcast_incast_${tag}.cm"       "$N" "$C_O1" "$C_O2" "$S" "$SEED"
    python3 "$CM/gen_allreduce.py"                  "$OUT/allreduce_ring_${tag}.cm"       "$N" "$N"   "$N" "$S" 0 "$SEED"
    python3 "$CM/gen_allreduce_butterfly.py"        "$OUT/allreduce_butterfly_${tag}.cm"  "$N" 1     "$N" "$S" 0 "$SEED"
  done
done

echo "Generated $(ls "$OUT"/*.cm | wc -l) matrices in $OUT"
