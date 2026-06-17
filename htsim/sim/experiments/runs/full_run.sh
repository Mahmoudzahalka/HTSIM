#!/bin/bash
cd /home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
TRACE=../experiments/traces/Llama7B_N32_GPU128_PP1_DP128_7B_BS128.bin
TOPO=topologies/fat_tree_128_1os.topo
OUT=../experiments/runs/full_completion.out
ERR=../experiments/runs/full_completion.stderr
: > "$OUT"; : > "$ERR"
echo "launching FULL completion run (setsid-detached) at $(date)" >> "$OUT"
stdbuf -oL ./htsim_uec -goal "$TRACE" -sender_cc_only -nodes 128 \
    -end 4000000 -topo "$TOPO" -linkspeed 200000 2> "$ERR" \
  | stdbuf -oL awk '
      /Spurious/ {next}
      /It terminates|PERFORMANCE|Maximum finishing time|queue on host/ {print; fflush(); next}
      /FLOW-FREED|QUIESCENT-COUNT|LGS-DIAG/ {print; fflush(); next}
      /STALL-DIAG/ {print; fflush(); next}
      /finished at/ {c++; if(c%200000==0){print "[FINISHED-COUNT] "c; fflush()}; next}
      END {print "[FINISHED-TOTAL] "c}
    ' >> "$OUT"
echo "HTSIM_EXIT=${PIPESTATUS[0]}" >> "$OUT"
echo "DONE at $(date)" >> "$OUT"
