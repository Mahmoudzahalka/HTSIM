#!/bin/bash
# IB (RoCE + DCQCN K=8 + PFC) concurrent global a2a @ 1024 nodes.
# 3 sizes {16,64,100}MB x 3 fabrics {1os,4os,8os} = 9 runs, strictly -P1.
# Each run sits in its own systemd user scope with a hard memory cap
# (MemoryMax=25G, no swap) so an over-budget run is cgroup-OOM-killed alone
# instead of taking the 31GB box down. Peak cgroup memory is polled and logged
# per run (memory.peak) -- the first measured IB a2a-1024 footprint.
# Reuses run_one_compare.sh unchanged (same harness/schema as the 99-run sweep).
# Same matrices as the UET a2a-concurrent sweep.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/ib_dcqcn/perm_incast_a2a_128_1024"
R="$OUT/run_one_compare.sh"
A2A="$DC/experiments/runs/uet/a2a_concurrent_128_1024/matrices"
MEMCAP="${MEMCAP:-25G}"
PROG="$OUT/sweep_a2a1024.progress.log"
MEMLOG="$OUT/sweep_a2a1024.mem.log"
export DCQCN_K="${DCQCN_K:-8}"
export WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_compare_work}"
export TIMEOUT="${TIMEOUT:-86400}" END_US="${END_US:-120000000}" QSIZE="${QSIZE:-1000}"
mkdir -p "$WORKROOT" "$OUT/logs" "$OUT/rows" "$OUT/util_rows"

J="$OUT/jobs_a2a1024.txt"; :>"$J"
for S in 16 64 100; do
  for fb in 1os 4os 8os; do
    echo "$A2A/a2a_1024n_${S}MB.cm $fb" >> "$J"
  done
done

CG="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/app.slice"
echo "[$(date)] IB a2a-1024 sweep K=$DCQCN_K -P1 memcap=$MEMCAP timeout=${TIMEOUT}s jobs=$(wc -l <"$J")" >> "$PROG"

while read -r m fb; do
  tag="$(basename "$m" .cm).${fb}"
  unit="ib-a2a1024-${tag//./-}"
  # memory.peak poller (scope cgroup vanishes when the run ends, so keep last value)
  (
    peak=0
    sleep 5
    while [ -d "$CG/${unit}.scope" ]; do
      p=$(cat "$CG/${unit}.scope/memory.peak" 2>/dev/null || echo 0)
      [ "$p" -gt "$peak" ] 2>/dev/null && peak=$p
      echo "$(date +%s) $tag cur=$(cat "$CG/${unit}.scope/memory.current" 2>/dev/null || echo 0) peak=$peak" > "$OUT/.mem_${tag}.now"
      sleep 30
    done
    echo "[$(date +%H:%M:%S)] $tag peak_bytes=$peak peak_GB=$(awk -v p="$peak" 'BEGIN{printf "%.2f", p/1e9}')" >> "$MEMLOG"
    rm -f "$OUT/.mem_${tag}.now"
  ) &
  poller=$!
  systemd-run --user --scope --quiet -p MemoryMax="$MEMCAP" -p MemorySwapMax=0 \
      --unit="$unit" bash "$R" "$m" "$fb" >> "$PROG" 2>&1
  echo "[$(date +%H:%M:%S)] $tag scope_rc=$?" >> "$PROG"
  wait "$poller"
done < "$J"

echo "[$(date)] all a2a-1024 runs done" >> "$PROG"
