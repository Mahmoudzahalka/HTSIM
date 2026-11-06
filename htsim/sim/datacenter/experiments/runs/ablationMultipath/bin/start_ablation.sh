#!/bin/bash
# Start the ablation sweep DETACHED -- survives closing the SSH session.
#   start:  PHASE=pilot bash bin/start_ablation.sh      (then PHASE=main)
#   watch:  tail -f ablationMultipath/sweep_ablation.progress.log
#   stop:   kill -TERM -$(cat ablationMultipath/sweep_ablation.pgid)
set -u
ABL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ABL/sweep_ablation.pgid" ] && kill -0 "-$(cat "$ABL/sweep_ablation.pgid")" 2>/dev/null; then
  echo "already running (pgid $(cat "$ABL/sweep_ablation.pgid")) -- stop it first" >&2; exit 1
fi
: "${PHASE:=pilot}"
# SCHED=budget: per-job memory caps packed under MEM_BUDGET_GB (bin/sweep_ablation_budget.py)
if [ "${SCHED:-}" = budget ]; then DRIVER=(python3 "$ABL/bin/sweep_ablation_budget.py"); else DRIVER=(bash "$ABL/bin/sweep_ablation.sh"); fi
setsid nohup env PHASE="$PHASE" "${DRIVER[@]}" >> "$ABL/sweep_ablation.out" 2>&1 < /dev/null &
pid=$!
sleep 1
pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
echo "${pgid:-$pid}" > "$ABL/sweep_ablation.pgid"
echo "started detached [$PHASE]: pid=$pid pgid=${pgid:-$pid}"
echo "  progress : tail -f $ABL/sweep_ablation.progress.log"
echo "  raw      : tail -f $ABL/sweep_ablation.out"
echo "  stop     : pkill -TERM -s ${pgid:-$pid}   (whole session: htsim runs in its own group under timeout)"
