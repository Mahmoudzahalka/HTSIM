#!/bin/bash
# Ring AllReduce sweep: 128/1024 nodes x {16,64,100} MB x {1os,4os,8os} = 18 runs.
# Two-phase: LIGHT (128-node) -P5, HEAVY (1024-node) -P2.
# -end 300000 (300s sim cap) is safety only; watchdog SIGTERMs on Connections-M.
set -u
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/allreduce_ring_128_1024"
R="$OUT/run_one.sh"
mkdir -p "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

export TIMEOUT="${TIMEOUT:-172800}"       # 48h wall-clock cap per run
export END_MS="${END_MS:-300000}"         # 300s sim cap (very generous)
export LOGTIME_US="${LOGTIME_US:-1000}"   # 1ms utilization sampling

LIGHT="$OUT/jobs_light.txt"; HEAVY="$OUT/jobs_heavy.txt"; : > "$LIGHT"; : > "$HEAVY"

for m in "$OUT"/matrices/*.cm; do
  bn=$(basename "$m" .cm)
  n=$(echo "$bn" | grep -oE '[0-9]+n' | head -1 | tr -d 'n')
  for fb in 1os 4os 8os; do
    if [ "$n" = "128" ]; then
      echo "$m $fb" >> "$LIGHT"
    else
      echo "$m $fb" >> "$HEAVY"
    fi
  done
done

echo "[$(date)] LIGHT=$(wc -l < "$LIGHT") jobs @ -P5 (128-node)"
echo "[$(date)] HEAVY=$(wc -l < "$HEAVY") jobs @ -P2 (1024-node)"

# Phase A: light @ -P5
xargs -P 5 -L 1 bash "$R" < "$LIGHT"
echo "[$(date)] light phase done"

# Phase B: heavy @ -P2
xargs -P 2 -L 1 bash "$R" < "$HEAVY"
echo "[$(date)] heavy phase done"

# Assemble CSVs
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
