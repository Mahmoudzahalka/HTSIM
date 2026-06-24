#!/bin/bash
# Single (matrix, fabric) job at consistent 200G (topos_200g/). Fabric: 1os|4os|8os.
set -u
DC=/home/mahmoud_murad_allaah/HTSIM/htsim/sim/datacenter
cd "$DC" || exit 1
OUT=experiments/runs/a3_200g
matrix="$1"; fabric="$2"
TIMEOUT="${TIMEOUT:-14400}"; END_MS="${END_MS:-2000}"

n=$(grep -m1 -oE "Nodes [0-9]+" "$matrix" | awk '{print $2}')
c=$(grep -m1 -oE "Connections [0-9]+" "$matrix" | awk '{print $2}')
base=$(echo "$matrix" | sed 's#connection_matrices/##; s#/#_#g')
log="$OUT/logs/${base}.${fabric}.log"
row="$OUT/rows/${base}.${fabric}.row"
topo="$OUT/topos_200g/fat_tree_${n}_${fabric}.topo"

t0=$(date +%s)
timeout "$TIMEOUT" ./htsim_uec -tm "$matrix" -sender_cc_only -nodes "$n" \
    -topo "$topo" -linkspeed 200000 -end "$END_MS" 2>&1 | awk '
      /Spurious/{sp++; next}
      /finished at/{print; next}
      /^New:/{print; next}
      /[Ee]rror|[Mm]ismatch|Topology Error|Aborted|core dumped|terminat/{print; next}
      END{print "SPURIOUS_COUNT " sp+0}' > "$log"
rc=${PIPESTATUS[0]}
t1=$(date +%s); wall=$((t1-t0))

tmp=$(mktemp)
grep -oE "finished at [0-9.]+" "$log" | awk '{print $3}' | sort -n > "$tmp"
fin=$(wc -l < "$tmp")
if [ "$fin" -gt 0 ]; then
  read -r fmin p50 p99 fmax < <(awk 'NR==FNR{a[++m]=$1;next}END{
    i50=int(m*0.5); if(i50<1)i50=1; i99=int(m*0.99); if(i99<1)i99=1;
    printf "%.1f %.1f %.1f %.1f", a[1], a[i50], a[i99], a[m]}' "$tmp" "$tmp")
  mk="$fmax"
else fmin=0; p50=0; p99=0; fmax=0; mk=0; fi
rm -f "$tmp"

bytes=$(grep -oE "total bytes [0-9]+" "$log" | awk '{s+=$3}END{printf "%.3f",(s+0)/1e9}')
read -r nw rtx rts bnc ack nack pull slk < <(grep -E "^New:" "$log" | tail -1 | awk '{
  for(i=1;i<=NF;i++){if($i=="New:")a=$(i+1);else if($i=="Rtx:")b=$(i+1);
  else if($i=="RTS:")cc=$(i+1);else if($i=="Bounced:")d=$(i+1);else if($i=="ACKs:")e=$(i+1);
  else if($i=="NACKs:")ff=$(i+1);else if($i=="Pulls:")g=$(i+1);else if($i=="sleek_pkts:")h=$(i+1)}
  printf "%s %s %s %s %s %s %s %s", a+0,b+0,cc+0,d+0,e+0,ff+0,g+0,h+0}')
sp=$(grep -oE "SPURIOUS_COUNT [0-9]+" "$log" | awk '{print $2}')

status="ok"; [ "$rc" = "124" ] && status="timeout"
{ [ "$fin" = "0" ] && [ "$rc" != "124" ]; } && status="failed"

printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
  "$matrix" "$n" "$c" "$fabric" "$status" "$wall" "$fin" "$mk" "$fmin" "$p50" "$p99" "$fmax" "$bytes" \
  "${nw:-0}" "${rtx:-0}" "${rts:-0}" "${bnc:-0}" "${ack:-0}" "${nack:-0}" "${pull:-0}" "${slk:-0}" "${sp:-0}" > "$row"
echo "[done $(date +%H:%M:%S)] $base $fabric status=$status wall=${wall}s flows=$fin makespan_us=$mk"
