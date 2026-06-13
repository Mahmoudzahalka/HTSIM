#!/usr/bin/env bash
# lb_sweep_moe.sh — compare load-balancing algos on the MoE trace.
# mixed = default packet-spray (baseline); ecmp = per-flow hashing (no spray,
# no cross-path reordering). Tests the reordering contribution to the duplicate
# storm WITHOUT perturbing the BDP/CC coupling (queue size & RTO held at default).
# Auto-kills each run when flow completions plateau. No -sleek.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/lb_sweep_moe_results.txt
ANALYZE=./analyze.sh

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64 nodes, fat_tree_64_1os, 200Gbps) load-balancing sweep"
  echo "# -sender_cc_only, NO -sleek, default queue (1xBDP) & RTO (100us)."
  echo "# Generated: $(date).  Baseline algo = mixed (packet spray)."
  echo "############################################################"
} >> "$SUMMARY"

# Safety cap: if a run goes runaway (livelock, never plateaus), abort it once sim
# time passes this many us so the sweep can't hang forever.
SIM_ABORT_US=300000

for lb in mixed ecmp; do
  out="$RUNDIR/moe8x8b_ft64_lb_${lb}.out"
  echo "===== [sweep] starting load_balancing_algo=${lb} -> $out ====="
  ./htsim_uec -goal "$TRACE" -sender_cc_only -load_balancing_algo "$lb" -nodes 64 \
      -end 250000 -topo "$TOPO" -linkspeed 200000 > "$out" 2>&1 &
  hpid=$!
  prev=-1; stable=0; note=""
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [lb=$lb] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    # runaway guard
    if [[ -n "${now:-}" ]] && awk -v n="$now" -v c="$SIM_ABORT_US" 'BEGIN{exit !(n>c)}'; then
      note=" *** ABORTED: runaway, sim past ${SIM_ABORT_US}us without completing ***"
      echo "  [lb=$lb]$note killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null
      break
    fi
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [lb=$lb] workload complete (finished=$cur). killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null
      break
    fi
  done
  {
    echo
    echo "============================================================"
    echo "load_balancing_algo = ${lb}${note}"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done load_balancing_algo=${lb} ====="
done
echo "ALL DONE -> $SUMMARY"
