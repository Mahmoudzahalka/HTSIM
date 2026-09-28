#!/bin/bash
# =============================================================================
# fidelityRuns -- sweep driver. Reads MANIFEST.csv, runs this machine's share.
#
#   MACHINE=local|bigbox   which manifest rows to take (default: local)
#   PARALLEL=N             concurrent htsim processes (default: 2)
#   HEAVY_MB=N             jobs with est_peak_MB above this run SERIALLY, after
#                          the light ones, so a big job never collides with
#                          another big job on a 31 GB box (default: 1500)
#   LIGHT_MEM_GB/HEAVY_MEM_GB  per-job ulimit -v for each phase. The invariant
#                          that keeps this box alive is
#                              PARALLEL * LIGHT_MEM_GB <= usable RAM
#                          so concurrent jobs can never overcommit. Defaults
#                          4 x 6 GB = 24 GB, then 1 x 20 GB serially.
#
# DETACHED BY DESIGN: start with bin/start_local.sh, which wraps this in
# setsid+nohup so closing the SSH session does not kill the sweep.
#
# Resumable: run_one_fidelity.sh skips any (cell,seed) whose .row is already ok,
# so re-running the driver after an interruption continues where it stopped.
# =============================================================================
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R="$FID/bin/run_one_fidelity.sh"
MAN="${MAN:-$FID/MANIFEST.csv}"
MACHINE="${MACHINE:-bigbox}"
# ---- MACHINE PROFILE -------------------------------------------------------
# Defaults are sized for the ~90 GB box, which now runs the whole study.
# The invariant that keeps any box alive is
#       PARALLEL * LIGHT_MEM_GB  <=  usable RAM
# Heavy jobs (the 2048-GPU MoE grid, ~32 GB each on IB) run strictly serially
# afterwards with a much larger cap.
#   90 GB box : PARALLEL=6  LIGHT_MEM_GB=10  HEAVY_MEM_GB=40   (60 GB worst case)
#   31 GB box : PARALLEL=4  LIGHT_MEM_GB=6   HEAVY_MEM_GB=20   (24 GB worst case)
PARALLEL="${PARALLEL:-6}"
HEAVY_MB="${HEAVY_MB:-1500}"
LIGHT_MEM_GB="${LIGHT_MEM_GB:-10}"
HEAVY_MEM_GB="${HEAVY_MEM_GB:-75}"
# HEAVY_PARALLEL (added 2026-09-28): the heavy phase was hardcoded -P1. That is right
# when a heavy job can reach 60+ GB, but the retry set's measured peaks are all under
# 8 GB, so serialising it wasted hours. Invariant is the same as the light phase:
#       HEAVY_PARALLEL x HEAVY_MEM_GB <= usable RAM
HEAVY_PARALLEL="${HEAVY_PARALLEL:-1}"
PROG="$FID/sweep_${MACHINE}.progress.log"

[ -f "$MAN" ] || { echo "no manifest at $MAN -- run bin/build_manifest.py first" >&2; exit 1; }

# Scratch: each run writes util.bin + raw stdout here, then deletes it. Point this
# at a disk with room; it is transient but can hold several GB while running.
export WORKROOT="${WORKROOT:-$FID/work}"
export HTSIM_ROOT="${HTSIM_ROOT:-/home/mahmoud_murad_allaah/HTSIM/htsim}"
mkdir -p "$WORKROOT" || { echo "cannot create WORKROOT $WORKROOT" >&2; exit 1; }

light=$(mktemp); heavy=$(mktemp)
# manifest cols: study,matrix,workload,size_MB,nodes,conns,stack,topo_kind,seed,rep,logtime_us,qsize,est_peak_MB,est_how,machine,orig_wall_s
awk -F, -v m="$MACHINE" -v h="$HEAVY_MB" -v L="$light" -v H="$heavy" 'NR>1 && $15==m {
   line = $11 "\t" $12 "\t" $1 "\t" $2 "\t" $7 "\t" $8 "\t" $9 "\t" $10;
   if ($13+0 > h) print line > H; else print line > L }' "$MAN"
nl=$(wc -l < "$light"); nh=$(wc -l < "$heavy")

echo "=== fidelity sweep [$MACHINE] $(date '+%F %T') ===" | tee -a "$PROG"
echo "    light: $nl jobs at -P$PARALLEL (cap ${LIGHT_MEM_GB}GB each = $((PARALLEL*LIGHT_MEM_GB))GB worst case)" | tee -a "$PROG"
echo "    heavy: $nh jobs at -P$HEAVY_PARALLEL (cap ${HEAVY_MEM_GB}GB each = $((HEAVY_PARALLEL*HEAVY_MEM_GB))GB worst case)  threshold ${HEAVY_MB}MB" | tee -a "$PROG"
echo "    RAM available: $(free -g | awk '/^Mem:/{print $7}') GB" | tee -a "$PROG"
echo "    workroot: $WORKROOT" | tee -a "$PROG"
echo "    htsim   : $HTSIM_ROOT" | tee -a "$PROG"
echo "    cores   : $(nproc 2>/dev/null || echo '?')" | tee -a "$PROG"

runner () {  # stdin line: logtime \t qsize \t study \t matrix \t stack \t topo \t seed \t rep
  IFS=$'\t' read -r lt qs study matrix stack topo seed rep
  LOGTIME_US="$lt" QSIZE="$qs" MEM_CAP_GB="${PHASE_MEM_GB:-6}" \
    bash "$R" "$study" "$matrix" "$stack" "$topo" "$seed" "$rep"
}
export -f runner; export R

if [ "$nl" -gt 0 ]; then
  echo "--- light phase $(date '+%T') ---" | tee -a "$PROG"
  PHASE_MEM_GB="$LIGHT_MEM_GB" export PHASE_MEM_GB
  xargs -P "$PARALLEL" -I{} bash -c 'echo "{}" | runner' < "$light" 2>&1 | tee -a "$PROG"
fi
if [ "$nh" -gt 0 ]; then
  echo "--- heavy phase (serial) $(date '+%T') ---" | tee -a "$PROG"
  PHASE_MEM_GB="$HEAVY_MEM_GB" export PHASE_MEM_GB
  xargs -P "$HEAVY_PARALLEL" -I{} bash -c 'echo "{}" | runner' < "$heavy" 2>&1 | tee -a "$PROG"
fi
rm -f "$light" "$heavy"

echo "=== sweep [$MACHINE] finished $(date '+%F %T') ===" | tee -a "$PROG"
python3 "$FID/bin/aggregate.py" 2>&1 | tee -a "$PROG"
