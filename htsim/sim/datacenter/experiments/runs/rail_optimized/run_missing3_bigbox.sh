#!/bin/bash
# The 3 outstanding runs: MoE all-to-all, 2048 GPUs, 100 MB -- on the 94 GB box.
#   ib.rail  - was OOM-killed at q=8000 on the old 31 GB box
#   ib.flat  - never finished (sweep stopped)
#   uet.flat - never started
# Serial (-P1) so the two ~32 GB IB runs never overlap. -q 8000 per RUN_ON_BIGGER_BOX.md
# (proven overflow-free at 2048); MUST still verify overflow=0 in the rows.
set -u
OUT=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter/experiments/runs/rail_optimized
export WORKROOT=/var/tmp/rail_work SCALE=2048 QSIZE=8000
export TIMEOUT=86400 END_US=600000000 LOGTIME_US=20000
M="$OUT/matrices/rail_alltoall_moe_2048gpu_100MB.cm"   # absolute: run_one_rail.sh cds into $work
echo "[$(date)] 3 missing runs @ -q $QSIZE, -P1"
for spec in "ib rail" "uet flat" "ib flat"; do
  set -- $spec
  echo "[$(date)] === starting $1 $2 ==="
  bash "$OUT/run_one_rail.sh" "$M" "$1" "$2"
done
echo "[$(date)] done"
