#!/bin/bash
# The 3 outstanding runs: MoE all-to-all, 2048 GPUs, 100 MB.
#   ib.rail  - was OOM-killed at q=8000 (31.9 GB, kernel log 18:20:18)
#   ib.flat  - never finished (sweep stopped)
#   uet.flat - never started
# Retrying at -q 4000: half the buffer memory of q=8000. MUST verify overflow=0,
# since q=4000 is only proven overflow-free at 1024, never at 2048.
set -u
OUT=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs/rail_optimized
export WORKROOT=/media/mahmoud_murad_allaah/Data/rail_work SCALE=2048 QSIZE=4000
export TIMEOUT=86400 END_US=600000000 LOGTIME_US=20000
M="$OUT/matrices/rail_alltoall_moe_2048gpu_100MB.cm"
echo "[$(date)] 3 missing runs @ -q $QSIZE, -P1"
for spec in "ib rail" "uet flat" "ib flat"; do
  set -- $spec
  bash "$OUT/run_one_rail.sh" "$M" "$1" "$2"
done
echo "[$(date)] done"
