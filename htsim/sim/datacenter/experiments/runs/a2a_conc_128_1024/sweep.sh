#!/bin/bash
# Two-phase CONCURRENT-GLOBAL A2A sweep on the /csl (Technion) box.
#
# Workload: full all-to-all over the WHOLE topology (groupsize = N), launched
# CONCURRENTLY -- every source posts all (N-1) peer flows at once
# (gen_serialn_alltoall.py with parallel = N-1, Triggers 0). This models an
# optimized MoE-style collective all-to-all, unlike the earlier serial
# a2a_128_1024 sweep (one flow in flight per source).
#
#   Phase A: 128-node runs at -P1.
#   Phase B: 1024-node runs strictly at -P1 (each pre-allocates ~1M
#            UecSrc+UecSink; run one at a time for memory safety).
# Entire sweep is serial (-P1) -- shared machine, keep memory footprint minimal
# (one htsim at a time). Phases are sequential -- 128 fully completes first.
set -u
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/a2a_conc_128_1024"
R="$OUT/run_one.sh"
GEN="$DC/connection_matrices/gen_serialn_alltoall.py"
mkdir -p "$OUT/matrices" "$OUT/rows" "$OUT/util_rows" "$OUT/logs" "$OUT/work"

export TIMEOUT="${TIMEOUT:-86400}"      # 24h wall cap per run
export END_MS="${END_MS:-600000}"       # 600s sim cap (watchdog SIGTERMs first)
export LOGTIME_US="${LOGTIME_US:-1000}" # 1 ms utilization sampling

# --- Generate matrices: concurrent global a2a, flow = SZ*1e6 bytes, seed 1 ---
for N in 128 1024; do
  P=$((N-1))
  for SZ in 16 64 100; do
    m="$OUT/matrices/a2a_${N}n_${SZ}MB.cm"
    if [ ! -s "$m" ]; then
      python3 "$GEN" "$m" "$N" "$N" "$N" "$P" "$((SZ*1000000))" 0 1 >/dev/null 2>&1
      echo "[gen] $(basename "$m")  conns=$(grep -m1 Connections "$m" | awk '{print $2}')  triggers=$(grep -m1 Triggers "$m" | awk '{print $2}')"
    fi
  done
done

LIGHT="$OUT/jobs_128.txt"; HEAVY="$OUT/jobs_1024.txt"; : > "$LIGHT"; : > "$HEAVY"
for N in 128 1024; do
  for SZ in 16 64 100; do
    m="$OUT/matrices/a2a_${N}n_${SZ}MB.cm"
    for fb in 1os 4os 8os; do
      if [ "$N" = 128 ]; then echo "$m $fb" >> "$LIGHT"; else echo "$m $fb" >> "$HEAVY"; fi
    done
  done
done

echo "[$(date)] Phase A: 128-node = $(wc -l < "$LIGHT") jobs @ -P1"
xargs -P 1 -L 1 bash "$R" < "$LIGHT"
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
