#!/usr/bin/env python3
"""
fidelityRuns -- collect every .row / .urow into per-run CSVs, then average the
seed repeats per cell.

Outputs into fidelityRuns/results/:
  runs_all.csv          every individual run (37 cols), one row per (cell,seed)
  results_mean.csv      per cell: mean/std/cv for every metric + n_runs
  results_summary.csv   the headline columns only, easy to eyeball
  utilization_all.csv   every individual util row (47 cols)
  utilization_mean.csv  per cell: mean/std for the 42 utilization stats
  variability.csv       cells ranked by makespan CV -- the fidelity payoff

--check-rep1 diffs the seed-13 runs against the ORIGINAL published CSVs.

CAUTION -- this changed meaning on 2026-09-21. It was a REPRODUCTION check: the old
sweeps never passed -seed, so they used main's default of 13, and seed 13 had to
match them exactly (it did, 0.00% on all 90 cells checked). The study has since
moved to the DGX H100 generation (400 G fabric instead of 200 G), so the numbers
are now EXPECTED to differ -- it measures the generation change, not correctness.
A "mismatch" here is the result, not a bug. Measured on 4 smoke cells:
  perm_random uet 1os   782.0 -> 397.6 us  (1.97x -- pure serialization, ~2x as expected)
  perm_random ib  1os  4449.0 -> 2570.4 us (1.73x -- latency is unchanged, so <2x)
  allreduce   uet rail  357.2 ->  237.6 us (1.50x -- latency-bound phases gain least)
  allreduce   ib  rail 1139.2 ->  391.6 us (2.91x -- SUPERLINEAR: 2x the link relieved
                                            congestion worth more than the link itself)
"""
import argparse, csv, glob, math, os, statistics as st, sys

FID  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNS = os.path.abspath(os.path.join(FID, ".."))
RES  = os.path.join(FID, "results")

ROW_COLS = ["study","matrix","workload","size_MB","nodes","conns","stack","topo_kind",
            "seed","rep","status","wall_s","peak_mb","flows_fin","makespan_us",
            "fct_min_us","fct_p50_us","fct_p99_us","fct_max_us","total_GB",
            "New","Rtx","RTS","Bounced","ACKs","NACKs","Pulls","sleek","spurious",
            "pfc_pauses","pfc_pause_us","max_queue_bytes",
            "slowdown_p50","slowdown_p99","slowdown_max","fairness_jain","overflow"]

UTIL_STATS = []
for grp in ["overall","tier0_up","tier0_down","tier1_up","tier1_down","tier2_up","tier2_down"]:
    UTIL_STATS += [f"{grp}_{s}" for s in ["n","mean","p50","p95","p99","max"]]
UROW_COLS = ["study","matrix_base","stack","topo_kind","seed"] + UTIL_STATS

KEY = ["study","workload","size_MB","nodes","stack","topo_kind"]
METRICS = ["makespan_us","fct_min_us","fct_p50_us","fct_p99_us","fct_max_us","total_GB",
           "New","Rtx","RTS","Bounced","ACKs","NACKs","Pulls","sleek","spurious",
           "pfc_pauses","pfc_pause_us","max_queue_bytes",
           "slowdown_p50","slowdown_p99","slowdown_max","fairness_jain","overflow",
           "wall_s","peak_mb"]


