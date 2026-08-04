#!/bin/bash
# Re-run the 12 MoE all-to-all runs (both scales) with a LARGER lossless buffer.
# Rationale: at -q 1000 the IB lossless queues overflowed (htsim only warns and
# keeps the packet), so those runs silently modelled a bigger buffer than asked.
# Verified on MoE-1024-100MB: q=1000 -> 12,833 overflow, q=4000/8000 -> 0, and the
# makespan is IDENTICAL (29,603.3 us) in all three, so this fixes the CONFIGURATION
# without changing the physics. All-reduce runs were already overflow-free at q=1000.
set -u
OUT=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter/experiments/runs/rail_optimized
R="$OUT/run_one_rail.sh"
export WORKROOT=/media/mahmoud_murad_allaah/Data/rail_work
export QSIZE=8000 TIMEOUT=86400 END_US=600000000 LOGTIME_US=20000
J="$OUT/jobs_moe.txt"; : > "$J"
for SC in 1024 2048; do for S in 16 64 100; do
  m="$OUT/matrices/rail_alltoall_moe_${SC}gpu_${S}MB.cm"
  [ -f "$m" ] || continue
  for topo in rail flat; do for stack in ib uet; do echo "$SC $m $stack $topo" >> "$J"; done; done
done; done
echo "[$(date)] MoE re-run at QSIZE=$QSIZE: $(wc -l < "$J") runs @ -P1"
while read -r sc m stack topo; do SCALE=$sc bash "$R" "$m" "$stack" "$topo"; done < "$J"
echo "[$(date)] runs done"
HDR="matrix,workload,size_MB,nodes,conns,stack,topology,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious,pfc_pauses,pfc_pause_us,max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain,overflow"
CSV="$OUT/results_rail.csv"; UCSV="$OUT/utilization_rail.csv"
echo "$HDR" > "$CSV"; cat "$OUT"/ib_dcqcn/rows/*.row "$OUT"/uet/rows/*.row >> "$CSV" 2>/dev/null || true
{ printf "matrix,stack,topology"; for t in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for s in n mean p50 p95 p99 max; do printf ",%s_%s" "$t" "$s"; done; done; printf "\n"; } > "$UCSV"
cat "$OUT"/ib_dcqcn/util_rows/*.urow "$OUT"/uet/util_rows/*.urow >> "$UCSV" 2>/dev/null || true
echo "[$(date)] COMPLETE results=$(($(wc -l<"$CSV")-1))/48 ok=$(cat "$OUT"/{ib_dcqcn,uet}/rows/*.row 2>/dev/null|awk -F, '$8=="ok"'|wc -l) overflow_flagged=$(cat "$OUT"/{ib_dcqcn,uet}/rows/*.row 2>/dev/null|awk -F, '$8=="lossless_overflow"'|wc -l)"
