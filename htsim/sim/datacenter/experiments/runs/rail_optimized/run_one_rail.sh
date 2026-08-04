#!/bin/bash
# One rail-optimized run, either stack, recording the FULL metric superset:
#   common      : makespan, FCT min/p50/p99/max, total_GB, per-tier utilization
#   UET-native  : New/Rtx/RTS/Bounced/ACKs/NACKs/Pulls/sleek/spurious (0 for IB)
#   IB-native   : pfc_pauses / pfc_pause_us / max_queue_bytes (0 for UET)
#   both        : slowdown p50/p99/max + Jain fairness
#
# NOTE on slowdown/fairness: both rail workloads are TRIGGER-STAGED, so a flow's
# finish time includes waiting for its trigger. These two columns therefore
# measure stage ordering, not congestion -- recorded for completeness but NOT
# comparable across workloads. Makespan/FCT/utilization/congestion are valid.
#
# usage: run_one_rail.sh <matrix> <ib|uet> <rail|flat>
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/rail_optimized"
PARSE=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/build/parse_output
matrix="$1"; stack="$2"; topo_kind="$3"

TIMEOUT="${TIMEOUT:-86400}"; END_US="${END_US:-600000000}"
LOGTIME_US="${LOGTIME_US:-20000}"; QSIZE="${QSIZE:-1000}"
NVLINK_MBPS="${NVLINK_MBPS:-3600000}"; GPS="${GPS:-8}"
SCALE="${SCALE:-1024}"   # 1024 or 2048 -- selects the topology set

case "$topo_kind" in
  rail) TOPO="$OUT/topos/rail_${SCALE}gpu_8rail.topo" ;;
  flat) TOPO="$OUT/topos/flat_${SCALE}gpu_sameshape.topo" ;;
  *) echo "topology must be rail|flat"; exit 1 ;;
esac
NVTOPO="$OUT/topos/nvlink_${SCALE}gpu_8pergpu.topo"

base=$(basename "$matrix" .cm)
case "$base" in *allreduce*) workload=allreduce_rail_aware ;; *alltoall*) workload=alltoall_moe_rail_aware ;; *) workload=$base ;; esac
size_MB=$(echo "$base" | grep -oE '[0-9]+MB' | tr -d 'MB')
n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
tag="${base}.${stack}.${topo_kind}"

log="$OUT/$( [ "$stack" = ib ] && echo ib_dcqcn || echo uet )/logs/${tag}.log"
row="$OUT/$( [ "$stack" = ib ] && echo ib_dcqcn || echo uet )/rows/${tag}.row"
urow="$OUT/$( [ "$stack" = ib ] && echo ib_dcqcn || echo uet )/util_rows/${tag}.urow"
[ -s "$row" ] && [ -s "$urow" ] && awk -F, '$8=="ok"{ok=1}END{exit !ok}' "$row" 2>/dev/null && { echo "[skip $(date +%H:%M:%S)] $tag"; exit 0; }

WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/rail_work}"
work="$WORKROOT/$tag"; rm -rf "$work"; mkdir -p "$work"
raw="$work/htsim.stdout"; : > "$raw"
NV="-nvlink_topo $NVTOPO -nvlink_linkspeed $NVLINK_MBPS -gpus_per_server $GPS"
t0=$(date +%s)

if [ "$stack" = ib ]; then
  MSS=4000
  ( cd "$work" && exec timeout "$TIMEOUT" "$DC/htsim_roce" -tm "$matrix" -nodes "$n" -topo "$TOPO" $NV \
      -linkspeed 200000 -strat ecmp_host -paths 128 -queue_type lossless_input -pfc_thresholds 12 15 \
      -q "$QSIZE" -dcqcn 8 -end "$END_US" -logtime_us "$LOGTIME_US" \
      -log tor_downqueue -log tor_upqueue -o "$work/util.bin" ) > "$raw" 2>&1 &
else
  MSS=4150
  ( cd "$work" && exec timeout "$TIMEOUT" "/home/mahmoud_murad_allaah/HTSIM/htsim/sim/build/datacenter/htsim_uec" \
      -tm "$matrix" -sender_cc_only -nodes "$n" -topo "$TOPO" $NV -linkspeed 200000 -end "$END_US" \
      -log tor_downqueue -log tor_upqueue -logtime_us "$LOGTIME_US" -o "$work/util.bin" ) > "$raw" 2>&1 &
fi
pid=$!
( sig=0; while kill -0 "$pid" 2>/dev/null; do
    f=$(grep -c "finished at" "$raw" 2>/dev/null || true); f=${f:-0}
    [ "$sig" -eq 0 ] && [ "$f" -ge "$c" ] 2>/dev/null && { kill -TERM "$pid" 2>/dev/null && sig=1; }
    sleep 0.5; done ) & wd=$!
