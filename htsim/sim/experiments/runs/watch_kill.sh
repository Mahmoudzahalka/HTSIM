#!/usr/bin/env bash
# watch_kill.sh <outfile> <proc_pattern>
# Kills the htsim process once flow completions stop growing (workload done).
out="$1"; pat="$2"
prev=-1; stable=0
while true; do
  sleep 20
  # Match the htsim binary by exact process name (comm=htsim_uec), NOT the bash
  # wrapper whose cmdline also contains the htsim invocation. Serial runs => 1 match.
  pid=$(pgrep -x htsim_uec | head -1)
  if [[ -z "$pid" ]]; then echo "[watch] process gone"; break; fi
  cur=$(grep -c "finished at" "$out" 2>/dev/null || echo 0)
  now=$(grep -oE "^[0-9.]+ flowid" "$out" 2>/dev/null | tail -1 | awk '{print $1}')
  echo "[watch] $(date +%T) finished=$cur sim_now_us=${now:-?} stable=$stable"
  if [[ "$cur" == "$prev" ]]; then stable=$((stable+1)); else stable=0; fi
  prev=$cur
  # 3 consecutive stable polls (60s) with completions not growing => workload done
  if [[ $stable -ge 3 && $cur -gt 0 ]]; then
    echo "[watch] workload complete (finished=$cur). killing $pid"
    kill "$pid"; sleep 3; kill -9 "$pid" 2>/dev/null; break
  fi
done
