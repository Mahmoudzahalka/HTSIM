#!/bin/bash
# DCQCN sweep (K=8): 5 patterns x {16,64,100}MB x {1,4,8}os x {128,1024} nodes = 90 runs.
# Light 128-node phase @ -P6, heavy 1024-node phase @ -P2 (scratch on 210GB disk).
# Directly comparable to the PFC-only results_combined.csv. Resume-aware.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_dcqcn_k8_128_1024"
R="$OUT/run_one_dcqcn.sh"
MATRICES="$DC/experiments/runs/all_workloads_128_1024/matrices"
export DCQCN_K="${DCQCN_K:-8}"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/dcqcn_sweep_work}"
export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-120000000}" LOGTIME_US="${LOGTIME_US:-1000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

# Build job lists (exclude allreduce/butterfly), cheapest-first within each phase.
LIGHT="$OUT/jobs_light.txt"; HEAVY="$OUT/jobs_heavy.txt"; : > "$LIGHT"; : > "$HEAVY"
for S in 16 64 100; do
  for pat in perm_random perm_fullbis incast_remote outcast_incast incast_random; do
    for N in 128 1024; do
      m="$MATRICES/${pat}_${N}n_${S}MB.cm"
      [ -f "$m" ] || continue
      for fb in 1os 4os 8os; do
        if [ "$N" = 128 ]; then echo "$m $fb" >> "$LIGHT"; else echo "$m $fb" >> "$HEAVY"; fi
      done
    done
  done
done

echo "[$(date)] DCQCN sweep K=$DCQCN_K  light=$(wc -l <"$LIGHT") @ -P6, heavy=$(wc -l <"$HEAVY") @ -P2  WORKROOT=$WORKROOT"
echo "[$(date)] === LIGHT (128-node) phase ==="
xargs -P 6 -L 1 bash "$R" < "$LIGHT"
echo "[$(date)] light done; === HEAVY (1024-node) phase ==="
xargs -P 2 -L 1 bash "$R" < "$HEAVY"
echo "[$(date)] heavy done"

# --- Assemble combined CSVs ---
CSV_MAIN="$OUT/results_dcqcn_k8.csv"; CSV_UTIL="$OUT/utilization_dcqcn_k8.csv"
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
echo "[$(date)] COMPLETE  main=$(($(wc -l <"$CSV_MAIN")-1))/90 rows  util=$(($(wc -l <"$CSV_UTIL")-1)) rows  ok=$(cat "$OUT"/rows/*.row 2>/dev/null|awk -F, '$5=="ok"'|wc -l)"
