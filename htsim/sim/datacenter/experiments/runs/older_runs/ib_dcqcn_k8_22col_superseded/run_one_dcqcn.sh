#!/bin/bash
# Single (matrix, fabric) IB DCQCN job at 200G: same PFC-lossless stack as the
# PFC-only sweep (run_one_ib.sh) PLUS DCQCN congestion control (-dcqcn K), so
# results are directly comparable to results_combined.csv.
#   -queue_type lossless_input -pfc_thresholds 12 15   lossless PFC fabric
#   -dcqcn $DCQCN_K   ECN marking threshold (packets) on egress LosslessOutputQueue
# Watchdog SIGTERMs htsim once all Connections-M flows finish (the util sampler
# would otherwise keep the sim alive to -end). Per-run scratch on the 210GB disk.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_dcqcn_k8_128_1024"
MATRICES="$DC/experiments/runs/uet/perm_incast_128_1024/matrices"
PARSE=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/build/parse_output
BIN="$DC/htsim_roce"
matrix="$1"; fabric="$2"

TIMEOUT="${TIMEOUT:-86400}"
END_US="${END_US:-120000000}"
LOGTIME_US="${LOGTIME_US:-1000}"
QSIZE="${QSIZE:-1000}"
PATHS="${PATHS:-128}"
DCQCN_K="${DCQCN_K:-8}"           # ECN threshold in packets (sensible default; tune later)

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(basename "$matrix" .cm)
tag="${base}.${fabric}"

log="$OUT/logs/${tag}.log"
row="$OUT/rows/${tag}.row"
util_row="$OUT/util_rows/${tag}.urow"

# Resume guard: skip a job already fully recorded (row=ok AND util_row present).
if [ -s "$row" ] && [ -s "$util_row" ] && awk -F, '$5=="ok"{ok=1}END{exit !ok}' "$row" 2>/dev/null; then
  echo "[skip $(date +%H:%M:%S)] ${tag} already done"; exit 0
fi

# Utilization is cumulative/makespan so long-makespan fan-in patterns tolerate
# coarse sampling losslessly (bounds util.bin + parse_output RAM). perm stays fine.
case "$base" in
  incast_*|outcast_*) LOGTIME_US="${LOGTIME_COARSE_US:-20000}" ;;
esac

WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/dcqcn_sweep_work}"
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

# Watchdog: SIGTERM htsim once all Connections-M flows have finished.
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

# --- Post-filter raw stdout into the compact per-run log ---
awk '
  /finished at/{print; next}
  /^New:/{print; next}
  /LOSSLESS not working/{ov++; next}
  /[Ee]rror|[Mm]ismatch|Topology Error|Aborted|core dumped|terminat/{print; next}
  END{print "OVERFLOW_COUNT " ov+0}' "$raw_stdout" > "$log"

# --- FCT stats ---
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
read -r nw rtx < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1)}
  printf "%s %s", a+0,b+0}')
ov=$(grep -oE "OVERFLOW_COUNT [0-9]+" "$log" | awk '{print $2}')

status="ok"
[ "$rc" = "124" ] && status="timeout"
if [ "$fin" -lt "$c" ] && [ "$rc" != "124" ]; then
  if [ "$fin" = "0" ]; then status="failed"; else status="incomplete"; fi
fi

# Same 22-column schema as results_combined.csv (UEC-only counters -> 0; NACKs
# col carries lossless overflow count, should be 0).
printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
  "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
  "${nw:-0}" "${rtx:-0}" "0" "0" "0" "${ov:-0}" "0" "0" "0" > "$row"

echo "[done $(date +%H:%M:%S)] ${tag} status=$status wall=${wall}s flows=${fin}/${c} makespan_us=${mk} overflow=${ov:-0} K=${DCQCN_K}"

# --- Utilization extraction ---
if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != "failed" ] && [ "$status" != "timeout" ]; then
  util_csv=$(python3 "$OUT/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  if [ -n "$util_csv" ]; then
    printf "%s,%s,%s\n" "$matrix" "$fabric" "$util_csv" > "$util_row"
  fi
fi

rm -rf "$work"
