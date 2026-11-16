#!/usr/bin/env python3
"""Summarise one htsim_uec run: CCT = time the last flow finished (us).

Reads the 'Flow ... finished at <us> ... total bytes <n>' lines and the matrix
header (via the 'Connections' count echoed by htsim is not guaranteed, so the
expected flow count is taken from the .cm passed with -tm on the command line
when available).
"""
import json, re, sys

FIN = re.compile(r"^Flow (\S+) flowId (\d+) .* finished at ([0-9.e+]+) .* total bytes (\d+)")
path = sys.argv[1]
fin, nbytes, spurious, cm = [], 0, 0, None
with open(path, errors="replace") as f:
    for line in f:
        m = FIN.match(line)
        if m:
            fin.append(float(m.group(3))); nbytes += int(m.group(4))
        elif line.startswith("Spurious"):
            spurious += 1
expected = None
try:  # the run dir's parent name doesn't carry the .cm; read it from time.err command line
    tv = open(path.rsplit("/", 1)[0] + "/time.err", errors="replace").read()
    m = re.search(r'Command being timed: ".* -tm (\S+)', tv)
    if m:
        cm = m.group(1)
        expected = int(open(cm).readlines()[1].split()[1])
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", tv)
    wall = re.search(r"Elapsed \(wall clock\) time.*: (\S+)", tv)
except OSError:
    rss = wall = None
fin.sort()
out = dict(flows_finished=len(fin), flows_expected=expected,
           complete=(expected is not None and len(fin) == expected),
           cct_us=fin[-1] if fin else None,
           fct_p50_us=fin[len(fin) // 2] if fin else None,
           first_finish_us=fin[0] if fin else None,
           bytes_delivered=nbytes, spurious_lines=spurious,
           max_rss_MB=int(rss.group(1)) // 1024 if rss else None,
           wall=wall.group(1) if wall else None)
print(json.dumps(out, indent=1))
