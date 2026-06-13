#!/usr/bin/env bash
# qsize_sweep_moe.sh — sweep -queue_size_bdp_factor on the MoE trace (fast,
# worst-case: trimming+NACC retransmit storm). For each value: run htsim,
# auto-kill when flow completions plateau (workload done), then summarize.
# No -sleek. Output dir: experiments/runs/.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/qsize_sweep_moe_results.txt
ANALYZE=./analyze.sh

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64 nodes, fat_tree_64_1os, 200Gbps) queue-size sweep"
  echo "# -sender_cc_only, NO -sleek.  Generated: $(date)"
  echo "# -queue_size_bdp_factor sweep. Baseline (default) = 1xBDP."
  echo "############################################################"
} >> "$SUMMARY"

for q in 1 2 4 8; do
  out="$RUNDIR/moe8x8b_ft64_q${q}xbdp.out"
  echo "===== [sweep] starting queue_size_bdp_factor=${q}xBDP -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -queue_size_bdp_factor "$q" -nodes 64 \
      -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [q=${q}x] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [q=${q}x] workload complete (finished=$cur). killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null
      break
    fi
  done
  {
    echo
    echo "============================================================"
    echo "queue_size_bdp_factor = ${q} xBDP"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done queue_size_bdp_factor=${q}xBDP ====="
done
echo "ALL DONE -> $SUMMARY"
