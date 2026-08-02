#!/bin/bash
# Walk logs/*.log and re-emit rows/*.row with a fixed FCT regex that handles
# scientific-notation `finished at` values (htsim's cout switches to sci for
# sim time > ~1 s, and the original regex `[0-9.]+` clipped `e+06`).
# Then re-assemble results_combined.csv.
set -u
DC=/csl/mahmoud.za/HTSIM/htsim/sim/datacenter
OUT="$DC/experiments/runs/uet/perm_incast_128_1024"
mkdir -p "$OUT/rows"

# Regex that captures either plain floats (`4.7`, `123456.789`) OR scientific
# form (`4.68919e+06`, `1.2E-3`). awk %f parses both.
FTREGEX='finished at [0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?'

for L in "$OUT"/logs/*.log; do
  tag=$(basename "$L" .log)          # e.g. incast_random_1024n_100MB.1os
  base="${tag%.*}"                    # incast_random_1024n_100MB
  fabric="${tag##*.}"                 # 1os / 4os / 8os
  matrix="$OUT/matrices/$base.cm"
  n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
  c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')

  # Times, in us. awk %f handles scientific notation cleanly.
  tmp=$(mktemp)
  grep -oE "$FTREGEX" "$L" | awk '{printf "%.6f\n", $3}' | sort -n > "$tmp"
  fin=$(wc -l < "$tmp")
  if [ "$fin" -gt 0 ]; then
    read -r fmin p50 p99 fmax < <(awk 'NR==FNR{a[++m]=$1;next}END{
      i50=int(m*0.5); if(i50<1)i50=1; i99=int(m*0.99); if(i99<1)i99=1;
      printf "%.1f %.1f %.1f %.1f", a[1], a[i50], a[i99], a[m]}' "$tmp" "$tmp")
    mk="$fmax"
  else fmin=0; p50=0; p99=0; fmax=0; mk=0; fi
  rm -f "$tmp"

  # Transport counters (unchanged -- these are integers, no notation issue)
  bytes=$(grep -oE "total bytes [0-9]+" "$L" | awk '{s+=$3}END{printf "%.3f",(s+0)/1e9}')
  read -r nw rtx rts bnc ack nack pull slk < <(grep -E "^New:" "$L" | tail -1 | awk '{
    for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1);
    else if($i=="RTS:")cc=$(i+1);else if($i=="Bounced:")d=$(i+1);else if($i=="ACKs:")e=$(i+1);
    else if($i=="NACKs:")ff=$(i+1);else if($i=="Pulls:")g=$(i+1);else if($i=="sleek_pkts:")h=$(i+1)}
    printf "%s %s %s %s %s %s %s %s", a+0,b+0,cc+0,d+0,e+0,ff+0,g+0,h+0}')
  sp=$(grep -oE "SPURIOUS_COUNT [0-9]+" "$L" | awk '{print $2}')

  # Read wall_s from the existing row (can't be recomputed from log alone)
  old="$OUT/rows/${tag}.row"
  if [ -s "$old" ]; then
    wall=$(awk -F',' '{print $6}' "$old")
  else
    wall=0
  fi

  # Status logic identical to run_one.sh
  status="ok"
  if [ "$fin" -lt "$c" ]; then
    if [ "$fin" = "0" ]; then status="failed"; else status="incomplete"; fi
  fi

  printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
    "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
    "${nw:-0}" "${rtx:-0}" "${rts:-0}" "${bnc:-0}" "${ack:-0}" "${nack:-0}" "${pull:-0}" "${slk:-0}" "${sp:-0}" > "$OUT/rows/${tag}.row"
done

CSV="$OUT/results_combined.csv"
echo "matrix,nodes,conns,fabric,status,wall_s,flows_fin,makespan_us,fct_min_us,fct_p50_us,fct_p99_us,fct_max_us,total_GB,New,Rtx,RTS,Bounced,ACKs,NACKs,Pulls,sleek,spurious" > "$CSV"
cat "$OUT"/rows/*.row >> "$CSV"

echo "Re-derived $(($(wc -l < "$CSV")-1)) rows -> $CSV"
