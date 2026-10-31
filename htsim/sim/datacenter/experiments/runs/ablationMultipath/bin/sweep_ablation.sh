#!/bin/bash
# =============================================================================
# ablationMultipath -- sweep driver. Reads ablationMultipath/MANIFEST.csv and runs
# each job through fidelityRuns/bin/run_one_fidelity.sh (same flags, watchdog,
# metrics as the fidelity study) with the arm's extra flags (ARM_ARGS).
#
#   PHASE=pilot|main|all     which manifest rows to run (default: pilot)
#   PARALLEL / LIGHT_MEM_GB  light jobs (perm / incast / outcast)
#   HEAVY_PARALLEL / HEAVY_MEM_GB  heavy jobs (allreduce_ring, a2a_concurrent),
#                            run after the light ones
#   Invariant that keeps the box alive:
#       PARALLEL x LIGHT_MEM_GB  <=  usable RAM   and
#       HEAVY_PARALLEL x HEAVY_MEM_GB  <=  usable RAM
#   90 GB box defaults: 6 x 10 GB light, 2 x 40 GB heavy.
#
# Start it with bin/start_ablation.sh (detached). Resumable: any job whose .row
# is already "ok" is skipped, so re-running continues where it stopped.
# =============================================================================
set -u
ABL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FID="$(cd "$ABL/../fidelityRuns" && pwd)"
R="$FID/bin/run_one_fidelity.sh"
MAN="${MAN:-$ABL/MANIFEST.csv}"
PHASE="${PHASE:-pilot}"
PARALLEL="${PARALLEL:-6}"
LIGHT_MEM_GB="${LIGHT_MEM_GB:-10}"
HEAVY_PARALLEL="${HEAVY_PARALLEL:-2}"
HEAVY_MEM_GB="${HEAVY_MEM_GB:-40}"
PROG="$ABL/sweep_ablation.progress.log"

[ -f "$MAN" ] || { echo "no manifest at $MAN -- run bin/build_ablation_manifest.py first" >&2; exit 1; }
case "$PHASE" in pilot|main|all) ;; *) echo "PHASE must be pilot|main|all" >&2; exit 1 ;; esac

export WORKROOT="${WORKROOT:-$ABL/work}"
export HTSIM_ROOT="${HTSIM_ROOT:-$HOME/HTSIM/htsim}"
export OUTROOT="$ABL"
mkdir -p "$WORKROOT" || { echo "cannot create WORKROOT $WORKROOT" >&2; exit 1; }

light=$(mktemp); heavy=$(mktemp)
# manifest: phase,arm,arm_args,study,matrix,workload,size_MB,nodes,conns,stack,topo_kind,seed,rep,logtime_us,qsize,heavy,baseline_study
awk -F, -v p="$PHASE" -v L="$light" -v H="$heavy" 'NR>1 && (p=="all" || $1==p) {
   line = $2 "\t" $3 "\t" $4 "\t" $5 "\t" $10 "\t" $11 "\t" $12 "\t" $13 "\t" $14 "\t" $15;
   if ($16=="1") print line > H; else print line > L }' "$MAN"
nl=$(wc -l < "$light"); nh=$(wc -l < "$heavy")

echo "=== multipath ablation [$PHASE] $(date '+%F %T') ===" | tee -a "$PROG"
echo "    light: $nl jobs at -P$PARALLEL (cap ${LIGHT_MEM_GB}GB each)" | tee -a "$PROG"
echo "    heavy: $nh jobs at -P$HEAVY_PARALLEL (cap ${HEAVY_MEM_GB}GB each)" | tee -a "$PROG"
echo "    RAM available: $(free -g | awk '/^Mem:/{print $7}') GB   cores: $(nproc 2>/dev/null || echo '?')" | tee -a "$PROG"
echo "    workroot: $WORKROOT ($(df -h --output=avail "$WORKROOT" | tail -1 | tr -d ' ') free)" | tee -a "$PROG"
echo "    htsim   : $HTSIM_ROOT" | tee -a "$PROG"

runner () {  # stdin: arm \t arm_args \t study \t matrix \t stack \t topo \t seed \t rep \t logtime \t qsize
  IFS=$'\t' read -r arm args study matrix stack topo seed rep lt qs
  ARM="$arm" ARM_ARGS="$args" LOGTIME_US="$lt" QSIZE="$qs" MEM_CAP_GB="${PHASE_MEM_GB:-10}" \
    bash "$R" "$study" "$matrix" "$stack" "$topo" "$seed" "$rep"
}
export -f runner; export R

if [ "$nl" -gt 0 ]; then
  echo "--- light $(date '+%T') ---" | tee -a "$PROG"
  PHASE_MEM_GB="$LIGHT_MEM_GB" export PHASE_MEM_GB
  xargs -P "$PARALLEL" -I{} bash -c 'echo "{}" | runner' < "$light" 2>&1 | tee -a "$PROG"
fi
if [ "$nh" -gt 0 ]; then
  echo "--- heavy $(date '+%T') ---" | tee -a "$PROG"
  PHASE_MEM_GB="$HEAVY_MEM_GB" export PHASE_MEM_GB
  xargs -P "$HEAVY_PARALLEL" -I{} bash -c 'echo "{}" | runner' < "$heavy" 2>&1 | tee -a "$PROG"
fi
rm -f "$light" "$heavy"

echo "=== ablation [$PHASE] finished $(date '+%F %T') ===" | tee -a "$PROG"
python3 "$ABL/bin/compare_ablation.py" 2>&1 | tee -a "$PROG"
