#!/usr/bin/env bash
# IB (RoCE + PFC + DCQCN) vs UET on the MoE dispatch matrices, using the EXACT
# 400 G configuration of the fidelity study: fidelityRuns/bin/run_one_fidelity.sh
# is called unchanged, so both stacks get the same flags, metrics (37-col .row)
# and status checks (incomplete / lossless_overflow / mem_capped) as before.
#
#   topology : fidelityRuns/topos/fat_tree_128_1os.topo  (400 G flat fat tree, k=8 shape, 1 us/hop)
#   IB       : htsim_roce -strat ecmp_host -paths 128 -queue_type lossless_input
#              -pfc_thresholds 12 15 -q $QSIZE -dcqcn 8 -linkspeed 400000
#   UET      : htsim_uec -sender_cc_only -linkspeed 400000  (defaults otherwise)
#   matrices : matrices/<TAG>_s<seed>.cm ; htsim -seed = the same <seed> (mapping seed)
#
# NOT the paper setup (800 G / 64 KB / REPS) -- that is run_moe_nscc.sh.
#
# usage: run_ib_vs_uet_400g.sh "<stacks>" "<seeds>"     e.g.  "ib uet" "1 2 3"
# env:   TAG (matrix family), P (parallel jobs, default 2), QSIZE (IB buffer pkts, default 1000)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUNNER=$HERE/../fidelityRuns/bin/run_one_fidelity.sh
TAG=${TAG:-moe_qwen3l0_text_128g_T8192_per-copy}
STUDY=${STUDY:-ib_vs_uet_400g_${TAG#moe_qwen3l0_}}
export OUTROOT=${OUTROOT:-$HERE/ib_vs_uet_400g}
export WORKROOT=${WORKROOT:-/media/mahmoud_murad_allaah/Data/moe_qwen3_layer0_routing/ib_vs_uet_400g_work}
export QSIZE=${QSIZE:-1000}
P=${P:-2}
stacks=$1; seeds=$2
mkdir -p "$OUTROOT"
jobs=()
for s in $seeds; do for st in $stacks; do jobs+=("$st $s"); done; done
printf '%s\n' "${jobs[@]}" | xargs -P "$P" -L 1 bash -c \
  'st=$0; s=$1; "'"$RUNNER"'" "'"$STUDY"'" "'"$HERE"'/matrices/'"$TAG"'_s${s}.cm" "$st" 1os "$s" 1'
