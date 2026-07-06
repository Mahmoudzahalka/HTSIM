#!/bin/bash
# Single (matrix, fabric) job at 200G with per-tier link-utilization capture.
# Uses external watchdog + SIGTERM to end htsim cleanly the moment all
# Connections-M flows finish (no need to pre-estimate makespan; log volume
# is bounded to actual workload duration).
#
# A2A sweep copy of all_workloads_128_1024/run_one.sh -- identical logic,
# paths repointed to this box (DC, OUT, and the built binaries under build/).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/a2a_128_1024"       # repo dir: small results only
# Root fs (/) has ~2GB free; the heavy scratch (util.bin + raw stdout, which
# balloons for 1M-flow 1024 runs) and the filtered logs go on the 196GB Data
# partition instead. Only the tiny rows/util_rows/CSVs stay in the repo OUT.
DATA="${DATA:-/media/mahmoud_murad_allaah/Data/a2a_128_1024}"
HTSIM="$DC/../build/datacenter/htsim_uec"     # built binary lives under build/
PARSE="$DC/../build/parse_output"             # parse_output lives under build/
matrix="$1"; fabric="$2"

TIMEOUT="${TIMEOUT:-86400}"        # hard wall-clock cap per run (safety)
END_MS="${END_MS:-600000}"         # 600 s simulated cap (only fires if the
                                   # watchdog misses -- serial A2A chains need
                                   # a GENEROUS cap so -end never clips mid-chain)
LOGTIME_US="${LOGTIME_US:-1000}"   # 1 ms utilization sampling
POLL_INTERVAL="${POLL_INTERVAL:-0.2}"  # watchdog poll period (seconds)

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(basename "$matrix" .cm)
tag="${base}.${fabric}"

log="$DATA/logs/${tag}.log"          # filtered log -> Data (big for 1024)
row="$OUT/rows/${tag}.row"           # tiny -> repo
util_row="$OUT/util_rows/${tag}.urow" # tiny -> repo
work="$DATA/work/${tag}"             # scratch (util.bin + raw stdout) -> Data
mkdir -p "$DATA/logs" "$OUT/rows" "$OUT/util_rows"
rm -rf "$work"; mkdir -p "$work"
raw_stdout="$work/htsim.stdout"
: > "$raw_stdout"

topo="$DC/experiments/runs/a3_200g/topos_200g/fat_tree_${n}_${fabric}.topo"

t0=$(date +%s)

# --- Launch htsim in its own workdir (so idmap.txt / util.bin don't collide) ---
(
  cd "$work" || exit 1
  exec timeout "$TIMEOUT" "$HTSIM" \
      -tm "$matrix" -sender_cc_only -nodes "$n" \
      -topo "$topo" -linkspeed 200000 -end "$END_MS" \
      -log tor_downqueue -log tor_upqueue -logtime_us "$LOGTIME_US" \
      -o "$work/util.bin"
) > "$raw_stdout" 2>&1 &
htsim_pid=$!

# --- Watchdog: poll stdout for finished flow count; SIGTERM htsim on match ---
(
  sig_sent=0
  while kill -0 "$htsim_pid" 2>/dev/null; do
    # `grep -c` returns 1 on no-match; suppress with || true
    fin=$(grep -c "finished at" "$raw_stdout" 2>/dev/null || true)
    fin=${fin:-0}
    if [ "$sig_sent" -eq 0 ] && [ "$fin" -ge "$c" ] 2>/dev/null; then
      kill -TERM "$htsim_pid" 2>/dev/null && sig_sent=1
    fi
    sleep "$POLL_INTERVAL"
  done
) &
watchdog_pid=$!

# Wait for htsim to finish (normal, SIGTERM-clean, or TIMEOUT-killed)
wait "$htsim_pid"
rc=$?
kill "$watchdog_pid" 2>/dev/null; wait "$watchdog_pid" 2>/dev/null

t1=$(date +%s); wall=$((t1-t0))

# --- Post-filter the raw stdout into the compact per-run log ---
awk '
  /Spurious/{sp++; next}
  /finished at/{print; next}
  /^New:/{print; next}
  /Received SIGTERM/{print; next}
  /[Ee]rror|[Mm]ismatch|Topology Error|Aborted|core dumped|terminat/{print; next}
  END{print "SPURIOUS_COUNT " sp+0}' "$raw_stdout" > "$log"

# --- FCT stats ---
# Regex must accept scientific notation: htsim's cout switches to sci form
# when timeAsUs(now()) exceeds ~1e6 us (~1 sec sim time). Old regex `[0-9.]+`
# clipped the exponent and produced makespans off by 6+ orders of magnitude.
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

bytes=$(grep -oE "total bytes [0-9]+" "$log" | awk '{s+=$3}END{printf "%.3f",(s+0)/1e9}')
read -r nw rtx rts bnc ack nack pull slk < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1);
  else if($i=="RTS:")cc=$(i+1);else if($i=="Bounced:")d=$(i+1);else if($i=="ACKs:")e=$(i+1);
  else if($i=="NACKs:")ff=$(i+1);else if($i=="Pulls:")g=$(i+1);else if($i=="sleek_pkts:")h=$(i+1)}
  printf "%s %s %s %s %s %s %s %s", a+0,b+0,cc+0,d+0,e+0,ff+0,g+0,h+0}')
sp=$(grep -oE "SPURIOUS_COUNT [0-9]+" "$log" | awk '{print $2}')

# Status: ok if flows_fin == expected, timeout on 124, incomplete if
# less than expected but sim wasn't timeout-killed, failed if zero flows.
status="ok"
[ "$rc" = "124" ] && status="timeout"
if [ "$fin" -lt "$c" ] && [ "$rc" != "124" ]; then
  if [ "$fin" = "0" ]; then status="failed"; else status="incomplete"; fi
fi

printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
  "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
  "${nw:-0}" "${rtx:-0}" "${rts:-0}" "${bnc:-0}" "${ack:-0}" "${nack:-0}" "${pull:-0}" "${slk:-0}" "${sp:-0}" > "$row"

# --- Utilization extraction (only on ok/incomplete; failed = no useful bin) ---
if [ -s "$work/util.bin" ] && [ -s "$work/idmap.txt" ] && [ "$status" != "failed" ]; then
  util_csv=$(python3 "$OUT/extract_util.py" "$PARSE" "$work/util.bin" "$work/idmap.txt" "$mk" 2>/dev/null || echo "")
  if [ -n "$util_csv" ]; then
    printf "%s,%s,%s\n" "$matrix" "$fabric" "$util_csv" > "$util_row"
  fi
fi

rm -rf "$work"

echo "[done $(date +%H:%M:%S)] $tag status=$status wall=${wall}s flows=$fin/$c makespan_us=$mk"
