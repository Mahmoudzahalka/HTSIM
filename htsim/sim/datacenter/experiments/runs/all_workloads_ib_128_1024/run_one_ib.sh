#!/bin/bash
# Single (matrix, fabric) IB PFC-only job at 200G, mirroring the UEC
# all_workloads_128_1024/run_one.sh so results are directly comparable.
#
# IB-like stack = htsim_roce with:
#   -strat ecmp_host   per-flow ECMP (single deterministic path per flow, like IB)
#   -queue_type lossless_input -pfc_thresholds 12 15   lossless PFC fabric
#   -q 1000            buffer sized so PFC is truly lossless (overflow=0)
#   (no -dcqcn)        PFC-only baseline; DCQCN CC is WIP on dev/ib-dcqcn-fix
#
# A watchdog greps "finished at" and SIGTERMs htsim when all Connections-M flows
# are done (util sampler would otherwise keep the sim alive to -end). main_roce
# now installs a SIGTERM handler (like main_uec) so the logfile finalizes
# cleanly and util.bin stays readable. -end is a safety cap; `timeout` bounds
# wall-clock.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_ib_128_1024"
PARSE=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/build/parse_output
BIN="$DC/htsim_roce"
matrix="$1"; fabric="$2"

TIMEOUT="${TIMEOUT:-86400}"          # hard wall-clock cap per run (safety)
END_US="${END_US:-120000000}"        # 120 s simulated cap (natural drain ends earlier)
LOGTIME_US="${LOGTIME_US:-1000}"     # 1 ms utilization sampling (matches UEC)
QSIZE="${QSIZE:-1000}"               # queue size in packets (PFC headroom)
PATHS="${PATHS:-128}"                # ECMP entropy count

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(basename "$matrix" .cm)
tag="${base}.${fabric}"

log="$OUT/logs/${tag}.log"
row="$OUT/rows/${tag}.row"
util_row="$OUT/util_rows/${tag}.urow"

# Resume guard: skip a job already fully recorded (row=ok AND util_row present),
# so a relaunch only redoes missing/failed runs. Cheap and idempotent.
if [ -s "$row" ] && [ -s "$util_row" ] && awk -F, '$5=="ok"{ok=1}END{exit !ok}' "$row" 2>/dev/null; then
  echo "[skip $(date +%H:%M:%S)] ${tag} already done"; exit 0
fi

# Utilization = cumulative-bytes/makespan, so long-makespan fan-in patterns
# (incast/outcast) tolerate coarse sampling losslessly, while short perm runs
# need fine sampling. util.bin size grows with makespan/sample-period and
# parse_output loads it WHOLE into RAM, so e.g. a 33s incast at 1ms => ~145GB
# util.bin that OOMs parse_output on a 31GB box. Coarse-sample the long
# patterns; keep perm fine. (Utilization is sampling-period-independent by
# construction, so this does not affect comparability with the 128/1024 runs.)
case "$base" in
  incast_*|outcast_*) LOGTIME_US="${LOGTIME_COARSE_US:-20000}" ;;  # 20 ms
esac
# Per-run scratch (util.bin + raw stdout) can be many GB for 1024-node runs, so
# it goes on a big disk via WORKROOT (the 210GB /media/.../Data by default);
# only the small rows/logs/util_rows stay under $OUT on root.
WORKROOT="${WORKROOT:-/media/mahmoud_murad_allaah/Data/ib_sweep_work}"
work="$WORKROOT/${tag}"
rm -rf "$work"; mkdir -p "$work"
raw_stdout="$work/htsim.stdout"
: > "$raw_stdout"

topo="$DC/experiments/runs/a3_200g/topos_200g/fat_tree_${n}_${fabric}.topo"

POLL_INTERVAL="${POLL_INTERVAL:-0.3}"
t0=$(date +%s)
(
  cd "$work" || exit 1
  exec timeout "$TIMEOUT" "$BIN" \
      -tm "$matrix" -nodes "$n" -topo "$topo" -linkspeed 200000 \
      -strat ecmp_host -paths "$PATHS" \
      -queue_type lossless_input -pfc_thresholds 12 15 -q "$QSIZE" \
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

# --- FCT stats (accept scientific notation, as UEC does) ---
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

# total_GB = sum of flow sizes in the matrix (delivered goodput; transport-independent).
bytes=$(awk '/->/{for(i=1;i<=NF;i++) if($i=="size"){s+=$(i+1)}} END{printf "%.3f",(s+0)/1e9}' "$matrix")

# roce summary prints only "New: <n> Rtx: <n>". UEC-only counters -> 0.
read -r nw rtx < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1)}
  printf "%s %s", a+0,b+0}')
ov=$(grep -oE "OVERFLOW_COUNT [0-9]+" "$log" | awk '{print $2}')

status="ok"
[ "$rc" = "124" ] && status="timeout"
if [ "$fin" -lt "$c" ] && [ "$rc" != "124" ]; then
  if [ "$fin" = "0" ]; then status="failed"; else status="incomplete"; fi
fi

# Same 22-column schema as UEC results_combined.csv. IB-unavailable UEC counters
# (RTS,Bounced,ACKs,Pulls,sleek,spurious) are 0; NACKs col carries lossless
# overflow-warning count (should be 0 for a correctly-sized buffer).
printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
  "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
  "${nw:-0}" "${rtx:-0}" "0" "0" "0" "${ov:-0}" "0" "0" "0" > "$row"

# --- Utilization extraction (only when the logfile finalized: ok/incomplete) ---
if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != "failed" ] && [ "$status" != "timeout" ]; then
  util_csv=$(python3 "$OUT/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  if [ -n "$util_csv" ]; then
    printf "%s,%s,%s\n" "$matrix" "$fabric" "$util_csv" > "$util_row"
  fi
fi

rm -rf "$work"
echo "[done $(date +%H:%M:%S)] $tag status=$status wall=${wall}s flows=$fin/$c makespan_us=$mk overflow=$ov"
