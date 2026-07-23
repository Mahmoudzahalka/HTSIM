#!/bin/bash
# 8192-node IB sweep at -P1 (one run at a time; 8192 is ~8x the 1024 memory
# footprint, so serialize to stay clear of OOM on the 31GB box). Per-run scratch
# (util.bin + raw stdout) goes on the 210GB disk via WORKROOT.
# Jobs ordered cheapest-first (16MB->100MB, perm->incast) so the heaviest
# incast/outcast 100MB runs land last, after the box has proven healthy.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_128_1024"
R="$OUT/run_one_ib.sh"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_sweep_work}"
export TIMEOUT="${TIMEOUT:-14400}" END_US="${END_US:-600000000}" LOGTIME_US="${LOGTIME_US:-1000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

JOBS="$OUT/jobs_8192.txt"; : > "$JOBS"
# order: size 16->64->100, pattern perm(light) -> incast/outcast(heavy)
for S in 16 64 100; do
  for pat in perm_random perm_fullbis incast_remote outcast_incast incast_random; do
    m="$OUT/matrices/${pat}_8192n_${S}MB.cm"
    [ -f "$m" ] || continue
    for fb in 1os 4os 8os; do echo "$m $fb" >> "$JOBS"; done
  done
done

echo "[$(date)] 8192 sweep: $(wc -l < "$JOBS") jobs @ -P1  WORKROOT=$WORKROOT  TIMEOUT=${TIMEOUT}s"
xargs -P 1 -L 1 bash "$R" < "$JOBS"
echo "[$(date)] 8192 sweep done"

# assemble an 8192-only CSV (keeps it separate from the 128/1024 combined set)
CSV="$OUT/results_8192.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV"
cat "$OUT"/rows/*8192n*.row >> "$CSV" 2>/dev/null || true
echo "[$(date)] 8192 rows: $(($(wc -l < "$CSV")-1))/45"
