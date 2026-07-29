#!/bin/bash
# IB-vs-UET comparison sweep (DCQCN K=8, MTU 4000, full instrumentation).
# Phase 1 (light,-P6): all_workloads 128-node (5 pat x 3 sz x 3 fb) + a2a-128.
# Phase 2 (heavy,-P2): all_workloads 1024-node.
# Phase 3 (a2a-1024,-P1, 6h cap): best-effort (1M flows; UET timed out here too).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/ib_uet_compare_128_1024"
R="$OUT/run_one_compare.sh"
AW="$DC/experiments/runs/all_workloads_128_1024/matrices"
A2A="$DC/experiments/runs/a2a_conc_128_1024/matrices"
export DCQCN_K="${DCQCN_K:-8}"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_compare_work}"
export END_US="${END_US:-120000000}" LOGTIME_US="${LOGTIME_US:-1000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

# a2a is memory-heavy (~8GB/run: all-to-all route explosion for 16k flows) so it
# gets its OWN low-parallelism phase, kept out of the -P6 light phase (which OOM'd
# it). a2a-1024 (1M flows, ~64x the memory) is dropped: it OOMs instantly and UET
# timed out there too -- "infeasible at 1024" is the comparable conclusion.
L="$OUT/jobs_light.txt"; H="$OUT/jobs_heavy.txt"; A="$OUT/jobs_a2a128.txt"; :>"$L"; :>"$H"; :>"$A"
for S in 16 64 100; do
  for pat in perm_random perm_fullbis incast_remote outcast_incast incast_random; do
    for fb in 1os 4os 8os; do
      [ -f "$AW/${pat}_128n_${S}MB.cm" ]  && echo "$AW/${pat}_128n_${S}MB.cm $fb"  >> "$L"
      [ -f "$AW/${pat}_1024n_${S}MB.cm" ] && echo "$AW/${pat}_1024n_${S}MB.cm $fb" >> "$H"
    done
  done
  for fb in 1os 4os 8os; do
    [ -f "$A2A/a2a_128n_${S}MB.cm" ] && echo "$A2A/a2a_128n_${S}MB.cm $fb" >> "$A"
  done
done

echo "[$(date)] IB-vs-UET sweep K=$DCQCN_K MTU=4000  light=$(wc -l<"$L") heavy=$(wc -l<"$H") a2a128=$(wc -l<"$A")"
echo "[$(date)] === Phase 1: light (128-node all_workloads) @ -P6 ==="
xargs -P 6 -L 1 bash "$R" < "$L"
echo "[$(date)] === Phase 2: heavy (1024-node all_workloads) @ -P2 ==="
xargs -P 2 -L 1 bash "$R" < "$H"
echo "[$(date)] === Phase 3: a2a-128 @ -P2 (memory-heavy) ==="
xargs -P 2 -L 1 bash "$R" < "$A"
echo "[$(date)] all phases done"

# --- assemble CSVs ---
CSV="$OUT/results_ib.csv"; UCSV="$OUT/utilization_ib.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious,pfc_pauses,pfc_pause_us,max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain" > "$CSV"
cat "$OUT"/rows/*.row >> "$CSV" 2>/dev/null || true
{ printf "matrix,fabric"; for t in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do for s in n mean p50 p95 p99 max; do printf ",%s_%s" "$t" "$s"; done; done; printf "\n"; } > "$UCSV"
cat "$OUT"/util_rows/*.urow >> "$UCSV" 2>/dev/null || true
echo "[$(date)] COMPLETE  results=$(($(wc -l<"$CSV")-1)) rows  util=$(($(wc -l<"$UCSV")-1))  ok=$(cat "$OUT"/rows/*.row 2>/dev/null|awk -F, '$5=="ok"'|wc -l)"
