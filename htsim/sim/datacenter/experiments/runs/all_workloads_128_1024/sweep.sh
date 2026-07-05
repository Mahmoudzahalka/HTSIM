#!/bin/bash
# Two-phase sweep of all matrices in all_workloads_128_1024/matrices across
# fabrics {1os,4os,8os}. Phase A: light (perm + butterfly-AR + small collectives)
# at -P5. Phase B: heavy (ring-AR + incast/outcast at 1024 with big flows) at -P2.
set -u
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_128_1024"
R="$OUT/run_one.sh"
mkdir -p "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

export TIMEOUT="${TIMEOUT:-86400}" END_MS="${END_MS:-30000}" LOGTIME_US="${LOGTIME_US:-1000}"

LIGHT="$OUT/jobs_light.txt"; HEAVY="$OUT/jobs_heavy.txt"; : > "$LIGHT"; : > "$HEAVY"

for m in "$OUT"/matrices/*.cm; do
  bn=$(basename "$m" .cm)
  # Skip AllReduce (both ring + butterfly): triggered-flow cascade is broken
  # in stock htsim main -- see WORKLOADS notes. Investigate separately.
  case "$bn" in allreduce_*) continue ;; esac
  # Extract node count from filename (e.g. perm_random_1024n_100MB -> 1024)
  n=$(echo "$bn" | grep -oE '[0-9]+n' | head -1 | tr -d 'n')
  sz=$(echo "$bn" | grep -oE '[0-9]+MB' | head -1 | tr -d 'MB')
  for fb in 1os 4os 8os; do
    heavy=0
    # Incast/outcast at 1024 with >=64MB flows are receiver-bound, slow.
    if [[ "$n" == 1024 && "$sz" -ge 64 ]] 2>/dev/null; then
      case "$bn" in
        incast_*|outcast_*) heavy=1 ;;
      esac
    fi
    if [ "$heavy" = 1 ]; then
      echo "$m $fb" >> "$HEAVY"
    else
      echo "$m $fb" >> "$LIGHT"
    fi
  done
done

echo "[$(date)] LIGHT=$(wc -l < "$LIGHT") jobs @ -P5"
echo "[$(date)] HEAVY=$(wc -l < "$HEAVY") jobs @ -P2 (queued after light)"

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

# Utilization header: matrix, fabric, then n/mean/p50/p95/p99/max for
# overall + tier0_up, tier0_down, tier1_up, tier1_down, tier2_up, tier2_down
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
