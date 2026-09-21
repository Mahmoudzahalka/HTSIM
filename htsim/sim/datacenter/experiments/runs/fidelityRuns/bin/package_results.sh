#!/bin/bash
# Package the study's RESULTS for transfer back to the analysis machine.
#
# Takes only the .row and .urow files -- ~1.2 MB for the full 1395-run study.
# The per-run .log files are deliberately EXCLUDED: they hold one line per finished
# flow, which is ~3.2 GB across the study. They stay on the big box; you only need
# them if a specific run needs investigating, and then you fetch that one file.
#
#   on the big box:   bash bin/package_results.sh
#   then:             scp fidelity_results.tar.gz you@analysisbox:~
#   on the analysis box, from inside its own fidelityRuns/:
#                     tar xzf ~/fidelity_results.tar.gz
#                     python3 bin/aggregate.py --check-rep1
set -u
FID="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$FID/fidelity_results.tar.gz}"
cd "$FID" || exit 1

n_row=$(find . -name '*.row'  | wc -l)
n_uro=$(find . -name '*.urow' | wc -l)
[ "$n_row" -gt 0 ] || { echo "no .row files found -- has the sweep produced anything yet?" >&2; exit 1; }

tar czf "$OUT" $(find . -path '*/rows/*.row' -o -path '*/util_rows/*.urow' | sed 's|^\./||')

echo "packaged $n_row rows + $n_uro util_rows -> $OUT ($(du -h "$OUT" | cut -f1))"
echo
awk -F, '{c[$11]++} END{print "status tally:"; for(s in c) printf "  %-18s %d\n", s, c[s]}' */rows/*.row
echo
exp=$(( $(wc -l < MANIFEST.csv) - 1 ))
echo "coverage: $n_row / $exp manifest jobs"
[ "$n_row" -lt "$exp" ] && echo "  (sweep not finished -- rerun bin/start_sweep.sh to continue, it skips completed cells)"
echo
echo "next: scp $OUT to the analysis machine, then from inside ITS fidelityRuns/:"
echo "  tar xzf $(basename "$OUT")"
echo "  python3 bin/aggregate.py --check-rep1"
echo "  python3 bin/make_graphs_fidelity.py"
