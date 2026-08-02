#!/bin/bash
# IB workload-parity sweep: the two workloads UET has but IB was missing.
#   Phase 1: ring all-reduce (128n x {16,64,100}MB x {1,4,8}os) = 9 runs
#   Phase 2: SERIAL all-to-all (same grid)                      = 9 runs
# Both are trigger-driven (staged), so only a few flows are active at once ->
# memory is light (~0.3GB/run) and we can run -P4. Serial a2a matrices share
# basenames with the concurrent ones, so TAG_PREFIX=serial_ keeps rows distinct.
# Same instrumented harness/schema as ib_uet_compare_128_1024 (29 cols).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/ib_dcqcn/allreduce_a2a_serial_128"
R="$OUT/run_one_parity.sh"
AR="$DC/experiments/runs/uet/allreduce_ring_128/matrices"
A2A_SERIAL="/media/mahmoud_murad_allaah/Data/a2a_128_1024/matrices"
export DCQCN_K="${DCQCN_K:-8}"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_parity_work}"
export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-120000000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

J1="$OUT/jobs_allreduce.txt"; J2="$OUT/jobs_a2a_serial.txt"; :>"$J1"; :>"$J2"
for S in 16 64 100; do
  for fb in 1os 4os 8os; do
    [ -f "$AR/allreduce_ring_128n_${S}MB.cm" ]  && echo "$AR/allreduce_ring_128n_${S}MB.cm $fb"  >> "$J1"
    [ -f "$A2A_SERIAL/a2a_128n_${S}MB.cm" ]     && echo "$A2A_SERIAL/a2a_128n_${S}MB.cm $fb"     >> "$J2"
  done
done

echo "[$(date)] IB workload parity  allreduce=$(wc -l<"$J1")  a2a_serial=$(wc -l<"$J2")  K=$DCQCN_K"
echo "[$(date)] === Phase 1: ring all-reduce @ -P4 ==="
xargs -P 4 -L 1 bash "$R" < "$J1"
echo "[$(date)] === Phase 2: serial all-to-all @ -P4 (TAG_PREFIX=serial_) ==="
TAG_PREFIX=serial_ xargs -P 4 -L 1 env TAG_PREFIX=serial_ bash "$R" < "$J2"
echo "[$(date)] all phases done"

CSV="$OUT/results_ib_parity.csv"; UCSV="$OUT/utilization_ib_parity.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious,pfc_pauses,pfc_pause_us,max_queue_bytes,slowdown_p50,slowdown_p99,slowdown_max,fairness_jain" > "$CSV"
cat "$OUT"/rows/*.row >> "$CSV" 2>/dev/null || true
{ printf "matrix,fabric"; for t in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do for s in n mean p50 p95 p99 max; do printf ",%s_%s" "$t" "$s"; done; done; printf "\n"; } > "$UCSV"
cat "$OUT"/util_rows/*.urow >> "$UCSV" 2>/dev/null || true
echo "[$(date)] COMPLETE  results=$(($(wc -l<"$CSV")-1))/18  util=$(($(wc -l<"$UCSV")-1))  ok=$(cat "$OUT"/rows/*.row 2>/dev/null|awk -F, '$5=="ok"'|wc -l)"
