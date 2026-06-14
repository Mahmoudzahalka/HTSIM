#!/usr/bin/env bash
# targetq_sweep_moe.sh — probe the ROOT CAUSE fix: NSCC's queue-delay setpoint.
# Root cause (see FINDINGS.md §3): NSCC misses its _target_Qdelay (~9.76us) by 4-6x,
# so queues ride full and RTT pins to the RTO. Test: lower -target_q_delay (more
# aggressive backoff) and watch, via -rtx_stats, whether it bounds the queue
# (avg_rtt down), cuts the spurious storm, and what it costs in makespan.
# All else default (1xBDP, auto RTO, MIXED), -sender_cc_only, NO -sleek.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/targetq_sweep_moe_results.txt
ANALYZE=./analyze.sh
SIM_ABORT_US=400000

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64n, fat_tree_64_1os, 200Gbps) NSCC target_q_delay sweep"
  echo "# -sender_cc_only -rtx_stats, NO -sleek. Default target_q_delay ~9.76us."
  echo "# Generated: $(date). Tests whether tighter NSCC backoff bounds the queue."
  echo "############################################################"
} >> "$SUMMARY"

for tq in 9.76 6 3 1.5; do
  out="$RUNDIR/moe8x8b_ft64_tq${tq}.out"
  echo "===== [sweep] target_q_delay=${tq}us -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -rtx_stats -target_q_delay "$tq" \
      -nodes 64 -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0; note=""
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [tq=$tq] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ -n "${now:-}" ]] && awk -v n="$now" -v c="$SIM_ABORT_US" 'BEGIN{exit !(n>c)}'; then
      note=" *** ABORTED: runaway past ${SIM_ABORT_US}us ***"
      echo "  [tq=$tq]$note"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [tq=$tq] complete (finished=$cur)"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
  done
  # representative steady-state RTT = mean of non-zero avg_rtt samples
  rttline=$(grep "\[RTXSTATS\]" "$out" | grep -oE "avg_rtt=[0-9.]+us max_rtt=[0-9.]+us" \
            | awk -F'[=u]' '$2>0{s+=$2; m+=$5; n++} END{if(n)printf "mean avg_rtt=%.1fus  mean max_rtt=%.1fus  (n=%d)", s/n, m/n, n; else print "no rtt samples"}')
  {
    echo
    echo "============================================================"
    echo "target_q_delay = ${tq} us${note}"
    echo "  RTT: ${rttline}"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done tq=${tq} ====="
done
echo "ALL DONE -> $SUMMARY"
