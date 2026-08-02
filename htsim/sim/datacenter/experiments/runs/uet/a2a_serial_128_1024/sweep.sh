#!/bin/bash
# Two-phase A2A sweep: full all-to-all x {16,64,100}MB x {1os,4os,8os} on
# 128 and 1024-node fat trees. Same runner/watchdog/metrics as the previous
# all_workloads_128_1024 + allreduce_ring_128_1024 sweeps.
#
#   Phase A: 128-node runs (small, ~1-2GB each) at -P3.
#   Phase B: 1024-node runs (~1M flows, ~20-25GB each) strictly at -P1.
# The two phases are sequential -- 128 fully completes before any 1024 run
# starts -- so 128 and 1024 never run concurrently (memory safety + explicit
# "don't parallelize 128 and 1024" requirement).
#
# Heavy scratch (work/) and filtered logs live on the 196GB Data partition
# (root fs has only ~2GB free); tiny rows/util_rows/CSVs land in this repo dir.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/uet/a2a_serial_128_1024"
DATA="${DATA:-/media/mahmoud_murad_allaah/Data/a2a_128_1024}"
R="$OUT/run_one.sh"
mkdir -p "$OUT/rows" "$OUT/util_rows" "$DATA/logs" "$DATA/work"

export TIMEOUT="${TIMEOUT:-86400}"      # 24h wall cap per run
export END_MS="${END_MS:-600000}"       # 600s sim cap -- generous so the serial
                                        # A2A trigger chain never gets clipped;
                                        # watchdog SIGTERMs at true completion
export LOGTIME_US="${LOGTIME_US:-1000}" # 1 ms utilization sampling
export DATA

LIGHT="$OUT/jobs_128.txt"; HEAVY="$OUT/jobs_1024.txt"; : > "$LIGHT"; : > "$HEAVY"

for N in 128 1024; do
  for SZ in 16 64 100; do
    m="$DATA/matrices/a2a_${N}n_${SZ}MB.cm"
    for fb in 1os 4os 8os; do
      if [ "$N" = 128 ]; then echo "$m $fb" >> "$LIGHT"; else echo "$m $fb" >> "$HEAVY"; fi
    done
  done
done

echo "[$(date)] Phase A: 128-node = $(wc -l < "$LIGHT") jobs @ -P4"
xargs -P 4 -L 1 bash "$R" < "$LIGHT"
echo "[$(date)] Phase A (128) done"

echo "[$(date)] Phase B: 1024-node = $(wc -l < "$HEAVY") jobs @ -P1"
xargs -P 1 -L 1 bash "$R" < "$HEAVY"
echo "[$(date)] Phase B (1024) done"

# --- Assemble CSVs (same schema as the prior sweeps) ---
CSV_MAIN="$OUT/results_combined.csv"
CSV_UTIL="$OUT/utilization_combined.csv"

echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV_MAIN"
cat "$OUT"/rows/*.row >> "$CSV_MAIN" 2>/dev/null || true

{
  printf "matrix,fabric"
  for tier in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for stat in n mean p50 p95 p99 max; do
      printf ",%s_%s" "$tier" "$stat"
    done
  done
  printf "\n"
} > "$CSV_UTIL"
cat "$OUT"/util_rows/*.urow >> "$CSV_UTIL" 2>/dev/null || true

echo "[$(date)] COMPLETE"
echo "  main: $CSV_MAIN ($(($(wc -l < "$CSV_MAIN")-1)) rows)"
echo "  util: $CSV_UTIL ($(($(wc -l < "$CSV_UTIL")-1)) rows)"
