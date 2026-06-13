#!/usr/bin/env bash
# Summarize an htsim ATLAHS/GOAL run output (stdout redirected to a file).
# Usage: ./analyze.sh <run_output_file>
#
# Reports makespan, flow/message counts, total bytes, FCT distribution,
# packet counts, and retransmit/duplicate diagnostics.

set -euo pipefail

f="${1:-}"
if [[ -z "$f" || ! -f "$f" ]]; then
    echo "Usage: $0 <run_output_file>" >&2
    exit 1
fi

echo "============================================================"
echo " htsim run summary: $f"
echo "============================================================"

echo "--- Makespan (workload runtime) ---"
mk=$(grep -oE "finished at [0-9.]+" "$f" | awk '{print $3}' | sort -n | tail -1)
if [[ -n "${mk:-}" ]]; then
    awk -v mk="$mk" 'BEGIN{printf "  last flow completed at : %s us  (= %.3f ms)\n", mk, mk/1000}'
else
    echo "  (no completed flows found)"
fi

echo "--- Flow / message counts ---"
nf=$(grep -c "finished at" "$f" || true)
echo "  flows (messages) completed : ${nf}"
stuck=$(grep "finished at" "$f" | grep -oE "in_flight now [0-9]+" \
        | awk '$3!=0{c++} END{print (c?c" NONZERO!":"yes (clean)")}')
echo "  all reported in_flight=0   : ${stuck}"

echo "--- Total bytes transferred ---"
# Use floating-point accumulation and print in GiB to avoid 32-bit %d clamping.
grep "finished at" "$f" | grep -oE "total bytes [0-9]+" \
    | awk '{s+=$3} END{printf "  total = %.0f bytes (%.2f GiB)\n", s, s/1024/1024/1024}'

echo "--- FCT distribution (us) ---"
grep "finished at" "$f" | grep -oE "finished at [0-9.]+" | awk '{print $3}' | sort -n | \
    awk '{a[NR]=$1; s+=$1} END{
        if (NR==0) {print "  (none)"; exit}
        printf "  count=%d  min=%.2f  mean=%.2f  max=%.2f\n", NR, a[1], s/NR, a[NR];
        printf "  p50=%.2f  p90=%.2f  p99=%.2f\n", a[int(NR*0.5)], a[int(NR*0.9)], a[int(NR*0.99)]
    }'

echo "--- Packets & retransmits ---"
grep "finished at" "$f" | grep -oE "total packets [0-9]+" \
    | awk '{s+=$3} END{print "  total packets sent : "s+0}'
rts=$(grep "finished at" "$f" | grep -oE "RTS [0-9]+" | awk '$2>0{c++} END{print c+0}')
echo "  RTS (Request-To-Send ctrl pkts) flows>0 : ${rts} / ${nf}"
echo "  duplicate-pkt (Spurious) log lines      : $(grep -c "Spurious" "$f" || true)"

echo "--- Slowest 5 flows (tail latency, us) ---"
grep "finished at" "$f" | grep -oE "finished at [0-9.]+" | awk '{print $3}' \
    | sort -rn | head -5 | sed 's/^/  /'
