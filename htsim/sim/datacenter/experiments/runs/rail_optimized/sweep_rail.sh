#!/bin/bash
# Rail-optimized sweep: 2 rail-aware workloads x 3 sizes x 2 topologies x 2 stacks
# = 24 runs, NVLink enabled throughout. Full metric superset (33 cols) + per-tier
# utilization for both stacks. Cheapest-first ordering; resume-aware.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/rail_optimized"
R="$OUT/run_one_rail.sh"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/rail_work}"
export SCALE="${SCALE:-1024}"
export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-600000000}" LOGTIME_US="${LOGTIME_US:-20000}"
mkdir -p "$WORKROOT" "$OUT"/{ib_dcqcn,uet}/{rows,util_rows,logs}

J="$OUT/jobs_rail.txt"; : > "$J"
for S in 16 64 100; do
  for wl in rail_allreduce rail_alltoall_moe; do
    m="$OUT/matrices/${wl}_${SCALE:-1024}gpu_${S}MB.cm"
    [ -f "$m" ] || continue
    for topo in rail flat; do for stack in ib uet; do echo "$m $stack $topo" >> "$J"; done; done
  done
done

echo "[$(date)] rail sweep: $(wc -l < "$J") runs @ -P${PARALLEL:-1}  (2 workloads x 3 sizes x 2 topos x 2 stacks)"
xargs -P "${PARALLEL:-1}" -L 1 bash "$R" < "$J"
echo "[$(date)] runs done"

# --- assemble ---
HDR="matrix,workload,size_MB,nodes,conns,stack,topology,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious,pfc_pauses,pfc_pause_us,max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain,overflow"
CSV="$OUT/results_rail.csv"; UCSV="$OUT/utilization_rail.csv"
echo "$HDR" > "$CSV"; cat "$OUT"/ib_dcqcn/rows/*.row "$OUT"/uet/rows/*.row >> "$CSV" 2>/dev/null || true
{ printf "matrix,stack,topology"
  for t in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for s in n mean p50 p95 p99 max; do printf ",%s_%s" "$t" "$s"; done; done; printf "\n"; } > "$UCSV"
cat "$OUT"/ib_dcqcn/util_rows/*.urow "$OUT"/uet/util_rows/*.urow >> "$UCSV" 2>/dev/null || true
echo "[$(date)] COMPLETE  results=$(($(wc -l<"$CSV")-1))/24  util=$(($(wc -l<"$UCSV")-1))  ok=$(cat "$OUT"/{ib_dcqcn,uet}/rows/*.row 2>/dev/null|awk -F, '$8=="ok"'|wc -l)"
