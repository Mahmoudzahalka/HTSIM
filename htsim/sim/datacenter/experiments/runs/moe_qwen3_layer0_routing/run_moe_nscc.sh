#!/usr/bin/env bash
# Run Ofan-style MoE dispatch matrices through htsim_uec with NSCC.
#
# Setup follows Ofan (arXiv 2610.07230) Sec. 6 / 6.6:
#   3-tier k=8 fat tree, 128 hosts, 800 Gbps links, 0.5 us per link
#   64 KB packets, ~800 KB per-port buffer (12 x 64 KB), ECN threshold 10 packets
#   NSCC sender CC, load balancing chosen by $LB (default REPS)
#
# usage: run_moe_nscc.sh <variant-tag> <seed> [<seed> ...]
#   variant-tag e.g. moe_qwen3l0_text_128g_T8192_per-copy  (matrices/<tag>_s<seed>.cm)
# env:  LB=reps|oblivious|...   END_MS=<sim end, ms>   OUT=<results root>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BIN=$HERE/../../../htsim_uec            # datacenter/htsim_uec -> build/datacenter/htsim_uec
# ORIGINAL: TOPO=$HERE/topos/fat_tree_128_k8_800g_500ns.topo  (still the default)
TOPO=${TOPO:-$HERE/topos/fat_tree_128_k8_800g_500ns.topo}
# Optional NVLink plane: set NVLINK_TOPO (e.g. topos/nvlink_128gpu_8pergpu.topo) to put
# same-server flows on NVLink (use with matrices made by make_moe_cm.py --nvlink).
NVLINK_TOPO=${NVLINK_TOPO:-}
NVLINK_MBPS=${NVLINK_MBPS:-3600000}
NV_ARGS=()
[ -n "$NVLINK_TOPO" ] && NV_ARGS=(-nvlink_topo "$NVLINK_TOPO" -nvlink_linkspeed "$NVLINK_MBPS" -gpus_per_server 8)
TOPO_TAG=$(basename "$TOPO" .topo)${NVLINK_TOPO:+_nvlink}
OUT=${OUT:-/media/mahmoud_murad_allaah/Data/moe_qwen3_layer0_routing/sims}
LB=${LB:-reps}
END_MS=${END_MS:-60}   # htsim_uec -end is in MILLISECONDS (eventlist.setEndtime(timeFromMs)); sim always runs to -end
# MTU: htsim stores packet size in uint16_t (network.h:186 Packet::_size, uec.h:214 UecSrc::_mtu),
# so -mtu 65536 wraps to 0 and the sim silently sends nothing. 65535 is the largest
# representable size (payload = 65535 - UEC header), i.e. the paper's "64 KB packets".
#MTU=65536; QPKT=12; ECN_PKT=10
MTU=65535; QPKT=12; ECN_PKT=10
tag=$1; shift
for seed in "$@"; do
  cm=$HERE/matrices/${tag}_s${seed}.cm
  [ -f "$cm" ] || { echo "missing $cm" >&2; exit 1; }
  # ORIGINAL: d=$OUT/${tag}_nscc_${LB}/s${seed}   (kept for the default fat tree, so old results stay where they are)
  if [ "$TOPO_TAG" = fat_tree_128_k8_800g_500ns ]; then d=$OUT/${tag}_nscc_${LB}/s${seed}
  else d=$OUT/${tag}_nscc_${LB}__${TOPO_TAG}/s${seed}; fi
  mkdir -p "$d"
  echo "$(date -Is) start $tag seed $seed -> $d"
  ( cd "$d" && /usr/bin/time -v "$BIN" -tm "$cm" -nodes 128 -topo "$TOPO" "${NV_ARGS[@]}" \
      -sender_cc_only -sender_cc_algo nscc -load_balancing_algo "$LB" \
      -linkspeed 800000 -mtu $MTU -q $QPKT -ecn $ECN_PKT $ECN_PKT \
      -seed "$seed" -end "$END_MS" -o util.bin ) > "$d/out" 2> "$d/time.err" || echo "seed $seed exit $?" >&2
  python3 "$HERE/summarize_sim.py" "$d/out" > "$d/summary.json"
  echo "$(date -Is) done  $tag seed $seed: $(cat "$d/summary.json" | tr -d '\n ')"
done
