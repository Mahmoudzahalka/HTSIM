#!/bin/bash
# IB PFC-only sweep of the 5 workload families across fabrics {1os,4os,8os} and
# node counts {128,1024}, mirroring the UEC all_workloads_128_1024/sweep.sh so
# results join directly. Reuses the SAME .cm matrices (via the matrices symlink).
#
# Phase A: all 128-node runs at -P5. Phase B: all 1024-node runs at -P2
# (heavier; watchdog ends each at flow completion). allreduce_* skipped
# (triggered-flow cascade broken in stock main, same as the UEC sweep).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_128_1024"
R="$OUT/run_one_ib.sh"
mkdir -p "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-120000000}" LOGTIME_US="${LOGTIME_US:-1000}" QSIZE="${QSIZE:-1000}"

LIGHT="$OUT/jobs_light.txt"; HEAVY="$OUT/jobs_heavy.txt"; : > "$LIGHT"; : > "$HEAVY"

for m in "$OUT"/matrices/*.cm; do
  bn=$(basename "$m" .cm)
  case "$bn" in allreduce_*) continue ;; esac
  n=$(echo "$bn" | grep -oE '[0-9]+n' | head -1 | tr -d 'n')
  for fb in 1os 4os 8os; do
    if [ "$n" = "1024" ]; then echo "$m $fb" >> "$HEAVY"; else echo "$m $fb" >> "$LIGHT"; fi
  done
done

echo "[$(date)] LIGHT (128-node)=$(wc -l < "$LIGHT") jobs @ -P5"
echo "[$(date)] HEAVY (1024-node)=$(wc -l < "$HEAVY") jobs @ -P2"

xargs -P 5 -L 1 bash "$R" < "$LIGHT"
echo "[$(date)] light phase done"
xargs -P 2 -L 1 bash "$R" < "$HEAVY"
echo "[$(date)] heavy phase done"

# --- Assemble CSVs (identical schema to the UEC sweep) ---
CSV_MAIN="$OUT/results_combined.csv"
CSV_UTIL="$OUT/utilization_combined.csv"

echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV_MAIN"
cat "$OUT"/rows/*.row >> "$CSV_MAIN" 2>/dev/null || true

{
  printf "matrix,fabric"
  for tier in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for stat in n mean p50 p95 p99 max; do printf ",%s_%s" "$tier" "$stat"; done
  done
  printf "\n"
} > "$CSV_UTIL"
cat "$OUT"/util_rows/*.urow >> "$CSV_UTIL" 2>/dev/null || true

echo "[$(date)] COMPLETE"
echo "  main: $CSV_MAIN ($(($(wc -l < "$CSV_MAIN")-1)) rows)"
echo "  util: $CSV_UTIL ($(($(wc -l < "$CSV_UTIL")-1)) rows)"
