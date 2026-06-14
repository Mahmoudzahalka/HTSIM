#!/usr/bin/env bash
# qasmooth_sweep_moe.sh — test the QA-hysteresis fix on MoE.
# -qa_smooth alpha: new cwnd = alpha*achieved + (1-alpha)*old_cwnd on quick_adapt.
# alpha=1.0 = stock bang-bang (control); lower = softer. Q: does smoothing give a
# clean, stable completion (3007 flows) with less spurious / lower makespan?
# -sender_cc_only -rtx_stats, all else default, NO -sleek.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/qasmooth_sweep_moe_results.txt
ANALYZE=./analyze.sh
SIM_ABORT_US=400000

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64n) QA-hysteresis (-qa_smooth) sweep. 3007 flows = clean."
  echo "# alpha=1.0 = stock bang-bang (control). -sender_cc_only -rtx_stats."
  echo "# Generated: $(date)."
  echo "############################################################"
} >> "$SUMMARY"

for a in 1.0 0.75 0.5 0.25; do
  out="$RUNDIR/moe8x8b_ft64_qas${a}.out"
  echo "===== [sweep] qa_smooth=${a} -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -rtx_stats -qa_smooth "$a" \
      -nodes 64 -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0; note=""
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [qas=$a] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ -n "${now:-}" ]] && awk -v n="$now" -v c="$SIM_ABORT_US" 'BEGIN{exit !(n>c)}'; then
      note=" *** ABORTED: runaway past ${SIM_ABORT_US}us ***"
      echo "  [qas=$a]$note"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [qas=$a] complete (finished=$cur)"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
  done
  flows=$(grep -c "finished at" "$out"); mk=$(grep -oE "finished at [0-9.]+" "$out" | awk '{print $3}' | sort -n | tail -1)
  rtt=$(grep "\[RTXSTATS\]" "$out" | grep -oE "avg_rtt=[0-9.]+" | awk -F= '$2>0{s+=$2;n++} END{if(n)printf "%.1f",s/n; else print "NA"}')
  {
    echo
    echo "============================================================"
    echo "qa_smooth alpha = ${a}${note}"
    echo "  flows=${flows} (3007=clean)  makespan_us=${mk:-NA}  mean_avg_rtt_us=${rtt}"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done qa_smooth=${a} ====="
done
echo "ALL DONE -> $SUMMARY"
