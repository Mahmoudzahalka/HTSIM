#!/usr/bin/env python3
"""Extract per-tier link-utilization summary from a htsim binary logfile.

Runs parse_output -ascii on the .bin, parses CUM_TRAFFIC records
(QueueLoggerSampling emits these periodically -- val1 = _cumarr in seconds,
i.e. cumulative link-busy time). Utilization for a queue is:

    util = _cumarr(final) / sim_time(final)

Queues are binned by tier/direction from their name in idmap.txt:
  SRC%d->LS%d  = host->ToR uplink   (tier0_up)
  LS%d->DST%d  = ToR->host downlink (tier0_down)
  LS%d->US_%d  = ToR->Agg uplink    (tier1_up)
  US%d->LS_%d  = Agg->ToR downlink  (tier1_down)
  US%d->CS%d   = Agg->Core uplink   (tier2_up)
  CS%d->US%d   = Core->Agg downlink (tier2_down)

Output: one CSV row with p50/p95/p99/max util per tier + overall.
"""
import os
import re
import subprocess
import sys
import statistics as st

TIER_PATTERNS = [
    ("tier0_up",   re.compile(r"^SRC\d+->LS")),
    ("tier0_down", re.compile(r"^LS\d+->DST")),
    ("tier1_up",   re.compile(r"^LS\d+->US")),
    ("tier1_down", re.compile(r"^US\d+->LS")),
    ("tier2_up",   re.compile(r"^US\d+->CS")),
    ("tier2_down", re.compile(r"^CS\d+->US")),
]


def classify(name):
    for tier, pat in TIER_PATTERNS:
        if pat.match(name):
            return tier
    return None


def load_idmap(idmap_path):
    m = {}
    if not os.path.exists(idmap_path):
        return m
    with open(idmap_path) as f:
        for line in f:
            parts = line.rstrip("\n").split(" ", 1)
            if len(parts) == 2:
                try:
                    m[int(parts[0])] = parts[1]
                except ValueError:
                    pass
    return m


def pct(vals, p):
    if not vals:
        return 0.0
    vs = sorted(vals)
    idx = min(len(vs) - 1, int(len(vs) * p))
    return vs[idx]


def main():
    if len(sys.argv) < 5:
        print("Usage: extract_util.py <parse_output_bin> <log.bin> <idmap.txt> <makespan_us>",
              file=sys.stderr)
        sys.exit(1)
    parse_bin = sys.argv[1]
    log_bin = sys.argv[2]
    idmap_path = sys.argv[3]
    try:
        makespan_s = float(sys.argv[4]) / 1e6
    except ValueError:
        makespan_s = 0.0

    idmap = load_idmap(idmap_path)

    # per-queue: last-seen (time_s, cumarr_s)
    last_seen = {}
    max_time = 0.0

    proc = subprocess.Popen(
        [parse_bin, log_bin, "-ascii"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1 << 20
    )
    for line in proc.stdout:
        # Format: "<t> Type QUEUE_APPROX ID <id> Ev CUM_TRAFFIC CumArr <v1> CumIdle <v2> CumDrop <v3>"
        if " Ev CUM_TRAFFIC " not in line:
            continue
        toks = line.split()
        # Tokens: 0=<t>, 1=Type, 2=QUEUE_APPROX, 3=ID, 4=<id>, 5=Ev,
        #         6=CUM_TRAFFIC, 7=CumArr, 8=<v1>, 9=CumIdle, 10=<v2>, 11=CumDrop, 12=<v3>
        try:
            t = float(toks[0])
            qid = int(toks[4])
            cumarr = float(toks[8])
        except (IndexError, ValueError):
            continue
        last_seen[qid] = (t, cumarr)
        if t > max_time:
            max_time = t
    proc.wait()

    # Divide cumarr (seconds of link-busy time) by makespan (seconds), NOT by
    # max sample time -- the logger keeps sampling after workload completion,
    # so max_time = -end cap, which dilutes utilization to near-zero.
    denom = makespan_s if makespan_s > 0 else max_time

    if denom <= 0 or not last_seen:
        cols = ["overall"] + [t for t, _ in TIER_PATTERNS]
        row_parts = []
        for _ in cols:
            row_parts += ["0", "0", "0", "0", "0", "0"]  # n, mean, p50, p95, p99, max
        print(",".join(row_parts))
        return

    # Bin per tier
    tier_utils = {t: [] for t, _ in TIER_PATTERNS}
    overall = []
    for qid, (t, cumarr) in last_seen.items():
        name = idmap.get(qid, "")
        tier = classify(name)
        util = cumarr / denom
        util = max(0.0, min(1.0, util))
        overall.append(util)
        if tier is not None:
            tier_utils[tier].append(util)

    def summ(vals):
        if not vals:
            return (0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return (
            len(vals),
            st.mean(vals),
            pct(vals, 0.50),
            pct(vals, 0.95),
            pct(vals, 0.99),
            max(vals),
        )

    parts = []
    # overall first
    n, mn, p50, p95, p99, mx = summ(overall)
    parts += [f"{n}", f"{mn:.4f}", f"{p50:.4f}", f"{p95:.4f}", f"{p99:.4f}", f"{mx:.4f}"]
    # then per tier in the fixed order
    for tier, _ in TIER_PATTERNS:
        n, mn, p50, p95, p99, mx = summ(tier_utils[tier])
        parts += [f"{n}", f"{mn:.4f}", f"{p50:.4f}", f"{p95:.4f}", f"{p99:.4f}", f"{mx:.4f}"]

    print(",".join(parts))


if __name__ == "__main__":
    main()
