#!/bin/bash
# Probe peak RSS for the memory-risky cells, under a hard address-space cap so a
# runaway cannot thrash this box (that previously locked the user out of SSH).
# htsim pre-allocates one Src+Sink per connection at SETUP, so a short probe
# captures most of the footprint; IB additionally grows as -q buffers fill, so
# treat the probe as a LOWER bound and keep the safety margin generous.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
SIM=/home/mahmoud_murad_allaah/HTSIM/htsim/sim
RT="$DC/experiments/runs/rail_optimized/topos"
SH="$DC/experiments/runs/shared/topos_200g"
RM="$DC/experiments/runs/rail_optimized/matrices"
CAP_GB="${CAP_GB:-12}"; SECS="${SECS:-150}"
W=/media/mahmoud_murad_allaah/Data/fidelity_probe
out="$DC/experiments/runs/fidelityRuns/bin/probe_memory.csv"
echo "matrix,stack,topo,qsize,conns,peak_MB,outcome" > "$out"

probe () { # matrix stack topo qsize
  local m="$1" stack="$2" topo="$3" q="$4"
  local n c base tag NV TOPO
  n=$(grep -m1 -oE "Nodes [0-9]+" "$m" | awk '{print $2}')
  c=$(grep -m1 -oE "Connections [0-9]+" "$m" | awk '{print $2}')
  base=$(basename "$m" .cm); tag="${base}.${stack}.${topo}.q${q}"
  case "$topo" in
    rail) TOPO="$RT/rail_${n}gpu_8rail.topo"; NV="-nvlink_topo $RT/nvlink_${n}gpu_8pergpu.topo -nvlink_linkspeed 3600000 -gpus_per_server 8" ;;
    flat) TOPO="$RT/flat_${n}gpu_sameshape.topo"; NV="-nvlink_topo $RT/nvlink_${n}gpu_8pergpu.topo -nvlink_linkspeed 3600000 -gpus_per_server 8" ;;
    *)    TOPO="$SH/fat_tree_${n}_${topo}.topo"; NV="" ;;
  esac
  rm -rf "$W/$tag"; mkdir -p "$W/$tag"
  ( cd "$W/$tag" && ulimit -v $((CAP_GB*1024*1024)) 2>/dev/null
    if [ "$stack" = ib ]; then
      exec "$DC/htsim_roce" -tm "$m" -nodes "$n" -topo "$TOPO" $NV -seed 13 \
        -linkspeed 200000 -strat ecmp_host -paths 128 -queue_type lossless_input \
        -pfc_thresholds 12 15 -q "$q" -dcqcn 8 -end 600000000 -logtime_us 20000 -o util.bin
    else
      exec "$SIM/build/datacenter/htsim_uec" -tm "$m" -sender_cc_only -nodes "$n" \
        -topo "$TOPO" $NV -seed 13 -linkspeed 200000 -end 600000 -logtime_us 20000 -o util.bin
    fi ) > "$W/$tag/out" 2>&1 &
  local pid=$! peak=0 i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$SECS" ]; do
    k=$(awk '/VmHWM/{print $2}' /proc/$pid/status 2>/dev/null); k=${k:-0}
    [ "$k" -gt "$peak" ] 2>/dev/null && peak=$k
    sleep 2; i=$((i+2))
  done
  local outcome=survived
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; else
     grep -qiE 'bad_alloc|out of memory|cannot allocate|Aborted' "$W/$tag/out" && outcome="HIT_${CAP_GB}GB_CAP" || outcome=exited_early
  fi
  wait "$pid" 2>/dev/null
  printf "%s,%s,%s,%s,%s,%.0f,%s\n" "$base" "$stack" "$topo" "$q" "$c" "$(echo "$peak/1024"|bc -l)" "$outcome" >> "$out"
  echo "  $tag -> peak $((peak/1024)) MB [$outcome]"
  rm -rf "$W/$tag"
}

echo "== probing (cap ${CAP_GB}GB, ${SECS}s each) =="
probe "$RM/rail_alltoall_moe_2048gpu_100MB.cm" ib  rail 8000
probe "$RM/rail_alltoall_moe_2048gpu_100MB.cm" ib  rail 1000
probe "$RM/rail_alltoall_moe_2048gpu_100MB.cm" uet rail 0
probe "$RM/rail_alltoall_moe_2048gpu_64MB.cm"  ib  rail 8000
probe "$RM/rail_alltoall_moe_2048gpu_16MB.cm"  ib  rail 8000
probe "$RM/rail_alltoall_moe_1024gpu_100MB.cm" ib  rail 1000
probe "$RM/rail_allreduce_2048gpu_100MB.cm"    ib  rail 8000
probe "$DC/experiments/runs/uet/allreduce_ring_128/matrices/allreduce_ring_128n_100MB.cm" uet 1os 0
probe "$DC/experiments/runs/uet/a2a_concurrent_128_1024/matrices/a2a_128n_100MB.cm"       uet 1os 0
probe "$DC/experiments/runs/uet/a2a_concurrent_128_1024/matrices/a2a_128n_100MB.cm"       ib  1os 1000
echo "== done =="; column -t -s, "$out"
