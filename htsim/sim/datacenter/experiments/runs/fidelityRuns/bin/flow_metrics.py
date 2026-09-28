#!/usr/bin/env python3
# Tier-2 per-flow metrics from a run's compact .log. Emits:
#   slowdown_p50,slowdown_p99,slowdown_max,fairness_jain
# slowdown = FCT / ideal, ideal = flow_bytes / linkrate. FCT ~= finish time
# (flows start ~0 in these matrices). Fairness = Jain index over per-flow rate.
#
# THE TWO STACKS LOG DIFFERENT LINES, and the old single regex only ever
# matched RoCE -- so every UET run silently scored 0.0000 on all four columns:
#   RoCE : "... finished at T total bytes N"
#          N is the cumulative ACK = PACKET COUNT, so bytes = N * mss.
#   UET  : "... finished at T total messages M total packets P RTS R
#           total bytes B in_flight now 0 ..."
#          B is REAL BYTES and is not adjacent to the timestamp.
# Distinguish on the presence of "total packets": UET has it, RoCE does not.
import sys, re
log  = sys.argv[1]
mss  = float(sys.argv[2])      # bytes per packet (MTU) -- RoCE lines only
Bpus = float(sys.argv[3])      # link bytes per microsecond (400Gbps -> 50000)

t_pat     = re.compile(r'finished at ([\d.eE+-]+)')
bytes_pat = re.compile(r'total bytes (\d+)')
pkts_pat  = re.compile(r'total packets (\d+)')

slow, rates = [], []
for line in open(log, errors='ignore'):
    mt = t_pat.search(line)
    if not mt:
        continue
    mb = bytes_pat.search(line)
    if not mb:
        continue
    t = float(mt.group(1))
    if t <= 0:
        continue
    n = float(mb.group(1))
    # UET reports real bytes; RoCE reports a packet count in the same field.
    b = n if pkts_pat.search(line) else n * mss
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
