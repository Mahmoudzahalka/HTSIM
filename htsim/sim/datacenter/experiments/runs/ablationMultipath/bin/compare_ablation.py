#!/usr/bin/env python3
"""Join ablation rows with their fidelity baselines and write comparison tables.

  baselines (from fidelityRuns/results/runs_all.csv, same cell + seed):
      ib  qp1   = RoCE + DCQCN + PFC, 1 QP per flow
      uet spray = UET default load balancing (mixed)
  ablation rows (ablationMultipath/abl_*/rows/*.row):
      ib  qp2 / qp4 / qp8 = -qps K
      uet ecmp            = -load_balancing_algo ecmp

outputs (ablationMultipath/results/):
  ablation_long.csv  one row per (cell, seed, stack, arm): status + key metrics,
                     ratio to that stack's baseline, and the baseline's 5-seed spread
  ablation_wide.csv  one row per (cell, seed): makespan of all 6 arms, multipath gains,
                     and the transport gap with and without multipath
  ablation_mean.csv  one row per (cell, stack, arm) across seeds: n, mean/std/min/max
                     makespan, gain of means vs baseline, and whether the arm's seed
                     range overlaps the baseline's (overlap = not separable from noise)
A ratio is flagged within_seed_noise when |ratio - 1| is smaller than the baseline
cell's (max-min)/mean makespan across the 5 fidelity seeds.
"""
import csv, glob, os, statistics as st, sys
from collections import defaultdict

ABL = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FID = os.path.abspath(os.path.join(ABL, "..", "fidelityRuns"))
RES = os.path.join(ABL, "results")
COLS = ["study","matrix","workload","size_MB","nodes","conns","stack","topo_kind","seed","rep","status","wall_s","peak_mb",
        "flows_fin","makespan_us","fct_min_us","fct_p50_us","fct_p99_us","fct_max_us","total_GB","New","Rtx","RTS","Bounced",
        "ACKs","NACKs","Pulls","sleek","spurious","pfc_pauses","pfc_pause_us","max_queue_bytes","slowdown_p50","slowdown_p99",
        "slowdown_max","fairness_jain","overflow"]
KEEP = ["status","makespan_us","fct_p50_us","fct_p99_us","slowdown_p99","fairness_jain","pfc_pauses","pfc_pause_us",
        "max_queue_bytes","Rtx","NACKs","spurious","overflow","peak_mb","wall_s"]
ARMS = {"ib": ["qp1","qp2","qp4","qp8"], "uet": ["spray","ecmp"]}
BASE_ARM = {"ib": "qp1", "uet": "spray"}


