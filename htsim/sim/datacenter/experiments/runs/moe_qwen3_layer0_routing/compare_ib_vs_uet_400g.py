#!/usr/bin/env python3
"""CCT comparison IB (RoCE+PFC+DCQCN) vs UET on the MoE matrices, 400 G flat fat tree.

Reads the fidelity-format .row files written by run_ib_vs_uet_400g.sh and prints,
per seed, each stack's CCT (= makespan, time the last flow finished) next to the
seed's lower bound: the busiest NIC's bytes (sent or received) at 400 Gbps,
payload only (no header overhead; IB/UET packet formats differ).
usage: compare_ib_vs_uet_400g.py [rows_dir]  [--csv out.csv]
"""
import csv, glob, os, sys
import numpy as np

COLS = ("study matrix workload size_MB nodes conns stack topo_kind seed rep status wall_s peak_mb "
        "flows_fin makespan_us fct_min fct_p50 fct_p99 fct_max total_GB New Rtx RTS Bounced ACKs NACKs "
        "Pulls sleek spurious pfc_pauses pfc_pause_us max_queue_bytes sd_p50 sd_p99 sd_max jain overflow").split()
HERE = os.path.dirname(os.path.abspath(__file__))
out_csv = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
args = [a for a in sys.argv[1:] if not a.startswith("--") and a != out_csv]
rows_dir = args[0] if args else glob.glob(os.path.join(HERE, "ib_vs_uet_400g", "*", "rows"))[0]


def bound_us(cm, gbps=400):
    send, recv = {}, {}
    for l in open(cm).readlines()[2:]:
        a, _, _, _, b = l.split(); s, d = map(int, a.split("->")); b = int(b)
        send[s] = send.get(s, 0) + b; recv[d] = recv.get(d, 0) + b
    return max(max(send.values()), max(recv.values())) * 8 / (gbps * 1e9) * 1e6


rows = {}
for f in glob.glob(os.path.join(rows_dir, "*.row")):
    r = dict(zip(COLS, next(csv.reader(open(f)))))
    rows[(int(r["seed"]), r["stack"])] = r
seeds = sorted({s for s, _ in rows})
table, ratio = [], []
print(f"{'seed':>4} {'bound us':>9} | {'IB CCT us':>10} {'over':>6} {'status':>8} {'PFC pauses':>10} | "
      f"{'UET CCT us':>10} {'over':>6} {'status':>8} {'Rtx':>8} | IB/UET")
for s in seeds:
    ib, ue = rows.get((s, "ib")), rows.get((s, "uet"))
    cm = (ib or ue)["matrix"]
    lb = bound_us(cm)
    def cell(r, extra):
        if not r: return f"{'-':>10} {'-':>6} {'missing':>8} {'-':>10}"
        mk = float(r["makespan_us"] or 0)
        return f"{mk:10.1f} {100 * (mk / lb - 1):5.1f}% {r['status']:>8} {r[extra]:>10}"
    rat = ""
    if ib and ue and ib["status"] == ue["status"] == "ok":
        x = float(ib["makespan_us"]) / float(ue["makespan_us"]); ratio.append(x); rat = f"{x:.3f}"
    print(f"{s:4d} {lb:9.1f} | {cell(ib, 'pfc_pauses')} | {cell(ue, 'Rtx')} | {rat}")
    table.append(dict(seed=s, bound_us=round(lb, 1),
                      ib_cct_us=ib and ib["makespan_us"], ib_status=ib and ib["status"],
                      ib_pfc_pauses=ib and ib["pfc_pauses"], ib_wall_s=ib and ib["wall_s"],
                      uet_cct_us=ue and ue["makespan_us"], uet_status=ue and ue["status"],
                      uet_rtx=ue and ue["Rtx"], uet_wall_s=ue and ue["wall_s"]))
for st in ("ib", "uet"):
    v = [float(rows[(s, st)]["makespan_us"]) for s in seeds if (s, st) in rows and rows[(s, st)]["status"] == "ok"]
    if v:
        print(f"{st.upper():>4} CCT: mean {np.mean(v):.1f} us"
              + (f", SEM {np.std(v, ddof=1) / np.sqrt(len(v)):.1f}" if len(v) > 1 else "") + f"  (n={len(v)} ok)")
if ratio:
    print(f"IB/UET CCT ratio: mean {np.mean(ratio):.3f}" + (f" (min {min(ratio):.3f}, max {max(ratio):.3f})" if len(ratio) > 1 else ""))
if out_csv:
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0])); w.writeheader(); w.writerows(table)