def fnum(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def collect(pattern, cols):
    out = []
    for p in sorted(glob.glob(pattern)):
        for line in open(p):
            line = line.rstrip("\n")
            if not line: continue
            parts = line.split(",")
            if len(parts) != len(cols):
                print(f"  !! {os.path.basename(p)}: {len(parts)} fields, expected {len(cols)} -- skipped", file=sys.stderr)
                continue
            out.append(dict(zip(cols, parts)))
    return out


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals: return (None, None, None, 0)
    m = st.mean(vals)
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    cv = (sd / m) if m else 0.0
    return (m, sd, cv, len(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-rep1", action="store_true")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)

    rows  = collect(os.path.join(FID, "*", "rows", "*.row"), ROW_COLS)
    urows = collect(os.path.join(FID, "*", "util_rows", "*.urow"), UROW_COLS)
    if not rows:
        print("no .row files yet -- nothing to aggregate"); return

    with open(os.path.join(RES, "runs_all.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_COLS); w.writeheader(); w.writerows(rows)

    ok = [r for r in rows if r["status"] == "ok"]
    bad = [r for r in rows if r["status"] != "ok"]

    # ---- per-cell aggregation over seeds -----------------------------------
    cells = {}
    for r in ok:
        cells.setdefault(tuple(r[k] for k in KEY), []).append(r)

    mean_cols = KEY + ["n_runs","seeds"] + [f"{m}_{s}" for m in METRICS for s in ("mean","std","cv")]
    agg_rows, var_rows = [], []
    for k, rs in sorted(cells.items()):
        d = dict(zip(KEY, k))
        d["n_runs"] = len(rs)
        d["seeds"] = "|".join(sorted((r["seed"] for r in rs), key=int))
        for m in METRICS:
            mu, sd, cv, n = stats([fnum(r[m]) for r in rs])
            d[f"{m}_mean"] = "" if mu is None else f"{mu:.4f}"
            d[f"{m}_std"]  = "" if sd is None else f"{sd:.4f}"
            d[f"{m}_cv"]   = "" if cv is None else f"{cv:.5f}"
        agg_rows.append(d)
        mu, sd, cv, n = stats([fnum(r["makespan_us"]) for r in rs])
        if mu:
            sem = (sd / math.sqrt(n)) if n > 1 else 0.0
            var_rows.append(dict(**dict(zip(KEY, k)), n_runs=n,
                                 makespan_mean_us=f"{mu:.1f}", makespan_std_us=f"{sd:.1f}",
                                 makespan_cv_pct=f"{100*cv:.2f}", sem_us=f"{sem:.1f}",
                                 ci95_halfwidth_us=f"{1.96*sem:.1f}",
                                 ci95_pct=f"{100*1.96*sem/mu:.2f}"))

    with open(os.path.join(RES, "results_mean.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=mean_cols); w.writeheader(); w.writerows(agg_rows)

    summ = KEY + ["n_runs","makespan_us_mean","makespan_us_std","makespan_us_cv",
                  "fct_p99_us_mean","Rtx_mean","NACKs_mean","spurious_mean",
                  "pfc_pauses_mean","pfc_pause_us_mean","slowdown_p99_mean",
                  "fairness_jain_mean","overflow_mean"]
    with open(os.path.join(RES, "results_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summ, extrasaction="ignore")
        w.writeheader(); w.writerows(agg_rows)

    var_rows.sort(key=lambda r: -float(r["makespan_cv_pct"]))
    if var_rows:
        with open(os.path.join(RES, "variability.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(var_rows[0].keys()))
            w.writeheader(); w.writerows(var_rows)

    # ---- utilization --------------------------------------------------------
    if urows:
        with open(os.path.join(RES, "utilization_all.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=UROW_COLS); w.writeheader(); w.writerows(urows)
        ucells = {}
        for r in urows:
            ucells.setdefault((r["study"], r["matrix_base"], r["stack"], r["topo_kind"]), []).append(r)
        ucols = ["study","matrix_base","stack","topo_kind","n_runs"] + \
                [f"{s}_{k}" for s in UTIL_STATS for k in ("mean","std")]
        uagg = []
        for k, rs in sorted(ucells.items()):
            d = dict(zip(["study","matrix_base","stack","topo_kind"], k)); d["n_runs"] = len(rs)
            for s in UTIL_STATS:
                mu, sd, cv, n = stats([fnum(r[s]) for r in rs])
                d[f"{s}_mean"] = "" if mu is None else f"{mu:.4f}"
                d[f"{s}_std"]  = "" if sd is None else f"{sd:.4f}"
            uagg.append(d)
        with open(os.path.join(RES, "utilization_mean.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ucols); w.writeheader(); w.writerows(uagg)

    print(f"aggregate: {len(rows)} runs ({len(ok)} ok, {len(bad)} not ok) over {len(cells)} cells")
    if bad:
        from collections import Counter
        for s, n in Counter(r["status"] for r in bad).most_common():
            print(f"   {s}: {n}")
    done = sum(1 for c in cells.values() if len(c) >= 5)
    print(f"   cells with >=5 seeds: {done}/{len(cells)}")
    if var_rows:
        print("   most seed-sensitive cells (makespan CV):")
        for r in var_rows[:8]:
            print(f"     {r['makespan_cv_pct']:>6}%  n={r['n_runs']}  {r['stack']:3s} "
                  f"{r['workload']:24s} {r['nodes']:>5}n {r['size_MB']:>3}MB {r['topo_kind']}")

    if a.check_rep1:
        check_rep1(ok)


def check_rep1(ok):
    """Seed 13 == main's default == what the original sweeps used."""
    import re
    srcs = {
        "uet_perm_incast": "uet/perm_incast_128_1024/results_combined.csv",
        "uet_a2a_concurrent": "uet/a2a_concurrent_128_1024/results_combined.csv",
        "uet_a2a_serial": "uet/a2a_serial_128_1024/results_combined.csv",
        "uet_allreduce_ring": "uet/allreduce_ring_128/results_combined.csv",
        "ib_perm_incast_a2a": "ib_dcqcn/perm_incast_a2a_128_1024/results_ib.csv",
        "ib_allreduce_a2a_serial": "ib_dcqcn/allreduce_a2a_serial_128/results_ib_parity.csv",
        "rail": "rail_optimized/results_rail.csv",
    }
    orig = {}
    for study, rel in srcs.items():
        p = os.path.join(RUNS, rel)
        if not os.path.exists(p): continue
        for x in csv.DictReader(open(p)):
            if x["status"] != "ok": continue
            b = os.path.basename(x["matrix"]).replace(".cm", "")
            t = x.get("fabric") or x.get("topology")
            stk = x.get("stack") or ("ib" if study.startswith("ib") else "uet")
            orig[(study, b, stk, t)] = fnum(x["makespan_us"])
    print("\n--- seed 13 @400G (H100) vs the published 200 G numbers ---")
    print("    NOTE: these SHOULD differ -- the fabric changed from 200 G to 400 G.")
    print("    This measures the generation change; it is no longer a correctness gate.")
    n = same = 0
    worst = []
    for r in ok:
        if r["seed"] != "13": continue
        b = os.path.basename(r["matrix"]).replace(".cm", "")
        o = orig.get((r["study"], b, r["stack"], r["topo_kind"]))
        if o is None: continue
        n += 1
        got = fnum(r["makespan_us"])
        d = abs(got - o) / o * 100 if o else 0
        if d < 0.5: same += 1
        worst.append((d, r["study"], b, r["stack"], r["topo_kind"], o, got))
    worst.sort(reverse=True)
    print(f"  compared {n} cells; {same} unchanged within 0.5% (expect few at a new link speed)")
    for d, s, b, stk, t, o, g in worst[:8]:
        print(f"    {d:6.2f}%  {s}/{b}.{stk}.{t}  orig={o:.1f} new={g:.1f}")


if __name__ == "__main__":
    main()
