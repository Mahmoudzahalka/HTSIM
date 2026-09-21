#!/usr/bin/env python3
"""
fidelityRuns -- rebuild the study's figures from the SEED MEANS, with error bars.

Every figure that the single-seed study drew as a point is drawn here as
mean +/- 95% CI over the seed repeats, so a difference can be read as real or
not. fig0 is new and has no single-seed equivalent: it shows how much of the
original spread was seed luck.

usage: make_graphs_fidelity.py [--min-n 2]
"""
import argparse, csv, math, os, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FID = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(FID, "results")
OUT = os.path.join(FID, "graphs")
OS_ORDER = ["1os", "4os", "8os"]
C_IB, C_UET = "#2F6DA8", "#B4671F"


def f(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def load(min_n):
    p = os.path.join(RES, "results_mean.csv")
    if not os.path.exists(p):
        raise SystemExit("no results/results_mean.csv -- run bin/aggregate.py first")
    rows = [r for r in csv.DictReader(open(p)) if int(r["n_runs"]) >= min_n]
    for r in rows:
        n = int(r["n_runs"])
        mu, sd = f(r["makespan_us_mean"]), f(r["makespan_us_std"])
        r["_mu"], r["_sd"], r["_n"] = mu, sd, n
        r["_ci"] = 1.96 * sd / math.sqrt(n) if (sd is not None and n > 1) else 0.0
    return rows


def fig0_variability(rows):
    """NEW: how much did the answer move with the seed alone?"""
    by = collections.defaultdict(list)
    for r in rows:
        if r["_mu"] and r["_n"] > 1:
            by[r["study"]].append(100.0 * r["_sd"] / r["_mu"])
    if not by: return
    studies = sorted(by, key=lambda s: -max(by[s]))
    fig, ax = plt.subplots(figsize=(10, 0.55 * sum(len(v) for v in by.values()) ** 0.5 + 3.2))
    data = [by[s] for s in studies]
    bp = ax.boxplot(data, vert=False, labels=studies, widths=0.6, patch_artist=True)
    for b in bp["boxes"]:
        b.set_facecolor("#2F6DA8"); b.set_alpha(0.35)
    for s, vals in zip(range(1, len(studies) + 1), data):
        ax.scatter(vals, [s] * len(vals), s=12, color="#9E3F38", zorder=3, alpha=0.7)
    ax.set_xlabel("makespan coefficient of variation across seeds (%)")
    ax.set_title("How much of a single-seed result was seed luck\n"
                 "(each dot is one cell; box = per-study distribution)", loc="left")
    ax.grid(axis="x", alpha=0.3)
    ax.axvline(0, color="k", lw=0.8)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig0_seed_variability.png", dpi=150); plt.close(fig)
    print("  fig0_seed_variability.png")


def fig_makespan_vs_os(rows, nodes):
    """Makespan vs oversubscription, IB vs UET, one panel per workload."""
    sel = [r for r in rows if r["topo_kind"] in OS_ORDER and int(r["nodes"]) == nodes]
    if not sel: return
    wls = sorted({(r["workload"], r["size_MB"]) for r in sel})
    wls = [w for w in wls if w[1] in ("16", "64", "100")]
    if not wls: return
    byw = collections.defaultdict(list)
    for w, s in wls: byw[w].append(s)
    names = sorted(byw)
    ncol = min(3, len(names)); nrow = math.ceil(len(names) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.6 * ncol, 3.5 * nrow), squeeze=False)
    for i, wl in enumerate(names):
        ax = axes[i // ncol][i % ncol]
        for stack, col in (("ib", C_IB), ("uet", C_UET)):
            for sz, ls in zip(sorted(byw[wl], key=int), ["-", "--", ":"]):
                pts = []
                for o in OS_ORDER:
                    m = [r for r in sel if r["workload"] == wl and r["size_MB"] == sz
                         and r["stack"] == stack and r["topo_kind"] == o]
                    if m and m[0]["_mu"]: pts.append((o, m[0]["_mu"] / 1000.0, m[0]["_ci"] / 1000.0))
                if not pts: continue
                ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=[p[2] for p in pts],
                            marker="o", ms=4, lw=1.4, ls=ls, color=col, capsize=3,
                            label=f"{stack.upper()} {sz}MB")
        ax.set_title(wl, fontsize=10, loc="left")
        ax.set_ylabel("makespan (ms)"); ax.set_yscale("log"); ax.grid(alpha=0.3)
        ax.legend(fontsize=6.5, ncol=2)
    for j in range(len(names), nrow * ncol): axes[j // ncol][j % ncol].axis("off")
    fig.suptitle(f"Makespan vs oversubscription, {nodes} nodes — mean ± 95% CI over seeds", y=0.999)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig1_makespan_vs_os_{nodes}.png", dpi=150); plt.close(fig)
    print(f"  fig1_makespan_vs_os_{nodes}.png")


def fig_rail(rows):
    """Rail vs flat control, both stacks, with CIs -- the rail study's fig1."""
    sel = [r for r in rows if r["study"] == "rail"]
    if not sel: return
    keys = sorted({(r["workload"], int(r["nodes"]), int(r["size_MB"])) for r in sel})
    if not keys: return
    labels, ib_r, ib_f, ue_r, ue_f = [], [], [], [], []
    for wl, n, sz in keys:
        def get(stack, topo):
            m = [r for r in sel if r["workload"] == wl and int(r["nodes"]) == n
                 and int(r["size_MB"]) == sz and r["stack"] == stack and r["topo_kind"] == topo]
            return (m[0]["_mu"] / 1000.0, m[0]["_ci"] / 1000.0) if m and m[0]["_mu"] else (0, 0)
        labels.append(f"{wl.replace('_rail_aware','')}\n{n}n {sz}MB")
        ib_r.append(get("ib", "rail")); ib_f.append(get("ib", "flat"))
        ue_r.append(get("uet", "rail")); ue_f.append(get("uet", "flat"))
    x = range(len(labels)); w = 0.2
    fig, ax = plt.subplots(figsize=(max(9, 1.5 * len(labels)), 4.8))
    for k, (vals, off, col, hatch, lab) in enumerate([
            (ib_f, -1.5, C_IB, "//", "IB flat"), (ib_r, -0.5, C_IB, "", "IB rail"),
            (ue_f, 0.5, C_UET, "//", "UET flat"), (ue_r, 1.5, C_UET, "", "UET rail")]):
        ax.bar([i + off * w for i in x], [v[0] for v in vals], w,
               yerr=[v[1] for v in vals], capsize=2.5, color=col, hatch=hatch,
               alpha=0.95 if hatch == "" else 0.55, label=lab,
               edgecolor="white", linewidth=0.6)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("makespan (ms)"); ax.grid(axis="y", alpha=0.3); ax.legend(fontsize=8)
    ax.set_title("Rail vs shape-matched flat control — mean ± 95% CI over seeds", loc="left")
    fig.tight_layout(); fig.savefig(f"{OUT}/fig2_rail_vs_flat.png", dpi=150); plt.close(fig)
    print("  fig2_rail_vs_flat.png")


def fig_ratio(rows):
    """IB/UET makespan ratio with error propagated from both stacks."""
    by = {}
    for r in rows:
        by[(r["study"], r["workload"], r["size_MB"], r["nodes"], r["topo_kind"], r["stack"])] = r
    pts = []
    for k, r in by.items():
        if r["stack"] != "ib": continue
        u = by.get(k[:-1] + ("uet",))
        if not (u and r["_mu"] and u["_mu"]): continue
        ratio = r["_mu"] / u["_mu"]
        rel = math.hypot((r["_ci"] / r["_mu"]), (u["_ci"] / u["_mu"]))
        pts.append((f'{k[1]}\n{k[3]}n {k[2]}MB {k[4]}', ratio, ratio * rel))
    if not pts: return
    pts.sort(key=lambda p: p[1])
    fig, ax = plt.subplots(figsize=(max(9, 0.42 * len(pts)), 5))
    xs = range(len(pts))
    ax.errorbar(list(xs), [p[1] for p in pts], yerr=[p[2] for p in pts],
                fmt="o", ms=4, color=C_IB, capsize=3, lw=1)
    ax.axhline(1.0, color="k", lw=1, ls="--")
    ax.set_xticks(list(xs)); ax.set_xticklabels([p[0] for p in pts], rotation=90, fontsize=5.5)
    ax.set_ylabel("IB / UET makespan   (<1 = IB faster)")
    ax.set_title("IB vs UET — mean ratio ± propagated 95% CI.\n"
                 "Points whose bar crosses 1.0 are not a measured difference.", loc="left")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig3_ib_uet_ratio.png", dpi=150); plt.close(fig)
    print("  fig3_ib_uet_ratio.png")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--min-n", type=int, default=2)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rows = load(a.min_n)
    print(f"graphs from {len(rows)} cells with n>={a.min_n} -> {OUT}")
    fig0_variability(rows)
    for n in (128, 1024): fig_makespan_vs_os(rows, n)
    fig_rail(rows)
    fig_ratio(rows)


if __name__ == "__main__":
    main()
