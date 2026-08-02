#!/bin/bash
# IB (RoCE + DCQCN K=8 + lossless PFC) run for the IB-vs-UET comparison.
# Same matrices/topo/linkspeed as the UET sweeps; MTU deliberately kept at 4000
# (main_roce default) vs UET's 4150 -- documented as a stack difference.
# Records, beyond makespan/FCT/util: PFC pauses(#)+pause-time(us)+peak buffer(B)
# (Tier 1, from htsim stdout) and per-flow slowdown p50/p99/max + Jain fairness
# (Tier 2, from the .log via flow_metrics.py).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/ib_dcqcn/allreduce_a2a_serial_128"
PARSE=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/build/parse_output
BIN="$DC/htsim_roce"
matrix="$1"; fabric="$2"

TIMEOUT="${TIMEOUT:-86400}"
END_US="${END_US:-120000000}"
LOGTIME_US="${LOGTIME_US:-1000}"
QSIZE="${QSIZE:-1000}"
PATHS="${PATHS:-128}"
DCQCN_K="${DCQCN_K:-8}"
MSS="${MSS:-4000}"          # IB MTU (deliberately 4000, != UET 4150)
BPUS="${BPUS:-25000}"       # 200Gbps in bytes/us (for slowdown ideal)

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(basename "$matrix" .cm)
tag="${TAG_PREFIX:-}${base}.${fabric}"

log="$OUT/logs/${tag}.log"
row="$OUT/rows/${tag}.row"
util_row="$OUT/util_rows/${tag}.urow"

if [ -s "$row" ] && [ -s "$util_row" ] && awk -F, '$5=="ok"{ok=1}END{exit !ok}' "$row" 2>/dev/null; then
  echo "[skip $(date +%H:%M:%S)] ${tag} already done"; exit 0
fi

case "$base" in
  incast_*|outcast_*|a2a_*|allreduce_*) LOGTIME_US="${LOGTIME_COARSE_US:-20000}" ;;
esac

WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_parity_work}"
work="$WORKROOT/${tag}"
rm -rf "$work"; mkdir -p "$work"
raw_stdout="$work/htsim.stdout"
: > "$raw_stdout"

topo="$DC/experiments/runs/shared/topos_200g/fat_tree_${n}_${fabric}.topo"
POLL_INTERVAL="${POLL_INTERVAL:-0.3}"
t0=$(date +%s)

(
  cd "$work" || exit 1
  exec timeout "$TIMEOUT" "$BIN" \
      -tm "$matrix" -nodes "$n" -topo "$topo" -linkspeed 200000 \
      -strat ecmp_host -paths "$PATHS" \
      -queue_type lossless_input -pfc_thresholds 12 15 -q "$QSIZE" \
      -dcqcn "$DCQCN_K" \
      -end "$END_US" -logtime_us "$LOGTIME_US" \
      -log tor_downqueue -log tor_upqueue \
      -o "$work/util.bin"
) > "$raw_stdout" 2>&1 &
htsim_pid=$!

(
  sig_sent=0
  while kill -0 "$htsim_pid" 2>/dev/null; do
    fin=$(grep -c "finished at" "$raw_stdout" 2>/dev/null || true); fin=${fin:-0}
    if [ "$sig_sent" -eq 0 ] && [ "$fin" -ge "$c" ] 2>/dev/null; then
      kill -TERM "$htsim_pid" 2>/dev/null && sig_sent=1
    fi
    sleep "$POLL_INTERVAL"
  done
) &
watchdog_pid=$!

wait "$htsim_pid"; rc=$?
kill "$watchdog_pid" 2>/dev/null; wait "$watchdog_pid" 2>/dev/null
t1=$(date +%s); wall=$((t1-t0))

# Post-filter (keep finished-at, New, PFC metric line, overflow, errors)
awk '
  /finished at/{print; next}
  /^New:/{print; next}
  /^PFC_PAUSES/{print; next}
  /LOSSLESS not working/{ov++; next}
  /[Ee]rror|[Mm]ismatch|Topology Error|Aborted|core dumped|terminat/{print; next}
  END{print "OVERFLOW_COUNT " ov+0}' "$raw_stdout" > "$log"

tmp=$(mktemp)
grep -oE "finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?" "$log" | awk '{printf "%.6f\n", $3}' | sort -n > "$tmp"
fin=$(wc -l < "$tmp")
if [ "$fin" -gt 0 ]; then
  read -r fmin p50 p99 fmax < <(awk 'NR==FNR{a[++m]=$1;next}END{
    i50=int(m*0.5); if(i50<1)i50=1; i99=int(m*0.99); if(i99<1)i99=1;
    printf "%.1f %.1f %.1f %.1f", a[1], a[i50], a[i99], a[m]}' "$tmp" "$tmp")
  mk="$fmax"
else fmin=0; p50=0; p99=0; fmax=0; mk=0; fi
rm -f "$tmp"

bytes=$(awk '/->/{for(i=1;i<=NF;i++) if($i=="size"){s+=$(i+1)}} END{printf "%.3f",(s+0)/1e9}' "$matrix")
read -r nw rtx < <(grep -E "^New:" "$log" | tail -1 | awk '{for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1)}printf "%s %s", a+0,b+0}')
ov=$(grep -oE "OVERFLOW_COUNT [0-9]+" "$log" | awk '{print $2}')

read -r pfcp pfcus maxq < <(grep -E "^PFC_PAUSES" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="PFC_PAUSES")a=$(i+1);else if($i=="PFC_PAUSE_US")b=$(i+1);else if($i=="MAX_QUEUE_BYTES")cc=$(i+1)}
  printf "%d %.1f %d", a+0, b+0, cc+0}')

status="ok"
[ "$rc" = "124" ] && status="timeout"
if [ "$fin" -lt "$c" ] && [ "$rc" != "124" ]; then
  if [ "$fin" = "0" ]; then status="failed"; else status="incomplete"; fi
fi

sd50=0; sd99=0; sdmax=0; fair=0
if [ "$fin" -gt 0 ]; then
  read -r sd50 sd99 sdmax fair < <(python3 "$OUT/flow_metrics.py" "$log" "$MSS" "$BPUS" 2>/dev/null | tr ',' ' ')
fi

# 22 base cols (UET-comparable schema) + 7 IB metric cols
printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
  "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
  "${nw:-0}" "${rtx:-0}" "0" "0" "0" "${ov:-0}" "0" "0" "0" \
  "${pfcp:-0}" "${pfcus:-0}" "${maxq:-0}" "${sd50:-0}" "${sd99:-0}" "${sdmax:-0}" "${fair:-0}" > "$row"

echo "[done $(date +%H:%M:%S)] ${tag} status=$status flows=${fin}/${c} mk=${mk}us pauses=${pfcp:-0} pause_us=${pfcus:-0} maxq=${maxq:-0} slow99=${sd99:-0} fair=${fair:-0}"

if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != "failed" ] && [ "$status" != "timeout" ]; then
  util_csv=$(python3 "$OUT/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  if [ -n "$util_csv" ]; then
    printf "%s,%s,%s\n" "$matrix" "$fabric" "$util_csv" > "$util_row"
  fi
fi

rm -rf "$work"
