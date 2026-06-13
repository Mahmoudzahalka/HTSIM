#!/usr/bin/env bash
# rto_sweep_moe.sh — sweep -min_rto on the MoE trace (fast, worst-case 96.6% RTS).
# For each RTO value: run htsim, auto-kill when flow completions plateau (workload
# done), then summarize. No -sleek (disabled). Output dir: experiments/runs/.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/rto_sweep_moe_results.txt
ANALYZE=./analyze.sh

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64 nodes, fat_tree_64_1os, 200Gbps) -min_rto sweep"
  echo "# -sender_cc_only, NO -sleek.  Generated: $(date)"
  echo "# Baseline (default RTO) = 100us."
  echo "############################################################"
} >> "$SUMMARY"

for rto in 100 200 400 800; do
  out="$RUNDIR/moe8x8b_ft64_rto${rto}.out"
  echo "===== [sweep] starting min_rto=${rto}us -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -min_rto "$rto" -nodes 64 \
      -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [rto=$rto] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [rto=$rto] workload complete (finished=$cur). killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null
      break
    fi
  done
  {
    echo
    echo "============================================================"
    echo "min_rto = ${rto} us"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done min_rto=${rto}us ====="
done
echo "ALL DONE -> $SUMMARY"
