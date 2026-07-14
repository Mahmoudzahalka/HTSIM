#!/bin/bash
# Assemble graph-ready combined CSVs from a sweep dir's rows/ + util_rows/.
#   - concatenates per-run fragments under the standard schema
#   - corrects 32-bit signed overflow (+2^32 when negative) on Rtx / NACKs
#   - appends derived columns: workload, size_MB, os_ratio, makespan_ms, nack_pct
# Usage: bash assemble_combined.sh <sweep_dir>
set -u
d="${1:?usage: assemble_combined.sh <sweep_dir>}"
sweep=$(basename "$d")                                  # tags rows so sweeps don't collide when merged
STD="matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious"

# ---- results_combined.csv ----
{
  echo "$STD,sweep,workload,size_MB,os_ratio,makespan_ms,rtx_corr,nacks_corr,nack_pct"
  cat "$d"/rows/*.row 2>/dev/null | awk -F, -v sweep="$sweep" 'BEGIN{OFS=","; W=4294967296}
  {
    m=$1; sub(/.*\//,"",m); sub(/\.cm$/,"",m);
    wl=m; sub(/_(128|1024)n_[0-9]+MB.*/,"",wl);         # workload = pattern name
    sz=""; if(match(m,/[0-9]+MB/)) sz=substr(m,RSTART,RLENGTH-2);
    os=$4; gsub(/os/,"",os);
    rtx=$15+0; if(rtx<0) rtx+=W;                        # 32-bit overflow fix
    nk=$19+0;  if(nk<0)  nk+=W;
    nw=$14+0;
    pct=(nw+rtx>0)? nk/(nw+rtx)*100 : 0;
    print $0, sweep, wl, sz, os, sprintf("%.1f",$8/1000), rtx, nk, sprintf("%.3f",pct)
  }'
} > "$d/results_combined.csv"

# ---- utilization_combined.csv (+ derived workload/size/os) ----
{
  printf "matrix,fabric"
  for tier in overall tier0_up tier0_down tier1_up tier1_down tier2_up tier2_down; do
    for stat in n mean p50 p95 p99 max; do printf ",%s_%s" "$tier" "$stat"; done
  done
  printf ",sweep,workload,size_MB,os_ratio\n"
  cat "$d"/util_rows/*.urow 2>/dev/null | awk -F, -v sweep="$sweep" 'BEGIN{OFS=","}
  {
    m=$1; sub(/.*\//,"",m); sub(/\.cm$/,"",m);
    wl=m; sub(/_(128|1024)n_[0-9]+MB.*/,"",wl);
    sz=""; if(match(m,/[0-9]+MB/)) sz=substr(m,RSTART,RLENGTH-2);
    os=$2; gsub(/os/,"",os);
    print $0, sweep, wl, sz, os
  }'
} > "$d/utilization_combined.csv"

echo "[$d] results=$(($(wc -l < "$d/results_combined.csv")-1)) rows, util=$(($(wc -l < "$d/utilization_combined.csv")-1)) rows"
