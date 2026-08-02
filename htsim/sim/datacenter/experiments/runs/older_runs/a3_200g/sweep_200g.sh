#!/bin/bash
# Corrected A3 sweep: explicit fabrics 1os/4os/8os at CONSISTENT 200G (topos_200g/).
# No 'auto' fabric. Two-phase concurrency: light -P5, then heavy perm_8192>=32MB -P2
# (full-bisection big perms peak ~10GB RSS; -P2 keeps 2x10<31GB safe).
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
cd "$DC" || exit 1
OUT=experiments/runs/older_runs/a3_200g
mkdir -p "$OUT/logs" "$OUT/rows"
export TIMEOUT=14400 END_MS=2000
R="$OUT/run_one_200g.sh"

LIGHT="$OUT/jobs_light.txt"; HEAVY="$OUT/jobs_heavy.txt"; : > "$LIGHT"; : > "$HEAVY"
find connection_matrices -name "*.cm" -o -name "*.tm" | while read -r f; do
  case "$f" in *dragonfly_single*|*slimfly_single*|*/a2a.cm|*test_cr_1f10m*) continue;; esac
  n=$(grep -m1 -oE "Nodes [0-9]+" "$f" | awk '{print $2}'); [ -z "$n" ] && continue
  case "$n" in 128|1024|8192) : ;; *) continue;; esac      # explicit-topo node counts only
  for os in 1os 4os 8os; do
    sz=$(echo "$f" | grep -oE "_(8192n_8192c_)?[0-9]+MB" | grep -oE "[0-9]+" | tail -1)
    if [[ "$f" == *perm_8192n_8192c_* ]] && [ "${sz:-0}" -ge 32 ] 2>/dev/null; then
      echo "$n $f $os" >> "$HEAVY"
    else
      echo "$n $f $os" >> "$LIGHT"
    fi
  done
done
sort -n -k1 -k2 "$LIGHT" | awk '{print $2" "$3}' > "$LIGHT.s"; mv "$LIGHT.s" "$LIGHT"
sort -n -k1 -k2 "$HEAVY" | awk '{print $2" "$3}' > "$HEAVY.s"; mv "$HEAVY.s" "$HEAVY"

echo "[200g $(date)] LIGHT=$(wc -l < "$LIGHT") jobs @ -P5 ; HEAVY=$(wc -l < "$HEAVY") jobs DEFERRED (OOM-safe)"
xargs -P 5 -L 1 bash "$R" < "$LIGHT"
echo "[200g $(date)] light phase done. HEAVY phase SKIPPED by request (perm_8192>=32MB)."
echo "[200g] To run the deferred heavy jobs later, ONE AT A TIME (safe, ~10GB each):"
while read -r m fb; do echo "      bash $R $m $fb"; done < "$HEAVY"

CSV="$OUT/results_combined.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV"
cat "$OUT"/rows/*.row >> "$CSV" 2>/dev/null
echo "[200g $(date)] COMPLETE -> $CSV ($(($(wc -l < "$CSV")-1)) rows)"
