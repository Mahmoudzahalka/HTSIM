#!/usr/bin/env python3
# Tier-2 per-flow metrics from a run's compact .log ("finished at T total bytes A"
# lines; A is the cumulative ACK = packet count). Emits:
#   slowdown_p50,slowdown_p99,slowdown_max,fairness_jain
# slowdown = FCT / ideal, ideal = flow_bytes / linkrate. FCT ~= finish time
# (flows start ~0 in these matrices). Fairness = Jain index over per-flow rate.
import sys, re
log = sys.argv[1]
mss = float(sys.argv[2])       # bytes per packet (MTU)
Bpus = float(sys.argv[3])      # link bytes per microsecond (200Gbps -> 25000)
slow, rates = [], []
pat = re.compile(r'finished at ([\d.eE+-]+) total bytes (\d+)')
for line in open(log, errors='ignore'):
    m = pat.search(line)
    if not m:
        continue
    t = float(m.group(1)); pkts = float(m.group(2))
    if t <= 0:
        continue
    b = pkts * mss
    ideal = b / Bpus
    if ideal > 0:
        slow.append(t / ideal)
        rates.append(b / t)
def pct(a, p):
    if not a: return 0.0
    a = sorted(a); i = min(int(len(a) * p), len(a) - 1); return a[i]
def jain(a):
    if not a: return 0.0
    s = sum(a); s2 = sum(x * x for x in a); n = len(a)
    return (s * s) / (n * s2) if s2 > 0 else 0.0
print("%.4f,%.4f,%.4f,%.4f" % (pct(slow, 0.5), pct(slow, 0.99),
                               max(slow) if slow else 0.0, jain(rates)))
