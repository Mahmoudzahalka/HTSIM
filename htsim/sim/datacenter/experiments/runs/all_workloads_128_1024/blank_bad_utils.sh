#!/bin/bash
# Blank utilization rows where the FCT-parse bug in the original run_one.sh
# gave extract_util.py a divisor ~1e6x too small (real makespan > 1 s but
# regex clipped scientific notation -> divisor was mantissa alone).
# For each blanked row, keep the (matrix, fabric) columns and set the 42
# statistics columns to empty so pandas etc. reads them as NaN.
set -u
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/all_workloads_128_1024"

# The 8 corrupted (matrix, fabric) pairs identified by comparing sci-aware
# makespan to old regex output (ratio >= 1e6).
CORRUPTED=(
  "incast_random_1024n_100MB.cm 1os"
  "incast_random_1024n_64MB.cm 1os"
  "incast_remote_1024n_100MB.cm 1os"
  "incast_remote_1024n_100MB.cm 4os"
  "incast_remote_1024n_100MB.cm 8os"
  "incast_remote_1024n_64MB.cm 1os"
  "incast_remote_1024n_64MB.cm 4os"
  "incast_remote_1024n_64MB.cm 8os"
)

# Blank each corrupted urow: keep matrix+fabric, empty everything else (42 stats)
for entry in "${CORRUPTED[@]}"; do
  mat_base="${entry%% *}"                # incast_random_1024n_100MB.cm
  fab="${entry##* }"                     # 1os
  urow="$OUT/util_rows/${mat_base%.cm}.${fab}.urow"
  matrix="$OUT/matrices/$mat_base"
  # 2 columns + 42 empty = 44 columns total
  printf "%s,%s%s\n" "$matrix" "$fab" "$(printf ',,%.0s' $(seq 1 42))" > "$urow"
done

# Reassemble the util CSV
CSV="$OUT/utilization_combined.csv"
{
  printf "matrix,fabric"
  for tier in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for stat in n mean p50 p95 p99 max; do
      printf ",%s_%s" "$tier" "$stat"
    done
  done
  printf "\n"
} > "$CSV"
cat "$OUT"/util_rows/*.urow >> "$CSV"

echo "Blanked ${#CORRUPTED[@]} corrupted util rows. Total rows: $(($(wc -l < "$CSV")-1))"
