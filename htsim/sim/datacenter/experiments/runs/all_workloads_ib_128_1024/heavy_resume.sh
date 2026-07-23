#!/bin/bash
# Resume: run ONLY the 1024-node (heavy) phase with per-run scratch on the 210GB
# disk (WORKROOT), then re-assemble the combined CSVs from all rows (the 45
# light 128-node rows are already saved). Light phase is NOT re-run.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_128_1024"
R="$OUT/run_one_ib.sh"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_sweep_work}"
export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-120000000}" LOGTIME_US="${LOGTIME_US:-1000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

HEAVY="$OUT/jobs_heavy.txt"; : > "$HEAVY"
for m in "$OUT"/matrices/*.cm; do
  bn=$(basename "$m" .cm)
  case "$bn" in allreduce_*) continue ;; esac
  n=$(echo "$bn" | grep -oE '[0-9]+n' | head -1 | tr -d 'n')
  [ "$n" = "1024" ] || continue
  for fb in 1os 4os 8os; do echo "$m $fb" >> "$HEAVY"; done
done

echo "[$(date)] HEAVY (1024-node)=$(wc -l < "$HEAVY") jobs @ -P2, WORKROOT=$WORKROOT"
xargs -P 2 -L 1 bash "$R" < "$HEAVY"
echo "[$(date)] heavy phase done"

# --- Re-assemble combined CSVs from ALL rows (light + heavy) ---
CSV_MAIN="$OUT/results_combined.csv"; CSV_UTIL="$OUT/utilization_combined.csv"
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
echo "[$(date)] COMPLETE  main=$(($(wc -l < "$CSV_MAIN")-1)) rows  util=$(($(wc -l < "$CSV_UTIL")-1)) rows"