def f(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def main():
    runs = defaultdict(dict)      # (workload,size,nodes,seed) -> {(stack,arm): row}
    for p in sorted(glob.glob(os.path.join(ABL, "abl_*", "rows", "*.row"))):
        parts = open(p).read().strip().split(",")
        if len(parts) != len(COLS):
            print(f"  !! {os.path.basename(p)}: {len(parts)} fields -- skipped", file=sys.stderr); continue
        r = dict(zip(COLS, parts))
        arm = r["study"].split("_")[-1]                       # abl_ib_qp4 -> qp4
        runs[(r["workload"], r["size_MB"], r["nodes"], r["seed"])][(r["stack"], arm)] = r
    if not runs:
        print("no ablation rows yet"); return

    spread = defaultdict(list)    # (stack,workload,size,nodes) -> makespans over all fidelity seeds
    base = {}
    with open(os.path.join(FID, "results", "runs_all.csv")) as fh:
        for r in csv.DictReader(fh):
            if r["topo_kind"] != "1os" or r["stack"] not in ARMS: continue
            k4 = (r["stack"], r["workload"], r["size_MB"], r["nodes"])
            if r["status"] == "ok" and f(r["makespan_us"]): spread[k4].append(f(r["makespan_us"]))
            cell = (r["workload"], r["size_MB"], r["nodes"], r["seed"])
            if cell in runs: base[(cell, r["stack"])] = r
    for (cell, stack), r in base.items():
        runs[cell][(stack, BASE_ARM[stack])] = r

    def sp(stack, cell):
        v = spread.get((stack,) + cell[:3], [])
        return (max(v) - min(v)) / st.mean(v) if len(v) >= 2 else None

    os.makedirs(RES, exist_ok=True)
    long_rows, wide_rows = [], []
    for cell in sorted(runs, key=lambda c: (int(c[2]), c[0], int(c[1]), int(c[3]))):
        arms = runs[cell]; ck = dict(zip(["workload","size_MB","nodes","seed"], cell)); w = dict(ck)
        for stack in ARMS:
            b = arms.get((stack, BASE_ARM[stack])); bmk = f(b["makespan_us"]) if b and b["status"] == "ok" else None
            s = sp(stack, cell)
            for arm in ARMS[stack]:
                r = arms.get((stack, arm))
                ok = r is not None and r["status"] == "ok"
                mk = f(r["makespan_us"]) if ok else None
                ratio = mk / bmk if (mk and bmk) else None
                long_rows.append({**ck, "stack": stack, "arm": arm, "baseline": arm == BASE_ARM[stack],
                                  **{k: (r[k] if r else "") for k in KEEP},
                                  "makespan_vs_baseline": f"{ratio:.4f}" if ratio else "",
                                  "baseline_seed_spread": f"{s:.4f}" if s is not None else "",
                                  "within_seed_noise": (abs(ratio - 1) < s) if (ratio and s is not None and arm != BASE_ARM[stack]) else ""})
                w[f"{stack}_{arm}"] = f"{mk:.1f}" if mk else (r["status"] if r else "")
        g = lambda k: f(w.get(k))
        for col, num, den in (("ib_gain_qp2", "ib_qp1", "ib_qp2"), ("ib_gain_qp4", "ib_qp1", "ib_qp4"),
                              ("ib_gain_qp8", "ib_qp1", "ib_qp8"), ("uet_gain_spray", "uet_ecmp", "uet_spray"),
                              ("gap_single_path_ib_over_uet", "ib_qp1", "uet_ecmp"),
                              ("gap_multipath_ib_qp8_over_uet", "ib_qp8", "uet_spray")):
            w[col] = f"{g(num)/g(den):.3f}" if (g(num) and g(den)) else ""
        wide_rows.append(w)

    # ---- across seeds: one row per (cell, stack, arm) -------------------------
    by_arm = defaultdict(list)
    for r in long_rows:
        if r["status"] == "ok" and f(r["makespan_us"]):
            by_arm[(r["workload"], r["size_MB"], r["nodes"], r["stack"], r["arm"])].append(f(r["makespan_us"]))
    mean_rows = []
    for (wl, sz, nd, stack, arm), v in sorted(by_arm.items(), key=lambda kv: (int(kv[0][2]), kv[0][0], int(kv[0][1]), kv[0][3], kv[0][4])):
        b = by_arm.get((wl, sz, nd, stack, BASE_ARM[stack]), [])
        m, bm = st.mean(v), (st.mean(b) if b else None)
        mean_rows.append({"workload": wl, "size_MB": sz, "nodes": nd, "stack": stack, "arm": arm, "n_seeds": len(v),
                          "makespan_mean_us": f"{m:.1f}", "makespan_std_us": f"{st.stdev(v):.1f}" if len(v) > 1 else "",
                          "makespan_min_us": f"{min(v):.1f}", "makespan_max_us": f"{max(v):.1f}",
                          "gain_vs_baseline": f"{bm/m:.4f}" if bm else "",       # >1 = arm faster than baseline
                          # seed ranges overlap -> the effect is not separable from seed noise
                          "ranges_overlap_baseline": (min(v) <= max(b) and min(b) <= max(v)) if (b and arm != BASE_ARM[stack]) else ""})

    for name, rows in (("ablation_long.csv", long_rows), ("ablation_wide.csv", wide_rows), ("ablation_mean.csv", mean_rows)):
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with open(os.path.join(RES, name), "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols); wr.writeheader(); wr.writerows(rows)

    hdr = ["workload","size_MB","nodes","ib_qp1","ib_qp2","ib_qp4","ib_qp8","uet_ecmp","uet_spray","ib_gain_qp8","uet_gain_spray"]
    print("makespan (us) per arm; gains are baseline/arm (>1 = multipath helps)")
    print("  " + "  ".join(f"{h:>12s}" for h in hdr))
    for w in wide_rows:
        print("  " + "  ".join(f"{str(w.get(h, '')):>12s}" for h in hdr))
    bad = [r for r in long_rows if r["status"] not in ("ok", "") and not r["baseline"]]
    print(f"\n{len(wide_rows)} cells, {sum(1 for r in long_rows if r['status']=='ok' and not r['baseline'])} ablation runs ok, "
          f"{len(bad)} not ok" + (": " + ", ".join(f"{r['workload']}/{r['size_MB']}/{r['nodes']} {r['stack']} {r['arm']}={r['status']}" for r in bad) if bad else ""))
    print(f"wrote {RES}/ablation_long.csv, ablation_wide.csv and ablation_mean.csv")


if __name__ == "__main__":
    main()
