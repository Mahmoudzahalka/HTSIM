#!/usr/bin/env bash
# qagate_sweep_moe.sh — probe the quick_adapt bang-bang (the brittleness mechanism).
# QA fires when _achieved_bytes < (_maxwnd >> _qa_gate) and hard-resets cwnd to the
# delivered rate. Lower gate => QA fires more (stall-prone); higher => fires less
# (runaway-prone). Q: is there a gate giving STABLE completion, or is it bistable?
# All else default, -sender_cc_only -rtx_stats, NO -sleek.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/qagate_sweep_moe_results.txt
ANALYZE=./analyze.sh
SIM_ABORT_US=400000

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64n) quick_adapt -qa_gate sweep (default gate=3=maxwnd/8)"
  echo "# -sender_cc_only -rtx_stats, NO -sleek. Generated: $(date)."
  echo "# Tests whether the QA bang-bang has any stable (non stall/runaway) point."
  echo "############################################################"
} >> "$SUMMARY"

for g in 1 2 3 5 8; do
  out="$RUNDIR/moe8x8b_ft64_qag${g}.out"
  echo "===== [sweep] qa_gate=${g} -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -rtx_stats -qa_gate "$g" \
      -nodes 64 -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0; note=""
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [qag=$g] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ -n "${now:-}" ]] && awk -v n="$now" -v c="$SIM_ABORT_US" 'BEGIN{exit !(n>c)}'; then
      note=" *** ABORTED: runaway past ${SIM_ABORT_US}us ***"
      echo "  [qag=$g]$note"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [qag=$g] complete (finished=$cur)"; kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
  done
  flows=$(grep -c "finished at" "$out"); mk=$(grep -oE "finished at [0-9.]+" "$out" | awk '{print $3}' | sort -n | tail -1)
  {
    echo
    echo "============================================================"
    echo "qa_gate = ${g}  (maxwnd/2^${g})${note}"
    echo "  flows=${flows}  makespan_us=${mk:-NA}  (3007 flows = full MoE completion)"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done qa_gate=${g} ====="
done
echo "ALL DONE -> $SUMMARY"
