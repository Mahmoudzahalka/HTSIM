#!/bin/bash
# Detached memory guard for the fidelity sweep.
#
# The sweep's own per-job `ulimit -v` stops ONE job from taking the box down, but
# nothing watches the machine as a whole. This does: it polls RAM/swap and the run
# statuses, and writes a timestamped line to oom_guard.log whenever something is
# worth knowing. It ALERTS ONLY -- it never kills a job, because a mem_capped or
# swapping run is a decision for a human, and completed cells are never lost
# (the sweep is resumable and skips any (cell,seed) with an ok row).
#
#   start:  setsid nohup bash bin/oom_guard.sh <sweep_pgid> >/dev/null 2>&1 &
#   watch:  tail -f oom_guard.log
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGID="${1:?usage: oom_guard.sh <sweep_pgid>}"
PROG="$FID/sweep_bigbox.progress.log"
LOG="$FID/oom_guard.log"
prev_bad=0; i=0
say () { printf '[%s] %s\n' "$(date '+%F %T')" "$1" >> "$LOG"; }

say "guard started, watching sweep pgid $PGID (alert-only; never kills a job)"
while :; do
  i=$((i+1))
  avail=$(free -g | awk '/^Mem:/{print $7}'); sw=$(free -g | awk '/^Swap:/{print $3}')
  wk=$(pgrep -c htsim 2>/dev/null || echo 0)

  [ "${sw:-0}" -gt 0 ]   && say "WARN  swap in use: ${sw}GB (avail=${avail}GB workers=$wk) -- lower PARALLEL if this grows"
  [ "${avail:-99}" -lt 20 ] && say "CRIT  only ${avail}GB RAM available (swap=${sw}GB workers=$wk)"

  bad=$(grep -cE 'status=(mem_capped|oom_or_killed|failed|timeout|lossless_overflow)' "$PROG" 2>/dev/null); bad=${bad:-0}
  if [ "$bad" -gt "$prev_bad" ]; then
    grep -E 'status=(mem_capped|oom_or_killed|failed|timeout|lossless_overflow)' "$PROG" 2>/dev/null \
      | tail -n $((bad - prev_bad)) | while read -r l; do say "BAD   $l"; done
    prev_bad=$bad
  fi

  if ! kill -0 "-$PGID" 2>/dev/null; then
    d=$(grep -c '^\[done' "$PROG" 2>/dev/null); d=${d:-0}
    say "sweep pgid $PGID gone -- $d done, $(find "$FID" -name '*.row' 2>/dev/null | wc -l)/1305 rows. guard exiting."
    exit 0
  fi

  # hourly heartbeat so a silent log is distinguishable from a dead guard
  [ $((i % 60)) -eq 0 ] && say "ok    $(grep -c '^\[done' "$PROG" 2>/dev/null)/1305 done, avail=${avail}GB swap=${sw}GB workers=$wk"
  sleep 60
done