wait "$pid"; rc=$?; kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
wall=$(( $(date +%s) - t0 ))

awk '/finished at/{print;next} /^New:/{print;next} /^PFC_PAUSES/{print;next}
     /SPURIOUS_COUNT/{print;next} /LOSSLESS not working/{ov++;next}
     /[Ee]rror|Aborted|core dumped/{print;next} END{print "OVERFLOW_COUNT " ov+0}' "$raw" > "$log"

tmp=$(mktemp); grep -oE "finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?" "$log" | awk '{printf "%.6f\n",$3}' | sort -n > "$tmp"
fin=$(wc -l < "$tmp")
if [ "$fin" -gt 0 ]; then
  read -r fmin p50 p99 fmax < <(awk 'NR==FNR{a[++m]=$1;next}END{i50=int(m*.5);i50=i50<1?1:i50;i99=int(m*.99);i99=i99<1?1:i99;
    printf "%.1f %.1f %.1f %.1f",a[1],a[i50],a[i99],a[m]}' "$tmp" "$tmp"); mk="$fmax"
else fmin=0;p50=0;p99=0;fmax=0;mk=0; fi; rm -f "$tmp"
bytes=$(awk '/->/{for(i=1;i<=NF;i++) if($i=="size"){s+=$(i+1)}}END{printf "%.3f",(s+0)/1e9}' "$matrix")

read -r nw rtx rts bnc ack nack pull slk < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1);else if($i=="RTS:")cc=$(i+1);
  else if($i=="Bounced:")d=$(i+1);else if($i=="ACKs:")e=$(i+1);else if($i=="NACKs:")ff=$(i+1);
  else if($i=="Pulls:")g=$(i+1);else if($i=="sleek_pkts:")h=$(i+1)} printf "%s %s %s %s %s %s %s %s",a+0,b+0,cc+0,d+0,e+0,ff+0,g+0,h+0}')
sp=$(grep -oE "SPURIOUS_COUNT [0-9]+" "$log" | tail -1 | awk '{print $2}')
read -r pfcp pfcus maxq < <(grep -E "^PFC_PAUSES" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="PFC_PAUSES")a=$(i+1);else if($i=="PFC_PAUSE_US")b=$(i+1);else if($i=="MAX_QUEUE_BYTES")cc=$(i+1)}
  printf "%d %.1f %d",a+0,b+0,cc+0}')
ov=$(grep -oE "OVERFLOW_COUNT [0-9]+" "$log" | awk '{print $2}')

status=ok; [ "$rc" = 124 ] && status=timeout
[ "$fin" -lt "$c" ] && [ "$rc" != 124 ] && { [ "$fin" = 0 ] && status=failed || status=incomplete; }
# A lossless fabric that overflowed is a MIS-CONFIGURED run, not a valid result:
# htsim only warns ("LOSSLESS not working") and keeps the packet, so the numbers
# silently correspond to a bigger buffer than -q asked for. Flag it rather than
# reporting ok, so the resume guard re-runs it with a larger -q.
[ "$stack" = ib ] && [ "${ov:-0}" -gt 0 ] 2>/dev/null && status=lossless_overflow
sd50=0;sd99=0;sdmax=0;fair=0
[ "$fin" -gt 0 ] && read -r sd50 sd99 sdmax fair < <(python3 "$OUT/../ib_dcqcn/perm_incast_a2a_128_1024/flow_metrics.py" "$log" "$MSS" 25000 2>/dev/null | tr ',' ' ')

printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
 "$matrix" "$workload" "${size_MB:-0}" "$n" "$c" "$stack" "$topo_kind" "$status" "$wall" "$fin" \
 "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
 "${nw:-0}" "${rtx:-0}" "${rts:-0}" "${bnc:-0}" "${ack:-0}" "${nack:-0}" "${pull:-0}" "${slk:-0}" "${sp:-0}" \
 "${pfcp:-0}" "${pfcus:-0}" "${maxq:-0}" "${sd50:-0}" "${sd99:-0}" "${sdmax:-0}" "${fair:-0}" "${ov:-0}" > "$row"

echo "[done $(date +%H:%M:%S)] $tag status=$status rc=$rc flows=$fin/$c mk=${mk}us ovf=${ov:-0} pauses=${pfcp:-0} wall=${wall}s"

if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != failed ] && [ "$status" != timeout ]; then
  u=$(python3 "$OUT/../ib_dcqcn/perm_incast_a2a_128_1024/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  [ -n "$u" ] && printf "%s,%s,%s,%s\n" "$base" "$stack" "$topo_kind" "$u" > "$urow"
fi
rm -rf "$work"
