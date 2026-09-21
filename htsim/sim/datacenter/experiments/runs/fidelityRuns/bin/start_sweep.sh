#!/bin/bash
# Start this box's share DETACHED -- survives closing the SSH session.
# setsid puts the sweep in its own session with no controlling terminal, so the
# SIGHUP sent when the ssh connection drops never reaches it.
#   start:  bash bin/start_local.sh
#   watch:  tail -f fidelityRuns/sweep_run.progress.log
#   stop:   kill -TERM -$(cat fidelityRuns/sweep_run.pgid)
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$FID/sweep_run.pgid" ] && kill -0 "-$(cat "$FID/sweep_run.pgid")" 2>/dev/null; then
  echo "already running (pgid $(cat "$FID/sweep_run.pgid")) -- stop it first" >&2; exit 1
fi
: "${PARALLEL:=6}"; : "${HEAVY_MB:=1500}"; : "${MACHINE:=bigbox}"
setsid nohup env MACHINE="$MACHINE" PARALLEL="$PARALLEL" HEAVY_MB="$HEAVY_MB" \
  bash "$FID/bin/sweep_fidelity.sh" >> "$FID/sweep_run.out" 2>&1 < /dev/null &
pid=$!
sleep 1
pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
echo "${pgid:-$pid}" > "$FID/sweep_run.pgid"
echo "started detached: pid=$pid pgid=${pgid:-$pid}"
echo "  progress : tail -f $FID/sweep_run.progress.log"
echo "  raw      : tail -f $FID/sweep_run.out"
echo "  stop     : kill -TERM -${pgid:-$pid}"
