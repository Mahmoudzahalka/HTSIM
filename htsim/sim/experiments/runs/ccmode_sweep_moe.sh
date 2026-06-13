#!/usr/bin/env bash
# ccmode_sweep_moe.sh — compare congestion-control MODES on the MoE trace.
# All sender-side knobs (RTO/queue/lb) at default; only the CC mode changes.
#   sender_only  : -sender_cc_only   (baseline used in every prior run)
#   receiver_only: -receiver_cc_only (credit-based, the designed anti-incast mode)
#   both         : -sender_cc -receiver_cc
# Auto-kills each run when flow completions plateau; runaway guard aborts past
# SIM_ABORT_US so a livelock can't hang the sweep. No -sleek.
set -u
cd "$(dirname "$0")/../../datacenter"
TRACE=../experiments/traces/MoE8x8B_N16_GPU64_TP1_PP8_DP8_EP1_7B_BS32.bin
TOPO=topologies/fat_tree_64_1os.topo
RUNDIR=../experiments/runs
SUMMARY=../experiments/ccmode_sweep_moe_results.txt
ANALYZE=./analyze.sh
SIM_ABORT_US=400000

: > "$SUMMARY"
{
  echo "############################################################"
  echo "# MoE8x8B (64 nodes, fat_tree_64_1os, 200Gbps) CC-MODE sweep"
  echo "# default queue(1xBDP)/RTO(100us)/lb(mixed), NO -sleek."
  echo "# Generated: $(date).  Baseline mode = sender_only."
  echo "############################################################"
} >> "$SUMMARY"

run_mode() {
  local label="$1"; shift
  local flags="$1"; shift
  local out="$RUNDIR/moe8x8b_ft64_cc_${label}.out"
  echo "===== [sweep] starting cc=${label}  flags='${flags}' -> $out ====="
  # shellcheck disable=SC2086
  ./htsim_uec -goal "$TRACE" $flags -nodes 64 -end 250000 -topo "$TOPO" \
      -linkspeed 200000 > "$out" 2>&1 &
  local hpid=$!
  local prev=-1 stable=0 note=""
  while kill -0 "$hpid" 2>/dev/null; do
    sleep 15
    local cur now
    cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
    now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  [cc=$label] finished=$cur sim_now_us=${now:-?} stable=$stable"
    if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
    prev=$cur
    if [[ -n "${now:-}" ]] && awk -v n="$now" -v c="$SIM_ABORT_US" 'BEGIN{exit !(n>c)}'; then
      note=" *** ABORTED: runaway, sim past ${SIM_ABORT_US}us without completing ***"
      echo "  [cc=$label]$note killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
    if [[ $stable -ge 3 && $cur -gt 0 ]]; then
      echo "  [cc=$label] workload complete (finished=$cur). killing $hpid"
      kill "$hpid" 2>/dev/null; sleep 3; kill -9 "$hpid" 2>/dev/null; break
    fi
  done
  {
    echo
    echo "============================================================"
    echo "cc_mode = ${label}  (flags: ${flags})${note}"
    echo "============================================================"
    bash "$ANALYZE" "$out" 2>/dev/null
  } >> "$SUMMARY"
  echo "===== [sweep] done cc=${label} ====="
}

run_mode "sender_only"   "-sender_cc_only"
run_mode "receiver_only" "-receiver_cc_only"
run_mode "both"          "-sender_cc -receiver_cc"
echo "ALL DONE -> $SUMMARY"
