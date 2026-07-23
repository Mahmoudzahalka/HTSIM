#!/bin/bash
# Re-run the 6 incast_random_8192n {64,100}MB jobs that hit the 4h wall cap, this
# time with a multi-day budget so the 8191->1 fan-in fully drains. Parallelized
# -P6 (8-core box; each htsim is single-threaded => 6 cores busy, 2 spare for
# parse/system; 6 x ~3GB sim << 30GB). Util sampling forced to 200ms via
# LOGTIME_COARSE_US so each util.bin (and the parse_output that loads it whole)
# stays ~2GB even at tens-of-seconds makespans -> safe when several parse at once.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_128_1024"
R="$OUT/run_one_ib.sh"
export WORKROOT="/media/mahmoud_murad_allaah/Data/ib_sweep_work"
export TIMEOUT=345600          # 4-day wall cap per run (don't cut off the drain)
export END_US=600000000        # 600s simulated cap (well above expected ~40-100s makespan)
export LOGTIME_COARSE_US=200000 # 200ms util sampling for these long incast runs
mkdir -p "$WORKROOT"

JOBS="$OUT/jobs_incast6.txt"; : > "$JOBS"
for S in 64 100; do for fb in 1os 4os 8os; do
  echo "$OUT/matrices/incast_random_8192n_${S}MB.cm $fb" >> "$JOBS"
done; done

echo "[$(date)] rerun 6 incast_random jobs @ -P6  TIMEOUT=${TIMEOUT}s  util=200ms"
xargs -P 6 -L 1 bash "$R" < "$JOBS"
echo "[$(date)] rerun done"

# re-assemble the 8192 CSV from all 8192 rows (now with the re-run results)
CSV="$OUT/results_8192.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV"
cat "$OUT"/rows/*8192n*.row >> "$CSV" 2>/dev/null || true
echo "[$(date)] 8192 rows: $(($(wc -l < "$CSV")-1))/45  ok=$(cat "$OUT"/rows/*8192n*.row|awk -F, '$5=="ok"'|wc -l)"
